"""실시간 워크플로우 API (SSE)"""
import asyncio
import json
import logging
from typing import AsyncGenerator, Annotated

from fastapi import APIRouter, UploadFile, File, Form
from fastapi.responses import StreamingResponse

from app.src.keyvalue_graph.schema_analyzer import SchemaAnalyzer
from app.src.keyvalue_graph.llm_based_loader import LLMBasedKeyValueLoader
from app.src.keyvalue_graph.clustering_normalizer import ClusteringNormalizer

router = APIRouter(prefix="/workflow", tags=["KeyValue Graph"])
logger = logging.getLogger(__name__)


async def workflow_stream(
    file_content: bytes,
    filename: str,
    auto_detect_schema: bool,
    sample_size: int,
    similarity_threshold: float,
    min_cluster_size: int,
    table_name: str = ""
) -> AsyncGenerator[str, None]:
    """워크플로우 실행 및 실시간 진행 상태 전송.

    단계:
    1. 입력 데이터 수신
    2. 스키마 분석
    3. Key-Value 추출 및 그래프 생성
    4. 정규화
    5. 완료
    """

    def send_event(step: int, status: str, message: str, data: dict = None):
        """SSE 이벤트 전송"""
        event = {
            "step": step,
            "status": status,  # 'processing', 'completed', 'error'
            "message": message,
            "timestamp": asyncio.get_event_loop().time(),
            "data": data or {}
        }
        return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    try:
        # 데이터셋(테이블) 식별자: 명시 안 하면 파일 stem 사용 → Level 1 게이팅 기준
        from pathlib import Path
        effective_table = table_name or Path(filename or "workflow_upload").stem

        # Step 0: 원본 파일 보존 (§3.2, 백엔드는 RAW_STORAGE_BACKEND) — 실패해도 워크플로우 계속
        try:
            from app.src.dataset.raw_storage import get_raw_storage
            storage = get_raw_storage()
            if storage.enabled:
                object_name = storage.store_raw_dataset(effective_table, filename or "upload.json", file_content)
                logger.info(f"[RawStorage] 원본 저장: {object_name}")
        except Exception as e:
            logger.warning(f"[RawStorage] 원본 저장 실패 (워크플로우는 계속): {e}")

        # Step 1: 파일 수신
        yield send_event(1, "processing", "📥 파일 수신 중...")
        data_list = json.loads(file_content.decode("utf-8"))

        if not isinstance(data_list, list):
            data_list = [data_list]

        yield send_event(1, "completed", f"✅ 파일 수신 완료 ({len(data_list)}건)", {
            "records_count": len(data_list)
        })
        await asyncio.sleep(0.5)

        # Step 2: 스키마 분석
        field_mapping = None
        detected_schema = None
        centrality_name = "데이터현황"

        if auto_detect_schema:
            yield send_event(2, "processing", "🔍 스키마 분석 중...")

            analyzer = SchemaAnalyzer(sample_size=sample_size)
            detected_schema = analyzer.analyze(data_list)

            # 필드 매핑 생성
            field_mapping = {
                original_key: field_info.korean_name
                for original_key, field_info in detected_schema.fields.items()
            }

            # extractable_metadata 추가
            for meta_key, meta_info in detected_schema.extractable_metadata.items():
                field_mapping[meta_key] = meta_info.korean_name

            centrality_name = detected_schema.centrality_name

            yield send_event(2, "completed", f"✅ 스키마 분석 완료 (도메인: {detected_schema.domain})", {
                "domain": detected_schema.domain,
                "centrality_name": centrality_name,
                "fields_count": len(field_mapping),
                "confidence": detected_schema.confidence
            })
        else:
            yield send_event(2, "completed", "⏭️  스키마 분석 스킵 (기본 매핑 사용)")

        await asyncio.sleep(0.5)

        # Step 3: Key-Value 추출 및 그래프 생성
        yield send_event(3, "processing", "⚙️  Key-Value 추출 및 그래프 생성 중...")

        loader = LLMBasedKeyValueLoader(field_mapping=field_mapping)

        success_count = 0
        failed_count = 0
        results = []

        for idx, data_item in enumerate(data_list):
            data_text = json.dumps(data_item, ensure_ascii=False)
            result = loader.extract_and_build_graph(
                data_text,
                centrality_name=centrality_name,
                source_file=filename or "workflow_upload",
                record_index=idx,
                extractable_metadata=detected_schema.extractable_metadata if detected_schema else None,
                table_name=effective_table
            )

            if result["success"]:
                success_count += 1
            else:
                failed_count += 1

            results.append({
                "index": idx,
                "document_id": result.get("document_id"),
                "success": result["success"]
            })

            # 진행률 중간 보고 (10건마다)
            if (idx + 1) % 10 == 0 or (idx + 1) == len(data_list):
                progress = ((idx + 1) / len(data_list)) * 100
                yield send_event(3, "processing",
                    f"⚙️  그래프 생성 중... ({idx + 1}/{len(data_list)}, {progress:.0f}%)", {
                        "processed": idx + 1,
                        "total": len(data_list),
                        "progress": progress
                    })

        yield send_event(3, "completed", f"✅ 그래프 생성 완료 ({success_count}건 성공, {failed_count}건 실패)", {
            "success_count": success_count,
            "failed_count": failed_count,
            "total": len(data_list)
        })
        await asyncio.sleep(0.5)

        # Step 4: 정규화
        yield send_event(4, "processing", "🔄 Value 정규화 중...")

        normalizer = ClusteringNormalizer()
        normalize_result = normalizer.normalize_all_keys(
            similarity_threshold=similarity_threshold,
            min_cluster_size=min_cluster_size
        )

        yield send_event(4, "completed", f"✅ 정규화 완료 ({normalize_result['normalized_count']}개 정규화)", {
            "keys_count": normalize_result['keys_count'],
            "clusters_count": normalize_result['clusters_count'],
            "normalized_count": normalize_result['normalized_count']
        })
        await asyncio.sleep(0.5)

        # Step 5: 완료
        yield send_event(5, "completed", "🎉 워크플로우 완료!", {
            "summary": {
                "records": len(data_list),
                "success": success_count,
                "failed": failed_count,
                "centrality_name": centrality_name,
                "normalized_values": normalize_result['normalized_count']
            }
        })

    except Exception as e:
        logger.error(f"워크플로우 실행 중 오류: {e}", exc_info=True)
        yield send_event(0, "error", f"❌ 오류 발생: {str(e)}", {
            "error": str(e),
            "error_type": type(e).__name__
        })


@router.post("/execute", summary="파일 업로드 → KV 그래프 워크플로우 실행 (SSE)")
async def execute_workflow(
    file: Annotated[UploadFile, File()],
    auto_detect_schema: Annotated[bool, Form()] = True,
    sample_size: Annotated[int, Form()] = 5,
    similarity_threshold: Annotated[float, Form()] = 0.85,
    min_cluster_size: Annotated[int, Form()] = 2,
    table_name: Annotated[str, Form()] = ""
):
    """파일 업로드 → 자동 워크플로우 실행 (SSE 스트리밍).

    Args:
        file: JSON 배열 파일
        auto_detect_schema: 스키마 자동 감지 여부
        sample_size: 스키마 분석 샘플 크기
        similarity_threshold: 정규화 유사도 임계값
        min_cluster_size: 정규화 최소 클러스터 크기
        table_name: 데이터셋(테이블)명. Level 1 관계/게이팅과 정합되도록 지정 권장.
            비우면 업로드 파일명 stem 을 사용.

    Returns:
        Server-Sent Events 스트림
    """
    # 파일을 미리 읽어서 메모리에 저장
    file_content = await file.read()
    filename = file.filename

    return StreamingResponse(
        workflow_stream(file_content, filename, auto_detect_schema, sample_size, similarity_threshold, min_cluster_size, table_name),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Nginx buffering 비활성화
        }
    )
