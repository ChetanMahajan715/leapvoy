import uuid
from typing import Any

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Profile


async def get_profile(s: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    p = await s.get(Profile, user_id)
    return dict(p.data) if p else {}


async def set_profile(s: AsyncSession, user_id: uuid.UUID, data: dict[str, Any]) -> None:
    stmt = insert(Profile).values(user_id=user_id, data=data)
    await s.execute(stmt.on_conflict_do_update(index_elements=["user_id"], set_={"data": data, "updated_at": func.now()}))
    await s.commit()
