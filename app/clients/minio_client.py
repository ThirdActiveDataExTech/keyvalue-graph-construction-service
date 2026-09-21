"""MinIO 객체 저장소 클라이언트 — 업로드 원본 데이터셋 보관 (§3.2).

설계 문서의 "원본 보관은 MinIO" 분담 원칙을 구현한다. 원본 파일(JSON/JSONL/CSV)을
변형 없이 객체 저장소에 보존하여 재처리·감사·대용량 원천 데이터 보관에 대응한다.

와이즈넛 사내 MinIO 는 S3 호환 엔드포인트이므로 boto3 S3 클라이언트로 접근한다
(ai-legal 프로젝트와 동일 방식). boto3 는 Neptune 서명용으로 이미 의존성에 포함되어
있어 추가 패키지가 필요 없다.

MinIO 가 비활성(MINIO_ENABLED=False)이거나 연결 실패 시에는 graceful degradation 한다
— 적재/워크플로우 본 흐름은 막지 않는다.
"""

import io
import logging
from datetime import datetime, timezone

from app.config import settings

logger = logging.getLogger(__name__)


class MinioStorage:
    """업로드 원본 데이터셋을 보관하는 MinIO(S3 호환) 래퍼."""

    def __init__(self) -> None:
        """설정 기반으로 boto3 S3 클라이언트를 초기화 (실패 시 비활성화)."""
        self.enabled = settings.MINIO_ENABLED
        self.bucket = settings.MINIO_BUCKET
        self._client = None

        if not self.enabled:
            logger.info("[MinIO] 비활성화 상태 (MINIO_ENABLED=False)")
            return

        try:
            import boto3

            self._client = boto3.client(
                "s3",
                endpoint_url=settings.MINIO_ENDPOINT,
                aws_access_key_id=settings.MINIO_ACCESS_KEY,
                aws_secret_access_key=settings.MINIO_SECRET_KEY,
                region_name=settings.MINIO_REGION,
                use_ssl=settings.MINIO_SECURE,
            )
            self._ensure_bucket()
            logger.info(f"[MinIO] 초기화 완료: endpoint={settings.MINIO_ENDPOINT}, bucket={self.bucket}")
        except Exception as e:
            # 연결/자격증명 실패 → 비활성화로 전환 (본 흐름 보호)
            self.enabled = False
            self._client = None
            logger.warning(f"[MinIO] 초기화 실패, 비활성화로 전환: {e}")

    def _ensure_bucket(self) -> None:
        """버킷이 없으면 생성."""
        if self._client is None:
            return
        from botocore.exceptions import ClientError

        try:
            self._client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self.bucket)
            logger.info(f"[MinIO] 버킷 생성: {self.bucket}")

    def store_raw_dataset(self, table_name: str, filename: str, content: bytes) -> str | None:
        """원본 데이터셋 파일을 객체로 저장.

        Args:
            table_name: 데이터셋(테이블)명 — 객체 경로 prefix 로 사용
            filename: 업로드 파일명
            content: 원본 바이트

        Returns:
            저장된 object key (비활성/실패 시 None)
        """
        if not self.enabled or self._client is None:
            return None

        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_table = "".join(c for c in table_name if c.isalnum() or c in "._-") or "dataset"
        object_key = f"{safe_table}/{ts}_{filename}"
        try:
            self._client.put_object(
                Bucket=self.bucket,
                Key=object_key,
                Body=io.BytesIO(content),
                ContentLength=len(content),
            )
            return object_key
        except Exception as e:
            logger.warning(f"[MinIO] 객체 저장 실패 ({object_key}): {e}")
            return None

    def load(self, storage_key: str) -> bytes | None:
        """저장 키로 객체 바이트를 읽어온다 (재처리용)."""
        if not self.enabled or self._client is None or not storage_key:
            return None
        try:
            resp = self._client.get_object(Bucket=self.bucket, Key=storage_key)
            return resp["Body"].read()
        except Exception as e:
            logger.warning(f"[MinIO] 객체 읽기 실패 ({storage_key}): {e}")
            return None


_storage: MinioStorage | None = None


def get_minio_storage() -> MinioStorage:
    """MinioStorage 싱글턴 팩토리."""
    global _storage
    if _storage is None:
        _storage = MinioStorage()
    return _storage
