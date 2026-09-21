import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.keyvalue_graph import ValueType
from app.src.keyvalue_graph.field_mappings import (
    FIELD_NAME_MAPPING,
    MULTI_VALUE_FIELDS,
)


class DataRecord(BaseModel):
    """데이터 레코드 (하나의 JSON 객체)."""

    source_file: str = Field(description="원본 파일명", examples=["data.json"])
    record_index: int = Field(description="파일 내 인덱스", examples=[0, 1, 2])
    raw_data: dict[str, Any] = Field(description="원본 JSON 데이터")
    key_values: dict[str, list[str]] = Field(
        default_factory=dict,
        description="추출된 Key-Value 쌍 (한글 필드명: 값 목록)"
    )
    original_key_mapping: dict[str, str] = Field(
        default_factory=dict,
        description="한글 필드명 → 원본 필드명 매핑 (예: {'병원명': 'BIZPLC_NM'})"
    )

    def extract_key_values(self) -> None:
        """원본 데이터에서 Key-Value 쌍 추출."""
        for original_field, value in self.raw_data.items():
            # 필드명 매핑
            korean_field = FIELD_NAME_MAPPING.get(original_field)
            if not korean_field:
                continue

            # 빈 값 스킵
            if value is None or (isinstance(value, str) and not value.strip()):
                continue

            # 값을 문자열로 변환
            value_str = str(value).strip()

            # 복합 값 분리 (쉼표로 구분된 값)
            if korean_field in MULTI_VALUE_FIELDS and "," in value_str:
                values = [v.strip() for v in value_str.split(",") if v.strip()]
            else:
                values = [value_str]

            self.key_values[korean_field] = values

    def get_document_id(self) -> str:
        """문서 ID 생성."""
        # 파일명에서 확장자 제거
        file_stem = Path(self.source_file).stem
        return f"{file_stem}_{self.record_index:04d}"

    def infer_value_type(self, key: str, value: str) -> ValueType:
        """값 타입 추론.

        Args:
            key: Key명
            value: 값

        Returns:
            ValueType
        """
        # 숫자형 필드
        numeric_keywords = ["수", "면적", "좌표", "위도", "경도"]
        if any(kw in key for kw in numeric_keywords):
            try:
                float(value)
                return ValueType.NUMBER
            except ValueError:
                pass

        # 날짜형 필드
        date_keywords = ["일자", "날짜"]
        if any(kw in key for kw in date_keywords):
            return ValueType.DATE

        return ValueType.TEXT


class DataLoader:
    """데이터 로더."""

    def __init__(self, file_path: str):
        """로더 초기화.

        Args:
            file_path: JSON 파일 경로
        """
        self.file_path = file_path
        self.file_name = Path(file_path).name

    def load(self) -> list[DataRecord]:
        """데이터 로딩.

        Returns:
            DataRecord 리스트
        """
        with open(self.file_path, encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            raise ValueError(f"Expected list, got {type(data)}")

        records = []
        for idx, raw_data in enumerate(data):
            record = DataRecord(
                source_file=self.file_name,
                record_index=idx,
                raw_data=raw_data,
            )
            record.extract_key_values()
            records.append(record)

        return records

    def get_all_keys(self, records: list[DataRecord]) -> list[str]:
        """모든 레코드에서 사용된 Key 목록 추출.

        Args:
            records: 데이터 레코드 리스트

        Returns:
            Key명 리스트 (중복 제거)
        """
        all_keys = set()
        for record in records:
            all_keys.update(record.key_values.keys())
        return sorted(all_keys)
