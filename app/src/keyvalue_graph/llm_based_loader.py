import json
from typing import Any, Dict

import logging

from app.src.keyvalue_graph.data_loader import DataRecord
from app.src.keyvalue_graph.field_mappings import FIELD_NAME_MAPPING
from app.src.keyvalue_graph.neptune_graph_builder import NeptuneGraphBuilder
from app.src.keyvalue_graph.text_utils import truncate_single_record
from app.src.meta_extract.llm_response import LLMResponse

logger = logging.getLogger(__name__)


class LLMBasedKeyValueLoader:
    """LLM을 사용하여 데이터로부터 Key-Value를 추출하고 Neptune에 저장하는 서비스."""

    def __init__(self, field_mapping: Dict[str, str] = None):
        """초기화.

        Args:
            field_mapping: 필드명 매핑 (원본 → 한글). None이면 기본 매핑 사용
        """
        self.graph_builder = NeptuneGraphBuilder()
        self.field_mapping = field_mapping or FIELD_NAME_MAPPING

    def extract_and_build_graph(
            self,
            data_text: str,
            centrality_name: str = "병원현황",
            domain: str = None,
            source_file: str = "llm_extract",
            record_index: int = 0,
            extractable_metadata: Dict[str, Any] = None,
            table_name: str = None
    ) -> Dict[str, Any]:
        """데이터로부터 LLM으로 Key-Value를 추출하고 그래프를 생성.

        Args:
            data_text: 원본 데이터 (JSON 문자열)
            centrality_name: 중심 노드 이름 (예: "병원현황", "판례정보")
            domain: 데이터 도메인 (예: "의료", "법률", "방송"). None이면 centrality_name 사용
            source_file: 소스 파일명
            record_index: 레코드 인덱스
            extractable_metadata: 추출 가능한 메타데이터 정의
            table_name: 데이터셋(테이블)명. Level 1 게이팅 기준. None이면 source_file stem 사용.

        Returns:
            그래프 생성 결과
        """
        # domain이 명시되지 않으면 centrality_name 사용 (하위 호환)
        if domain is None:
            domain = centrality_name
        # 0. 데이터 전처리: JSON 파싱 + Truncate
        try:
            raw_data = json.loads(data_text)
        except json.JSONDecodeError:
            raw_data = {}
            logger.warning("JSON 파싱 실패, 빈 데이터 사용")

        # 긴 텍스트 필드 truncate (key_value_extract 컨텍스트: 더 긴 임계값 사용)
        truncated_data = truncate_single_record(raw_data, context="key_value_extract")
        truncated_data_text = json.dumps(truncated_data, ensure_ascii=False)

        logger.info(
            f"데이터 전처리 완료: 원본 {len(data_text)}자 → {len(truncated_data_text)}자"
        )

        # 1. LLM으로 Key-Value 추출
        logger.info("LLM으로 Key-Value 추출 시작")

        # field_mapping이 있으면 추출할 필드 목록 힌트 추가
        if self.field_mapping:
            field_hints_lines = []

            # 원본 필드 + extractable_metadata 필드 구분
            for key, korean_name in self.field_mapping.items():
                # extractable_metadata에 있는 필드면 description 추가
                if extractable_metadata and key in extractable_metadata:
                    meta_info = extractable_metadata[key]
                    field_hints_lines.append(
                        f"- {key} ({korean_name}): {meta_info.description} "
                        f"[source: {meta_info.source_field}]"
                    )
                else:
                    # 원본 필드
                    field_hints_lines.append(f"- {key} ({korean_name})")

            field_hints = "\n".join(field_hints_lines)
            data_with_hints = (
                f"# 추출할 필드 목록:\n{field_hints}\n\n"
                f"# 데이터:\n{truncated_data_text}"
            )
            logger.info(f"필드 힌트 추가: {len(field_hints_lines)}개 필드")
        else:
            data_with_hints = truncated_data_text

        llm_response = LLMResponse("key_value_extract")
        extraction_result = llm_response.generate_llm_response(
            variables={"data_text": data_with_hints}
        )

        if not isinstance(extraction_result, dict):
            raise ValueError(
                f"LLM 응답이 dict가 아닙니다: {type(extraction_result)}"
            )

        raw_key_values = extraction_result.get("key_values", {})
        logger.info(f"추출된 Key 개수: {len(raw_key_values)}")

        # 2. Key를 한글로 매핑 (역매핑 정보도 저장)
        korean_key_values, original_key_mapping = self._map_keys_to_korean(raw_key_values)

        # 3. DataRecord 생성 (원본 데이터 사용)
        record = DataRecord(
            source_file=source_file,
            record_index=record_index,
            raw_data=raw_data,
        )
        # LLM이 추출한 Key-Value를 직접 설정
        record.key_values = korean_key_values
        record.original_key_mapping = original_key_mapping

        # 4. 그래프 생성 (Neptune + OpenSearch) - 에러 발생 시 예외 전파
        result = self.graph_builder.build_from_record(
            record,
            centrality_name=centrality_name,
            domain=domain,
            table_name=table_name
        )

        logger.info(
            f"그래프 생성 완료: Centrality={centrality_name}, Document={result['document_id']}, "
            f"Keys={result['keys_count']}, Values={result['values_count']}"
        )

        return {
            "success": True,
            "centrality_name": centrality_name,
            "document_id": result["document_id"],
            "keys_count": result["keys_count"],
            "values_count": result["values_count"],
            "normalized_count": 0,
            "extraction": {
                "raw_keys": list(raw_key_values.keys()),
                "korean_keys": list(korean_key_values.keys()),
            },
        }

    def _map_keys_to_korean(
            self, raw_key_values: Dict[str, list[str]]
    ) -> tuple[Dict[str, list[str]], Dict[str, str]]:
        """원본 필드명을 한글로 매핑.

        Args:
            raw_key_values: 원본 Key-Value (예: {"BIZPLC_NM": ["병원명"], ...})

        Returns:
            (한글 매핑된 Key-Value, 한글→원본 매핑)
        """
        korean_key_values = {}
        original_key_mapping = {}

        for raw_key, values in raw_key_values.items():
            # 한글 매핑 조회 (인스턴스 field_mapping 사용)
            korean_key = self.field_mapping.get(raw_key, raw_key)

            # 빈 배열이면 건너뛰기
            if not values:
                continue

            korean_key_values[korean_key] = values
            original_key_mapping[korean_key] = raw_key

        logger.info(
            f"Key 매핑 완료: {len(raw_key_values)} → {len(korean_key_values)}"
        )
        return korean_key_values, original_key_mapping
