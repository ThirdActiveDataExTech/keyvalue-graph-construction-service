"""Neptune RDF 기반 그래프 레포지토리."""

from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import logging
from urllib.parse import quote

from app.clients.neptune import NeptuneClient, get_neptune_client
from app.config import settings
from app.exceptions.service import ApplicationError

logger = logging.getLogger(__name__)


class GraphRepository:
    """Neptune RDF 그래프 데이터베이스 레포지토리."""

    def __init__(self, client: Optional[NeptuneClient] = None):
        """레포지토리 초기화.

        Args:
            client: Neptune 클라이언트 (기본값: None, 자동 생성)
        """
        self.client = client or get_neptune_client()
        self.namespace = settings.RDF_NAMESPACE
        self.prefix = settings.RDF_NAMESPACE_PREFIX

        logger.info(f"GraphRepository 초기화: namespace={self.namespace}")

        # 연결 테스트
        if not self.client.test_connection():
            raise ApplicationError(
                code=503,
                message="Neptune 서버에 연결할 수 없습니다",
                result={"error_type": "service_unavailable"}
            )

    def _make_uri(self, resource_id: str) -> str:
        """리소스 URI 생성.

        Args:
            resource_id: 리소스 ID

        Returns:
            완전한 URI
        """
        return f"<{self.namespace}{quote(resource_id)}>"

    def execute_query(self, query: str, parameters: Optional[Dict[str, Any]] = None) -> List[Dict]:
        """SPARQL SELECT 쿼리 실행.

        Args:
            query: SPARQL SELECT 쿼리
            parameters: 쿼리 파라미터 (SPARQL에서는 쿼리 문자열에 직접 삽입됨)

        Returns:
            쿼리 결과 리스트

        Raises:
            ApplicationError: 쿼리 실행 실패 시
        """
        try:
            # 파라미터가 있으면 쿼리 문자열에 치환
            if parameters:
                for key, value in parameters.items():
                    placeholder = f"${key}"
                    if isinstance(value, str):
                        query = query.replace(placeholder, f"'{value}'")
                    else:
                        query = query.replace(placeholder, str(value))

            result = self.client.execute_query(query)
            bindings = result.get("results", {}).get("bindings", [])

            # SPARQL 결과를 Dict 형식으로 변환
            return self._convert_bindings_to_dicts(bindings)

        except Exception as e:
            logger.error(f"SPARQL 쿼리 실행 실패: {e}")
            raise ApplicationError(
                code=400,
                message="SPARQL 쿼리 실행 실패",
                result={"error_type": "sparql_error", "detail": str(e)}
            )

    def _convert_bindings_to_dicts(self, bindings: List[Dict]) -> List[Dict]:
        """SPARQL bindings를 간단한 dict 형식으로 변환.

        Args:
            bindings: SPARQL 결과 bindings

        Returns:
            변환된 dict 리스트
        """
        results = []
        for binding in bindings:
            row = {}
            for key, value in binding.items():
                row[key] = value.get("value")
            results.append(row)
        return results

    def create_vector_index(self) -> None:
        """Vector index 생성 (Neptune에서는 Neptune ML 사용).

        Note:
            Neptune RDF에서는 vector index를 직접 생성하지 않습니다.
            Neptune ML을 사용하여 별도로 설정해야 합니다.
        """
        logger.warning("Neptune RDF에서는 vector index를 직접 생성하지 않습니다. Neptune ML을 사용하세요.")

    def create_graph_embedding_index(self, dimensions: int = 128) -> None:
        """그래프 임베딩 인덱스 생성 (Neptune ML 사용).

        Args:
            dimensions: 임베딩 차원 (기본: 128)

        Note:
            Neptune ML을 사용하여 별도로 설정해야 합니다.
        """
        logger.warning("Neptune RDF에서는 그래프 임베딩 인덱스를 직접 생성하지 않습니다. Neptune ML을 사용하세요.")

    def create_key_name_embedding_index(self) -> None:
        """Key name 임베딩 인덱스 생성 (Neptune ML 사용).

        Note:
            Neptune ML을 사용하여 별도로 설정해야 합니다.
        """
        logger.warning("Neptune RDF에서는 임베딩 인덱스를 직접 생성하지 않습니다. Neptune ML을 사용하세요.")

    def create_value_embedding_index(self) -> None:
        """Value 임베딩 인덱스 생성 (Neptune ML 사용).

        Note:
            Neptune ML을 사용하여 별도로 설정해야 합니다.
        """
        logger.warning("Neptune RDF에서는 임베딩 인덱스를 직접 생성하지 않습니다. Neptune ML을 사용하세요.")

    def create_document_relations(
        self,
        source_doc_id: str,
        relations: List[Dict[str, Any]]
    ) -> int:
        """Document 간 의미적 관계 생성.

        Args:
            source_doc_id: 출발 문서 ID
            relations: 관계 정보 리스트
                [{
                    "target_doc_id": "doc_xxx",
                    "relation_type": "EXTENDS",
                    "reason": "이유",
                    "confidence": 0.85
                }]

        Returns:
            생성된 관계 개수
        """
        if not relations:
            return 0

        count = 0

        for rel in relations:
            try:
                source_uri = self._make_uri(source_doc_id)
                target_uri = self._make_uri(rel["target_doc_id"])
                relation_type = rel["relation_type"]
                relation_uri = f"<{self.namespace}{relation_type}>"

                # SPARQL INSERT
                # 관계를 RDF 트리플로 표현
                # 추가 메타데이터는 reification 또는 named graph 사용 가능
                update = f"""
                PREFIX kv: <{self.namespace}>
                PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
                PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

                INSERT DATA {{
                    {source_uri} {relation_uri} {target_uri} .
                    {source_uri} kv:hasRelationReason "{rel['reason']}" .
                    {source_uri} kv:hasRelationConfidence "{rel['confidence']}"^^<http://www.w3.org/2001/XMLSchema#float> .
                }}
                """

                self.client.execute_update(update)
                count += 1

            except Exception as e:
                logger.error(f"관계 생성 실패: {e}")

        return count

    def create_document_relation(
        self,
        source_doc_id: str,
        target_doc_id: str,
        relation_type: str,
        score: float,
        method: str = "llm",
        reason: str = "",
    ) -> str:
        """Level 2 (레코드 간) 관계를 RDF Reification 으로 Neptune에 영구 저장 (§8.5).

        관계 엣지 자체에 메타데이터(유형/점수/근거/방법)를 부착하여 액티브 메타데이터로
        기록한다. Dataset 레벨(§7) 저장 방식과 동일한 reification 패턴을 사용한다.

        Args:
            source_doc_id: 출발 Document ID
            target_doc_id: 도착 Document ID
            relation_type: 관계 유형 (SAME_AS / RELATED_TO / REFERENCES)
            score: 종합 점수 (0~1)
            method: 생성 방법 (rule / embedding / llm)
            reason: 판단 근거

        Returns:
            생성된 관계 reification 노드의 ID 문자열
        """
        ns = self.namespace
        source_uri = self._make_uri(f"document/{source_doc_id}")
        target_uri = self._make_uri(f"document/{target_doc_id}")
        rel_id = f"docrelation/{source_doc_id}--{target_doc_id}"
        rel_uri = self._make_uri(rel_id)
        created_at = datetime.now(timezone.utc).isoformat()

        def _esc(s: str) -> str:
            return s.replace("\\", "\\\\").replace('"', '\\"')

        update = f"""
        PREFIX kv: <{ns}>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

        DELETE {{ {rel_uri} ?p ?o . }}
        WHERE  {{ OPTIONAL {{ {rel_uri} ?p ?o . }} }} ;

        INSERT DATA {{
            {rel_uri} rdf:type rdf:Statement ;
                rdf:subject {source_uri} ;
                rdf:predicate kv:relatedTo ;
                rdf:object {target_uri} ;
                kv:relationType "{_esc(relation_type)}" ;
                kv:relationScore "{score}"^^xsd:float ;
                kv:relationMethod "{_esc(method)}" ;
                kv:relationReason "{_esc(reason)}" ;
                kv:createdAt "{created_at}"^^xsd:dateTime .
        }}
        """
        self.client.execute_update(update)
        logger.info(
            f"[Level2 Relation] {source_doc_id} --[{relation_type}]--> {target_doc_id} "
            f"(score={score}, method={method})"
        )
        return rel_id

    def get_document_by_id(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Document ID로 문서 조회.

        Args:
            doc_id: 문서 ID

        Returns:
            문서 정보 (없으면 None)
        """
        doc_uri = self._make_uri(doc_id)

        query = f"""
        PREFIX kv: <{self.namespace}>

        SELECT ?p ?o
        WHERE {{
            {doc_uri} ?p ?o .
        }}
        """

        results = self.execute_query(query)

        if not results:
            return None

        # 결과를 dict로 변환
        doc = {"id": doc_id}
        for row in results:
            prop = row["p"]
            value = row["o"]
            # namespace 제거
            if prop.startswith(self.namespace):
                key = prop[len(self.namespace):]
                doc[key] = value

        return doc

    def count_documents(self) -> int:
        """전체 Document 수 조회.

        Returns:
            Document 개수
        """
        query = f"""
        PREFIX kv: <{self.namespace}>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

        SELECT (COUNT(?doc) as ?count)
        WHERE {{
            ?doc rdf:type kv:Document .
        }}
        """

        results = self.execute_query(query)
        if results and len(results) > 0:
            return int(results[0].get("count", 0))
        return 0

    def count_keys(self) -> int:
        """전체 Key 수 조회.

        Returns:
            Key 개수
        """
        query = f"""
        PREFIX kv: <{self.namespace}>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

        SELECT (COUNT(?key) as ?count)
        WHERE {{
            ?key rdf:type kv:Key .
        }}
        """

        results = self.execute_query(query)
        if results and len(results) > 0:
            return int(results[0].get("count", 0))
        return 0

    def count_values(self) -> int:
        """전체 Value 수 조회.

        Returns:
            Value 개수
        """
        query = f"""
        PREFIX kv: <{self.namespace}>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

        SELECT (COUNT(?value) as ?count)
        WHERE {{
            ?value rdf:type kv:Value .
        }}
        """

        results = self.execute_query(query)
        if results and len(results) > 0:
            return int(results[0].get("count", 0))
        return 0
