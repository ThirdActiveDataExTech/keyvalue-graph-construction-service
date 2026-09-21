"""OpenSearch 클라이언트 모듈."""

import logging
import uuid
from typing import Optional
from opensearchpy import OpenSearch
from opensearchpy.exceptions import NotFoundError

from app.config import settings
from app.exceptions.service import ApplicationError

logger = logging.getLogger(__name__)


class OpenSearchClient:
    """OpenSearch 클라이언트."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        use_ssl: bool = False,
        verify_certs: bool = False
    ):
        """OpenSearch 클라이언트 초기화.

        Args:
            host: OpenSearch 호스트 (기본값: settings.OPENSEARCH_HOST)
            port: OpenSearch 포트 (기본값: settings.OPENSEARCH_PORT)
            use_ssl: SSL 사용 여부 (기본값: False)
            verify_certs: SSL 인증서 검증 여부 (기본값: False)
        """
        self.host = host or settings.OPENSEARCH_HOST
        self.port = port or settings.OPENSEARCH_PORT
        self.use_ssl = use_ssl
        self.verify_certs = verify_certs

        self.client = OpenSearch(
            hosts=[{'host': self.host, 'port': self.port}],
            http_auth=None,
            use_ssl=self.use_ssl,
            verify_certs=self.verify_certs,
            ssl_assert_hostname=False,
            ssl_show_warn=False
        )

        logger.info(f"OpenSearch 클라이언트 초기화: {self.host}:{self.port}")

    def index_document(self, index: str, body: dict, doc_id: str = None, add_id_to_body: bool = True) -> tuple[str, dict]:
        """문서 인덱싱.

        Args:
            index: 인덱스 이름
            body: 문서 내용
            doc_id: 문서 ID (None이면 UUID 자동 생성)
            add_id_to_body: body에 doc_id 필드를 추가할지 여부

        Returns:
            (사용된 ID, 인덱싱 결과)

        Raises:
            ApplicationError: 인덱싱 실패 시
        """
        try:
            if doc_id is None:
                doc_uuid = str(uuid.uuid4())
                if add_id_to_body:
                    body_with_id = {**body, "doc_id": doc_uuid}
                else:
                    body_with_id = body
            else:
                doc_uuid = doc_id
                body_with_id = body

            response = self.client.index(
                index=index,
                id=doc_uuid,
                body=body_with_id,
                params={'refresh': 'true'}
            )
            return doc_uuid, response
        except Exception as e:
            logger.error(f"문서 인덱싱 실패: {e}")
            raise ApplicationError(
                code=500,
                message="OpenSearch 문서 인덱싱 실패",
                result={"error_type": "index_error", "detail": str(e)}
            )

    def bulk_index(self, index: str, documents: list[dict]) -> dict:
        """대량 문서 인덱싱.

        Args:
            index: 인덱스 이름
            documents: 문서 리스트 (각 문서는 _id와 body 포함)

        Returns:
            벌크 인덱싱 결과

        Raises:
            ApplicationError: 벌크 인덱싱 실패 시
        """
        try:
            from opensearchpy import helpers

            actions = [
                {
                    "_index": index,
                    "_id": doc["_id"],
                    "_source": doc["body"]
                }
                for doc in documents
            ]

            success, failed = helpers.bulk(
                self.client,
                actions,
                refresh=True,
                raise_on_error=False
            )

            return {
                "success": success,
                "failed": len(failed) if isinstance(failed, list) else 0,
                "errors": failed if isinstance(failed, list) else []
            }

        except Exception as e:
            logger.error(f"대량 문서 인덱싱 실패: {e}")
            raise ApplicationError(
                code=500,
                message="OpenSearch 대량 인덱싱 실패",
                result={"error_type": "bulk_index_error", "detail": str(e)}
            )

    def search(self, index: str, body: dict) -> dict:
        """문서 검색.

        Args:
            index: 인덱스 이름
            body: 검색 쿼리

        Returns:
            검색 결과

        Raises:
            ApplicationError: 검색 실패 시
        """
        try:
            response = self.client.search(
                index=index,
                body=body
            )
            return response
        except NotFoundError:
            # 지연 생성 인덱스(KV 그래프 등)가 아직 없는 정상 상태 — 빈 결과로 처리
            logger.debug(f"인덱스 미존재 — 빈 결과 반환: {index}")
            return {"hits": {"hits": [], "total": {"value": 0}}}
        except Exception as e:
            logger.error(f"문서 검색 실패: {e}")
            raise ApplicationError(
                code=500,
                message="OpenSearch 검색 실패",
                result={"error_type": "search_error", "detail": str(e)}
            )

    def delete_document(self, index: str, doc_id: str) -> dict:
        """문서 삭제.

        Args:
            index: 인덱스 이름
            doc_id: 문서 ID

        Returns:
            삭제 결과

        Raises:
            ApplicationError: 삭제 실패 시
        """
        try:
            response = self.client.delete(
                index=index,
                id=doc_id,
                params={'refresh': 'true'}
            )
            return response
        except Exception as e:
            logger.error(f"문서 삭제 실패: {e}")
            raise ApplicationError(
                code=500,
                message="OpenSearch 문서 삭제 실패",
                result={"error_type": "delete_error", "detail": str(e)}
            )

    def test_connection(self) -> bool:
        """OpenSearch 연결 테스트.

        Returns:
            연결 성공 여부
        """
        try:
            info = self.client.info()
            logger.info(f"OpenSearch 연결 성공: {info['version']['number']}")
            return True
        except Exception as e:
            logger.error(f"OpenSearch 연결 실패: {e}")
            return False


def get_opensearch_client() -> OpenSearchClient:
    """OpenSearch 클라이언트 팩토리 함수.

    Returns:
        OpenSearchClient 인스턴스
    """
    return OpenSearchClient(
        host=settings.OPENSEARCH_HOST,
        port=settings.OPENSEARCH_PORT,
        use_ssl=settings.OPENSEARCH_USE_SSL,
        verify_certs=settings.OPENSEARCH_VERIFY_CERTS
    )
