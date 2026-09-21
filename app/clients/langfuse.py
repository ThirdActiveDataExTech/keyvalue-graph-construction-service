import logging
from functools import lru_cache
from typing import Optional

from langfuse._client.client import Langfuse

from app.config import settings


@lru_cache(maxsize=1)
def get_client() -> Optional[Langfuse]:
    """Get Langfuse client with caching."""
    try:
        return Langfuse(
            secret_key=settings.LANGFUSE_SECRET_KEY, public_key=settings.LANGFUSE_PUBLIC_KEY, host=settings.LANGFUSE_HOST
        )
    except Exception as e:
        logging.error(f"Failed to initialize Langfuse client: {e}")
        return None
