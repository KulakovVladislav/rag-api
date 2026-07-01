from functools import lru_cache

import redis

from app.config import settings


@lru_cache(maxsize=1)
def get_redis_client():
    return redis.from_url(
        settings.redis_url,
        decode_responses=True
    )
