"""GET /models: the model picker: every AI model, its free usage left today, and which one Auto starts with."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user, get_db
from app.core.config import get_settings
from app.db.models import User
from app.llm import models

router = APIRouter()


@router.get("/models")
async def list_models(user: User = Depends(current_user), s: AsyncSession = Depends(get_db)):
    settings = get_settings()
    return {"models": await models.list_models(s, datetime.now(UTC)), "auto": settings.llm_small,
            "auto_email": settings.llm_large}
