from typing import Optional

import logging
import numpy as np
from sklearn.cluster import HDBSCAN

from app.src.embedding.embedding_service import embedding_service
from app.src.meta_extract.llm_response import LLMResponse

logger = logging.getLogger(__name__)


class ProperNounLabeler:
    """고유명사 Taxonomy 레이블링

    표준 Taxonomy 우선 사용, 없으면 LLM 기반 클러스터링으로 생성
    """

    def __init__(self):
        """Init - Taxonomy 캐시"""
        self.taxonomy_cache: dict[str, list[str]] = {}

    def label_values(
            self,
            key_name: str,
            values: list[str],
            force_rebuild_taxonomy: bool = False
    ) -> dict[str, str]:
        """고유명사 값들에 Taxonomy 레이블 부여

        Args:
            key_name: Key명
            values: 값 목록
            force_rebuild_taxonomy: Taxonomy 강제 재생성

        Returns:
            {value: taxonomy_label} 매핑
        """
        if not values:
            return {}

        # 1. 표준 Taxonomy 우선 사용
        from app.src.keyvalue_graph.field_mappings import FIELD_TAXONOMY_MAPPING

        standard_taxonomy = FIELD_TAXONOMY_MAPPING.get(key_name)

        if standard_taxonomy:
            logger.info(f"표준 Taxonomy 적용: {key_name}")
            return self._apply_standard_taxonomy(key_name, values, standard_taxonomy)

        # 2. 표준이 없으면 LLM 기반 Taxonomy 생성
        if key_name not in self.taxonomy_cache or force_rebuild_taxonomy:
            logger.info(f"LLM 기반 Taxonomy 생성 시작: {key_name}")
            self.taxonomy_cache[key_name] = self._build_taxonomy(key_name, values)
            logger.info(f"Taxonomy 생성 완료: {self.taxonomy_cache[key_name]}")

        taxonomy = self.taxonomy_cache[key_name]

        # LLM으로 일괄 레이블링
        return self._batch_labeling(key_name, values, taxonomy)

    def _apply_standard_taxonomy(
            self,
            key_name: str,
            values: list[str],
            standard_taxonomy: list[str]
    ) -> dict[str, str]:
        """표준 Taxonomy 적용 (키워드 기반 + LLM fallback)"""
        from app.src.keyvalue_graph.field_mappings import TAXONOMY_KEYWORD_RULES

        result = {}

        for value in values:
            matched_label = None

            # 키워드 규칙 매칭
            for keyword, label in TAXONOMY_KEYWORD_RULES.items():
                if keyword in value and label in standard_taxonomy:
                    matched_label = label
                    break

            # 매칭 실패 시 LLM
            if not matched_label:
                labels = self._batch_labeling(key_name, [value], standard_taxonomy)
                matched_label = labels.get(value, "기타")

            result[value] = matched_label

        return result

    def _build_taxonomy(self, key_name: str, sample_values: list[str]) -> list[str]:
        """LLM 기반 Taxonomy 생성 (Open-ended → 클러스터링)"""
        samples = sample_values[:50]

        # Open-ended 레이블링
        values_str = "\n".join([f"  - {v}" for v in samples])

        try:
            llm_response = LLMResponse(task="proper_noun_labeling")
            # Open-ended용 임시 taxonomy (LLM이 자유롭게 생성)
            result = llm_response.generate_llm_response(
                variables={
                    "key_name": key_name,
                    "values_list": values_str,
                    "taxonomy": "자유 형식으로 레이블 생성"
                }
            )

            raw_labels = [item["label"] for item in result["labels"]]
            unique_labels = list(set(raw_labels))

            # 클러스터링 (레이블이 많으면)
            if len(unique_labels) > 5:
                return self._cluster_labels(unique_labels)
            else:
                return unique_labels

        except Exception as e:
            logger.error(f"Taxonomy 생성 실패: {e}")
            return ["기타"]

    def _cluster_labels(self, labels: list[str]) -> list[str]:
        """레이블 클러스터링 → 대표 레이블 선정"""
        try:
            embeddings = [embedding_service.generate_embedding(lbl, show_progress_bar=False) for lbl in labels]
            embeddings_array = np.array(embeddings)

            clusterer = HDBSCAN(min_cluster_size=2, metric='euclidean')
            cluster_ids = clusterer.fit_predict(embeddings_array)

            # 클러스터별 대표 레이블
            taxonomy = []
            for cluster_id in set(cluster_ids):
                if cluster_id == -1:
                    # Noise는 모두 포함
                    taxonomy.extend([labels[i] for i, cid in enumerate(cluster_ids) if cid == -1])
                else:
                    # 클러스터 대표 (첫 번째)
                    idx = [i for i, cid in enumerate(cluster_ids) if cid == cluster_id][0]
                    taxonomy.append(labels[idx])

            return taxonomy

        except Exception as e:
            logger.warning(f"클러스터링 실패: {e}")
            return labels

    def _batch_labeling(
            self,
            key_name: str,
            values: list[str],
            taxonomy: list[str]
    ) -> dict[str, str]:
        """LLM으로 일괄 레이블링 (Constrained)"""
        values_str = "\n".join([f"  - {v}" for v in values])
        taxonomy_str = "\n".join([f"  - {t}" for t in taxonomy])

        try:
            llm_response = LLMResponse(task="proper_noun_labeling")
            result = llm_response.generate_llm_response(
                variables={
                    "key_name": key_name,
                    "values_list": values_str,
                    "taxonomy": taxonomy_str
                }
            )

            # {value: label} 매핑 생성
            label_map = {}
            for item in result["labels"]:
                val = item["value"]
                lbl = item["label"]
                # 유효성 검증
                if lbl not in taxonomy and lbl != "기타":
                    lbl = "기타"
                label_map[val] = lbl

            return label_map

        except Exception as e:
            logger.error(f"레이블링 실패: {e}")
            return {v: "기타" for v in values}

    def get_taxonomy(self, key_name: str) -> Optional[list[str]]:
        """Taxonomy 조회"""
        return self.taxonomy_cache.get(key_name)


# 싱글톤 인스턴스
proper_noun_labeler = ProperNounLabeler()
