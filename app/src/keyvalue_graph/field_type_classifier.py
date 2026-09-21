from typing import Literal
import logging
from app.src.meta_extract.llm_response import LLMResponse

logger = logging.getLogger(__name__)

FieldType = Literal["semantic", "numeric_date", "proper_noun"]


class FieldTypeClassifier:
    """필드 타입 분류기

    메타데이터 필드명과 샘플 값을 분석하여 적합한 매칭 전략 결정
    """

    def classify(
            self,
            key_name: str,
            sample_values: list[str],
    ) -> dict[str, str | float]:
        """필드 타입 분류

        Args:
            key_name: 필드명 (예: "발행기관명", "발행일자")
            sample_values: 샘플 값 목록 (최대 5개)

        Returns:
            {
                "field_type": "semantic" | "numeric_date" | "proper_noun",
                "confidence": 0.0~1.0
            }
        """
        # 샘플 값 제한 (최대 5개)
        samples = sample_values[:5] if len(sample_values) > 5 else sample_values
        samples_str = "\n".join([f"  - {v}" for v in samples])

        try:
            llm_response = LLMResponse(task="field_type_classification")
            result = llm_response.generate_llm_response(
                variables={"key_name": key_name, "sample_values": samples_str}
            )

            # 타입 검증
            if not isinstance(result, dict):
                logger.warning(f"LLM 응답이 dict가 아님: {type(result)}, 기본값 반환")
                return {"field_type": "semantic", "confidence": 0.5}

            logger.debug(
                f"필드 타입 분류 완료: {key_name} → {result['field_type']} (신뢰도: {result['confidence']})"
            )
            return result

        except Exception as e:
            logger.warning(f"필드 타입 분류 실패: {key_name}, 기본값(semantic) 반환. 오류: {e}")
            return {"field_type": "semantic", "confidence": 0.5}


# 싱글톤 인스턴스
field_type_classifier = FieldTypeClassifier()
