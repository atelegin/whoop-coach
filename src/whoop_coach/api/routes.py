"""FastAPI routes."""

import base64
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from telegram import Update

from whoop_coach.config import get_settings
from whoop_coach.crypto import encrypt_tokens
from whoop_coach.db.models import OAuthState, User, WebhookEvent, WebhookEventStatus
from whoop_coach.db.session import async_session_factory
from whoop_coach.whoop.client import WhoopClient

router = APIRouter()

# OAuth state TTL (10 minutes)
STATE_TTL_MINUTES = 10

# Webhook signature freshness (5 minutes)
WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS = 300


def verify_whoop_signature(body: bytes, sig: str, ts: str) -> bool:
    """Verify WHOOP webhook HMAC-SHA256 signature.
    
    Per WHOOP docs: signature = base64(HMAC-SHA256(timestamp + body, secret))
    """
    settings = get_settings()
    if not settings.WHOOP_WEBHOOK_SECRET:
        return False
    
    # Check timestamp freshness (ts is in milliseconds)
    try:
        ts_int = int(ts)
        # Convert to seconds for comparison
        if abs(time.time() * 1000 - ts_int) > WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS * 1000:
            return False
    except (ValueError, TypeError):
        return False
    
    # Compute expected signature: timestamp (as string) + body (no separator)
    signed_payload = ts.encode() + body
    expected = hmac.new(
        settings.WHOOP_WEBHOOK_SECRET.encode(),
        signed_payload,
        hashlib.sha256
    ).digest()
    
    try:
        received = base64.b64decode(sig)
    except Exception:
        return False
    
    return hmac.compare_digest(expected, received)


@router.get("/health")
async def health_check() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}


@router.post("/webhooks/telegram")
async def telegram_webhook(request: Request) -> Response:
    """Receive Telegram updates via webhook (Variant B).

    PTB Application is stored in app.state.tg_app.
    """
    tg_app = request.app.state.tg_app
    bot = tg_app.bot

    json_data = await request.json()
    update = Update.de_json(json_data, bot)
    await tg_app.process_update(update)

    return Response(status_code=200)


@router.get("/auth/whoop")
async def whoop_auth_start(telegram_id: int = Query(...)) -> RedirectResponse:
    """Start WHOOP OAuth flow.
    
    Generates secure state, stores it with telegram_id, redirects to WHOOP.
    """
    client = WhoopClient()
    state = WhoopClient.generate_state()

    # Store state in DB
    async with async_session_factory() as session:
        async with session.begin():
            oauth_state = OAuthState(state=state, telegram_id=telegram_id)
            session.add(oauth_state)

    # Redirect to WHOOP
    authorize_url = client.build_authorize_url(state)
    return RedirectResponse(url=authorize_url)


@router.get("/auth/whoop/callback")
async def whoop_auth_callback(
    code: str = Query(...),
    state: str = Query(...),
) -> dict:
    """WHOOP OAuth callback — exchange code for tokens."""
    now = datetime.now(UTC)

    async with async_session_factory() as session:
        async with session.begin():
            # Validate state
            result = await session.execute(
                select(OAuthState).where(OAuthState.state == state)
            )
            oauth_state = result.scalar_one_or_none()

            if not oauth_state:
                raise HTTPException(status_code=400, detail="Invalid state")

            # Check TTL
            state_age = now - oauth_state.created_at.replace(tzinfo=UTC)
            if state_age > timedelta(minutes=STATE_TTL_MINUTES):
                raise HTTPException(status_code=400, detail="State expired")

            # Check if already used
            if oauth_state.used_at is not None:
                raise HTTPException(status_code=400, detail="State already used")

            # Mark as used
            oauth_state.used_at = now
            telegram_id = oauth_state.telegram_id

            # Exchange code for tokens
            client = WhoopClient()
            try:
                token_response = await client.exchange_code(code)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Token exchange failed: {e}")
            finally:
                await client.close()

            # Get WHOOP user ID
            import logging
            logger = logging.getLogger(__name__)
            
            client_with_token = WhoopClient(access_token=token_response.access_token)
            try:
                profile = await client_with_token.get_profile()
                whoop_user_id = str(profile.get("user_id", ""))
                logger.info(f"[OAuth] Profile fetched: whoop_user_id={whoop_user_id}")
                if not whoop_user_id:
                    logger.warning(f"[OAuth] Empty whoop_user_id from profile: {profile}")
            except Exception as e:
                logger.error(f"[OAuth] Failed to fetch profile: {type(e).__name__}: {e}")
                whoop_user_id = None
            finally:
                await client_with_token.close()

            # Encrypt and store tokens
            tokens_dict = token_response.to_dict()
            encrypted = encrypt_tokens(tokens_dict)

            # Update user
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()

            if user:
                user.whoop_tokens_enc = encrypted
                if whoop_user_id:
                    user.whoop_user_id = whoop_user_id
            else:
                # Create user if doesn't exist
                user = User(
                    telegram_id=telegram_id,
                    whoop_tokens_enc=encrypted,
                    whoop_user_id=whoop_user_id,
                )
                session.add(user)

    return {
        "status": "success",
        "message": "✅ WHOOP подключен! Вернись в Telegram и используй /last",
    }


@router.post("/webhooks/whoop")
async def whoop_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict:
    """Handle WHOOP webhooks (recovery.updated).
    
    1. Verify signature (required in prod, optional in dev)
    2. Store event with trace_id for idempotency
    3. Queue background processing
    4. Return 2xx immediately
    """
    import logging
    logger = logging.getLogger(__name__)
    
    body = await request.body()
    sig = request.headers.get("X-WHOOP-Signature", "")
    ts = request.headers.get("X-WHOOP-Signature-Timestamp", "")
    
    settings = get_settings()
    
    logger.info(f"[WHOOP] Received webhook, body_len={len(body)}, sig={bool(sig)}, ts={bool(ts)}")
    
    # Signature verification: skip if secret not configured
    if settings.WHOOP_WEBHOOK_SECRET:
        if sig and ts:
            if not verify_whoop_signature(body, sig, ts):
                logger.warning("[WHOOP] Invalid signature!")
                raise HTTPException(401, "Invalid signature")
        elif settings.is_prod:
            # Prod mode requires signature when secret is set
            logger.warning("[WHOOP] Missing signature headers in prod!")
            raise HTTPException(401, "Missing signature headers")
    
    payload = json.loads(body)
    event_type = payload.get("type")
    trace_id = payload.get("trace_id", "")
    sleep_id = payload.get("id", "")
    whoop_user_id = str(payload.get("user_id", ""))
    
    logger.info(f"[WHOOP] event_type={event_type}, trace_id={trace_id[:8]}..., user={whoop_user_id}")
    
    # Only handle recovery.updated
    if event_type != "recovery.updated":
        logger.info(f"[WHOOP] Ignoring event type: {event_type}")
        return {"status": "ignored", "reason": f"event_type={event_type}"}
    
    if not trace_id or not sleep_id:
        logger.warning("[WHOOP] Missing trace_id or sleep_id")
        return {"status": "ignored", "reason": "missing_trace_or_sleep_id"}
    
    async with async_session_factory() as session:
        # Idempotency check
        exists = await session.execute(
            select(WebhookEvent).where(WebhookEvent.trace_id == trace_id)
        )
        if exists.scalar_one_or_none():
            logger.info(f"[WHOOP] Duplicate event, trace_id={trace_id[:8]}...")
            return {"status": "duplicate"}
        
        # Find user
        user_result = await session.execute(
            select(User).where(User.whoop_user_id == whoop_user_id)
        )
        user = user_result.scalar_one_or_none()
        if not user:
            logger.warning(f"[WHOOP] Unknown user: whoop_user_id={whoop_user_id}")
            return {"status": "ignored", "reason": "unknown_user"}
        
        logger.info(f"[WHOOP] Found user: telegram_id={user.telegram_id}")
        
        # Store event
        event = WebhookEvent(
            trace_id=trace_id,
            sleep_id=sleep_id,
            event_type=event_type,
            user_id=user.id,
            status=WebhookEventStatus.PENDING,
        )
        session.add(event)
        await session.commit()
        
        logger.info(f"[WHOOP] Event stored, id={event.id}, queueing background task")
        
        # Queue background processing
        background_tasks.add_task(
            process_recovery_event,
            event.id,
            request.app,
        )
    
    return {"status": "accepted"}


async def process_recovery_event(event_id, app) -> None:
    """Background: fetch recovery → check morning feedback → send plan.
    
    Imported here to avoid circular imports.
    """
    # Import here to avoid circular dependency
    from whoop_coach.webhook_processor import process_recovery_webhook
    await process_recovery_webhook(event_id, app)

