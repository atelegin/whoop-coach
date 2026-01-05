"""YouTube URL parsing utilities."""

import re
from urllib.parse import parse_qs, urlparse


# Regex patterns for YouTube video IDs (11 chars: alphanumeric + _ + -)
_VIDEO_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{11}$")


def parse_youtube_url(url: str) -> str | None:
    """Extract video ID from YouTube URL.

    Supports:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://m.youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://youtube.com/shorts/VIDEO_ID
    - URLs with additional params (t=, list=, etc.)

    Returns:
        Video ID (11 chars) or None if not a valid YouTube URL.
    """
    if not url:
        return None

    try:
        parsed = urlparse(url.strip())
    except Exception:
        return None

    host = parsed.netloc.lower().replace("www.", "").replace("m.", "")

    # youtu.be/VIDEO_ID
    if host == "youtu.be":
        video_id = parsed.path.lstrip("/").split("/")[0]
        if _VIDEO_ID_PATTERN.match(video_id):
            return video_id
        return None

    # youtube.com variants
    if host not in ("youtube.com",):
        return None

    path = parsed.path.lower()

    # /watch?v=VIDEO_ID
    if path == "/watch":
        qs = parse_qs(parsed.query)
        video_ids = qs.get("v", [])
        if video_ids and _VIDEO_ID_PATTERN.match(video_ids[0]):
            return video_ids[0]
        return None

    # /shorts/VIDEO_ID
    if path.startswith("/shorts/"):
        video_id = parsed.path.split("/")[2] if len(parsed.path.split("/")) > 2 else ""
        if _VIDEO_ID_PATTERN.match(video_id):
            return video_id
        return None

    # /embed/VIDEO_ID or /v/VIDEO_ID
    if path.startswith("/embed/") or path.startswith("/v/"):
        parts = parsed.path.split("/")
        video_id = parts[2] if len(parts) > 2 else ""
        if _VIDEO_ID_PATTERN.match(video_id):
            return video_id
        return None

    return None
