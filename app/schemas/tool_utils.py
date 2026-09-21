"""LLM function tool 생성 유틸.

openai.pydantic_function_tool 의 JSON Schema 출력에는 Bedrock Claude 의
tool 스키마 검증이 거부하는 형태가 있어 생성 시점에 정리한다:

1. number 타입의 minimum/maximum 등 제약 키
   ("tools.0.custom: For 'number' type, properties maximum, minimum are not supported")
2. dict[str, X] 필드가 만드는 map 스키마 (additionalProperties 가 object)
   ("For 'object' type, 'additionalProperties: object' is not supported")
   → {key, value} 항목 배열 스키마로 변환하고, LLM 응답을 받은 뒤
     restore_map_fields() 로 다시 dict 로 복원한다 (llm_response 에서 호출).
"""

from typing import Any, Optional, Type

from openai import pydantic_function_tool as _openai_pydantic_function_tool
from pydantic import BaseModel

_UNSUPPORTED_NUMBER_KEYS = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"}

# 툴 이름 → map 스키마에서 entry 배열로 변환된 최상위 필드명 목록
_MAP_FIELDS_BY_TOOL: dict[str, list[str]] = {}


def _strip_number_bounds(node: Any) -> None:
    """JSON Schema 트리에서 Bedrock 미지원 number 제약 키를 제거 (in-place)."""
    if isinstance(node, dict):
        for key in _UNSUPPORTED_NUMBER_KEYS & node.keys():
            del node[key]
        for value in node.values():
            _strip_number_bounds(value)
    elif isinstance(node, list):
        for item in node:
            _strip_number_bounds(item)


def _is_map_schema(prop: Any) -> bool:
    """dict[str, X] 필드가 생성하는 map 스키마인지 판별."""
    return (
        isinstance(prop, dict)
        and prop.get("type") == "object"
        and isinstance(prop.get("additionalProperties"), dict)
    )


def _convert_map_properties(params: dict) -> list[str]:
    """최상위 map 프로퍼티를 {key, value} 항목 배열 스키마로 변환하고 필드명 반환.

    현재 모든 dict 필드가 루트 모델의 최상위 프로퍼티라 최상위만 처리한다.
    중첩 map 이 새로 생기면 스키마 검증 테스트(test_tool_schema)가 잡아낸다.
    """
    converted: list[str] = []
    for name, prop in params.get("properties", {}).items():
        if not _is_map_schema(prop):
            continue
        value_schema = prop["additionalProperties"]
        params["properties"][name] = {
            "type": "array",
            "description": (prop.get("description", "") + " — key/value 항목 배열로 반환").strip(" —"),
            "items": {
                "type": "object",
                "properties": {"key": {"type": "string"}, "value": value_schema},
                "required": ["key", "value"],
                "additionalProperties": False,
            },
        }
        converted.append(name)
    return converted


def restore_map_fields(tool_name: str, args: dict) -> dict:
    """entry 배열로 받은 map 필드를 dict 로 복원 (LLM 응답 후처리).

    모델이 dict 형태로 반환한 경우는 그대로 둔다.
    """
    for field in _MAP_FIELDS_BY_TOOL.get(tool_name, []):
        value = args.get(field)
        if isinstance(value, list):
            args[field] = {
                entry["key"]: entry["value"]
                for entry in value
                if isinstance(entry, dict) and "key" in entry
            }
    return args


def pydantic_function_tool(
    model: Type[BaseModel],
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> Any:
    """openai.pydantic_function_tool + Bedrock 호환 스키마 정리."""
    tool = _openai_pydantic_function_tool(model, name=name, description=description)
    params = tool["function"].get("parameters", {})
    _strip_number_bounds(params)
    map_fields = _convert_map_properties(params)
    if map_fields:
        _MAP_FIELDS_BY_TOOL[tool["function"]["name"]] = map_fields
    return tool
