from typing import Annotated, Optional
from functools import lru_cache
from fastapi import Security
from fastapi.security import APIKeyHeader
from langfuse import Langfuse
from langchain_openai import ChatOpenAI
from app.utils.authentication import token_validation
from app.clients import langfuse, openai
from langfuse.model import PromptClient
from langfuse.api.resources.commons.errors.not_found_error import NotFoundError
from langfuse.api.core.api_error import ApiError
import logging

header_scheme = APIKeyHeader(name="x-token")


async def get_token_header(x_token: Annotated[str, Security(header_scheme)]):
    await token_validation(x_token)


@lru_cache(maxsize=1)
def get_chatopenai_client() -> ChatOpenAI:
    """Langchain OpenAI 클라이언트 생성 및 도구 바인딩"""
    return openai.get_chat_client()


@lru_cache(maxsize=3)
def get_langfuse_prompt(prompt_name: str, prompt_label: str) -> PromptClient | None:
    try:
        prompt = langfuse_client.get_prompt(prompt_name, label=prompt_label)  # pyright: ignore
        return prompt
    except (NotFoundError, AttributeError, ApiError) as e:
        logging.warning(f"langfuse fail - return fallback prompt: {e}")
        return None


# Client Instances
chatopenai_client: ChatOpenAI = get_chatopenai_client()
langfuse_client: Optional[Langfuse] = langfuse.get_client()
