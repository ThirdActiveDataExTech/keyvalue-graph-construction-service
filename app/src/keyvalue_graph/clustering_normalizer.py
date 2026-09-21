from typing import Any

import logging
import numpy as np
from rapidfuzz import fuzz
from sklearn.cluster import DBSCAN

from app.repositories.graph_repository import GraphRepository
from app.src.meta_extract.llm_response import LLMResponse

logger = logging.getLogger(__name__)


class ClusteringNormalizer:
    """클러스터링 기반 Value 정규화 서비스

    각 Key별로 Value들을 유사도 기반 클러스터링하고,
    각 클러스터의 대표값을 NormalizedValue로 지정
    """

    def __init__(self, graph_repo: GraphRepository = None):
        """GraphRepository를 주입받아 초기화."""
        self.graph_repo = graph_repo or GraphRepository()

    def normalize_all_keys(
            self,
            similarity_threshold: float = 0.85,
            min_cluster_size: int = 2
    ) -> dict[str, Any]:
        """모든 Key의 Value들을 클러스터링하여 정규화

        Args:
            similarity_threshold: 유사도 임계값 (0~1, 높을수록 엄격)
            min_cluster_size: 최소 클러스터 크기 (작은 클러스터 무시)

        Returns:
            통계 정보
        """
        # 1. 모든 Key 조회
        keys = self._get_all_keys()
        logger.info(f"정규화 대상 Key: {len(keys)}개")

        total_clusters = 0
        total_normalized = 0
        failed_keys = 0

        # 2. Key별로 클러스터링 및 정규화
        for key_name in keys:
            try:
                result = self.normalize_key_values(
                    key_name,
                    similarity_threshold,
                    min_cluster_size
                )
                total_clusters += result["clusters_count"]
                total_normalized += result["normalized_count"]
            except Exception as e:
                # Key 정규화 실패 시 스킵
                failed_keys += 1
                logger.warning(
                    f"Key '{key_name}' 정규화 실패 (스킵): {str(e)}"
                )
                continue

        logger.info(
            f"정규화 완료: {len(keys)}개 Key, "
            f"{total_clusters}개 클러스터, "
            f"{total_normalized}개 Value 정규화, "
            f"{failed_keys}개 Key 실패"
        )

        return {
            "keys_count": len(keys),
            "clusters_count": total_clusters,
            "normalized_count": total_normalized,
            "failed_keys": failed_keys
        }

    def normalize_key_values(
            self,
            key_name: str,
            similarity_threshold: float = 0.80,
            min_cluster_size: int = 2
    ) -> dict[str, Any]:
        """특정 Key의 Value들을 클러스터링하여 정규화

        Args:
            key_name: Key명 (예: "병원명")
            similarity_threshold: 유사도 임계값
            min_cluster_size: 최소 클러스터 크기

        Returns:
            통계 정보
        """
        logger.info(f"Key '{key_name}' 정규화 시작")

        # 1. Key의 모든 Value 조회
        values = self._get_values_for_key(key_name)
        if len(values) < min_cluster_size:
            logger.info(f"Key '{key_name}': Value가 {len(values)}개로 너무 적음. 스킵.")
            return {"clusters_count": 0, "normalized_count": 0}

        logger.info(f"Key '{key_name}': {len(values)}개 Value 조회")

        # 2. 숫자 타입 체크
        numeric_values, is_numeric = self._try_parse_numeric(values)

        # 3. 클러스터링 (타입별 분기)
        if is_numeric:
            # 3-A. 숫자 → Gap-based 클러스터링
            logger.info(f"Key '{key_name}': 숫자 타입 감지, Gap-based 클러스터링 수행")
            clusters = self._numeric_gap_clustering(
                values, numeric_values, min_cluster_size
            )
        else:
            # 3-B. 문자열 → RapidFuzz + DBSCAN
            logger.info(f"Key '{key_name}': 문자열 타입, Fuzzy 클러스터링 수행")
            similarity_matrix = self._calculate_similarity_matrix(values)
            distance_matrix = 1 - similarity_matrix
            clustering = DBSCAN(
                eps=1 - similarity_threshold,
                min_samples=min_cluster_size,
                metric='precomputed'
            )
            labels = clustering.fit_predict(distance_matrix)
            clusters = self._group_by_cluster(values, labels, min_cluster_size)

        logger.info(f"Key '{key_name}': {len(clusters)}개 클러스터 생성")

        # 5. 각 클러스터의 대표값 선정 및 정규화
        normalized_count = 0
        skipped_count = 0
        for _, cluster_values in clusters.items():
            try:
                representative = self._select_representative(key_name, cluster_values)
                normalized_count += self._create_normalized_relations(
                    key_name,
                    cluster_values,
                    representative
                )
            except Exception as e:
                # LLM이 tool call을 하지 않거나 기타 에러 발생 시 스킵
                skipped_count += 1
                logger.warning(
                    f"Key '{key_name}' 클러스터 정규화 실패 (스킵): "
                    f"Values={cluster_values[:3]}{'...' if len(cluster_values) > 3 else ''}, "
                    f"Error={str(e)}"
                )
                continue

        logger.info(
            f"Key '{key_name}' 정규화 완료: "
            f"{len(clusters)}개 클러스터, {normalized_count}개 정규화, {skipped_count}개 스킵"
        )

        return {
            "clusters_count": len(clusters),
            "normalized_count": normalized_count
        }

    def _get_all_keys(self) -> list[str]:
        """모든 Key명 조회

        Returns:
            Key명 리스트
        """
        query = """
        MATCH (k:Key)
        RETURN k.name as key_name
        ORDER BY k.name
        """
        results = self.graph_repo.execute_query(query)
        return [r["key_name"] for r in results]

    def _get_values_for_key(self, key_name: str) -> list[str]:
        """특정 Key의 모든 Value 조회 (이미 정규화된 Value 제외)

        Args:
            key_name: Key명

        Returns:
            Value 리스트 (중복 제거, 정규화되지 않은 것만)
        """
        query = """
        MATCH (k:Key {name: $key_name})-[:HAS_VALUE]->(v:Value)
        WHERE NOT (v)-[:SAME_AS]->(:NormalizedValue)
        RETURN DISTINCT v.name as value
        ORDER BY v.name
        """
        results = self.graph_repo.execute_query(query, {"key_name": key_name})
        return [r["value"] for r in results]

    def _calculate_similarity_matrix(self, values: list[str]) -> np.ndarray:
        """Value 간 유사도 행렬 계산

        Args:
            values: Value 리스트

        Returns:
            유사도 행렬 (NxN)
        """
        n = len(values)
        matrix = np.zeros((n, n))

        for i in range(n):
            for j in range(i, n):
                if i == j:
                    matrix[i][j] = 1.0
                else:
                    # Token Sort Ratio (단어 순서 무관)
                    similarity = fuzz.token_sort_ratio(values[i], values[j]) / 100.0
                    matrix[i][j] = similarity
                    matrix[j][i] = similarity

        return matrix

    def _group_by_cluster(
            self,
            values: list[str],
            labels: np.ndarray,
            min_cluster_size: int
    ) -> dict[int, list[str]]:
        """클러스터별로 Value 그룹화

        Args:
            values: Value 리스트
            labels: 클러스터 레이블 (-1은 노이즈)
            min_cluster_size: 최소 클러스터 크기

        Returns:
            {cluster_id: [value1, value2, ...]}
        """
        clusters = {}

        for value, label in zip(values, labels):
            # 노이즈(-1) 제외
            if label == -1:
                continue

            if label not in clusters:
                clusters[label] = []
            clusters[label].append(value)

        # 작은 클러스터 제거
        clusters = {
            cid: vals for cid, vals in clusters.items()
            if len(vals) >= min_cluster_size
        }

        return clusters

    def _select_representative(self, key_name: str, cluster_values: list[str]) -> str:
        """클러스터 대표값 선정 (LLM 기반)

        LLM에게 클러스터 내 값들을 보내서 적절한 정규화 값을 생성하도록 함.

        Args:
            key_name: Key명 (로깅용, LLM에게는 전달하지 않음)
            cluster_values: 클러스터 내 Value 리스트

        Returns:
            LLM이 선택/생성한 대표값
        """
        # 중복 제거하고 정렬 (LLM에게 깔끔하게 보내기)
        unique_values = sorted(set(cluster_values))

        logger.info(
            f"클러스터 대표값 선정 (LLM): Key='{key_name}', "
            f"클러스터 크기={len(cluster_values)}, 고유값={len(unique_values)}"
        )

        # LLM 호출 (Key는 전달하지 않음, Value만 전달)
        llm_response = LLMResponse("cluster_normalize")
        result = llm_response.generate_llm_response(
            variables={
                "cluster_values": unique_values
            }
        )

        representative = result["normalized_value"]

        logger.info(
            f"클러스터 대표값: '{representative}' "
            f"(입력: {unique_values[:3]}{'...' if len(unique_values) > 3 else ''})"
        )

        return representative

    def _create_normalized_relations(
            self,
            key_name: str,
            cluster_values: list[str],
            representative: str
    ) -> int:
        """NormalizedValue 생성 및 SAME_AS 관계 생성

        Args:
            key_name: Key명
            cluster_values: 클러스터 내 모든 Value
            representative: 대표값

        Returns:
            생성된 관계 수
        """
        count = 0
        for value in cluster_values:
            count += 1

        self._create_document_normalized_relations(key_name, cluster_values, representative)

        return count

    def _create_document_normalized_relations(
            self,
            key_name: str,
            cluster_values: list[str],
            representative: str
    ) -> None:
        """Document -[HAS_NORMALIZED_VALUE]-> NormalizedValue 관계 생성

        Args:
            key_name: Key명
            cluster_values: 클러스터 내 모든 Value
            representative: 대표값
        """
        norm_id = f"{key_name}:normalized:{representative}"

        for value in cluster_values:
            query = """
            MATCH (k:Key {name: $key_name})-[:HAS_VALUE]->(v:Value {name: $value})
            MATCH (v)-[:EXTRACTED_FROM]->(d:Document)
            MATCH (nv:NormalizedValue {id: $norm_id})
            MERGE (d)-[r:HAS_NORMALIZED_VALUE]->(nv)
            ON CREATE SET r.created_at = datetime()
            """
            self.graph_repo.execute_query(
                query,
                {
                    "key_name": key_name,
                    "value": value,
                    "norm_id": norm_id
                }
            )

    def _try_parse_numeric(self, values: list[str]) -> tuple[list[float], bool]:
        """값들이 모두 숫자로 변환 가능한지 체크

        Args:
            values: Value 리스트 (문자열)

        Returns:
            (숫자 리스트, 모두 숫자 여부)
        """
        numeric_values = []
        for v in values:
            try:
                # 쉼표 제거 후 변환 시도
                cleaned = v.replace(",", "").strip()
                numeric_values.append(float(cleaned))
            except (ValueError, AttributeError):
                return [], False

        return numeric_values, True

    def _numeric_gap_clustering(
        self,
        original_values: list[str],
        numeric_values: list[float],
        min_cluster_size: int
    ) -> dict[int, list[str]]:
        """숫자 데이터의 Gap-based 클러스터링

        전체 분포를 고려하여 Gap이 큰 지점을 기준으로 클러스터 분리

        Args:
            original_values: 원본 문자열 Value 리스트
            numeric_values: 숫자로 변환된 Value 리스트
            min_cluster_size: 최소 클러스터 크기

        Returns:
            {cluster_id: [value1, value2, ...]}
        """
        # 1. 값과 원본 문자열을 함께 정렬
        sorted_pairs = sorted(zip(numeric_values, original_values), key=lambda x: x[0])
        sorted_numeric = [p[0] for p in sorted_pairs]
        sorted_original = [p[1] for p in sorted_pairs]

        # 2. 인접 값 사이 Gap 계산
        if len(sorted_numeric) < 2:
            return {0: original_values}

        gaps = [sorted_numeric[i+1] - sorted_numeric[i]
                for i in range(len(sorted_numeric) - 1)]

        # 3. 비정상적으로 큰 Gap 찾기
        if len(gaps) == 0:
            return {0: original_values}

        mean_gap = np.mean(gaps)
        std_gap = np.std(gaps)

        # Gap이 평균 + 2*표준편차보다 크면 "큰 Gap"으로 판단
        threshold = mean_gap + 2 * std_gap
        large_gap_indices = [i for i, g in enumerate(gaps) if g > threshold]

        logger.info(
            f"숫자 클러스터링: 값 범위=[{min(sorted_numeric):.2f}, {max(sorted_numeric):.2f}], "
            f"평균 Gap={mean_gap:.2f}, 표준편차={std_gap:.2f}, "
            f"큰 Gap 개수={len(large_gap_indices)}"
        )

        # 4. 큰 Gap을 기준으로 그룹 분리
        clusters_list = []
        start = 0
        for gap_idx in large_gap_indices:
            cluster = sorted_original[start:gap_idx+1]
            if len(cluster) >= min_cluster_size:
                clusters_list.append(cluster)
            start = gap_idx + 1

        # 마지막 그룹
        last_cluster = sorted_original[start:]
        if len(last_cluster) >= min_cluster_size:
            clusters_list.append(last_cluster)

        # 5. Dict 형태로 변환 (기존 반환 형식 유지)
        clusters = {i: cluster for i, cluster in enumerate(clusters_list)}

        return clusters
