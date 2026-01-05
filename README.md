# WHOOP × Telegram Coach

Персональный тренировочный ассистент: рекомендации тренировок на основе данных WHOOP.

## Quick Start (Dev)

```bash
# Clone & setup
cd whoop-coach
cp .env.example .env
# Fill in TELEGRAM_BOT_TOKEN

# Install
pip install -e ".[dev]"

# Run migrations
alembic upgrade head

# Start bot (polling mode)
python -m whoop_coach.dev
```

## Production

```bash
# Set ENV=prod and TELEGRAM_WEBHOOK_URL in .env
uvicorn whoop_coach.main:app --host 0.0.0.0 --port 8000
```

## Project Structure

```
src/whoop_coach/
├── main.py          # FastAPI app + PTB lifecycle
├── dev.py           # Dev entrypoint (polling)
├── config.py        # Settings
├── bot/             # Telegram handlers
├── api/             # FastAPI routes
└── db/              # SQLAlchemy models
```
