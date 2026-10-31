from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager

from sqlalchemy.ext.asyncio import AsyncSession

# Opens one short tenant-scoped transaction: `async with scope() as session: ...`
SessionScope = Callable[[], AbstractAsyncContextManager[AsyncSession]]
Heartbeat = Callable[[], Awaitable[None]]
