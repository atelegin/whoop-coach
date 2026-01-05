"""Main entrypoint — FastAPI app for production."""

from whoop_coach.api.app import create_app

app = create_app()
