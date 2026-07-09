"""정적 HTML 기반 자체 채용 페이지 어댑터.

JS 렌더링 없이 서버가 완성된 HTML을 주는 자체 채용 사이트용.
requests + BeautifulSoup만으로 안정 수집된다.
"""
import re

from bs4 import BeautifulSoup

from src.scraper.ats.base import BaseATSAdapter

# 제목 뒤에 붙는 메타(등록일·상시채용·D-day) 분리용
_TITLE_CUT = re.compile(r"\s+(?:상시채용|\d{4}-\d{2}-\d{2}|D-\d+)")


class PearlAbyssAdapter(BaseATSAdapter):
    """펄어비스 자체 채용 페이지(정적 HTML).

    목록: https://www.pearlabyss.com/ko-KR/Company/Careers/List
    공고 링크는 `/Company/Careers/detail?_jobOpeningNo={n}` 형태이며, 링크 텍스트에
    제목과 메타(등록일/경력/지역/직군)가 함께 들어 있어 제목만 분리해 사용한다.
    """

    LIST_URL = "https://www.pearlabyss.com/ko-KR/Company/Careers/List"
    BASE = "https://www.pearlabyss.com"

    def __init__(self, company_name="펄어비스", source="pearlabyss", session=None):
        super().__init__(source, company_name, session)

    def fetch(self):
        results = []
        res = self.session.get(self.LIST_URL, timeout=15)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        seen = set()
        for a in soup.select("a[href*='_jobOpeningNo']"):
            href = a.get("href", "")
            m = re.search(r"_jobOpeningNo=(\d+)", href)
            if not m:
                continue
            opening_no = m.group(1)
            if opening_no in seen:
                continue
            seen.add(opening_no)

            raw_text = a.get_text(" ", strip=True)
            title = _TITLE_CUT.split(raw_text, maxsplit=1)[0].strip()
            if not self.is_finance_job(title):
                continue

            job_id = f"{self.source}_{opening_no}"
            url = (self.BASE + href) if href.startswith("/") else href
            body = self._fetch_detail_body(url)
            results.append(self.build_posting(job_id, title, url, body or title, None, "경기 과천"))
        return results

    def _fetch_detail_body(self, url):
        """상세 페이지 JD 본문 (분류 정확도용). 정적 SSR이라 requests로 충분
        (2026-07-09 실측: article 요소에 960자 본문). 실패 시 빈 문자열."""
        try:
            res = self.session.get(url, timeout=15)
            if res.status_code != 200:
                return ""
            soup = BeautifulSoup(res.text, "html.parser")
            main = soup.select_one("article") or soup.select_one("main")
            if not main:
                return ""
            text = main.get_text("\n").strip()
            return text if len(text) > 80 else ""
        except Exception:
            return ""
