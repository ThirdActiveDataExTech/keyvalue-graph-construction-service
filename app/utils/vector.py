"""벡터 유사도 공용 유틸 (relation_pipeline / domain_classifier / ppmi_analyzer 공용)."""

import math


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """dense 벡터 코사인 유사도 (0.0~1.0 클램프)."""
    dot = sum(x * y for x, y in zip(v1, v2))
    norm1 = math.sqrt(sum(x * x for x in v1))
    norm2 = math.sqrt(sum(x * x for x in v2))
    if not norm1 or not norm2:
        return 0.0
    return max(0.0, min(1.0, dot / (norm1 * norm2)))


def sparse_cosine_similarity(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    """희소(feature→weight dict) 벡터 코사인 유사도 (0.0~1.0 클램프)."""
    dot = sum(w * vec_b[f] for f, w in vec_a.items() if f in vec_b)
    norm_a = math.sqrt(sum(w * w for w in vec_a.values()))
    norm_b = math.sqrt(sum(w * w for w in vec_b.values()))
    if not norm_a or not norm_b:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


def mean_vector(vectors: list[list[float]]) -> list[float]:
    """동일 차원 벡터들의 평균 벡터 (centroid)."""
    dim = len(vectors[0])
    return [sum(v[i] for v in vectors) / len(vectors) for i in range(dim)]
