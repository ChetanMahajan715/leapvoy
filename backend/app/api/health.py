from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import get_engine

router = APIRouter()


@router.get("/health")
async def health(engine: AsyncEngine = Depends(get_engine)):
    try:
        async with engine.connect() as conn:
            pgvector = (
                await conn.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'"))
            ).scalar()
    except (OSError, SQLAlchemyError):
        return JSONResponse({"status": "error", "db": "down"}, status_code=503)
    return {"status": "ok", "db": "ok", "pgvector": pgvector}
