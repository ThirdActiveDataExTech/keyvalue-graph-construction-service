# keyvalue-graph-builder

> Key-Value 그래프 기반 데이터 구조 분석 및 값 정규화 그래프 구축

## 개요

도메인 스키마를 모르는 이기종 데이터를 **Key-Value 그래프**로 구조화한다. 필드명·값을
노드로 올리고 표기가 다른 값을 대표값으로 정규화해, 값을 공유하는 레코드 사이의 관계
후보를 찾는다.

```
Document ─HAS_KEY→ Key ─HAS_VALUE→ Value ─SAME_AS→ NormalizedValue
                                     └─EXTRACTED_FROM→ Document
```

| 단계 | 모듈 | 하는 일 |
|---|---|---|
| 스키마 분석 | `schema_analyzer` | 필드 통계·타입·추출 대상 판별 |
| KV 추출 | `llm_based_loader` | 레코드 → Key/Value 쌍 |
| 고유명사 라벨링 | `proper_noun_labeler` | 분류체계 태깅 |
| 값 정규화 | `clustering_normalizer` | 표기 변형 → 대표값 |
| 그래프 적재 | `neptune_graph_builder` | Neptune(RDF) + OpenSearch 색인 |
| 관계 후보 | `relation_candidate_finder` | 공유 값 기반 후보 탐색 |

## 실행

```bash
uv sync --all-groups
cp .env.example .env    # 접속 정보 입력
uv run fastapi dev app/main.py
```

## 주요 API

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/keyvalue-graph/analyze-schema` | 스키마 분석 |
| POST | `/keyvalue-graph/build` | KV 그래프 생성·적재 |
| POST | `/keyvalue-graph/normalize` | 값 클러스터 정규화 |
| POST | `/keyvalue-graph/relations` | 레코드 관계 후보 탐색 |
| POST | `/workflow/execute` | 파일 업로드 → 전 과정 실행 (SSE) |

## 연계 모듈

레코드 관계 후보 탐색 범위는 [dataset-relation-generator](../dataset-relation-generator) 가
생성한 데이터셋 간 관계(Level 1)로 좁힌다(`level1_gating`). Neptune 질의로만 연결되며
코드 의존은 없고, Level 1 관계가 없으면 자기 데이터셋 안에서만 탐색한다.

## 라이선스

Apache License 2.0 — [LICENSE](LICENSE)
