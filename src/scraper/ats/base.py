"""ATS(채용 시스템)별 수집 어댑터의 공통 베이스.

게임사마다 채용 시스템이 제각각이다(Greenhouse / Lever / greetinghr / JOBDA / 자체 SPA).
각 ATS 어댑터는 BaseATSAdapter를 상속해 fetch()만 구현하면 되고,
직무(재무) 필터·posting 표준화·세션 생성은 공통으로 제공한다.

게임사 '자체 채용 페이지'를 직접 수집하는 용도라 회사 필터(게임사 여부)는 불필요하고,
재무/회계/세무/자금 '직무' 필터만 적용한다.
"""
import sys

from src.scraper.filters import is_finance_job as _is_finance_job
from src.utils.http import make_session
from src.utils.timeutil import now_kst_str, today_kst_str

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
        self.is_last_run_success = False

    def is_finance_job(self, title, body=""):
        """제목 기준으로 재무/회계/세무/자금 직군인지 판별 (공통 필터 위임).

        body 인자는 호환을 위해 남기지만 의도적으로 사용하지 않는다 — 본문 매칭은
        영어 부분문자열('ir'∈hiring)·한국어 인사말('감사합니다') 오탐이 심하다.
        게임사 자체페이지 제목은 직무가 명확하므로 제목만으로 충분히 정확하다.
        """
        return _is_finance_job(title)

    def build_posting(self, job_id, title, origin_url, raw_html, posted_at=None, location=None):
        """기존 파이프라인(db_manager.upsert_job_posting)이 기대하는 표준 dict 생성."""
        now = now_kst_str()
        return {
            "id": job_id,
            "source": self.source,
            "company_name": self.company_name,
            "title": title,
            "origin_url": origin_url,
            "location": location or "",
            "posted_at": (posted_at or today_kst_str()),
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
            jobs = self.fetch()
            self.is_last_run_success = True
            return jobs
        except Exception as e:
            self.is_last_run_success = False
            print(f"    [ERR] {self.company_name}({self.source}) 수집 실패: {e}", file=sys.stderr)
            return []
