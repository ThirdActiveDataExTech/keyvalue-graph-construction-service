from app.config import settings
from langchain_openai import ChatOpenAI


def get_chat_client(
    model: str = settings.CLAUDE_MODEL_NAME,
    base_url: str = settings.LITE_LLM_BASE_URL,
    temperature: float = 0.0,
    api_key: str = settings.CLAUDE_API_KEY,
) -> ChatOpenAI:
    return ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=temperature,
    )
