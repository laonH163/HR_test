"""잡코리아 기업 채용페이지 우회 어댑터.

봇차단(넥슨)·자체 SPA(엔씨·넷마블)·외부 ATS(컴투스·웹젠 JOBDA, 위메이드 NineHire,
데브시스터즈 Teamtailor)로 자체페이지 직접수집이 어려운 회사들을, 잡코리아의
기업 채용페이지(`company/{id}/recruit`, 정적 HTML)로 우회 수집한다.

사용자 결정(2026-06-01): 이들 그룹은 잡코리아 우회로 통일. 공고 링크는 잡코리아
GI_Read 경유가 된다(자체 직링이 아님).

[2026-06-22 강화] 잡코리아 company_id는 시간이 지나면 폐지/재배정될 수 있어
엉뚱한 회사로 오매핑되는 사고가 있었다(예: '빅게임스튜디오'로 등록된 id가 실제로는
'앱클론(주)' 바이오회사). 이를 막기 위해:
  1) 회사명 교차검증 — 페이지 <title>의 회사명이 등록 회사명(또는 별칭)과 일치할
     때만 공고를 수집한다. 불일치 시 경고 후 0건 반환(오염 차단).
  2) 페이지네이션 — 진행공고가 많은 기업(예: 엔씨 64건)은 1페이지(~30건)만 읽으면
     재무 공고가 뒷페이지에 있을 때 영구 누락된다. ?Page=N 으로 끝까지 순회한다.
"""
import re
from datetime import timedelta

from bs4 import BeautifulSoup

from src.scraper.ats.base import BaseATSAdapter
from src.utils.timeutil import now_kst

# 제목 뒤 메타(경력/마감일/상시채용 등) 시작 지점 — 표시용 제목만 분리.
# '계약직/정규직/지역'은 제목에 괄호로 붙는 경우가 많아 컷 키워드에서 제외한다.
_META_CUT = re.compile(r"\s+(?:new|경력무관|신입|경력|D-?\d+|상시채용|수시채용|채용시)\b")

# 마감(종료) 공고 배지. 잡코리아 기업페이지는 진행중 공고뿐 아니라 과거 마감 공고도
# 함께 나열한다(예: 미투온/위메이드맥스 재무 공고 다수가 '마감 (~과거날짜)'). 마감 공고를
# ACTIVE로 적재하면 영구히 마감 처리되지 않는 좀비 공고가 되므로 수집 단계에서 제외한다.
# 활성 공고는 'D-N' 카운트다운/'상시채용' 배지라 이 패턴과 겹치지 않는다.
# '결산 마감 담당자' 같은 제목 오탐을 피하려고 '마감 (~' 형태(마감일 괄호)만 종료로 본다.
_CLOSED_BADGE = re.compile(r"마감\s*\(~")

# 마감 카운트다운 배지 (예: 'D-8'). 절대 마감일로 환산해 deadline 컬럼에 저장한다.
_DDAY_BADGE = re.compile(r"\bD-(\d+)\b")

# 회사명 정규화(법인표기·공백·괄호 제거 + 소문자) — title 교차검증/별칭 매칭용.
_CORP_TOKENS = ("주식회사", "(주)", "㈜", "（주）", "(유)", "㈜")


def _deadline_from_dday(raw_text, today=None):
    """목록 텍스트의 'D-N' 배지를 절대 마감일('YYYY-MM-DD')로 환산.

    D-N은 매일 1씩 줄지만 환산된 절대 날짜는 동일하므로 DB에 안정적으로 저장된다.
    배지가 없으면(상시채용/채용시 마감) None.
    """
    m = _DDAY_BADGE.search(raw_text or "")
    if not m:
        return None
    days = int(m.group(1))
    base = today or now_kst().date()
    return (base + timedelta(days=days)).strftime("%Y-%m-%d")


def _norm_company(text):
    if not text:
        return ""
    t = text
    for tok in _CORP_TOKENS:
        t = t.replace(tok, "")
    t = re.sub(r"[\s()\[\]·.,\-]", "", t)
    return t.lower()


class JobKoreaCompanyAdapter(BaseATSAdapter):
    """잡코리아 기업 채용페이지에서 특정 회사 공고를 우회 수집한다.

    company_id: 잡코리아 기업 고유번호 (company/{id}/recruit)
    verify_aliases: 페이지 title 회사명이 등록명과 다를 수 있는 정상 케이스의 별칭 목록
        (예: 엔씨소프트 → ["NC"], NHN → ["엔에이치엔"]). 미지정 시 [company_name] 사용.
    fetch_detail: True면 통과 공고의 상세 본문까지 받아 분류 정확도를 높인다.
    max_pages: 페이지네이션 상한(요청 폭주 방지). 기본 5페이지(~150공고)까지 순회.
    """

    def __init__(self, company_id, company_name, source, session=None,
                 fetch_detail=True, verify_aliases=None, max_pages=5):
        super().__init__(source, company_name, session)
        self.company_id = company_id
        self.fetch_detail = fetch_detail
        self.verify_aliases = verify_aliases or [company_name]
        self.max_pages = max_pages

    def _verify_company(self, soup):
        """페이지 <title>의 회사명이 기대 회사명(별칭 포함)과 일치하는지 검증.

        title 예: "(주)넥슨코리아 채용 - 2026년 진행 중인 공고 총 29건 | 잡코리아"
        오매핑(앱클론·에프앤자산평가 등)을 걸러 DB 오염을 원천 차단한다.
        """
        title = soup.title.get_text() if soup.title else ""
        norm_title = _norm_company(title)
        if not norm_title:
            return False
        for alias in self.verify_aliases:
            na = _norm_company(alias)
            if na and na in norm_title:
                return True
        return False

    def fetch(self):
        results = []
        seen = set()
        verified = False

        for page in range(1, self.max_pages + 1):
            url = f"https://www.jobkorea.co.kr/company/{self.company_id}/recruit?Page={page}"
            res = self.session.get(url, timeout=15)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, "html.parser")

            # 1페이지에서 회사명 교차검증 — 실패 시 오매핑으로 보고 전량 폐기(오염 차단).
            if page == 1:
                if not self._verify_company(soup):
                    import sys
                    real = (soup.title.get_text().strip()[:40] if soup.title else "?")
                    print(
                        f"    [WARN] 잡코리아 회사 불일치(오매핑 의심) — 등록='{self.company_name}'(id={self.company_id}) "
                        f"실제페이지='{real}'. 수집 건너뜀.",
                        file=sys.stderr,
                    )
                    return []
                verified = True

            page_gnos = self._extract_page(soup, seen, results)
            # 새 공고가 더 없으면(마지막 페이지 도달) 중단
            if page_gnos == 0:
                break

        return results

    def _extract_page(self, soup, seen, results):
        """한 페이지의 재무 공고를 results에 적재하고, 이 페이지에서 새로 본 공고 수를 반환."""
        new_count = 0
        for a in soup.select("a[href*='/Recruit/GI_Read/']"):
            href = a.get("href", "")
            m = re.search(r"/Recruit/GI_Read/(\d+)", href)
            if not m:
                continue
            gno = m.group(1)
            if gno in seen:
                continue
            seen.add(gno)
            new_count += 1

            raw_text = a.get_text(" ", strip=True)
            # 마감(종료) 공고는 ACTIVE 적재 대상에서 제외 (좀비 공고 방지)
            if _CLOSED_BADGE.search(raw_text):
                continue
            # 잡코리아 목록 텍스트는 '제목 + 직무분류 꼬리표(예: 회계담당자)' 형태라
            # 전체 텍스트로 재무 판별한다(직무분류 신호 활용). 목록 텍스트는 한글 위주라
            # base의 본문 매칭 오탐('ir'∈hiring·'감사합니다')이 발생하지 않는다.
            if not self.is_finance_job(raw_text):
                continue

            title = _META_CUT.split(raw_text, maxsplit=1)[0].strip() or raw_text[:60]
            origin = f"https://www.jobkorea.co.kr/Recruit/GI_Read/{gno}"
            body = self._fetch_detail_body(gno) if self.fetch_detail else ""
            deadline = _deadline_from_dday(raw_text)
            results.append(
                self.build_posting(f"{self.source}_{gno}", title, origin, body or title, None, None,
                                   deadline=deadline)
            )
        return new_count

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
