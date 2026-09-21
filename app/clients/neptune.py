"""Neptune RDF 클라이언트 모듈."""

import logging
from typing import Dict, Any, Optional
import requests
import urllib3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.session import Session

from app.config import settings
from app.exceptions.service import ApplicationError

# SSH 터널 사용 시 SSL 경고 비활성화
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


class NeptuneClient:
    """Neptune RDF SPARQL 클라이언트."""

    def __init__(
        self,
        endpoint: Optional[str] = None,
        region: Optional[str] = None,
        use_iam: bool = True,
        verify_ssl: bool = False
    ):
        """Neptune 클라이언트 초기화.

        Args:
            endpoint: Neptune 엔드포인트 (기본값: settings.NEPTUNE_ENDPOINT)
            region: AWS 리전 (기본값: settings.NEPTUNE_REGION)
            use_iam: IAM 인증 사용 여부 (기본값: True)
            verify_ssl: SSL 검증 여부 (기본값: False, SSH 터널 사용 시)
        """
        self.endpoint = endpoint or settings.NEPTUNE_ENDPOINT
        self.region = region or settings.NEPTUNE_REGION
        self.use_iam = use_iam if use_iam is not None else settings.NEPTUNE_USE_IAM
        self.verify_ssl = verify_ssl

        # SSH 터널 사용 시 IAM 서명을 위한 원본 엔드포인트
        self.signing_endpoint = settings.NEPTUNE_DIRECT_ENDPOINT if (self.use_iam and 'localhost' in self.endpoint) else self.endpoint

        logger.info(f"Neptune 클라이언트 초기화: endpoint={self.endpoint}, signing_endpoint={self.signing_endpoint}, region={self.region}")

    def _sign_request(self, request: AWSRequest) -> None:
        """AWS SigV4 서명 추가.

        Args:
            request: AWS 요청 객체
        """
        if self.use_iam:
            credentials = Session().get_credentials()
            SigV4Auth(credentials, 'neptune-db', self.region).add_auth(request)

    def execute_query(self, query: str) -> Dict[str, Any]:
        """SPARQL SELECT 쿼리 실행.

        Args:
            query: SPARQL SELECT 쿼리

        Returns:
            쿼리 결과 (JSON 형식)

        Raises:
            ApplicationError: 쿼리 실행 실패 시
        """
        try:
            # localhost인 경우 bastion을 통해 awscurl 실행
            if 'localhost' in self.endpoint and not self.use_iam:
                return self._execute_via_bastion(query, is_query=True)

            url = f'{self.endpoint}/sparql/'
            request = AWSRequest(
                method='POST',
                url=url,
                data={'query': query}
            )
            self._sign_request(request)

            response = requests.post(
                url,
                headers=dict(request.headers),
                data={'query': query},
                verify=self.verify_ssl
            )
            response.raise_for_status()

            return response.json()

        except requests.exceptions.RequestException as e:
            logger.error(f"SPARQL 쿼리 실행 실패: {e}")
            raise ApplicationError(
                code=500,
                message="Neptune SPARQL 쿼리 실행 실패",
                result={"error_type": "query_error", "detail": str(e)}
            )

    def execute_update(self, update: str) -> Dict[str, Any]:
        """SPARQL UPDATE (INSERT/DELETE) 실행.

        Args:
            update: SPARQL UPDATE 쿼리

        Returns:
            업데이트 결과 (JSON 형식, 또는 성공 메시지)

        Raises:
            ApplicationError: 업데이트 실행 실패 시
        """
        try:
            logger.info(f"SPARQL UPDATE 실행 시작 (endpoint={self.endpoint}, use_iam={self.use_iam})")

            # localhost인 경우 bastion을 통해 awscurl 실행
            if 'localhost' in self.endpoint and not self.use_iam:
                logger.info("bastion 프록시를 통해 UPDATE 실행")
                result = self._execute_via_bastion(update, is_query=False)
                logger.info(f"bastion UPDATE 결과: {result}")
                return result

            # 실제 요청 URL (SSH 터널이면 localhost)
            request_url = f'{self.endpoint}/sparql'

            # IAM 서명용 URL (원본 Neptune 엔드포인트)
            signing_url = f'{self.signing_endpoint}/sparql'

            # URL 인코딩된 body 생성 (서명과 실제 요청에 동일하게 사용)
            import urllib.parse
            body = f'update={urllib.parse.quote(update)}'

            # AWS Request 생성 (서명용 URL 사용)
            request = AWSRequest(
                method='POST',
                url=signing_url,
                data=body,
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            self._sign_request(request)

            # 실제 HTTP 요청 (request_url로, 서명된 헤더 포함)
            response = requests.post(
                request_url,
                headers=dict(request.headers),
                data=body,
                verify=self.verify_ssl
            )

            if response.status_code != 200:
                error_body = response.text
                logger.error(f"Neptune 응답 상태: {response.status_code}, 본문: {error_body}")

            response.raise_for_status()

            return response.json() if response.text else {"status": "success"}

        except requests.exceptions.RequestException as e:
            logger.error(f"SPARQL 업데이트 실행 실패: {e}")
            raise ApplicationError(
                code=500,
                message="Neptune SPARQL 업데이트 실행 실패",
                result={"error_type": "update_error", "detail": str(e)}
            )

    def _execute_via_bastion(self, query_or_update: str, is_query: bool = True) -> Dict[str, Any]:
        """bastion을 통해 awscurl로 쿼리 실행.

        Args:
            query_or_update: SPARQL 쿼리 또는 업데이트
            is_query: True면 query, False면 update

        Returns:
            실행 결과
        """
        import subprocess
        import json
        import os
        import urllib.parse

        param_name = 'query' if is_query else 'update'

        # SSH 키 경로 (config에서 읽기)
        ssh_key = os.path.expanduser(settings.NEPTUNE_BASTION_SSH_KEY)

        # Neptune 직접 엔드포인트 (config에서 읽기)
        neptune_url = settings.NEPTUNE_DIRECT_ENDPOINT

        # URL 인코딩된 데이터 생성
        encoded_data = f'{param_name}={urllib.parse.quote(query_or_update)}'

        # awscurl 명령 생성 (stdin으로 데이터 전달)
        bastion_host = f"{settings.NEPTUNE_BASTION_USER}@{settings.NEPTUNE_BASTION_HOST}"
        cmd = [
            'ssh', '-i', ssh_key,
            bastion_host,
            f"awscurl --service neptune-db --region {self.region} "
            f"'{neptune_url}/sparql' -X POST "
            f"-H 'Content-Type: application/x-www-form-urlencoded' "
            f"--data @-"
        ]

        try:
            result = subprocess.run(
                cmd,
                input=encoded_data,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                logger.error(f"bastion 실행 실패: {result.stderr}")
                raise ApplicationError(
                    code=500,
                    message="Neptune 쿼리 실행 실패",
                    result={"error": result.stderr}
                )

            # JSON 응답 파싱
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                # UPDATE는 JSON이 아닐 수 있음
                return {"status": "success", "output": result.stdout}

        except subprocess.TimeoutExpired:
            logger.error("bastion 실행 타임아웃")
            raise ApplicationError(
                code=500,
                message="Neptune 쿼리 타임아웃",
                result={"error": "timeout"}
            )
        except Exception as e:
            logger.error(f"bastion 실행 오류: {e}")
            raise ApplicationError(
                code=500,
                message="Neptune 쿼리 실행 오류",
                result={"error": str(e)}
            )

    def test_connection(self) -> bool:
        """Neptune 연결 테스트.

        Returns:
            연결 성공 여부
        """
        try:
            result = self.execute_query("SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 1")
            logger.info("Neptune 연결 테스트 성공")
            return True
        except Exception as e:
            logger.error(f"Neptune 연결 테스트 실패: {e}")
            return False


def get_neptune_client() -> NeptuneClient:
    """Neptune 클라이언트 팩토리 함수.

    Returns:
        NeptuneClient 인스턴스
    """
    return NeptuneClient(
        endpoint=settings.NEPTUNE_ENDPOINT,
        region=settings.NEPTUNE_REGION,
        use_iam=settings.NEPTUNE_USE_IAM,
        verify_ssl=False  # SSH 터널 사용 시 비활성화
    )
