from typing import Dict


class FallbackPrompts:
    SCHEMA_ANALYSIS: str = """**반드시 analyze_schema tool을 사용하여 응답할 것.**

당신은 데이터에서 숨겨진 메타데이터를 발굴하는 전문가입니다.

# 임무
다음 데이터를 분석하여:
1. 데이터의 **도메인**과 **중심 개념**을 파악하고
2. **모든 원본 필드명을 의미있는 한글로 변환**하고
3. **긴 텍스트 필드에서 추출 가능한 메타데이터**를 설계하세요

**중요: 모든 필드명(원본 필드 + extractable_metadata)은 반드시 한글로 작성하세요.**

## 샘플 데이터
{sample_data}

## 통계 정보
{statistics}

---

# 핵심 임무 1: 원본 필드 한글 변환 (fields) ⭐⭐⭐

**반드시 모든 원본 필드를 한글로 번역하세요!**

예시 (병원 데이터):
```
원본: BIZPLC_NM → korean_name: "병원명"
원본: GENRL_AMBLNC_VCNT → korean_name: "일반구급차수"
원본: SICKBD_CNT → korean_name: "병상수"
```

---

# 핵심 임무 2: 추출 가능한 메타데이터 설계 (extractable_metadata) ⭐

**원칙:**
1. 긴 텍스트 필드("text", "content", "description" 등)의 **내용을 분석**
2. 원본 필드에 **없는 새로운 정보**만 extractable_metadata로 설계
3. **검색/분류/필터링에 유용**한 메타데이터 우선
4. **실제로 추출 가능한** 것만 포함

## 추출 가능한 메타데이터 예시 (도메인별)

### 예시 1: 의료연구 논문
```
text: "Female breast cancer incidence... Utah... Mormon... 1985-1999..."

extractable_metadata:
- 연구주제 (text_list): ["유방암 발병률", "종교와 건강"]
- 연구기간 (date_range): ["1985-1999"]
- 연구지역 (text): ["Utah"]
- 질병분류 (text_list): ["암", "유방암"]
- 연구대상 (category): ["여성", "종교인"]
```

### 예시 2: 병원 정보
```
text: "노인 전문 요양병원. 치매, 파킨슨병 환자 특화 케어..."

extractable_metadata:
- 전문분야 (text_list): ["노인의료", "요양케어"]
- 주요질환 (text_list): ["치매", "파킨슨병"]
- 대상환자 (category): ["노인", "만성질환자"]
```

### 예시 3: 법률 판례
```
text: "원고 승소. 손해배상 청구... 서울중앙지법 2022.05.10 선고..."

extractable_metadata:
- 판결결과 (category): ["원고 승소"]
- 사건유형 (category): ["손해배상"]
- 법원 (text): ["서울중앙지법"]
- 선고일 (date): ["2022-05-10"]
```

### 예시 4: 제조업 공장
```
text: "자동차 부품 전문 제조. ISO 9001 인증. 직원 150명..."

extractable_metadata:
- 제조품목 (text_list): ["자동차 부품"]
- 인증현황 (text_list): ["ISO 9001"]
- 규모 (number): ["150"]  // 직원수
```

### 예시 5: 전자상거래 상품
```
text: "삼성 갤럭시 최신 모델. 128GB, 블루. 배터리 5000mAh..."

extractable_metadata:
- 브랜드 (category): ["삼성"]
- 제품라인 (category): ["갤럭시"]
- 용량 (text): ["128GB"]
- 색상 (category): ["블루"]
- 사양 (text_list): ["배터리 5000mAh"]
```

## 메타데이터 타입 가이드
- **text**: 단일 텍스트 (예: 지역, 법원명)
- **text_list**: 여러 키워드/항목 (예: 주제, 질병, 인증)
- **number**: 숫자 (예: 직원수, 용량)
- **date**: 단일 날짜
- **date_range**: 기간 (예: "1985-1999")
- **category**: 분류/상태 (예: 결과, 유형, 브랜드)

## 추출 가능 메타데이터 판단 기준

**추출 가능**
- 텍스트에서 명시적으로 언급된 개체/값
- 분류/검색에 직접 활용 가능
- 구체적이고 명확한 정보

**추출 불가능**
- 원본 필드에 이미 있는 정보 (중복)
- 텍스트에 없는 추측/추론
- 너무 추상적이거나 모호한 개념

## 주의사항
- **이 예시들은 참고용**입니다. 실제 데이터 내용에 맞게 설계하세요
- 원본 필드 구조를 그대로 복사하지 마세요
- 텍스트가 짧거나 구조화된 데이터만 있으면 extractable_metadata는 빈 딕셔너리 {{}}
- examples는 샘플 데이터에서 실제로 추출한 값만 포함

---

# 출력 형식

반드시 analyze_schema tool 호출:
```
{{
    "domain": "도메인명 (예: 의료, 법률, ... )",
    "centrality_name": "거시적 도메인명 (예: 의료, 법률, 방송 등) - domain과 동일하거나 더 포괄적으로",
    "fields": {{
        "원본필드명": {{
            "korean_name": "의미있는 한글명",
            "data_type": "타입 (text, number, date 등)",
            "description": "필드 설명"
        }},
        ...
    }},
    "extractable_metadata": {{
        "메타필드명": {{
            "korean_name": "한글명",
            "source_field": "원본필드명 (text, content 등)",
            "data_type": "타입 (text, text_list, number, date, date_range, category)",
            "description": "이 메타데이터가 무엇인지 명확한 설명",
            "examples": ["샘플에서 실제 추출한 예시1", "예시2"]
        }},
        ...
    }},
    "confidence": 0.0~1.0,
    "notes": "추가 설명"
}}
```

**필수: 원본 필드(fields)도 반드시 출력하세요!**
- **모든 원본 필드의 korean_name을 의미있는 한글로 번역** (예: "GENRL_AMBLNC_VCNT" → "일반구급차수")
- 영문 약어는 풀어서 의미를 명확히 (CNT→수, NM→명, ADDR→주소 등)
- extractable_metadata만 집중해서 설계하세요.
- 추출 가능한 메타데이터가 없으면 extractable_metadata는 {{}}로 반환하세요.
"""

    CLUSTER_NORMALIZE: str = """**반드시 normalize_cluster tool을 사용하여 응답할 것.**

당신은 유사한 값들을 분석하여 적절한 정규화 값을 생성하는 전문가입니다.

# 임무
다음은 클러스터링으로 묶인 유사한 값들의 리스트입니다.
이 값들을 대표할 수 있는 **하나의 정규화 값**을 선택하거나 생성하세요.

Values (클러스터): {cluster_values}

# 중요 원칙

**출력은 반드시 Value들 자체에서 나와야 합니다**
- "병상수", "날짜", "범위" 같은 추상적 메타 개념을 만들지 마세요
- 주어진 Value 중 하나를 선택하거나, Value들의 조합/정제 형태만 허용

# 정규화 전략

## 1. 가장 완전하고 표준적인 형태 선택

예시:
- ["꿈이있는 치과", "꿈이있는치과병원", "꿈이있는치과"]
  → "꿈이있는치과병원" (가장 완전한 형태)

- ["서울대병원", "서울대학교병원", "서울대 병원"]
  → "서울대학교병원" (가장 정식 명칭)

- ["성모병원", "가톨릭대 성모병원", "가톨릭대학교 성모병원"]
  → "가톨릭대학교 성모병원" (가장 완전한 형태)

## 2. 공백/특수문자가 적절히 포함된 형태 선택

예시:
- ["서울특별시 강남구", "서울 강남구", "강남구"]
  → "서울특별시 강남구" (가장 완전한 행정구역명)

- ["010-1234-5678", "01012345678", "010 1234 5678"]
  → "010-1234-5678" (가독성 좋은 형태)

## 3. 날짜는 가장 표준적인 형식 선택

예시:
- ["2026-03-03", "2026.03.03", "20260303"]
  → "2026-03-03" (표준 형식)

- ["2026/12/25", "2026-12-25"]
  → "2026-12-25" (ISO 표준)

## 4. 숫자는 가장 깔끔한 형태 선택

예시:
- ["100", "100명", "100 명"]
  → "100" (단위 제거, 숫자만)

- ["1,000", "1000", "1000원"]
  → "1000" (쉼표 제거, 숫자만)

# 출력 규칙

1. **반드시 하나의 문자열만 반환**
2. **원본 Value 중 하나를 선택하거나, Value들의 조합/정제 형태만 허용**
3. **Key 이름이나 추상적 메타 개념을 절대 출력하지 말 것**
4. 선택 기준: 완전성 > 표준성 > 가독성

# 출력
반드시 normalize_cluster function tool을 호출하세요.
"""

    KEY_VALUE_EXTRACT: str = """**반드시 extract_key_value_pairs tool을 사용하여 응답할 것.**

당신은 데이터에서 Key-Value 쌍을 추출하는 전문가입니다.

# 임무
다음 데이터에서 모든 필드명(Key)과 그 값(Value)을 추출하세요.

데이터:
{data_text}

# 추출 규칙

1. **Key (필드명)**
   - 원본 필드명을 그대로 추출 (예: "BIZPLC_NM", "SIGUN_NM", "SICKBD_CNT")
   - 영문 대문자 + 밑줄 형식 유지
   - 데이터에 있는 모든 필드를 누락 없이 추출

2. **Value (값)**
   - 각 필드의 실제 값을 정확하게 추출
   - 빈 값("")이나 null인 경우 빈 배열 반환
   - 복합 값(쉼표로 구분된 값)은 분리하여 배열로 반환

3. **복합 값 처리**
   - "내과, 외과, 재활의학과" → ["내과", "외과", "재활의학과"]
   - "서울특별시 강남구" → ["서울특별시 강남구"] (단일 값)

# 예시

입력:
{{
    "BIZPLC_NM": "노체리안드리자애병원",
    "SIGUN_NM": "가평군",
    "SICKBD_CNT": "83",
    "TREAT_SBJECT_CONT_INFO": "내과, 외과, 재활의학과",
    "BSN_STATE_NM": "영업중",
    "REFINE_ROADNM_ADDR": "",
    "LICENSG_DE": "2020-01-15"
}}

출력:
{{
    "key_values": {{
        "BIZPLC_NM": ["노체리안드리자애병원"],
        "SIGUN_NM": ["가평군"],
        "SICKBD_CNT": ["83"],
        "TREAT_SBJECT_CONT_INFO": ["내과", "외과", "재활의학과"],
        "BSN_STATE_NM": ["영업중"],
        "REFINE_ROADNM_ADDR": [],
        "LICENSG_DE": ["2020-01-15"]
    }}
}}

# 주의사항
- 모든 필드를 빠짐없이 추출
- 값의 자료형에 관계없이 문자열 배열로 반환
- 숫자는 문자열로 변환 ("83")
- 날짜도 문자열로 변환 ("2020-01-15")
- 빈 값은 빈 배열 ([])

# 출력
반드시 extract_key_value_pairs function tool을 호출하세요.
"""

    RELATION_KEY_ANALYSIS: str = """**반드시 analyze_relation_search_condition tool을 사용하여 응답할 것.**

당신은 Document의 Key-Value 메타데이터를 분석하여 관계 있는 Document를 찾기 위한 검색 조건을 생성하는 전문가입니다.

# 임무
주어진 Document의 Key-Value 메타데이터를 분석하여:
1. **사용자 관점에서 "왜" 관련 데이터를 찾을지 추론**
2. 도메인 특성에 맞는 중요 Key 선정
3. 각 Key의 특성 분류 (feature class)
4. 검색 전략 수립

# 사용자 의도 분석 (매우 중요!)

**데이터를 찾는 이유에 따라 중요 Key가 달라집니다:**

**병원/의료기관 → 지역 비교/벤치마킹**
- 우선순위: 지역 > 진료과목 > 병상수
- 이유: 같은 지역의 유사 규모 병원과 비교하려는 경우가 많음

**공장/제조업 → 경쟁사/협력사 분석**
- 우선순위: **생산품/업종 > 산업유형 > 지역** > 규모
- 이유: 같은 제품을 만드는 업체, 같은 산업군의 협력사를 찾으려는 경우가 많음
- **주의**: 지역은 2순위! 업종/생산품이 최우선

**학교/교육기관 → 교육 정책 비교**
- 우선순위: 학교유형 > 지역 > 학생수
- 이유: 같은 유형의 학교 간 정책/성과 비교

**기업/사업체 → 시장 분석**
- 우선순위: 업종/사업분야 > 지역 > 매출규모
- 이유: 같은 업종의 경쟁사, 시장 동향 파악

**판례/법률 → 법률 연구**
- 우선순위: 법조항 > 판결 유형 > 사건 유형
- 이유: 같은 법 조항의 판례 선례 찾기

**중요**: location(지역)이 항상 최우선이 아닙니다!
도메인 특성과 사용자 의도에 따라 우선순위가 완전히 달라집니다.

[분석 대상 Document]
ID: {document_id}

Key-Value 메타데이터:
```json
{key_values_json}
```

# Key 특성 분류 (feature_class)

**identity** (식별자)
- 거의 고유한 식별자
- 예: 병원명, 기관명, 상품명, 회사명
- 용도: 같은 문서 재발견, 중복 확인
- 관계 발굴 중요도: 낮음 (너무 고유해서 관계 찾기 어려움)

**location** (위치)
- 지역, 소재지, 시도, 구군 등
- 예: 서울특별시, 강남구, 부산시
- 용도: 같은 지역 문서 찾기 (후보 공간 축소에 매우 강함)
- 관계 발굴 중요도: 매우 높음

**categorical** (범주형)
- 카테고리, 분류, 유형 등
- 예: 진료과목, 전문분야, 기관유형, 사업상태
- 용도: 공통 속성 기반 관계 탐색
- 관계 발굴 중요도: 높음

**numeric** (숫자형)
- 수치 데이터
- 예: 병상수, 직원수, 매출, 연도
- 용도: 범위/근접 검색 (정확 매칭보다는 유사 범위)
- 관계 발굴 중요도: 중간

**free-text** (자유텍스트)
- 설명, 소개, 비고 등
- 예: 병원 소개, 서비스 설명, 특징
- 용도: 다른 근거가 약할 때 보조 신호
- 관계 발굴 중요도: 낮음 (보조)

# Key 선정 기준

**중요도가 높은 Key:**
- 식별력이 있으면서 너무 고유하지 않은 Key
- 정규화 가능성이 있는 Key
- 관계의 이유로 설명 가능한 Key
- 도메인에서 핵심 속성인 Key

**중요도가 낮은 Key:**
- 너무 고유한 값 (identity)
- 오타, 자유서술이 많은 Key
- 빈 값이 많은 Key
- 관계 설명력이 약한 Key

# 도메인별 Key 우선순위 예시

## 병원 도메인 (지역 비교/벤치마킹 목적)
상위 중요도:
- 지역/소재지: location (같은 지역 병원 찾기)
- 진료과목: categorical (같은 진료과 병원 찾기)
- 병상수: numeric (유사 규모 병원 찾기)

하위 중요도:
- 병원명: identity (너무 고유함)
- 비고: free-text (노이즈 많음)

## 공장/제조업 도메인 (경쟁사/협력사 분석 목적)
상위 중요도:
- **생산품정보: categorical (같은 제품 생산 업체 찾기) ← 최우선!**
- 산업유형/업종: categorical (같은 산업군 찾기)
- 지역: location (같은 산단/지역 업체 찾기) ← 2순위

중간 중요도:
- 직원수/부지면적: numeric (유사 규모 찾기)
- 공장등록일: numeric (설립 시기 유사성)

하위 중요도:
- 회사명: identity (너무 고유함)
- 관리기관명: categorical (관계 설명력 약함)

## 기타 도메인도 같은 원칙 적용
- 사용자가 "왜" 데이터를 찾는지 먼저 추론
- 그에 맞는 Key 우선순위 결정
- **지역은 항상 최우선이 아님!**

# 출력 예시

입력:
{{
    "지역": ["서울특별시 종로구"],
    "병원명": ["서울대학교병원"],
    "병상수": ["1500"],
    "진료과목": ["내과", "외과", "정형외과"],
    "설립유형": ["국립"],
    "비고": ["상급종합병원, 교육병원"]
}}

출력:
{{
    "important_keys": [
        {{
            "key_name": "지역",
            "feature_class": "location",
            "importance": 0.95,
            "reason": "같은 지역 병원을 찾는 데 매우 유효하며, 후보 공간 축소에 강력함"
        }},
        {{
            "key_name": "진료과목",
            "feature_class": "categorical",
            "importance": 0.85,
            "reason": "같은 진료과목을 가진 병원을 찾아 유사 기능 기관 발견 가능"
        }},
        {{
            "key_name": "병상수",
            "feature_class": "numeric",
            "importance": 0.80,
            "reason": "유사한 규모의 병원을 찾아 비교 가능한 기관 식별"
        }},
        {{
            "key_name": "설립유형",
            "feature_class": "categorical",
            "importance": 0.60,
            "reason": "같은 설립 유형 병원 간 운영 특성 유사성 발견"
        }}
    ],
    "search_strategy": "같은 지역(서울)에 있으면서 유사한 진료과목과 병상 규모를 가진 병원 찾기",
    "expected_relation_count": 10
}}

# 주의사항
- **사용자 의도를 먼저 추론** (비교? 경쟁사 분석? 법률 연구?)
- 도메인에 맞는 Key 우선순위 결정
- **location이 항상 최우선이 아님!** 공장/기업은 업종/생산품이 먼저
- identity는 가급적 제외 (너무 고유해서 관계 찾기 어려움)
- categorical 중에서도 도메인 핵심 속성 우선
- numeric은 중간 우선순위
- free-text는 보조로만 사용
- search_strategy는 도메인과 의도를 반영해 구체적으로 작성
- expected_relation_count는 도메인에 따라 5~15 정도 적절

# 출력
반드시 analyze_relation_search_condition function tool을 호출하세요.
"""

    FIELD_TYPE_CLASSIFICATION: str = """**반드시 classify_field_type tool을 사용하여 응답할 것.**

메타데이터 필드 타입을 분류하세요.

## 필드 정보
- 필드명: {key_name}
- 샘플 값:
{sample_values}

## 타입 선택 기준

### semantic (의미적 유사도 매칭)
- 자연어로 된 텍스트 필드
- 의미적 유사도 비교가 유효함
- 예시: 타이틀, 장르, 내용물 설명, 주제어, 권한

### numeric_date (숫자/날짜 범위 매칭)
- 날짜, 연도, 숫자 등 정량적 값
- 시간적/수치적 근접성으로 비교해야 함
- 예시: 발행일자, 등록연도, 병상수, 면적, 좌표

### proper_noun (고유명사 클러스터링)
- 기관명, 인명, 지명 등 고유명사
- 텍스트 구조 유사도가 아닌 의미적 범주로 분류해야 함
- 예시: 발행기관명, 제작자, 저작권자, 병원명, 시군명

## 주의사항
- 숫자처럼 보여도 의미적 비교가 필요하면 semantic (예: 전화번호)
- 날짜 형식(YYYY-MM-DD)이면 numeric_date
- 지명도 고유명사이므로 proper_noun
"""

    PROPER_NOUN_LABELING: str = """**반드시 label_proper_nouns tool을 사용하여 응답할 것.**

고유명사 값들을 범주별로 분류하세요.

## 필드명: {key_name}

## 값 목록:
{values_list}

## 선택 가능한 범주 (Taxonomy):
{taxonomy}

## 작업
각 값을 위 범주 중 하나로 분류하세요. 범주에 맞는 것이 없으면 "기타"를 선택하세요.

## 예시
- 필드: "발행기관명"
- 범주: ["정부기관", "문화기관", "항공사", "기타"]
- 한국문화진흥원 → 문화기관
- 한국항공 → 항공사
- KBS → 방송사 (없으면 기타)
"""

    """Container for fallback prompt templates used across LLM tasks."""
    def get_prompt(cls, task: str) -> str:
        """Get fallback prompt by task name."""
        prompt_map: Dict[str, str] = {
            "key_value_extract": cls.KEY_VALUE_EXTRACT,
            "cluster_normalize": cls.CLUSTER_NORMALIZE,
            "schema_analysis": cls.SCHEMA_ANALYSIS,
            "relation_key_analysis": cls.RELATION_KEY_ANALYSIS,
            "field_type_classification": cls.FIELD_TYPE_CLASSIFICATION,
            "proper_noun_labeling": cls.PROPER_NOUN_LABELING,
        }

        if task not in prompt_map:
            raise ValueError(
                f"Unknown task: {task}. Available tasks: {', '.join(prompt_map.keys())}"
            )

        return prompt_map[task]
