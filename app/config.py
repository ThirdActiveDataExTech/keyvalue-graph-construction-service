import logging
import re
from typing import Literal, List, Annotated, Any, Union, Dict

from pydantic import AnyUrl, BeforeValidator, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from langfuse.langchain import CallbackHandler


def parse_cors(v: Any) -> Union[List[str], str]:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",")]
    elif isinstance(v, list) or isinstance(v, str):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_ignore_empty=True, extra="ignore"
    )

    # Environment: local, staging, production
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"

    PORT: int = 8000
    SERVICE_NAME: str = "3rd party"
    SERVICE_CODE: int = 100
    MAJOR_VERSION: str = "v1"
    STATUS: str = "dev"
    STATIC_DIRECTORY: str = "./static"

    # Request Server URL
    SERVER_URL: str = ""  # FastAPI SERVER URL 설정이 필요할 경우, 해당 변수로 설정

    # LOG
    LEVEL: str = "INFO"
    JSON_LOG: bool = False
    LOGURU_FORMAT: str = "<green>{time:YY-MM-DD HH:mm:ss.SSS}</green> | " \
                         "<level>{level: <8}</level> | " \
                         "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> " \
                         "- {process} {thread} {extra[request_id]} <level>{message}</level>"

    # LOG SAVE CONFIG
    SAVE: bool = True
    LOG_SAVE_PATH: str = "./logs"
    ROTATION: str = "00:00"
    RETENTION: str = "10 days"
    COMPRESSION: str = "zip"

    @field_validator('LEVEL')
    def validate_log_level(cls, v):
        if v.upper() not in 'CRITICAL|ERROR|WARNING|INFO|DEBUG|NOTSET'.split('|'):
            raise ValueError(f"로그레벨 `LEVEL` 은 'CRITICAL|ERROR|WARNING|INFO|DEBUG|NOTSET' 만 가능. LEVEL={v}")
        return v

    @field_validator('SERVER_URL')
    def valid_server_url(cls, v):
        server_url_regex = r'^https?:\/\/(www\.)?[a-zA-Z0-9-]+(\.[a-zA-Z]{2,})+(\/[a-zA-Z0-9-._~:/?#[\]@!$&\'()*+,;=]*)?$'
        pattern = re.compile(server_url_regex)
        if v:
            if bool(pattern.match(v)):
                return v
            else:
                raise ValueError(f"URL Validation Error (regex {pattern=}), current url={v}")
        else:
            return None

    @computed_field  # type: ignore[misc]
    @property
    def log_level(self) -> Any:  # real return type: numeric value (int)
        return logging.getLevelName(self.LEVEL)

    @computed_field  # type: ignore[misc]
    @property
    def servers(self) -> Union[List[Dict[str, str]], None]:
        if self.SERVER_URL:
            return [{"url": f"{self.SERVER_URL}", "description": f"{self.ENVIRONMENT.capitalize()} Server"}]
        else:
            return None

    @computed_field  # type: ignore[misc]
    @property
    def root_path_in_servers(self) -> bool:
        if self.SERVER_URL:
            return False
        else:
            return True

    # Backend
    BACKEND_CORS_ORIGINS: Annotated[Union[List[AnyUrl], str], BeforeValidator(parse_cors)] = []

    # Service Config
    X_TOKEN: str = ""
    # DB Config
    SQLITE_FILE_NAME: str = "database.db"
    # llm config
    MAIN_MODEL_NAME: str = "wise-lloa"
    FALLBACK_MODEL_LIST: List[str] = ["claude", "gpt"]
    CLAUDE_MODEL_NAME: str = "claude-3-7-sonnet"
    CLAUDE_API_KEY: str = ""
    LITE_LLM_BASE_URL: str = ""

    # Langfuse Config
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_HOST: str = ""

    # RDF Config
    RDF_NAMESPACE: str = "http://example.org/keyvalue#"
    RDF_NAMESPACE_PREFIX: str = "kv"

    # Neptune Config
    NEPTUNE_ENDPOINT: str = "https://localhost:8183"
    NEPTUNE_REGION: str = "ap-northeast-1"
    NEPTUNE_DIRECT_ENDPOINT: str = ""
    NEPTUNE_USE_IAM: bool = True

    # Neptune Bastion Config
    NEPTUNE_BASTION_SSH_KEY: str = ""
    NEPTUNE_BASTION_HOST: str = ""
    NEPTUNE_BASTION_USER: str = ""

    # OpenSearch Config
    OPENSEARCH_HOST: str = "localhost"
    OPENSEARCH_PORT: int = 9200
    OPENSEARCH_USE_SSL: bool = False
    OPENSEARCH_VERIFY_CERTS: bool = False
    # 인덱스 명칭은 설계 문서(§3.2/§13)의 third-party-* 규칙을 따른다.
    OPENSEARCH_DOCUMENTS_INDEX: str = "third-party-graph-documents"
    OPENSEARCH_KEYS_INDEX: str = "third-party-graph-keys"
    OPENSEARCH_VALUES_INDEX: str = "third-party-graph-values"
    OPENSEARCH_DATASETS_INDEX: str = "third-party-datasets"

    # 원본 업로드 파일(blob) 보관 백엔드 선택 (§3.2): filesystem | minio | none
    #   - filesystem: 로컬 디스크(또는 PVC 마운트 경로)에 저장 — active-metadata 프로젝트와 동일 방식
    #   - minio: 아래 MINIO_* 설정으로 S3 호환 객체 저장소에 저장
    #   - none: 원본 blob 미보관 (레코드는 OpenSearch/Neptune에 적재됨)
    RAW_STORAGE_BACKEND: str = "filesystem"
    # filesystem 백엔드의 루트 경로. k8s 배포 시 PVC 마운트 경로로 주입 (예: /data/raw)
    RAW_STORAGE_PATH: str = "./raw_uploads"

    # MinIO (객체 저장소) Config — 업로드 원본 데이터셋 보관 (§3.2)
    # S3 호환이라 boto3 로 접근. 배포 클러스터(thirdparty 네임스페이스)에 minio pod 가 있으므로
    # 실제 값은 .env / k8s env 로 주입한다. 아래는 in-cluster 서비스 DNS 형태의 placeholder 기본값.
    #   예) MINIO_ENDPOINT=http://minio.thirdparty.svc.cluster.local:9000
    # 값이 비어있거나 접속 실패 시 graceful degradation (적재/워크플로우는 계속).
    MINIO_ENABLED: bool = False
    MINIO_ENDPOINT: str = "http://minio.thirdparty.svc.cluster.local:9000"
    MINIO_ACCESS_KEY: str = ""
    MINIO_SECRET_KEY: str = ""
    MINIO_SECURE: bool = False
    MINIO_REGION: str = "ap-northeast-2"
    MINIO_BUCKET: str = "third-party-datasets-raw"

    # Level 2 (레코드 간) 관계 발굴 설정
    # Level 1에서 연결된 데이터셋 내부로만 후보 탐색을 제한할지 여부 (§2, §8)
    LEVEL2_GATE_BY_LEVEL1: bool = True
    # 후보 발굴 시 OpenSearch Key/Value 검색 k 값
    LEVEL2_KEY_SEARCH_K: int = 5
    LEVEL2_VALUE_SEARCH_K: int = 20
    # SAME_AS 로 승격할 종합 점수 하한 (정규화/식별자 강일치 신호)
    LEVEL2_SAME_AS_THRESHOLD: float = 0.9

    # 통합 카탈로그(active-metadata-management catalog-service) 연동 Config
    CATALOG_SERVICE_URL: str = "http://localhost:8084"
    CATALOG_SERVICE_X_TOKEN: str = ""
    # identifier 검색 시 클라이언트 매칭에 사용할 최대 페이지 수 (100건/페이지)
    CATALOG_SERVICE_MAX_PAGES: int = 50
    CATALOG_PUSH_ENABLED: bool = False
    RELATION_AUTO_APPROVE_THRESHOLD: float = 0.85

    # 컬럼 간 연관성 분석 서비스(column-to-column-correlation-analysis) 연동 Config
    CORRELATION_SERVICE_ENABLED: bool = False
    CORRELATION_SERVICE_URL: str = "http://localhost:8002"
    CORRELATION_SERVICE_X_TOKEN: str = ""
    DOMAIN_CLASSIFY_THRESHOLD: float = 0.5

    # KV 지식그래프 PPMI 상호 연관성 분석
    PPMI_ENABLED: bool = True
    PPMI_WEIGHT: float = 0.2

    # 카탈로그 변경 자동 동기화(액티브 루프) Config
    CATALOG_SYNC_ENABLED: bool = False
    CATALOG_SYNC_INTERVAL_MINUTES: int = 60

    # 카탈로그 access_url 실데이터 수집
    CATALOG_FETCH_DATA_ENABLED: bool = True
    DATA_FETCH_TIMEOUT_SECONDS: int = 30
    DATA_FETCH_MAX_BYTES: int = 50 * 1024 * 1024
    DATA_FETCH_MAX_RECORDS: int = 5000

    KV_BUILD_ON_SYNC: bool = False

    # Dataset RDF Namespace
    DATASET_RDF_NAMESPACE: str = "http://datarelation.wisenet.co.kr/ontology#"
    DATASET_RDF_NAMESPACE_PREFIX: str = "dm"

    # Embedding Config
    EMBEDDING_MODEL_NAME: str = "jhgan/ko-sroberta-multitask"
    SIMILARITY_THRESHOLD: float = 0.75
    SIMILARITY_TOP_K: int = 5


settings = Settings()  # type: ignore
print(settings.model_dump_json())
langfuse_handler = CallbackHandler()
