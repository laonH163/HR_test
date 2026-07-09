"""재무 직무·게임사 판별 공통 필터 (단일 소스 오브 트루스).

기존에는 동일한 키워드 사전과 판별 함수가 wanted/saramin/jobkorea 스크래퍼와
ats/base.py에 4벌로 복붙되어 있어, 규칙 하나를 고치려면 4곳을 동시에 수정해야 했고
실제로 '채용' 블랙리스트가 base.py에서만 제거되어 소스마다 판정이 달랐다.
모든 스크래퍼는 이 모듈의 함수를 사용한다.

[통합 시 결정 사항]
- '채용' 단독 블랙리스트 제거 — '세무조정 담당자 채용' 같은 정상 재무 공고를 죽이는
  오탐이 라이브로 확인됨(base.py의 검증된 방침을 전체로 확대). HR 리크루터 직무는
  '채용담당' 복합어로 차단한다.
- '안내' 단독 블랙리스트 제거 — '재무팀 채용 안내' 오탐 방지. 호텔/카지노 프런트
  직무는 '안내데스크' 복합어 + 재무 키워드 부재로 걸러진다.
- 게임잡 전용이던 'ERP'는 소문자 비교 버그로 실제로는 한 번도 매칭된 적이 없어
  승계하지 않는다(ERP 개발자 오탐 위험도 있음).
"""
import re

# 대한민국 게임 회사, 계열사, 지주사 및 글로벌 게임 도메인 명칭 마스터 사전
GAME_KEYWORDS = [
    "게임", "game", "nexon", "krafton", "ncsoft", "netmarble", "neowiz", "smilegate",
    "펄어비스", "위메이드", "카카오게임즈", "그라비티", "넥슨", "크래프톤", "엔씨소프트",
    "넷마블", "네오위즈", "스마일게이트", "데브시스터즈", "컴투스", "웹젠", "조이시티",
    "한빛소프트", "썸에이지", "해긴", "쿡앱스", "클로버게임즈", "시프트업", "라인게임즈",
    "더블유게임즈", "레드브릭", "엔씨", "com2us", "wemade", "gravity", "kakaogames",
    "pearlabyss", "webzen", "shiftup", "linegames", "joycity", "액션스퀘어",
    "위메이드맥스", "위메이드플레이", "컴투스홀딩스", "컴투스플랫폼", "NHN", "nhn",
    "엔에이치엔", "네오플", "아이덴티티", "그라비티네오싸이언", "웹젠레드코어", "웹젠블루포트",
    "하이브im", "hybeim", "빅게임스튜디오", "vicgamestudios", "vic game"
]
# 매칭은 소문자 기준으로 수행 (영문 대소문자 표기 차이 흡수)
_GAME_KEYWORDS_LOWER = [kw.lower() for kw in GAME_KEYWORDS]

# 순수 카지노, 리조트, 오락실 등 게임 개발/IT 도메인이 아닌 기업 블랙리스트
COMPANY_BLACKLIST = [
    "람정", "신화월드", "카지노", "casino", "호텔", "hotel", "리조트", "resort",
    "홀덤", "보드게임카페", "보드카페", "멀티방", "오락실"
]

# 비재무/비사무 직무 제목 블랙리스트 (제목에 하나라도 있으면 재무 직무 아님)
TITLE_BLACKLIST = [
    "딜러", "dealer", "식음료", "f&b", "객실", "서빙", "바텐더", "벨맨",
    "캐셔", "카운터", "알바", "아르바이트", "안내데스크", "안내 데스크",
    "legal", "counsel", "compliance", "인사", "recru", "채용담당", "채용 담당",
    "변호사", "준법", "공정거래", "보상", "급여", "pmo", "비서", "총무",
    # 재무 부서 소속 개발직 배제 — '[재무관리본부] 정산 시스템 개발 담당자'(넥슨)처럼
    # 부서명의 '재무'로 통과하는 개발 직함(2026-07-09 실측, DB 83개 제목 표본에서
    # 해당 1건만 제외됨을 확인). 단독 '개발'은 과격해 넣지 않고, 'IT 담당자'류
    # (내부회계 시스템 IT 등 회계 유관직)는 의도적으로 보존한다.
    "개발자", "개발 담당", "개발담당", "시스템 개발", "프로그래머", "엔지니어",
    "developer", "programmer", "engineer"
]

# 비사무 직종 키워드 (본문/컨텍스트 텍스트 검사용 — 카지노 딜러·서빙 등)
NON_OFFICE_BLACKLIST = [
    "딜러", "dealer", "식음료", "f&b", "객실", "서빙", "바텐더", "벨맨",
    "캐셔", "카운터", "알바", "아르바이트"
]

# 재무/회계/세무/자금 직군 판별 키워드
FINANCE_KEYWORDS_KO = [
    "재무", "회계", "세무", "자금", "경리", "결산", "내부회계", "내부통제",
    "재무기획", "자금운용", "원가", "회계사", "세무사"
]
FINANCE_KEYWORDS_EN = [
    "finance", "financial", "accounting", "accountant", "tax",
    "treasury", "payroll", "fp&a"
]

# '감사'는 '고객감사 이벤트'·'감사패' 등 비재무 오탐이 많아 단독 키워드에서 제외하고,
# 재무·회계 맥락 복합어로만 인정한다.
AUDIT_PATTERN = r"(내부\s?감사|회계\s?감사|상근\s?감사|외부\s?감사|감사\s?담당|감사팀|감사실|감사역|감사\s?업무)"


def is_finance_job(title):
    """제목 기준으로 재무/회계/세무/자금 직군인지 판별.

    제목만 사용한다 — 본문 매칭은 영어 부분문자열('ir'∈hiring)·한국어 인사말
    ('감사합니다') 오탐이 심하다(라이브에서 53/53건 전부 오탐 확인).
    """
    if not title:
        return False
    title_lower = title.lower()

    # 비재무/비사무 직무 제외
    for blocked in TITLE_BLACKLIST:
        if blocked in title_lower:
            return False

    if any(kw in title for kw in FINANCE_KEYWORDS_KO):
        return True
    if any(kw in title_lower for kw in FINANCE_KEYWORDS_EN):
        return True

    # 감사: 재무·회계 맥락 복합어만 인정('고객감사' 등 오탐 배제)
    if re.search(AUDIT_PATTERN, title):
        return True

    # IR(투자자관계/공시): 약어라 단어 경계로만 매칭해 hiring 등 오탐 방지
    if re.search(r"\bir\b", title_lower):
        return True

    # 재무공시/회계공시 등 구체적인 재무 맥락 공시만 매칭 (단독 '공시' 제거 대응)
    if re.search(r"(재무\s?공시|회계\s?공시|기업\s?공시)", title):
        return True

    return False


def is_game_company(company_name, context_text=""):
    """회사명(또는 제목/본문 컨텍스트)에 게임 도메인 키워드가 있는지 필터링.

    context_text에는 공고 제목이나 본문 요약을 넘긴다. 카지노/리조트 등
    비개발 오락업종과 비사무 직종 컨텍스트는 원천 차단한다.
    """
    norm_name = (company_name or "").lower()
    norm_ctx = (context_text or "").lower()

    # 1. 회사/업종 블랙리스트 검사 (회사명 + 컨텍스트)
    for blocked in COMPANY_BLACKLIST:
        if blocked in norm_name or blocked in norm_ctx:
            return False

    # 2. 비사무 직종 컨텍스트 검사 (딜러·서빙 등)
    for blocked in NON_OFFICE_BLACKLIST:
        if blocked in norm_ctx:
            return False

    # 3. 회사명 또는 컨텍스트에 게임 도메인 키워드 매칭
    for kw in _GAME_KEYWORDS_LOWER:
        if kw in norm_name or kw in norm_ctx:
            return True

    return False
