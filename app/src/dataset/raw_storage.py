"""원본 업로드 파일(blob) 보관 — 백엔드 선택형 (§3.2).

설계 문서의 "원본 보관" 요구를 충족하되, 환경에 따라 저장 백엔드를 바꿀 수 있게 추상화한다.
config.RAW_STORAGE_BACKEND 로 선택:
    - filesystem: 로컬 디스크/PVC 경로에 저장 (active-metadata 프로젝트와 동일 방식, 기본값)
    - minio:      S3 호환 객체 저장소 (app.clients.minio_client 재사용)
    - none:       미보관 (레코드는 이미 OpenSearch/Neptune에 적재됨)

모든 백엔드는 공통 인터페이스를 가진다:
    - .enabled: bool
    - .store_raw_dataset(table_name, filename, content) -> str | None  (저장 키 반환)
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


def _build_storage_key(table_name: str, filename: str) -> str:
    """데이터셋/날짜 기반 저장 키 생성: {table}/{YYYY}/{MM}/{DD}/{ts}_{filename}."""
    safe_table = "".join(c for c in table_name if c.isalnum() or c in "._-") or "dataset"
    safe_name = "".join(c for c in filename if c.isalnum() or c in "._-") or "upload"
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%dT%H%M%SZ")
    return f"{safe_table}/{now.year}/{now.month:02d}/{now.day:02d}/{ts}_{safe_name}"


class FilesystemRawStorage:
    """로컬 파일시스템(또는 마운트된 PVC) 기반 원본 보관."""

    def __init__(self, base_path: str) -> None:
        """base_path 루트로 초기화."""
        self.base_path = Path(base_path)
        self.enabled = True

    def store_raw_dataset(self, table_name: str, filename: str, content: bytes) -> str | None:
        """원본 파일을 base_path 아래에 저장하고 저장 키를 반환."""
        storage_key = _build_storage_key(table_name, filename)
        path = self.base_path / storage_key
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            logger.info(f"[RawStorage:fs] 원본 저장: {path}")
            return storage_key
        except OSError as e:
            logger.warning(f"[RawStorage:fs] 저장 실패 ({path}): {e}")
            return None

    def load(self, storage_key: str) -> bytes | None:
        """저장 키로 원본 파일 바이트를 읽어온다 (재처리용)."""
        if not storage_key:
            return None
        path = self.base_path / storage_key
        try:
            return path.read_bytes()
        except OSError as e:
            logger.warning(f"[RawStorage:fs] 읽기 실패 ({path}): {e}")
            return None


class _NoopRawStorage:
    """미보관 백엔드."""

    enabled = False

    def store_raw_dataset(self, table_name: str, filename: str, content: bytes) -> str | None:
        """아무것도 하지 않음."""
        return None

    def load(self, storage_key: str) -> bytes | None:
        """미보관 백엔드 — 항상 None."""
        return None


_storage = None


def get_raw_storage():
    """설정된 백엔드의 원본 보관 인스턴스를 반환 (싱글턴)."""
    global _storage
    if _storage is not None:
        return _storage

    backend = (settings.RAW_STORAGE_BACKEND or "none").lower()
    if backend == "filesystem":
        _storage = FilesystemRawStorage(settings.RAW_STORAGE_PATH)
    elif backend == "minio":
        from app.clients.minio_client import get_minio_storage

        _storage = get_minio_storage()
    else:
        _storage = _NoopRawStorage()

    logger.info(f"[RawStorage] backend={backend}, enabled={_storage.enabled}")
    return _storage
