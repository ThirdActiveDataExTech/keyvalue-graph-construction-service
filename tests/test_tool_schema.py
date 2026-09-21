"""LLM function tool 스키마의 Bedrock 호환성 검증.

Bedrock Claude 는 tool 스키마의 number 타입에 minimum/maximum 이 있으면
400 을 반환하므로, 모든 툴 스키마에 해당 키가 없어야 한다 (tool_utils 참고).
"""

from app.schemas.keyvalue_graph import field_type_classification_tool, proper_noun_labeling_tool
from app.schemas.meta import cluster_normalization_tool, key_value_extraction_tool
from app.schemas.relation_discovery import relation_search_condition_tool
from app.schemas.schema_analysis import schema_analysis_tool

ALL_TOOLS = [
    field_type_classification_tool,
    proper_noun_labeling_tool,
    key_value_extraction_tool,
    cluster_normalization_tool,
    relation_search_condition_tool,
    schema_analysis_tool,
]

_FORBIDDEN = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"}


def _has_bounds(node) -> bool:
    if isinstance(node, dict):
        if _FORBIDDEN & node.keys():
            return True
        return any(_has_bounds(v) for v in node.values())
    if isinstance(node, list):
        return any(_has_bounds(i) for i in node)
    return False


def test_no_number_bounds_in_tool_schemas():
    for tool in ALL_TOOLS:
        fn = tool["function"]
        assert not _has_bounds(fn.get("parameters", {})), f"{fn['name']} 에 minimum/maximum 잔존"


def _has_map_schema(node) -> bool:
    """additionalProperties 가 object 인 map 스키마 잔존 여부 (Bedrock 400 원인)."""
    if isinstance(node, dict):
        if node.get("type") == "object" and isinstance(node.get("additionalProperties"), dict):
            return True
        return any(_has_map_schema(v) for v in node.values())
    if isinstance(node, list):
        return any(_has_map_schema(i) for i in node)
    return False


def test_no_map_schemas_in_tool_schemas():
    for tool in ALL_TOOLS:
        fn = tool["function"]
        assert not _has_map_schema(fn.get("parameters", {})), f"{fn['name']} 에 map 스키마 잔존"


def test_dict_fields_converted_to_entry_arrays():
    """dict 필드가 {key, value} 항목 배열로 변환되었는지 확인."""
    params = key_value_extraction_tool["function"]["parameters"]
    kv = params["properties"]["key_values"]
    assert kv["type"] == "array"
    assert set(kv["items"]["required"]) == {"key", "value"}

    params = schema_analysis_tool["function"]["parameters"]
    for field in ("fields", "extractable_metadata"):
        assert params["properties"][field]["type"] == "array", field


def test_restore_map_fields_round_trip():
    from app.schemas.tool_utils import restore_map_fields

    tool_name = key_value_extraction_tool["function"]["name"]
    args = {"key_values": [{"key": "병원명", "value": ["서울대병원"]}, {"key": "시도", "value": ["서울"]}]}
    restored = restore_map_fields(tool_name, args)
    assert restored["key_values"] == {"병원명": ["서울대병원"], "시도": ["서울"]}

    args = {"key_values": {"병원명": ["서울대병원"]}}
    assert restore_map_fields(tool_name, args)["key_values"] == {"병원명": ["서울대병원"]}
