SUMMARY = "메타데이터 기반 데이터 관계 생성 API"
DESCRIPTION = (
    "데이터셋 메타데이터 추출&임베딩&파이프라인(규칙 → 유사도 → LLM 검증)으로 "
    "데이터셋 간 관계를 생성하여 Neptune 지식그래프와 OpenSearch에 적재합니다.\n\n"
    "- **Datasets**: 데이터셋 등록·조회·삭제\n"
    "- **Relations**: 관계 생성 파이프라인·조회·승인 반영\n"
    "- **Search**: 유사/자연어/연계 검색과 그래프 시각화\n"
    "- **Catalog**: 통합 카탈로그 연동(등록·동기화)\n"
    "- **KeyValue Graph**: 레코드 수준 Key-Value 그래프(Level 2)"
)
LICENSE_INFO = {
    "name": "Wisenut"
}

OPENAPI_TAGS = [
    {"name": "Datasets", "description": "데이터셋 등록·조회·삭제·현황"},
    {"name": "Search", "description": "유사 테이블 검색, 자연어 검색, 연계 데이터셋 탐색, 부분 그래프 조회"},
    {"name": "Relations", "description": "데이터셋 간 관계 생성(3-Tier 파이프라인)·저장·조회"},
    {"name": "Catalog", "description": "① 통합 카탈로그 연동 — 엔트리 등록, 변경 동기화, 승인 결정 콜백"},
    {"name": "KeyValue Graph", "description": "레코드 수준 Key-Value 그래프 생성·정규화·관계 후보 발굴 (Level 2)"},
    {"name": "System", "description": "헬스체크·버전 정보"},
]

# Graph Embedding 알고리즘 설정 (HashGNN)
GRAPH_EMBEDDING_DIM = 128
HASHGNN_ITERATIONS = 3
HASHGNN_EMBEDDING_DENSITY = 128
