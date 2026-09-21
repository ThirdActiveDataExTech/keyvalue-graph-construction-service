from typing import List

from sentence_transformers import SentenceTransformer

from app.config import settings
from app.exceptions.base import ApplicationError


class EmbeddingService:
    """Embedding 생성 로직"""

    def __init__(self):
        """초기화 - SentenceTransformer 모델 로드"""
        self._model_name: str = settings.EMBEDDING_MODEL_NAME
        self._model: SentenceTransformer = SentenceTransformer(self._model_name)

    def generate_embedding(self, text: str, show_progress_bar: bool = False) -> List[float]:
        """텍스트를 embedding 벡터로 변환

        Args:
            text: 변환할 텍스트
            show_progress_bar: 진행 상황 표시 여부 (기본: False)

        Returns:
            embedding 벡터 (float list, 차원은 모델에 따라 결정됨)

        Raises:
            ApplicationError: 텍스트가 비어있거나 embedding 생성 실패
        """
        if not text or not text.strip():
            raise ApplicationError(
                code=400,
                message="입력 텍스트가 비어있습니다.",
                result={"error_type": "empty_text"}
            )
        embedding = self._model.encode(text, convert_to_numpy=True, show_progress_bar=show_progress_bar)
        return embedding.tolist()

    @staticmethod
    def binarize_embedding(embedding: List[float], method: str = "threshold") -> List[float]:
        """Float embedding을 binary embedding으로 변환

        Args:
            embedding: 원본 float embedding
            method: 변환 방법 ("threshold" 또는 "sign")
                - "threshold": 0보다 크면 1.0, 아니면 0.0
                - "sign": 0 이상이면 1.0, 음수면 0.0

        Returns:
            Binary embedding (0.0 또는 1.0로만 구성된 리스트)
        """
        if method == "threshold":
            return [1.0 if x > 0 else 0.0 for x in embedding]
        elif method == "sign":
            return [1.0 if x >= 0 else 0.0 for x in embedding]
        else:
            raise ValueError(f"지원하지 않는 변환 방법: {method}")


embedding_service = EmbeddingService()
