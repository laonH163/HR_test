"""교차 소스 중복 공고 판별 유틸.

같은 공고가 공식 기업페이지 어댑터(com2us 등)와 플랫폼 검색(잡코리아·게임잡·사람인·원티드)
양쪽에서 수집되면 URL·id가 완전히 달라 GI번호 병합(dedupe_jobkorea_gi)으로는 못 잡는다.
여기의 내용 기반 키(정규화 회사명 + 정규화 제목)로 표시 계층(텔레그램·대시보드)이 병합한다.

주의: 대시보드 템플릿(templates/dashboard_template.html)의 processRawJobsData()에
동일 로직이 JS로 미러링되어 있다. 여기를 바꾸면 템플릿도 함께 맞출 것.
"""
import re
from datetime import datetime

# 재공고(🔁) 인정 최소 공백(일) — 마감 후 이 기간 이상 지나 재등장해야 배지를 붙인다.
# 하루 이틀 내 재등장(수집 플랩·잡코리아 gno 갱신·플랫폼 이동)은 '장기 미충원' 신호가
# 아니므로 제외. 같은 실행 안에서 구공고 마감+신공고 등장이 동시에 잡히는 경우도
# 보수적으로 미표시된다(의도된 트레이드오프 — 배지는 고신뢰 신호만).
MIN_REPOST_GAP_DAYS = 2

# 플랫폼 검색 소스 — 이 외의 소스(기업페이지 어댑터·자체 채용페이지)는 모두 '공식'으로 간주
PLATFORM_SOURCES = {"wanted", "saramin", "jobkorea", "gamejob"}

_CORP_TOKENS = ["(주)", "주식회사", "㈜", "（주）"]
_BRACKET_PREFIX_RE = re.compile(r"^\[([^\[\]]{1,30})\]\s*")


def normalize_company(name):
    """회사명 정규화 — 공백·법인 표기 제거 + 소문자화 (중복 판별 키용)"""
    norm = "".join((name or "").split()).lower()
    for token in _CORP_TOKENS:
        norm = norm.replace(token, "")
    return norm


def source_rank(source):
    """대표 카드 우선순위 — 공식(기업 어댑터·자체 채용페이지)=0, 플랫폼 검색=1"""
    return 1 if (source or "").lower() in PLATFORM_SOURCES else 0


def compute_repost_flags(active_postings, closed_history):
    """재공고(🔁) 판별 — {content_key: 마지막 마감 관측일 'YYYY-MM-DD'} 반환.

    규칙: 현재 활성 그룹(같은 content_key의 활성 공고들)의 **최초 관측 시각**이
    같은 키의 **마지막 CLOSED 관측 시각**보다 뒤일 때만 재공고로 본다.
    → 한쪽 소스 행만 닫혔는데 다른 소스 행이 계속 활성이던 이력(플랩·좀비 CLOSED)은
      그룹 최초 관측이 마감 이전이므로 자연히 걸러진다.
    벤치마킹 근거: hiring.cafe 운영기 — 재게시(repost)는 장기 미충원/유령공고의 최강 신호.

    입력은 dict 리스트여야 한다(sqlite3.Row는 .get이 없음 — 호출부에서 dict 변환).
    ※ 결과 플래그는 데이터로 주입되므로 대시보드 JS에 로직 미러링이 필요 없다.
    """
    latest_closed = {}
    for row in closed_history or []:
        key = content_key(row.get("company_name"), row.get("title"))
        closed_at = row.get("closed_at") or ""
        if closed_at and closed_at > latest_closed.get(key, ""):
            latest_closed[key] = closed_at

    group_first_seen = {}
    for job in active_postings or []:
        key = content_key(job.get("company_name"), job.get("title"))
        first_seen = job.get("first_seen_at") or ""
        if first_seen and (key not in group_first_seen or first_seen < group_first_seen[key]):
            group_first_seen[key] = first_seen

    flags = {}
    for key, first_seen in group_first_seen.items():
        closed_at = latest_closed.get(key)
        if not closed_at or closed_at >= first_seen:
            continue
        try:
            gap_days = (datetime.strptime(first_seen[:10], "%Y-%m-%d")
                        - datetime.strptime(closed_at[:10], "%Y-%m-%d")).days
        except ValueError:
            continue
        if gap_days >= MIN_REPOST_GAP_DAYS:
            flags[key] = closed_at[:10]
    return flags


def content_key(company_name, title):
    """소스가 달라도 같은 공고면 일치하는 (회사키, 제목키) 생성.

    제목 맨 앞 '[회사명류]' 프리픽스가 회사명과 포함관계일 때만(컴투스 ⊂ 컴투스홀딩스)
    더 긴 쪽을 회사키로 승격하고 제목키에서 프리픽스를 제거한다.
    — 실측(2026-07-08): 컴투스 기업페이지(회사명 '컴투스', 제목 '[컴투스홀딩스] 재무관리 팀장')와
      게임잡(회사명 '컴투스 홀딩스', 프리픽스 없는 제목)이 같은 공고인데 키가 어긋나 이중 표시됨.
    포함관계가 아닌 '[경력]' '[신입]' 같은 프리픽스는 그대로 두어 오병합을 막는다."""
    comp = normalize_company(company_name)
    title = (title or "").strip()
    m = _BRACKET_PREFIX_RE.match(title)
    if m:
        hint = normalize_company(m.group(1))
        if len(hint) >= 2 and comp and (comp in hint or hint in comp):
            stripped = title[m.end():].strip()
            if stripped:
                title = stripped
            if len(hint) > len(comp):
                comp = hint
    return comp, "".join(title.split()).lower()
