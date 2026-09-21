from typing import Any, Dict, List, Set

import logging

logger = logging.getLogger(__name__)

# 컨텍스트별 Truncate 설정
TRUNCATE_CONFIGS = {
    "schema_analysis": {
        "threshold": 500,  # 필드 타입만 파악하므로 짧게
        "prefix": 200,
        "suffix": 100,
    },
    "key_value_extract": {
        "threshold": 5000,  # 실제 값 추출이므로 길게
        "prefix": 2000,
        "suffix": 1000,
    },
    "default": {
        "threshold": 500,
        "prefix": 200,
        "suffix": 100,
    }
}

# 하위 호환성을 위한 기본값
LONG_TEXT_THRESHOLD = TRUNCATE_CONFIGS["default"]["threshold"]
TRUNCATE_PREFIX_LENGTH = TRUNCATE_CONFIGS["default"]["prefix"]
TRUNCATE_SUFFIX_LENGTH = TRUNCATE_CONFIGS["default"]["suffix"]


def detect_long_text_fields(
        records: List[Dict[str, Any]] | None = None,
        field_statistics: Dict[str, Any] | None = None,
        threshold: int | None = None,
        context: str = "default"
) -> Set[str]:
    """긴 텍스트 필드 감지

    Args:
        records: 데이터 레코드 리스트 (단일 레코드 감지용)
        field_statistics: 필드별 통계 (평균 길이 기반 감지용)
        threshold: 긴 텍스트로 간주할 길이 임계값 (None이면 context 기반)
        context: 컨텍스트 ("schema_analysis", "key_value_extract", "default")

    Returns:
        긴 텍스트 필드명 집합
    """
    # threshold가 명시되지 않으면 context에서 가져오기
    if threshold is None:
        config = TRUNCATE_CONFIGS.get(context, TRUNCATE_CONFIGS["default"])
        threshold = config["threshold"]
    long_fields = set()

    # 방법 1: 통계 기반 (평균 길이)
    if field_statistics:
        long_fields = {
            field
            for field, stats in field_statistics.items()
            if stats.value_lengths["avg"] > threshold
        }

    # 방법 2: 단일 레코드 기반
    elif records:
        if isinstance(records, dict):
            records = [records]

        # 모든 레코드에서 긴 필드 찾기
        for record in records:
            for key, value in record.items():
                if isinstance(value, str) and len(value) > threshold:
                    long_fields.add(key)

    if long_fields:
        logger.info(
            f"긴 텍스트 필드 감지: {long_fields} (임계값: {threshold}자)"
        )

    return long_fields


def truncate_long_text_fields(
        records: List[Dict[str, Any]],
        long_text_fields: Set[str],
        prefix_length: int | None = None,
        suffix_length: int | None = None,
        context: str = "default"
) -> List[Dict[str, Any]]:
    """긴 텍스트 필드를 truncate

    Args:
        records: 원본 레코드 리스트
        long_text_fields: truncate할 필드명 집합
        prefix_length: 앞부분 유지 길이 (None이면 context 기반)
        suffix_length: 뒷부분 유지 길이 (None이면 context 기반)
        context: 컨텍스트 ("schema_analysis", "key_value_extract", "default")

    Returns:
        truncate된 레코드 리스트 (원본은 변경하지 않음)
    """
    # 길이가 명시되지 않으면 context에서 가져오기
    if prefix_length is None or suffix_length is None:
        config = TRUNCATE_CONFIGS.get(context, TRUNCATE_CONFIGS["default"])
        prefix_length = config["prefix"]
        suffix_length = config["suffix"]
    if not long_text_fields:
        return records

    truncated_records = []
    min_length = prefix_length + suffix_length

    for record in records:
        truncated = {}
        for key, value in record.items():
            if key in long_text_fields and isinstance(value, str):
                # truncate 적용
                if len(value) > min_length:
                    truncated[key] = (
                            value[:prefix_length]
                            + "\n...(중략)...\n"
                            + value[-suffix_length:]
                    )
                    logger.debug(
                        f"필드 '{key}' truncate: {len(value)}자 → {len(truncated[key])}자"
                    )
                else:
                    truncated[key] = value
            else:
                truncated[key] = value

        truncated_records.append(truncated)

    return truncated_records


def truncate_single_record(
        record: Dict[str, Any],
        long_text_fields: Set[str] | None = None,
        context: str = "default",
        threshold: int | None = None,
        prefix_length: int | None = None,
        suffix_length: int | None = None
) -> Dict[str, Any]:
    """단일 레코드의 긴 텍스트 필드 truncate

    Args:
        record: 원본 레코드
        long_text_fields: truncate할 필드명 집합 (None이면 자동 감지)
        context: 컨텍스트 ("schema_analysis", "key_value_extract", "default")
        threshold: 긴 텍스트 임계값 (None이면 context 기반)
        prefix_length: 앞부분 유지 길이 (None이면 context 기반)
        suffix_length: 뒷부분 유지 길이 (None이면 context 기반)

    Returns:
        truncate된 레코드
    """
    # 긴 필드 자동 감지
    if long_text_fields is None:
        long_text_fields = detect_long_text_fields(
            records=[record], threshold=threshold, context=context
        )

    if not long_text_fields:
        return record

    # truncate 적용
    result = truncate_long_text_fields(
        records=[record],
        long_text_fields=long_text_fields,
        prefix_length=prefix_length,
        suffix_length=suffix_length,
        context=context
    )

    return result[0]
