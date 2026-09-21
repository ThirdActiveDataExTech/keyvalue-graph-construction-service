from typing import List

from app.schemas.tool_utils import pydantic_function_tool
from pydantic import BaseModel, Field


class KeyValueExtractionResult(BaseModel):
    """Key-Value 추출 결과"""
    key_values: dict[str, List[str]] = Field(
        ...,
        description="추출된 Key-Value 쌍. Key는 원본 필드명(예: 'BIZPLC_NM'), Value는 문자열 배열"
    )


key_value_extraction_tool = pydantic_function_tool(
    KeyValueExtractionResult,
    name="extract_key_value_pairs",
    description="데이터에서 모든 필드명(Key)과 그 값(Value)을 추출합니다."
)


class ClusterNormalizationResult(BaseModel):
    """클러스터 정규화 결과"""
    normalized_value: str = Field(
        ...,
        description="클러스터를 대표하는 정규화된 값. 원본 값 중 하나를 선택하거나 적절한 메타 개념을 생성."
    )


cluster_normalization_tool = pydantic_function_tool(
    ClusterNormalizationResult,
    name="normalize_cluster",
    description="유사한 값들의 클러스터를 분석하여 적절한 정규화 값을 생성합니다."
)
