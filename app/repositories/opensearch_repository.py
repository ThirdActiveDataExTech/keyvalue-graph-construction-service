from typing import List, Optional, Dict, Any

import logging

from app.clients.opensearch import OpenSearchClient, get_opensearch_client
from app.config import settings

logger = logging.getLogger(__name__)


class OpenSearchRepository:
    """OpenSearch 저장소."""

    def __init__(self, client: Optional[OpenSearchClient] = None):
        """OpenSearch 저장소 초기화.

        Args:
            client: OpenSearchClient 인스턴스 (기본값: None, 자동 생성)
        """
        self.client = client or get_opensearch_client()
        self.documents_index = settings.OPENSEARCH_DOCUMENTS_INDEX
        self.keys_index = settings.OPENSEARCH_KEYS_INDEX
        self.values_index = settings.OPENSEARCH_VALUES_INDEX

    def index_document(
            self,
            content: str,
            embedding: List[float],
            domain: str = "",
            metadata: Optional[Dict[str, Any]] = None,
            document_id: Optional[str] = None,
            table_name: str = ""
    ) -> Dict[str, Any]:
        """Document 노드 인덱싱.

        Args:
            content: 문서 내용
            embedding: 문서 임베딩 벡터 (768차원)
            domain: 데이터 도메인 (예: 의료, 법률, 방송)
            metadata: 메타데이터
            document_id: 문서 ID. 지정 시 OpenSearch _id 로 사용하여 Neptune documentId 와 동일 키로 정렬.
                미지정 시 UUID 자동 생성.
            table_name: 이 문서가 속한 데이터셋(테이블)명. Level 1 게이팅 및 Value 검색 필터에 사용.

        Returns:
            인덱싱 결과 {"doc_id": document_id, ...}
        """
        body = {
            "content": content,
            "embedding": embedding,
            "domain": domain,
            "table_name": table_name,
            "metadata": metadata or {}
        }
        if document_id is not None:
            body["doc_id"] = document_id
            doc_id, response = self.client.index_document(
                self.documents_index, body, doc_id=document_id, add_id_to_body=False
            )
        else:
            doc_id, response = self.client.index_document(self.documents_index, body)
        return {"doc_id": doc_id, **response}

    def index_key(
            self,
            key_name: str,
            key_type: str,
            key_type_confidence: float,
            domain: str = "",
            original_key_name: Optional[str] = None,
            embedding: Optional[List[float]] = None
    ) -> Dict[str, Any]:
        """Key 노드 인덱싱.

        Args:
            key_name: Key 이름 (한글)
            key_type: 필드 타입 (semantic, numeric_date, proper_noun)
            key_type_confidence: 타입 분류 신뢰도
            domain: 데이터 도메인 (예: 의료, 법률, 방송)
            original_key_name: 원본 필드명 (예: BIZPLC_NM)
            embedding: Key 임베딩 벡터 (semantic/proper_noun만)

        Returns:
            인덱싱 결과 {"key_id": UUID, ...}
        """
        body = {
            "key_name": key_name,
            "key_type": key_type,
            "key_type_confidence": key_type_confidence,
            "domain": domain
        }
        if original_key_name:
            body["original_key_name"] = original_key_name
        if embedding is not None:
            body["embedding"] = embedding

        # UUID 자동 생성, key_id 필드에도 UUID 저장
        key_uuid, response = self.client.index_document(self.keys_index, body, add_id_to_body=False)

        # key_id 필드 업데이트
        self.client.client.update(
            index=self.keys_index,
            id=key_uuid,
            body={"doc": {"key_id": key_uuid}}
        )

        return {"key_id": key_uuid, **response}

    def index_value(
            self,
            value_content: str,
            parent_key_id: str,
            parent_key_name: str,
            parent_key_type: str,
            document_ids: List[str],
            embedding: Optional[List[float]] = None,
            value_type: str = "text",
            numeric_value: Optional[float] = None,
            table_name: str = ""
    ) -> Dict[str, Any]:
        """Value 노드 인덱싱.

        Args:
            value_content: Value 내용
            parent_key_id: 부모 Key ID (UUID)
            parent_key_name: 부모 Key 이름 (한글)
            parent_key_type: 부모 Key 타입 (semantic, numeric_date, proper_noun)
            document_ids: 이 Value가 추출된 Document ID 리스트
            embedding: Value 임베딩 벡터 (semantic/proper_noun만)
            value_type: Value 데이터 타입 (text, number 등)
            numeric_value: 숫자 값 (numeric_date 타입만)
            table_name: 이 Value가 속한 데이터셋(테이블)명. Level 1 게이팅 필터에 사용.

        Returns:
            인덱싱 결과 {"value_id": UUID, ...}
        """
        body = {
            "value_content": value_content,
            "parent_key_id": parent_key_id,
            "parent_key_name": parent_key_name,
            "parent_key_type": parent_key_type,
            "document_ids": document_ids,
            "value_type": value_type,
            "table_name": table_name
        }
        if embedding is not None:
            body["embedding"] = embedding
        if numeric_value is not None:
            body["numeric_value"] = numeric_value

        # Value는 doc_id 필드를 body에 추가하지 않음
        value_uuid, response = self.client.index_document(self.values_index, body, add_id_to_body=False)

        # value_id 필드 업데이트
        self.client.client.update(
            index=self.values_index,
            id=value_uuid,
            body={"doc": {"value_id": value_uuid}}
        )

        return {"value_id": value_uuid, **response}

    def bulk_index_documents(self, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Document 노드 대량 인덱싱.

        Args:
            documents: 문서 리스트
                각 문서는 {_id, doc_id, content, embedding, metadata} 포함

        Returns:
            벌크 인덱싱 결과
        """
        return self.client.bulk_index(self.documents_index, documents)

    def bulk_index_keys(self, keys: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Key 노드 대량 인덱싱.

        Args:
            keys: Key 리스트
                각 Key는 {_id, key_id, key_name, embedding} 포함

        Returns:
            벌크 인덱싱 결과
        """
        return self.client.bulk_index(self.keys_index, keys)

    def bulk_index_values(self, values: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Value 노드 대량 인덱싱.

        Args:
            values: Value 리스트
                각 Value는 {_id, value_id, value_content, parent_key_id, embedding, value_type} 포함

        Returns:
            벌크 인덱싱 결과
        """
        return self.client.bulk_index(self.values_index, values)

    def search_documents(
            self,
            query_vector: List[float],
            top_k: int = 5,
            filter_doc_ids: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Document 벡터 검색.

        Args:
            query_vector: 쿼리 임베딩 벡터
            top_k: 반환할 최대 결과 수
            filter_doc_ids: 검색 범위를 제한할 Document ID 리스트

        Returns:
            검색 결과 리스트 (각 결과는 doc_id, content, score 포함)
        """
        query_body = {
            "size": top_k,
            "query": {
                "bool": {
                    "must": {
                        "knn": {
                            "embedding": {
                                "vector": query_vector,
                                "k": top_k
                            }
                        }
                    }
                }
            }
        }

        if filter_doc_ids:
            query_body["query"]["bool"]["filter"] = [
                {"terms": {"doc_id": filter_doc_ids}}
            ]

        response = self.client.search(self.documents_index, query_body)

        results = []
        for hit in response["hits"]["hits"]:
            results.append({
                "doc_id": hit["_source"]["doc_id"],
                "content": hit["_source"]["content"],
                "score": hit["_score"],
                "metadata": hit["_source"].get("metadata", {})
            })

        return results

    def search_keys(
            self,
            query_vector: List[float],
            top_k: int = 3
    ) -> List[Dict[str, Any]]:
        """Key 벡터 검색.

        Args:
            query_vector: 쿼리 임베딩 벡터
            top_k: 반환할 최대 결과 수

        Returns:
            검색 결과 리스트 (각 결과는 key_id, key_name, score 포함)
        """
        query_body = {
            "size": top_k,
            "query": {
                "knn": {
                    "embedding": {
                        "vector": query_vector,
                        "k": top_k
                    }
                }
            }
        }

        response = self.client.search(self.keys_index, query_body)

        results = []
        for hit in response["hits"]["hits"]:
            results.append({
                "key_id": hit["_source"]["key_id"],
                "key_name": hit["_source"]["key_name"],
                "score": hit["_score"]
            })

        return results

    def search_values(
            self,
            query_vector: List[float],
            parent_key_ids: List[str],
            top_k: int = 10,
            allowed_table_names: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Value 벡터 검색 (특정 Key들에 속한 Value만).

        Args:
            query_vector: 쿼리 임베딩 벡터
            parent_key_ids: 검색 범위를 제한할 Key ID 리스트
            top_k: 반환할 최대 결과 수
            allowed_table_names: Level 1 게이팅 — 검색 대상을 이 데이터셋(테이블)들에 속한
                Value로만 제한. None이면 제한하지 않음.

        Returns:
            검색 결과 리스트 (value_id, value_content, parent_key_id, parent_key_name,
            value_type, numeric_value, document_ids, table_name, score 포함)
        """
        filters: List[Dict[str, Any]] = [{"terms": {"parent_key_id": parent_key_ids}}]
        if allowed_table_names:
            # 동적 매핑 문자열은 .keyword 서브필드로 정확 매칭
            filters.append({"terms": {"table_name.keyword": allowed_table_names}})

        query_body = {
            "size": top_k,
            "query": {
                "bool": {
                    "must": {
                        "knn": {
                            "embedding": {
                                "vector": query_vector,
                                "k": top_k
                            }
                        }
                    },
                    "filter": filters
                }
            }
        }

        response = self.client.search(self.values_index, query_body)

        results = []
        for hit in response["hits"]["hits"]:
            source = hit["_source"]
            results.append({
                "value_id": source["value_id"],
                "value_content": source["value_content"],
                "parent_key_id": source["parent_key_id"],
                "parent_key_name": source.get("parent_key_name", ""),
                "parent_key_type": source.get("parent_key_type", "semantic"),
                "value_type": source["value_type"],
                "numeric_value": source.get("numeric_value"),
                "document_ids": source.get("document_ids", []),
                "table_name": source.get("table_name", ""),
                "score": hit["_score"]
            })

        return results

    def get_document_key_values(self, document_id: str, size: int = 500) -> List[Dict[str, Any]]:
        """특정 Document에서 추출된 모든 Value(=Key-Value)를 조회.

        Neptune openCypher 대신 OpenSearch values 인덱스에서 직접 조회한다.

        Args:
            document_id: 기준 Document ID (Neptune documentId 와 동일 키)
            size: 최대 조회 개수

        Returns:
            Value 문서 리스트 (parent_key_name, parent_key_type, value_content,
            numeric_value, embedding, table_name 포함)
        """
        query_body = {
            "size": size,
            "query": {"term": {"document_ids.keyword": document_id}},
        }
        response = self.client.search(self.values_index, query_body)
        return [hit["_source"] for hit in response["hits"]["hits"]]

    def get_table_feature_counts(self, table_name: str, size: int = 500) -> Dict[str, int]:
        """데이터셋(테이블)의 KV 그래프 특징 출현 횟수 집계 — PPMI 연관성 분석용.

        values 인덱스를 table_name 으로 필터해 Key 이름과 Value 내용을 terms aggregation.
        특징 표기는 "key:{이름}" / "value:{내용}" 으로 구분한다.

        Returns:
            {특징: 출현 횟수}. KV 그래프 미구축/실패 시 빈 dict
        """
        try:
            response = self.client.search(
                self.values_index,
                {
                    "size": 0,
                    "query": {"term": {"table_name.keyword": table_name}},
                    "aggs": {
                        "keys": {"terms": {"field": "parent_key_name.keyword", "size": size}},
                        "values": {"terms": {"field": "value_content.keyword", "size": size}},
                    },
                },
            )
            aggs = response.get("aggregations", {})
            counts: Dict[str, int] = {}
            for bucket in aggs.get("keys", {}).get("buckets", []):
                counts[f"key:{bucket['key']}"] = bucket["doc_count"]
            for bucket in aggs.get("values", {}).get("buckets", []):
                counts[f"value:{bucket['key']}"] = bucket["doc_count"]
            return counts
        except Exception:
            return {}

    def count_documents_by_table(self, table_name: str) -> int:
        """특정 데이터셋(테이블)에 속한 Document 수를 반환 (KV 그래프 처리 여부 판단용).

        Args:
            table_name: 데이터셋(테이블)명

        Returns:
            Document 개수 (인덱스 없거나 조회 실패 시 0)
        """
        try:
            if not self.client.client.indices.exists(index=self.documents_index):
                return 0
            resp = self.client.client.count(
                index=self.documents_index,
                body={"query": {"term": {"table_name.keyword": table_name}}},
            )
            return int(resp.get("count", 0))
        except Exception:
            return 0

    def get_document_table(self, document_id: str) -> Optional[str]:
        """Document ID로 소속 데이터셋(테이블)명을 조회.

        Args:
            document_id: Document ID

        Returns:
            table_name 또는 None
        """
        try:
            source = self.client.client.get(index=self.documents_index, id=document_id)["_source"]
            return source.get("table_name") or None
        except Exception:
            # 문서 인덱스에 없으면 values 인덱스에서 보조 조회
            values = self.get_document_key_values(document_id, size=1)
            if values:
                return values[0].get("table_name") or None
            return None

    def delete_document(self, doc_id: str) -> Dict[str, Any]:
        """Document 삭제.

        Args:
            doc_id: 문서 ID (UUID)

        Returns:
            삭제 결과
        """
        return self.client.delete_document(self.documents_index, doc_id)

    def delete_key(self, key_id: str) -> Dict[str, Any]:
        """Key 삭제.

        Args:
            key_id: Key ID (UUID)

        Returns:
            삭제 결과
        """
        return self.client.delete_document(self.keys_index, key_id)

    def delete_value(self, value_id: str) -> Dict[str, Any]:
        """Value 삭제.

        Args:
            value_id: Value ID (UUID)

        Returns:
            삭제 결과
        """
        return self.client.delete_document(self.values_index, value_id)


def get_opensearch_repository() -> OpenSearchRepository:
    """OpenSearch 저장소 팩토리 함수.

    Returns:
        OpenSearchRepository 인스턴스
    """
    return OpenSearchRepository()
