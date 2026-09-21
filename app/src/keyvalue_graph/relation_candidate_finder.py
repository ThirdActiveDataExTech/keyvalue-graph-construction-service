"""관계 후보 Document 발굴 서비스 (Level 2, 온디맨드).

설계 문서 §8 구현. 핵심 경로는 "Key 먼저 → 연결된 Value 검색"(§8.2)으로,
OpenSearch 의 k-NN 인덱스를 사용한다. 후보 탐색 범위는 Level 1에서 연결된
데이터셋으로 제한(게이팅)된다(§2, §8).

종합 점수(§8.4):
    final = 0.40·KeyAlignment + 0.30·TypedValueMatch
            + 0.20·GraphStructure(현재 placeholder 0.0, 4차년도 GNN)
            + 0.10·DocumentSemantic
"""

import logging
import math
from typing import Any, Optional

from app.config import settings
from app.repositories.opensearch_repository import OpenSearchRepository, get_opensearch_repository
from app.src.embedding.embedding_service import embedding_service

logger = logging.getLogger(__name__)

# Level 2 관계 유형 (§8.6) — 최소 3종
RELATION_SAME_AS = "SAME_AS"
RELATION_RELATED_TO = "RELATED_TO"
RELATION_REFERENCES = "REFERENCES"


def _clamp01(x: float) -> float:
    """점수를 [0, 1] 범위로 클램프."""
    return max(0.0, min(1.0, x))


class RelationCandidate:
    """관계 후보 Document 정보."""

    def __init__(
        self,
        doc_id: str,
        aligned_attribute_score: float,
        typed_value_match_score: float,
        graph_structure_similarity: float,
        document_semantic_score: float,
        matched_keys: list[str],
        matched_values: dict[str, str],
        relation_type: str = RELATION_RELATED_TO,
        table_name: str = "",
    ):
        """RelationCandidate 초기화."""
        self.doc_id = doc_id
        self.aligned_attribute_score = aligned_attribute_score  # Key 정렬 (의미적 스키마 매칭)
        self.typed_value_match_score = typed_value_match_score  # 타입별 값 비교
        self.graph_structure_similarity = graph_structure_similarity  # GraphSAGE 구조 유사도 (placeholder)
        self.document_semantic_score = document_semantic_score  # 문서 전체 의미 유사도
        self.matched_keys = matched_keys
        self.matched_values = matched_values
        self.relation_type = relation_type
        self.table_name = table_name
        self.final_score = self._calculate_final_score()

    def _calculate_final_score(self) -> float:
        """최종 점수 계산 (§8.4 가중치)."""
        return (
            0.40 * self.aligned_attribute_score
            + 0.30 * self.typed_value_match_score
            + 0.20 * self.graph_structure_similarity
            + 0.10 * self.document_semantic_score
        )

    def to_dict(self) -> dict[str, Any]:
        """후보 정보를 딕셔너리로 변환."""
        return {
            "doc_id": self.doc_id,
            "table_name": self.table_name,
            "relation_type": self.relation_type,
            "score": round(self.final_score, 3),
            "breakdown": {
                "aligned_attribute": round(self.aligned_attribute_score, 3),
                "typed_value_match": round(self.typed_value_match_score, 3),
                "graph_structure": round(self.graph_structure_similarity, 3),
                "document_semantic": round(self.document_semantic_score, 3),
            },
            "matched_keys": self.matched_keys,
            "matched_values": self.matched_values,
        }


class RelationCandidateFinder:
    """관계 후보 Document 발굴 서비스 (OpenSearch 2단 검색 + Level 1 게이팅)."""

    def __init__(self, opensearch_repo: OpenSearchRepository | None = None):
        """RelationCandidateFinder 초기화."""
        self.os_repo = opensearch_repo or get_opensearch_repository()

    # ──────────────────────────────────────────────
    # Entry point
    # ──────────────────────────────────────────────

    def find_candidates(
        self,
        source_doc_id: str,
        important_keys: list[str],
        important_values: dict[str, list[str]],
        feature_classes: Optional[dict[str, str]] = None,
        allowed_table_names: Optional[set[str]] = None,
        top_k: int = 10,
    ) -> list[RelationCandidate]:
        """관계 후보 Document 검색.

        Args:
            source_doc_id: 기준 Document ID
            important_keys: 중요 Key 목록 (LLM이 선정)
            important_values: 중요 Key의 실제 값들 {key_name: [values]}
            feature_classes: 중요 Key별 feature_class {key_name: identity/location/...}
                (Level 2 관계 유형 판정에 사용)
            allowed_table_names: Level 1 게이팅 — 후보가 속할 수 있는 데이터셋 집합.
                None이면 게이팅하지 않음(전체 탐색).
            top_k: 반환할 후보 개수

        Returns:
            RelationCandidate 리스트 (점수 순)
        """
        feature_classes = feature_classes or {}
        allowed_list = sorted(allowed_table_names) if allowed_table_names else None

        logger.info(
            f"관계 후보 검색 시작: {source_doc_id}, 중요 Key={important_keys}, "
            f"게이팅={'없음' if allowed_list is None else allowed_list}"
        )

        # 기준 레코드의 Key-Value 메타데이터 (key_type, numeric_value) 조회
        source_kv = self._load_source_kv(source_doc_id)

        # 후보 집계: doc_id -> {aligned, typed, matched_keys, matched_values, table_name}
        candidates: dict[str, dict[str, Any]] = {}

        for key_name in important_keys:
            kv_info = source_kv.get(key_name)
            key_type = kv_info["key_type"] if kv_info else "semantic"
            source_values = important_values.get(key_name) or (kv_info["values"] if kv_info else [])
            if not source_values:
                continue

            # ── §8.2 1단: Key 먼저 검색 (이형 동의어 흡수) ──
            key_vec = embedding_service.generate_embedding(key_name)
            similar_keys = self.os_repo.search_keys(key_vec, top_k=settings.LEVEL2_KEY_SEARCH_K)
            if not similar_keys:
                continue
            parent_key_ids = [k["key_id"] for k in similar_keys]
            key_alignment = self._aggregate_key_alignment(similar_keys)
            matched_key_names = [k["key_name"] for k in similar_keys]

            # ── §8.2 2단: 연결된 Value 검색 (게이팅 범위 내) ──
            for source_value in source_values:
                value_vec = embedding_service.generate_embedding(str(source_value))
                value_hits = self.os_repo.search_values(
                    value_vec,
                    parent_key_ids=parent_key_ids,
                    top_k=settings.LEVEL2_VALUE_SEARCH_K,
                    allowed_table_names=allowed_list,
                )
                self._accumulate(
                    candidates,
                    key_name,
                    key_type,
                    str(source_value),
                    kv_info,
                    key_alignment,
                    matched_key_names,
                    value_hits,
                    source_doc_id,
                )

        if not candidates:
            return []

        # 정규화: 누적 점수를 중요 Key 수로 평균
        n_keys = max(len(important_keys), 1)

        results: list[RelationCandidate] = []
        for doc_id, agg in candidates.items():
            aligned = _clamp01(agg["aligned"] / n_keys)
            typed = _clamp01(agg["typed"] / n_keys)
            doc_sem = self._document_semantic(source_doc_id, doc_id)
            graph_sim = self._graph_structure_similarity(source_doc_id, doc_id)

            candidate = RelationCandidate(
                doc_id=doc_id,
                aligned_attribute_score=aligned,
                typed_value_match_score=typed,
                graph_structure_similarity=graph_sim,
                document_semantic_score=doc_sem,
                matched_keys=sorted(agg["matched_keys"]),
                matched_values=agg["matched_values"],
                table_name=agg["table_name"],
            )
            candidate.relation_type = self._classify_relation_type(
                candidate, agg, important_values, feature_classes
            )
            results.append(candidate)

        results.sort(key=lambda c: c.final_score, reverse=True)
        logger.info(f"관계 후보 {len(results)}개 발견, 상위 {top_k}개 반환")
        return results[:top_k]

    # ──────────────────────────────────────────────
    # 내부 로직
    # ──────────────────────────────────────────────

    def _load_source_kv(self, source_doc_id: str) -> dict[str, dict[str, Any]]:
        """기준 Document의 Key-Value(타입/숫자값 포함)를 OpenSearch에서 조회."""
        rows = self.os_repo.get_document_key_values(source_doc_id)
        kv: dict[str, dict[str, Any]] = {}
        for r in rows:
            key = r.get("parent_key_name", "")
            if not key:
                continue
            entry = kv.setdefault(
                key,
                {"key_type": r.get("parent_key_type", "semantic"), "values": [], "numeric_values": []},
            )
            entry["values"].append(r.get("value_content", ""))
            if r.get("numeric_value") is not None:
                entry["numeric_values"].append(float(r["numeric_value"]))
        return kv

    @staticmethod
    def _aggregate_key_alignment(similar_keys: list[dict[str, Any]]) -> float:
        """search_keys 결과 점수를 Key 정렬 신호(0~1)로 집계."""
        if not similar_keys:
            return 0.0
        return _clamp01(max(k.get("score", 0.0) for k in similar_keys))

    def _accumulate(
        self,
        candidates: dict[str, dict[str, Any]],
        key_name: str,
        key_type: str,
        source_value: str,
        kv_info: Optional[dict[str, Any]],
        key_alignment: float,
        matched_key_names: list[str],
        value_hits: list[dict[str, Any]],
        source_doc_id: str,
    ) -> None:
        """Value 검색 결과를 후보 Document별로 누적 (타입별 비교 §8.3 반영)."""
        source_numeric = None
        if kv_info and kv_info.get("numeric_values"):
            source_numeric = kv_info["numeric_values"][0]

        for hit in value_hits:
            for doc_id in hit.get("document_ids", []):
                if doc_id == source_doc_id:
                    continue

                typed_score = self._typed_value_score(
                    key_type, source_value, source_numeric, hit
                )
                if typed_score <= 0.0:
                    continue

                agg = candidates.setdefault(
                    doc_id,
                    {
                        "aligned": 0.0,
                        "typed": 0.0,
                        "matched_keys": set(),
                        "matched_values": {},
                        "table_name": hit.get("table_name", ""),
                        "exact_keys": set(),
                    },
                )
                agg["aligned"] += key_alignment
                agg["typed"] += typed_score
                agg["matched_keys"].update(matched_key_names)
                agg["matched_values"][key_name] = hit.get("value_content", "")
                if not agg["table_name"]:
                    agg["table_name"] = hit.get("table_name", "")
                # 값이 정확히 일치하면 강한 식별 신호로 기록 (관계 유형 판정용)
                if str(hit.get("value_content", "")).strip() == source_value.strip():
                    agg["exact_keys"].add(key_name)

    def _typed_value_score(
        self,
        key_type: str,
        source_value: str,
        source_numeric: Optional[float],
        hit: dict[str, Any],
    ) -> float:
        """key_type 별 Value 비교 점수 산출 (§8.3)."""
        if key_type == "numeric_date":
            target_numeric = hit.get("numeric_value")
            if source_numeric is None or target_numeric is None:
                return 0.0
            scale = max(abs(source_numeric) * 0.5, 100.0)
            return _clamp01(1.0 - abs(source_numeric - float(target_numeric)) / scale)

        # semantic / proper_noun: 임베딩 코사인 유사도 (OpenSearch k-NN 점수 사용)
        sim = _clamp01(hit.get("score", 0.0))
        if key_type == "proper_noun":
            # taxonomy 동일 범주 가중(근사): 값이 정확 일치하면 가중 상향
            if str(hit.get("value_content", "")).strip() == source_value.strip():
                sim = _clamp01(sim * 1.5)
        return sim

    def _document_semantic(self, source_doc_id: str, target_doc_id: str) -> float:
        """문서 전체 의미 유사도 (보조 지표, §8.4 10%).

        documents 인덱스에 저장된 문서 임베딩 간 코사인 유사도. 조회 실패 시 0.0.
        """
        try:
            client = self.os_repo.client.client
            resp = client.mget(
                index=self.os_repo.documents_index,
                body={"ids": [source_doc_id, target_doc_id]},
            )
            docs = {d["_id"]: d.get("_source", {}) for d in resp.get("docs", []) if d.get("found")}
            v1 = docs.get(source_doc_id, {}).get("embedding")
            v2 = docs.get(target_doc_id, {}).get("embedding")
            if not v1 or not v2:
                return 0.0
            return _clamp01(self._cosine(v1, v2))
        except Exception:
            return 0.0

    @staticmethod
    def _cosine(v1: list[float], v2: list[float]) -> float:
        """두 벡터의 코사인 유사도."""
        dot = sum(a * b for a, b in zip(v1, v2))
        n1 = math.sqrt(sum(a * a for a in v1))
        n2 = math.sqrt(sum(b * b for b in v2))
        if n1 == 0 or n2 == 0:
            return 0.0
        return dot / (n1 * n2)

    @staticmethod
    def _graph_structure_similarity(_source_doc_id: str, _target_doc_id: str) -> float:
        """GraphSAGE 기반 구조 유사도.

        4차년도 GNN/GraphSAGE 관계 생성 모델로 활성화 예정(§8.4, §10.4).
        현재는 placeholder 0.0.
        """
        return 0.0

    def _classify_relation_type(
        self,
        candidate: RelationCandidate,
        agg: dict[str, Any],
        important_values: dict[str, list[str]],
        feature_classes: dict[str, str],
    ) -> str:
        """Level 2 관계 유형 판정 (§8.6).

        - SAME_AS: 식별/위치 Key가 정확히 일치하고 종합 점수가 매우 높음 (동일 개체).
        - REFERENCES: 식별자(identity) Key가 일치 (한 레코드가 다른 레코드를 참조).
        - RELATED_TO: 그 외 (공유 속성/유사 값으로 의미적 연관).
        """
        exact_keys = agg.get("exact_keys", set())
        identity_keys = {k for k in exact_keys if feature_classes.get(k) == "identity"}
        strong_keys = {k for k in exact_keys if feature_classes.get(k) in ("identity", "location")}

        if strong_keys and candidate.final_score >= settings.LEVEL2_SAME_AS_THRESHOLD:
            return RELATION_SAME_AS
        if identity_keys:
            return RELATION_REFERENCES
        return RELATION_RELATED_TO
