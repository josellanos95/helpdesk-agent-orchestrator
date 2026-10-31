from functools import lru_cache

import redis.asyncio as redis

from app.config import get_settings


@lru_cache
def get_redis_client() -> redis.Redis:
    # Lazy: building the client does not connect, so importing the app never needs Redis.
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
