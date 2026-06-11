"""잡코리아 기업 채용페이지 우회 어댑터.

봇차단(넥슨)·자체 SPA(엔씨·넷마블)·외부 ATS(컴투스·웹젠 JOBDA, 위메이드 NineHire,
데브시스터즈 Teamtailor)로 자체페이지 직접수집이 어려운 회사들을, 잡코리아의
기업 채용페이지(`company/{id}/recruit`, 정적 HTML)로 우회 수집한다.

사용자 결정(2026-06-01): 이들 그룹은 잡코리아 우회로 통일. 공고 링크는 잡코리아
GI_Read 경유가 된다(자체 직링이 아님).
"""
import re

from bs4 import BeautifulSoup

from src.scraper.ats.base import BaseATSAdapter

# 제목 뒤 메타(경력/마감일/상시채용 등) 시작 지점 — 표시용 제목만 분리.
# '계약직/정규직/지역'은 제목에 괄호로 붙는 경우가 많아 컷 키워드에서 제외한다.
_META_CUT = re.compile(r"\s+(?:new|경력무관|신입|경력|D-?\d+|상시채용|수시채용|채용시)\b")


class JobKoreaCompanyAdapter(BaseATSAdapter):
    """잡코리아 기업 채용페이지에서 특정 회사 공고를 우회 수집한다.

    company_id: 잡코리아 기업 고유번호 (company/{id}/recruit)
    fetch_detail: True면 통과 공고의 상세 본문까지 받아 분류 정확도를 높인다.
    """

    def __init__(self, company_id, company_name, source, session=None, fetch_detail=True):
        super().__init__(source, company_name, session)
        self.company_id = company_id
        self.fetch_detail = fetch_detail

    def fetch(self):
        results = []
        url = f"https://www.jobkorea.co.kr/company/{self.company_id}/recruit"
        res = self.session.get(url, timeout=15)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        seen = set()
        for a in soup.select("a[href*='/Recruit/GI_Read/']"):
            href = a.get("href", "")
            m = re.search(r"/Recruit/GI_Read/(\d+)", href)
            if not m:
                continue
            gno = m.group(1)
            if gno in seen:
                continue
            seen.add(gno)

            raw_text = a.get_text(" ", strip=True)
            # 잡코리아 목록 텍스트는 '제목 + 직무분류 꼬리표(예: 회계담당자)' 형태라
            # 전체 텍스트로 재무 판별한다(직무분류 신호 활용). 목록 텍스트는 한글 위주라
            # base의 본문 매칭 오탐('ir'∈hiring·'감사합니다')이 발생하지 않는다.
            if not self.is_finance_job(raw_text):
                continue

            title = _META_CUT.split(raw_text, maxsplit=1)[0].strip() or raw_text[:60]
            origin = f"https://www.jobkorea.co.kr/Recruit/GI_Read/{gno}"
            body = self._fetch_detail_body(gno) if self.fetch_detail else ""
            results.append(
                self.build_posting(f"{self.source}_{gno}", title, origin, body or title, None, None)
            )
        return results

    def _fetch_detail_body(self, gno):
        """상세 페이지 본문 텍스트 (분류 정확도용). 실패 시 빈 문자열."""
        try:
            url = f"https://www.jobkorea.co.kr/Recruit/GI_Read/{gno}"
            r = self.session.get(url, timeout=10)
            if r.status_code != 200:
                return ""
            soup = BeautifulSoup(r.text, "html.parser")
            main = (soup.select_one(".recruit-detail-con") or soup.select_one("#container")
                    or soup.select_one("#content") or soup.select_one("body"))
            return main.get_text("\n").strip() if main else ""
        except Exception:
            return ""
