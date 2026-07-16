"""JD(직무기술) 본문 보유 여부·열화 판정 유틸.

'제목만 수집된 공고'와 '실제 상세요강을 확보한 공고'를 구분하는 단일 기준.
- 수집 파이프라인(jobkorea_detail): 본문 보강이 필요한 공고 선별 + 품질 게이트
- DB upsert(db_manager): 본문 축소 방지 가드 — 이미 확보한 상세요강을
  열화된 수집분(제목만/스니펫만)이 지워버리지 않도록 방어

두 곳이 같은 기준을 써야 보강↔보존이 어긋나지 않으므로 여기로 단일화한다.
"""
import re

# 상세요강 '실본문'에만 나타나는 섹션 헤더.
# ※ '지원자격'·'모집요강'·'근무조건'은 잡코리아 SPA 껍데기의 탭/메타 라벨에도 존재해
#   (2026-07-16 실DB 실측: 검색 수집분 4/4건이 껍데기 라벨만으로 오검출) 마커에서 제외.
JD_MARKERS = ("담당업무", "자격요건", "우대사항", "주요업무")


def has_jd_markers(text):
    """텍스트에 상세요강 실본문 섹션 헤더가 있는지 판별.

    공백을 제거하고 대조한다 — '자격 요건'·'담당 업무'처럼 띄어 쓴 변형도
    hybrid_engine의 섹션 파서와 동일하게 본문으로 인정하기 위함."""
    if not text:
        return False
    normalized = re.sub(r"\s+", "", text)
    return any(marker in normalized for marker in JD_MARKERS)


def body_degraded(existing_raw, incoming_raw):
    """오늘 수집분(incoming)이 기확보 본문(existing) 대비 '열화'인지 판정.

    True면 upsert가 기존 본문을 보존한다. 규칙(2026-07-16 실측 기반):
    - 길이가 같거나 늘었으면 열화 아님 (정상 개정)
    - 마커 소실 + 분량 70% 미만 → 열화 (상세 접근 실패로 제목/요약만 수집된 전형)
    - 마커와 무관한 대붕괴(400자 이상 본문이 1/3 이하로) → 열화
      — 사람인 4,999자·크래프톤 3,500자처럼 마커 없는 정상 본문도 보호
    - 분량이 70% 이상 유지되면 마커가 사라져도 정상 개정으로 허용
      — 영문 JD 전환 등 정당한 재작성이 구본에 영구 고착되는 것 방지
    """
    ex_len = len(existing_raw or "")
    inc_len = len(incoming_raw or "")
    if inc_len >= ex_len:
        return False
    if has_jd_markers(existing_raw) and not has_jd_markers(incoming_raw) and inc_len < ex_len * 0.7:
        return True
    return ex_len >= 400 and inc_len * 3 <= ex_len
