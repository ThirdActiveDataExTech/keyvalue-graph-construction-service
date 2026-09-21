import time
from typing import Dict, Any, Union

import logging
from langfuse.model import PromptClient
from openai import APIError

from app.config import langfuse_handler
from app.dependencies import chatopenai_client, get_langfuse_prompt
from app.exceptions.base import ApplicationError
from app.schemas.keyvalue_graph import (
    field_type_classification_tool,
    proper_noun_labeling_tool,
)
from app.schemas.meta import (
    cluster_normalization_tool,
    key_value_extraction_tool,
)
from app.schemas.relation_discovery import (
    relation_search_condition_tool,
)
from app.schemas.schema_analysis import (
    schema_analysis_tool,
)
from app.schemas.tool_utils import restore_map_fields
from app.src.meta_extract.fallback_prompts import FallbackPrompts


class LLMResponse:
    """LLM 응답 처리 클래스 - 메타데이터 추출용"""

    PROMPT_LABEL = "production"

    # task 이름 == Langfuse 프롬프트 이름. 각 task 가 사용할 function tool 매핑.
    TASK_TOOLS = {
        "key_value_extract": key_value_extraction_tool,
        "cluster_normalize": cluster_normalization_tool,
        "schema_analysis": schema_analysis_tool,
        "relation_key_analysis": relation_search_condition_tool,
        "field_type_classification": field_type_classification_tool,
        "proper_noun_labeling": proper_noun_labeling_tool,
    }

    def __init__(self, task: str):
        """Init 매서드"""
        if task not in self.TASK_TOOLS:
            raise ValueError(f"Unknown task: {task}")
        self.task = task

    def generate_llm_response(self, variables: Any) -> Dict[str, Any]:
        """통합 LLM 응답 처리"""
        prompt = self._get_prompt()
        compiled_prompt = self._compile_prompt(prompt, **variables)
        response = self._invoke_llm_unified(compiled_prompt)
        return self._process_llm_response(response)

    @staticmethod
    def _extract_message_from_tool_call(tool_call: Dict[str, Any]) -> Dict[str, Any]:
        """tool_call에서 args 추출하기"""
        try:
            response_message = tool_call["args"]
            logging.debug(f"Extracted metadata: {response_message}")
            return response_message
        except KeyError:
            raise KeyError("tool_call에 'args' 키가 없습니다")

    def _process_llm_response(self, response: Any) -> Dict[str, Any]:
        """LLM 응답 처리하여 메타데이터 추출"""
        try:
            tool_call = response.tool_calls[0]
            args = self._extract_message_from_tool_call(tool_call)
        except (IndexError, AttributeError, KeyError) as e:
            raise ApplicationError(code=400, message=f"No tool calls in llm_response: {str(e)}",
                                   result={"exception": f"llm response: {response.content}"})
        # dict 필드는 Bedrock 호환을 위해 entry 배열 스키마로 나가므로 dict 로 복원
        tool_name = self.TASK_TOOLS[self.task]["function"]["name"]
        return restore_map_fields(tool_name, args)

    @staticmethod
    def _compile_prompt(prompt, **variables):
        """프롬프트 컴파일 처리 - 랭퓨즈와 폴백 프롬프트 처리 대응"""
        if hasattr(prompt, 'compile'):
            return prompt.compile(**variables)
        return prompt.format(**variables)

    def _get_prompt(self) -> Union[PromptClient, str]:
        """통합 프롬프트 가져오기 - Langfuse 실패 시 폴백 프롬프트 반환"""
        prompt = get_langfuse_prompt(prompt_name=self.task, prompt_label=self.PROMPT_LABEL)
        if prompt is None:
            logging.warning(f"LLM Response: {self.task} 프롬프트 폴백")
            prompt = FallbackPrompts.get_prompt(self.task)
        return prompt

    def _invoke_llm_unified(self, compiled_prompt: str) -> Any:
        """통합 LLM 호출"""
        llm = chatopenai_client.bind_tools([self.TASK_TOOLS[self.task]])
        for attempt in range(2):
            try:
                return llm.invoke(
                    compiled_prompt,
                    config={
                        "callbacks": [langfuse_handler],
                        "metadata": {"langfuse_tags": [self.task]},
                    },
                )
            except APIError as e:
                if ("503" in str(e) or "Too many connections" in str(e)) and attempt == 0:
                    logging.warning(f"LLM 503 에러, 2초 후 재시도")
                    time.sleep(2)
                    continue
                raise
