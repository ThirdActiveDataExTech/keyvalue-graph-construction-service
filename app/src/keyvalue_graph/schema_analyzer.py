from collections import Counter
from typing import Any, Dict, List
import re

import logging

from app.schemas.schema_analysis import FieldStatistics, FieldAnalysis, SchemaAnalysisResult
from app.src.meta_extract.llm_response import LLMResponse
from app.src.keyvalue_graph.text_utils import (
    detect_long_text_fields,
    truncate_long_text_fields
)

logger = logging.getLogger(__name__)


class SchemaAnalyzer:
    """데이터 샘플링 + 통계 분석 기반 스키마 추론"""

    def __init__(self, sample_size: int = 5):
        """초기화

        Args:
            sample_size: 샘플링할 레코드 개수
        """
        self.sample_size = sample_size

    def analyze(self, records: List[Dict[str, Any]]) -> SchemaAnalysisResult:
        """데이터를 분석하여 스키마 추론

        Args:
            records: 데이터 레코드 리스트

        Returns:
            SchemaAnalysisResult
        """
        if not records:
            raise ValueError("레코드가 비어있습니다")

        logger.info(f"스키마 분석 시작: {len(records)}개 레코드")

        # 1. 샘플 데이터 추출
        sample_records = self._sample_records(records)

        # 2. 필드별 통계 수집
        field_statistics = self._collect_statistics(records)

        # 3. LLM에게 분석 요청 (extractable_metadata만)
        schema = self._llm_inference(sample_records, field_statistics)

        # 4. fields 자동 생성 (LLM이 생성하지 않았을 경우)
        if not schema.fields:
            schema.fields = self._auto_generate_fields(field_statistics)
            logger.info(f"원본 필드 자동 생성: {len(schema.fields)}개")

        logger.info(
            f"스키마 분석 완료: 도메인={schema.domain}, "
            f"중심노드={schema.centrality_name}, "
            f"필드 {len(schema.fields)}개, "
            f"추출 메타데이터 {len(schema.extractable_metadata)}개, "
            f"신뢰도={schema.confidence:.2f}"
        )

        return schema

    def _sample_records(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """레코드 샘플링

        Args:
            records: 전체 레코드

        Returns:
            샘플 레코드 리스트
        """
        # 균등하게 샘플링 (처음, 중간, 끝)
        if len(records) <= self.sample_size:
            return records

        step = len(records) // self.sample_size
        indices = [i * step for i in range(self.sample_size)]
        samples = [records[i] for i in indices]

        logger.info(f"샘플링: {len(records)}개 중 {len(samples)}개 추출")
        return samples

    def _auto_generate_fields(
        self, field_statistics: Dict[str, FieldStatistics]
    ) -> Dict[str, FieldAnalysis]:
        """필드 자동 생성 (통계 기반 간단한 타입 추론)

        Args:
            field_statistics: 필드별 통계

        Returns:
            필드명 → FieldAnalysis 딕셔너리
        """
        fields = {}

        for field_name, stats in field_statistics.items():
            # 타입 추론 (간단한 휴리스틱)
            data_type = self._infer_data_type(stats)

            # 한글명: 필드명 그대로 사용 (또는 언더스코어를 공백으로)
            korean_name = field_name.replace("_", " ")

            fields[field_name] = FieldAnalysis(
                korean_name=korean_name,
                description=f"자동 생성된 필드 (타입: {data_type})",
                data_type=data_type
            )

        logger.info(f"필드 자동 생성 완료: {len(fields)}개")
        return fields

    def _infer_data_type(self, stats: FieldStatistics) -> str:
        """통계 기반 데이터 타입 추론

        Args:
            stats: 필드 통계

        Returns:
            추론된 타입 (text, number, date, url, email, address, phone 등)
        """
        if not stats.samples:
            return "text"

        # 샘플 값들 확인
        sample = stats.samples[0] if stats.samples else ""

        # URL 패턴
        if re.match(r"^https?://", sample):
            return "url"

        # Email 패턴
        if "@" in sample and "." in sample:
            return "email"

        # 전화번호 패턴
        if re.match(r"^[\d\-\s\(\)]+$", sample) and len(sample) >= 9:
            return "phone"

        # 날짜 패턴
        if re.match(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", sample):
            return "date"

        # 숫자 패턴 (모든 샘플이 숫자)
        if all(
            re.match(r"^[\d.,]+$", s) for s in stats.samples[:3] if s
        ):
            return "number"

        # 주소 패턴 (시, 구, 동, 로, 길 포함)
        if any(keyword in sample for keyword in ["시", "구", "동", "로", "길"]):
            return "address"

        # 기본: text
        return "text"

    def _collect_statistics(
            self, records: List[Dict[str, Any]]
    ) -> Dict[str, FieldStatistics]:
        """필드별 통계 정보 수집

        Args:
            records: 전체 레코드

        Returns:
            필드명 → FieldStatistics 딕셔너리
        """
        # 모든 필드명 추출
        all_fields = set()
        for record in records:
            all_fields.update(record.keys())

        statistics = {}
        total_count = len(records)

        for field in all_fields:
            # 필드별 값 수집
            values = []
            null_count = 0

            for record in records:
                value = record.get(field)
                if value is None or value == "":
                    null_count += 1
                else:
                    values.append(str(value))

            # 통계 계산
            unique_count = len(set(values))
            null_ratio = null_count / total_count if total_count > 0 else 0.0

            # 샘플 값 추출 (최대 5개, 중복 제거 후 빈도순)
            value_counter = Counter(values)
            samples = [val for val, _ in value_counter.most_common(5)]

            # 값 길이 통계
            if values:
                lengths = [len(v) for v in values]
                value_lengths = {
                    "min": min(lengths),
                    "max": max(lengths),
                    "avg": sum(lengths) // len(lengths),
                }
            else:
                value_lengths = {"min": 0, "max": 0, "avg": 0}

            statistics[field] = FieldStatistics(
                total_count=total_count,
                unique_count=unique_count,
                null_count=null_count,
                null_ratio=round(null_ratio, 3),
                samples=samples,
                value_lengths=value_lengths,
            )

        logger.info(f"통계 수집 완료: {len(statistics)}개 필드")
        return statistics

    def _llm_inference(
            self,
            sample_records: List[Dict[str, Any]],
            field_statistics: Dict[str, FieldStatistics],
    ) -> SchemaAnalysisResult:
        """LLM으로 스키마 추론 (긴 텍스트 필드 자동 샘플링)

        Args:
            sample_records: 샘플 레코드
            field_statistics: 필드별 통계

        Returns:
            SchemaAnalysisResult
        """
        import json

        # 긴 텍스트 필드 감지 (통계 기반, schema_analysis 컨텍스트)
        long_text_fields = detect_long_text_fields(
            field_statistics=field_statistics,
            context="schema_analysis"
        )

        # 샘플 데이터 truncate
        truncated_samples = truncate_long_text_fields(
            sample_records, long_text_fields, context="schema_analysis"
        )

        sample_data_str = json.dumps(truncated_samples, ensure_ascii=False, indent=2)

        # 통계를 보기 좋게 포맷팅 (긴 텍스트 필드는 샘플 대신 길이 정보만)
        statistics_lines = []
        for field, stats in field_statistics.items():
            line = (
                f"{field}:\n"
                f"  - 전체: {stats.total_count}개\n"
                f"  - 고유값: {stats.unique_count}개\n"
                f"  - Null: {stats.null_count}개 ({stats.null_ratio * 100:.1f}%)\n"
            )

            # 긴 텍스트 필드면 샘플 생략
            if field in long_text_fields:
                line += f"  - 샘플: [긴 텍스트 - 평균 {stats.value_lengths['avg']}자, 최대 {stats.value_lengths['max']}자]\n"
            else:
                line += f"  - 샘플: {stats.samples}\n"

            line += (
                f"  - 길이: min={stats.value_lengths['min']}, "
                f"max={stats.value_lengths['max']}, "
                f"avg={stats.value_lengths['avg']}"
            )
            statistics_lines.append(line)

        statistics_str = "\n\n".join(statistics_lines)

        # LLM 호출
        llm_response = LLMResponse("schema_analysis")
        result = llm_response.generate_llm_response(
            variables={"sample_data": sample_data_str, "statistics": statistics_str}
        )

        # 결과가 딕셔너리인지 확인
        if not isinstance(result, dict):
            raise ValueError(f"LLM 응답이 딕셔너리가 아닙니다: {type(result)}")

        # Pydantic 모델로 변환
        schema = SchemaAnalysisResult(
            domain=result["domain"],
            centrality_name=result["centrality_name"],
            fields=result.get("fields", {}),  # LLM이 반환하지 않을 수 있음
            extractable_metadata=result.get("extractable_metadata", {}),
            confidence=result.get("confidence", 0.0),
            notes=result.get("notes", "")
        )

        logger.info(
            f"LLM 응답: 필드 {len(schema.fields)}개, "
            f"추출 메타데이터 {len(schema.extractable_metadata)}개"
        )

        return schema
