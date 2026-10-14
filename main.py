"""Entry point for the FastAPI app: `fastapi dev main.py` (or `uvicorn main:app --reload`)."""
from bsi.api.main import app

__all__ = ["app"]
