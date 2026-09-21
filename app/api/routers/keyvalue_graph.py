import json
import logging
from typing import Annotated

from fastapi import APIRouter, Body, UploadFile, File
from fastapi.responses import JSONResponse

from app.schemas.response import APIResponseModel
from app.src.keyvalue_graph.clustering_normalizer import ClusteringNormalizer
from app.src.keyvalue_graph.llm_based_loader import LLMBasedKeyValueLoader
from app.src.keyvalue_graph.relation_candidate_finder import RelationCandidateFinder
from app.src.keyvalue_graph.schema_analyzer import SchemaAnalyzer

router = APIRouter(prefix="/keyvalue", tags=["KeyValue Graph"])
logger = logging.getLogger(__name__)


@router.post(
    "/batch_extract",
    summary="레코드 배치 Key-Value 추출 및 그래프 생성",
    response_model=APIResponseModel,
    response_class=JSONResponse,
)
async def batch_extract_key_value_from_json(
        file: Annotated[UploadFile, File()],
        centrality_name: str = "병원현황",
        auto_detect_schema: bool = False,
        sample_size: int = 5,
        table_name: str = ""
):
    """JSON 배열 파일에서 Key-Value를 배치 추출하고 그래프 생성.

    Args:
        file: JSON 배열 파일 [{...}, {...}, ...]
        centrality_name: 중심 노드 이름 (예: "병원현황", "판례정보"). auto_detect_schema=True면 무시됨
        auto_detect_schema: 스키마 자동 감지 여부 (True: 데이터 분석 후 자동 감지, False: 기본 매핑 사용)
        sample_size: 스키마 분석 시 샘플링할 레코드 개수 (auto_detect_schema=True일 때만 사용)

    Returns:
        배치 처리 결과 (성공/실패 통계)
    """
    content = await file.read()
    data_list = json.loads(content.decode("utf-8"))

    if not isinstance(data_list, list):
        data_list = [data_list]

    # 데이터셋(테이블) 식별자: 미지정 시 파일 stem 사용 → Level 1 게이팅 기준
    from pathlib import Path
    effective_table = table_name or Path(file.filename or "batch_upload").stem

    # 원본 파일 보존 (§3.2, 백엔드는 RAW_STORAGE_BACKEND)
    try:
        from app.src.dataset.raw_storage import get_raw_storage
        storage = get_raw_storage()
        if storage.enabled:
            storage.store_raw_dataset(effective_table, file.filename or "batch_upload", content)
    except Exception as e:
        logger.warning(f"[RawStorage] 원본 저장 실패 (배치는 계속): {e}")

    # 스키마 자동 감지 모드
    field_mapping = None
    detected_schema = None

    if auto_detect_schema:
        analyzer = SchemaAnalyzer(sample_size=sample_size)
        detected_schema = analyzer.analyze(data_list)

        # 원본 필드 매핑
        field_mapping = {
            original_key: field_info.korean_name
            for original_key, field_info in detected_schema.fields.items()
        }

        # extractable_metadata 추가 (합치기!)
        for meta_key, meta_info in detected_schema.extractable_metadata.items():
            field_mapping[meta_key] = meta_info.korean_name

        # 감지된 domain과 centrality_name 사용
        domain = detected_schema.domain
        centrality_name = detected_schema.centrality_name

        logger.info(
            f"스키마 분석 결과: domain={domain}, centrality_name={centrality_name}"
        )
        logger.info(
            f"통합 필드 매핑: 원본 {len(detected_schema.fields)}개 + "
            f"메타데이터 {len(detected_schema.extractable_metadata)}개 = "
            f"총 {len(field_mapping)}개"
        )

    loader = LLMBasedKeyValueLoader(field_mapping=field_mapping)

    success_count = 0
    results = []

    for idx, data_item in enumerate(data_list):
        try:
            data_text = json.dumps(data_item, ensure_ascii=False)
            result = loader.extract_and_build_graph(
                data_text,
                centrality_name=centrality_name,
                domain=domain if auto_detect_schema else centrality_name,
                source_file=file.filename or "batch_upload",
                record_index=idx,
                extractable_metadata=detected_schema.extractable_metadata if detected_schema else None,
                table_name=effective_table
            )

            success_count += 1
            results.append({
                "index": idx,
                "document_id": result["document_id"],
                "success": True,
                "keys_count": result["keys_count"],
                "values_count": result["values_count"]
            })

        except Exception as e:
            # 에러 발생 시 즉시 중단하고 상세 정보 반환
            error_message = str(e)
            logger.error(f"배치 처리 중단: {idx+1}/{len(data_list)} 레코드에서 에러 발생 - {error_message}")

            error_detail = {
                "index": idx,
                "success": False,
                "error": error_message,
                "error_type": type(e).__name__,
                "centrality_name": centrality_name,
                "processed_count": success_count,
                "failed_at": idx,
                "total_count": len(data_list),
                "previous_results": results
            }

            return APIResponseModel(
                result=error_detail,
                description=f"배치 처리 실패: {idx+1}번째 레코드에서 {type(e).__name__} 에러 발생 (전체 {len(data_list)}개 중 {success_count}개 성공)",
                code=500
            )

    # 모든 레코드 성공 시 결과 반환
    if auto_detect_schema and detected_schema:
        description = (
            f"배치 처리 완료 [자동 스키마 감지]\n"
            f"- 도메인: {detected_schema.domain}\n"
            f"- Centrality: {centrality_name}\n"
            f"- 감지된 필드: {len(field_mapping)}개\n"
            f"- 처리 결과: {success_count}건 성공"
        )
        result_data = {
            "total": len(data_list),
            "success": success_count,
            "failed": 0,
            "centrality_name": centrality_name,
            "auto_detected": True,
            "detected_schema": {
                "domain": detected_schema.domain,
                "centrality_name": detected_schema.centrality_name,
                "fields": {
                    field_name: {
                        "korean_name": field_info.korean_name,
                        "description": field_info.description,
                        "data_type": field_info.data_type
                    }
                    for field_name, field_info in detected_schema.fields.items()
                },
                "confidence": detected_schema.confidence
            },
            "details": results
        }
    else:
        description = f"배치 처리 완료 (Centrality: {centrality_name}): {success_count}건 성공"
        result_data = {
            "total": len(data_list),
            "success": success_count,
            "failed": 0,
            "centrality_name": centrality_name,
            "auto_detected": False,
            "details": results
        }

    return APIResponseModel(
        result=result_data,
        description=description
    )


@router.post(
    "/normalize",
    summary="클러스터링 기반 Value 자동 정규화",
    response_model=APIResponseModel,
    response_class=JSONResponse,
)
async def normalize_key_values(
        key_name: Annotated[str | None, Body(embed=True)] = None,
        similarity_threshold: Annotated[float, Body(embed=True)] = 0.85,
        min_cluster_size: Annotated[int, Body(embed=True)] = 2
):
    """클러스터링 기반 Value 자동 정규화.

    Args:
        key_name: 특정 Key명만 정규화 (None이면 전체 Key 정규화)
        similarity_threshold: 유사도 임계값 (0~1, 높을수록 엄격). 기본값 0.85
        min_cluster_size: 최소 클러스터 크기 (작은 클러스터 무시). 기본값 2

    Flow:
        1. Key별로 연결된 모든 Value 조회
        2. Value 간 유사도 행렬 계산 (RapidFuzz token_sort_ratio)
        3. DBSCAN 클러스터링으로 유사한 Value 그룹화
        4. 각 클러스터의 대표값 선정 (빈도수 높은 것, 동률이면 긴 것)
        5. NormalizedValue 노드 생성 및 SAME_AS 관계 생성

    Returns:
        정규화 통계 (Key 수, 클러스터 수, 정규화된 Value 수)
    """
    normalizer = ClusteringNormalizer()

    if key_name:
        result = normalizer.normalize_key_values(
            key_name,
            similarity_threshold=similarity_threshold,
            min_cluster_size=min_cluster_size
        )
        return APIResponseModel(
            result=result,
            description=f"Key '{key_name}' 정규화 완료: {result['clusters_count']}개 클러스터, {result['normalized_count']}개 정규화"
        )
    else:
        result = normalizer.normalize_all_keys(
            similarity_threshold=similarity_threshold,
            min_cluster_size=min_cluster_size
        )
        return APIResponseModel(
            result=result,
            description=(
                    f"전체 정규화 완료: {result['keys_count']}개 Key, "
                    f"{result['clusters_count']}개 클러스터, "
                    f"{result['normalized_count']}개 정규화"
                    + (f", {result['failed_keys']}개 Key 실패" if result.get('failed_keys', 0) > 0 else "")
            )
        )


@router.post(
    "/analyze_schema",
    summary="데이터 스키마 자동 분석 (LLM)",
    response_model=APIResponseModel,
    response_class=JSONResponse,
)
async def analyze_data_schema(
        file: Annotated[UploadFile, File()],
        sample_size: Annotated[int, Body(embed=True)] = 5
):
    """데이터 스키마 자동 분석

    파일을 업로드하면 샘플링 + 통계 분석을 통해 스키마를 자동으로 추론합니다.

    Args:
        file: JSON 배열 파일 [{...}, {...}, ...]
        sample_size: 샘플링할 레코드 개수 (기본: 5)

    Flow:
        1. 파일에서 레코드 추출
        2. 샘플링 (균등 분포)
        3. 필드별 통계 수집 (unique 개수, null 비율, 샘플 값)
        4. LLM으로 스키마 추론 (도메인, 필드 한글명, 데이터 타입)
    """
    content = await file.read()
    data_list = json.loads(content.decode("utf-8"))

    if not isinstance(data_list, list):
        data_list = [data_list]

    if not data_list:
        return APIResponseModel(
            result={"error": "데이터가 비어있습니다"},
            description="스키마 분석 실패: 빈 데이터"
        )

    # 스키마 분석
    analyzer = SchemaAnalyzer(sample_size=sample_size)
    schema = analyzer.analyze(data_list)

    return APIResponseModel(
        result={
            "domain": schema.domain,
            "centrality_name": schema.centrality_name,
            "fields": {
                field_name: {
                    "korean_name": field_info.korean_name,
                    "description": field_info.description,
                    "data_type": field_info.data_type
                }
                for field_name, field_info in schema.fields.items()
            },
            "extractable_metadata": {
                meta_name: {
                    "korean_name": meta_info.korean_name,
                    "source_field": meta_info.source_field,
                    "data_type": meta_info.data_type,
                    "description": meta_info.description,
                    "examples": meta_info.examples
                }
                for meta_name, meta_info in schema.extractable_metadata.items()
            },
            "confidence": schema.confidence,
            "notes": schema.notes,
            "analyzed_records": len(data_list)
        },
        description=(
            f"스키마 분석 완료: 도메인={schema.domain}, "
            f"필드 {len(schema.fields)}개, "
            f"추출 가능 메타데이터 {len(schema.extractable_metadata)}개, "
            f"신뢰도={schema.confidence:.2f}"
        )
    )


@router.post(
    "/discover_relation_candidates",
    summary="레코드 간 관계 후보 발굴 (Level 2, 온디맨드)",
    response_model=APIResponseModel,
    response_class=JSONResponse,
)
async def discover_relation_candidates(
    source_doc_id: Annotated[str, Body(embed=True, description="기준 Document ID")],
    top_k: Annotated[int, Body(embed=True, description="반환할 후보 개수")] = 10,
):
    """단일 Document ID로 관계 후보 발굴 (온디맨드 방식)

    프로세스:
    1. Document의 Key-Value 메타데이터 분석
    2. LLM이 핵심 Key 선정 및 검색 전략 수립
    3. 그래프 구조 + 벡터 유사도로 후보 검색
    4. 상위 N개 후보 반환 (사용자 검토용)

    Args:
        source_doc_id: 기준 Document ID
        top_k: 반환할 후보 개수 (기본 10개)
    """
    from app.config import settings
    from app.repositories.opensearch_repository import get_opensearch_repository
    from app.src.dataset.level1_gating import Level1GatingService
    from app.src.meta_extract.llm_response import LLMResponse

    os_repo = get_opensearch_repository()

    # 1. Document의 Key-Value 메타데이터 조회 (OpenSearch values 인덱스)
    kv_rows = os_repo.get_document_key_values(source_doc_id)
    if not kv_rows:
        return APIResponseModel(
            result={"error": "Document를 찾을 수 없습니다"},
            description=f"관계 후보 발굴 실패: Document ID '{source_doc_id}'를 찾을 수 없습니다",
        )

    key_values: dict[str, list[str]] = {}
    for r in kv_rows:
        key = r.get("parent_key_name", "")
        if key:
            key_values.setdefault(key, []).append(r.get("value_content", ""))

    # 2. LLM으로 핵심 Key 분석 (중요 Key + feature_class + 검색 전략)
    llm_response = LLMResponse("relation_key_analysis")
    key_values_json = json.dumps(key_values, ensure_ascii=False, indent=2)
    key_values_formatted = "\n".join([f"- {k}: {v}" for k, v in key_values.items()])

    analysis_result = llm_response.generate_llm_response(
        variables={
            "document_id": source_doc_id,
            "key_values": key_values,
            "key_values_json": key_values_json,
            "key_values_formatted": key_values_formatted,
        }
    )

    important_keys = [ki["key_name"] for ki in analysis_result["important_keys"]]
    feature_classes = {
        ki["key_name"]: ki.get("feature_class", "") for ki in analysis_result["important_keys"]
    }
    search_strategy = analysis_result["search_strategy"]
    important_values = {k: key_values.get(k, []) for k in important_keys}

    logger.info(f"LLM 분석 결과: 중요 Key={important_keys}, 전략={search_strategy}")

    # 2-1. Level 1 게이팅 — 기준 레코드 데이터셋과 Level 1으로 연결된 데이터셋으로 후보 제한
    allowed_tables = None
    source_table = os_repo.get_document_table(source_doc_id)
    if settings.LEVEL2_GATE_BY_LEVEL1 and source_table:
        allowed_tables = Level1GatingService().compute_allowed_tables(source_table)
        logger.info(f"Level 1 게이팅 적용: source_table={source_table}, 허용={sorted(allowed_tables)}")

    # 3. 후보 Document 검색 (OpenSearch 2단 검색 + 게이팅)
    finder = RelationCandidateFinder(opensearch_repo=os_repo)
    candidates = finder.find_candidates(
        source_doc_id=source_doc_id,
        important_keys=important_keys,
        important_values=important_values,
        feature_classes=feature_classes,
        allowed_table_names=allowed_tables,
        top_k=top_k,
    )

    result_payload = {
        "source_doc_id": source_doc_id,
        "source_table": source_table,
        "allowed_tables": sorted(allowed_tables) if allowed_tables else None,
        "source_doc_info": {
            "key_values": key_values,
            "important_keys": important_keys,
            "feature_classes": feature_classes,
            "important_values": important_values,
        },
        "candidates": [c.to_dict() for c in candidates],
        "search_strategy": search_strategy,
        "important_keys": important_keys,
    }

    if not candidates:
        return APIResponseModel(
            result=result_payload,
            description=f"관계 후보를 찾지 못했습니다 (중요 Key: {important_keys})",
        )

    return APIResponseModel(
        result=result_payload,
        description=f"관계 후보 {len(candidates)}개 발견 (전략: {search_strategy})",
    )
