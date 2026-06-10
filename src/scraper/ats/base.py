"""ATS(채용 시스템)별 수집 어댑터의 공통 베이스.

게임사마다 채용 시스템이 제각각이다(Greenhouse / Lever / greetinghr / JOBDA / 자체 SPA).
각 ATS 어댑터는 BaseATSAdapter를 상속해 fetch()만 구현하면 되고,
직무(재무) 필터·posting 표준화·세션 생성은 공통으로 제공한다.

게임사 '자체 채용 페이지'를 직접 수집하는 용도라 회사 필터(게임사 여부)는 불필요하고,
재무/회계/세무/자금 '직무' 필터만 적용한다.
"""
import re
import sys
from datetime import datetime

from src.utils.http import make_session

# 재무/회계/세무/자금 직군 판별 키워드.
# 제목(title) 기준으로만 매칭한다 — 본문은 영어 부분문자열('ir'∈hiring/their)과
# 한국어 인사말('감사합니다')이 대량 오탐을 유발하기 때문(라이브에서 53/53건 전부 오탐 확인).
FINANCE_KEYWORDS_KO = [
    "재무", "회계", "세무", "자금", "경리", "결산", "내부회계", "내부통제",
    "재무기획", "자금운용", "원가", "회계사", "세무사"
]
# '감사'는 '고객감사 이벤트'·'감사패' 등 비재무 오탐이 많아 단독 키워드에서 제외하고,
# 재무·회계 맥락 복합어로만 인정한다(아래 is_finance_job의 정규식).
_AUDIT_PATTERN = r"(내부\s?감사|회계\s?감사|상근\s?감사|외부\s?감사|감사\s?담당|감사팀|감사실|감사역|감사\s?업무)"
FINANCE_KEYWORDS_EN = [
    "finance", "financial", "accounting", "accountant", "tax",
    "treasury", "payroll", "fp&a",
]

# 비재무/비사무 직무 제외 (혹시 모를 오탐 방지 — 게임사 자체페이지엔 드물지만 일관성 위해 유지)
# 비재무/비사무 직무 제외 (혹시 모를 오탐 방지 — 게임사 자체페이지엔 드물지만 일관성 위해 유지)
# '채용' 키워드는 '재무 담당자 채용'처럼 제목 끝에 유효하게 쓰이므로 블랙리스트에서 제외하여
# '하이브IM 세무조정 담당자 채용' 같은 공고가 안전하게 통과할 수 있도록 합니다.
TITLE_BLACKLIST = [
    "딜러", "dealer", "식음료", "f&b", "객실", "서빙", "바텐더", "벨맨", "캐셔", "카운터", "알바", "아르바이트",
    "legal", "counsel", "compliance", "인사", "recru", "변호사", "준법", "공정거래",
    "보상", "급여", "pmo", "비서", "총무"
]

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}


class BaseATSAdapter:
    """모든 ATS 어댑터의 공통 부모.

    source: DB의 job_postings.source 값이자 job id 접두사 (예: 'krafton', 'neowiz')
    company_name: 표시용 회사명 (예: '크래프톤')
    """

    def __init__(self, source, company_name, session=None):
        self.source = source
        self.company_name = company_name
        self.session = session or make_session(headers=DEFAULT_HEADERS)

    def is_finance_job(self, title, body=""):
        """제목 기준으로 재무/회계/세무/자금 직군인지 판별.

        body 인자는 호환을 위해 남기지만 의도적으로 사용하지 않는다 — 본문 매칭은
        영어 부분문자열('ir'∈hiring)·한국어 인사말('감사합니다') 오탐이 심하다.
        게임사 자체페이지 제목은 직무가 명확하므로 제목만으로 충분히 정확하다.
        """
        if not title:
            return False
        title_lower = title.lower()
        for blocked in TITLE_BLACKLIST:
            if blocked in title_lower:
                return False
        if any(kw in title for kw in FINANCE_KEYWORDS_KO):
            return True
        if any(kw in title_lower for kw in FINANCE_KEYWORDS_EN):
            return True
        # 감사: 재무·회계 맥락 복합어만 인정('고객감사 이벤트'·'감사패' 등 오탐 배제)
        if re.search(_AUDIT_PATTERN, title):
            return True
        # IR(투자자관계/공시): 약어라 단어 경계로만 매칭해 hiring 등 오탐 방지
        if re.search(r"\bir\b", title_lower):
            return True
        # 재무공시/회계공시 등 구체적인 재무 맥락 공시만 매칭 (단독 '공시' 제거 대응)
        if re.search(r"(재무\s?공시|회계\s?공시|기업\s?공시)", title):
            return True
        return False

    def build_posting(self, job_id, title, origin_url, raw_html, posted_at=None, location=None):
        """기존 파이프라인(db_manager.upsert_job_posting)이 기대하는 표준 dict 생성."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return {
            "id": job_id,
            "source": self.source,
            "company_name": self.company_name,
            "title": title,
            "origin_url": origin_url,
            "location": location or "",
            "posted_at": (posted_at or datetime.today().strftime("%Y-%m-%d")),
            "status": "ACTIVE",
            "raw_html": raw_html if raw_html else title,
            "first_seen_at": now,
            "last_updated_at": now,
        }

    def fetch(self):
        """각 ATS 어댑터가 구현. 재무 직군 posting dict 리스트를 반환한다."""
        raise NotImplementedError

    def safe_fetch(self):
        """예외를 삼키고 stderr에 로깅 — 한 회사 실패가 전체 파이프라인을 멈추지 않게."""
        try:
            return self.fetch()
        except Exception as e:
            print(f"    [ERR] {self.company_name}({self.source}) 수집 실패: {e}", file=sys.stderr)
            return []
