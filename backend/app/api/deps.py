from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.accounts import auth
from app.db.models import Device, User
from app.db.session import get_sessionmaker

_bearer = HTTPBearer(auto_error=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as s:
        yield s


async def current(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer), s: AsyncSession = Depends(get_db)
) -> tuple[User, Device]:
    if creds is None:
        raise HTTPException(401, "Sign in first")
    try:
        return await auth.user_from_access(s, creds.credentials)
    except auth.AuthError as e:
        raise HTTPException(401, str(e)) from e


async def current_user(me: tuple[User, Device] = Depends(current)) -> User:
    return me[0]


def get_sm() -> async_sessionmaker[AsyncSession]:
    """For streaming responses: they outlive the request's own session, so they open their own."""
    return get_sessionmaker()
