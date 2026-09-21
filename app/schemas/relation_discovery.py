"""관계 발굴을 위한 스키마 정의"""

from pydantic import BaseModel, Field
from app.schemas.tool_utils import pydantic_function_tool


class KeyImportance(BaseModel):
    """Key의 중요도 정보"""

    key_name: str = Field(description="Key명 (예: '병원명', '지역')")
    feature_class: str = Field(
        description="Key의 특성 분류: 'identity'(식별자), 'location'(위치), 'categorical'(범주형), 'numeric'(숫자), 'free-text'(자유텍스트)"
    )
    importance: float = Field(ge=0.0, le=1.0, description="중요도 (0~1, 높을수록 관계 판단에 중요)")
    reason: str = Field(description="중요하다고 판단한 이유")


class RelationSearchCondition(BaseModel):
    """관계 검색 조건"""

    important_keys: list[KeyImportance] = Field(
        description="관계 판단에 중요한 Key 목록 (중요도 순으로 정렬)"
    )
    search_strategy: str = Field(
        description="검색 전략 설명 (예: '같은 지역의 유사 규모 병원 찾기')"
    )
    expected_relation_count: int = Field(
        ge=1, le=20, description="예상되는 관계 Document 개수 (1~20)"
    )


# OpenAI Tool 정의
relation_search_condition_tool = pydantic_function_tool(
    RelationSearchCondition,
    name="analyze_relation_search_condition",
    description="Document의 Key-Value 메타데이터를 분석하여 관계 있는 Document를 찾기 위한 검색 조건을 생성합니다.",
)
