"""무인증 공개 API 기반 ATS 어댑터 (Greenhouse / Lever / greetinghr).

세 ATS 모두 인증 없이 표준 JSON API를 제공하므로 requests만으로 안정적으로
수집된다(봇차단·JS 렌더링 불필요). 같은 ATS를 쓰는 새 게임사는 식별자만 추가하면 된다.

라이브 검증(2026-06-01):
- Greenhouse 크래프톤(board=krafton): 200, 재무직 3건(별도/연결회계 등)
- Lever 네오위즈(site=neowiz): 200, 34건(현재 재무직 0)
- greetinghr 카카오게임즈(workspace=7144): 헤더로 workspace id 해석 가능
"""
import html
from datetime import date

from bs4 import BeautifulSoup

from src.scraper.ats.base import BaseATSAdapter
from src.utils.timeutil import now_kst


def _html_to_text(raw):
    """HTML(엔티티 이스케이프 포함) 본문을 평문으로 변환."""
    if not raw:
        return ""
    return BeautifulSoup(html.unescape(raw), "html.parser").get_text(separator="\n").strip()


class GreenhouseAdapter(BaseATSAdapter):
    """Greenhouse Job Board API. 예: 크래프톤(board_token='krafton').

    `?content=true`로 공고 본문까지 함께 받아 분류 정확도를 확보한다.
    """

    def __init__(self, board_token, company_name, source=None, session=None):
        super().__init__(source or board_token, company_name, session)
        self.board_token = board_token

    def fetch(self):
        results = []
        url = f"https://boards-api.greenhouse.io/v1/boards/{self.board_token}/jobs?content=true"
        res = self.session.get(url, timeout=15)
        res.raise_for_status()
        for job in res.json().get("jobs", []):
            title = job.get("title", "")
            body = _html_to_text(job.get("content", ""))
            if not self.is_finance_job(title, body):
                continue
            job_id = f"{self.source}_{job.get('id')}"
            loc = (job.get("location") or {}).get("name")
            posted = (job.get("updated_at") or job.get("first_published") or "")[:10] or None
            results.append(self.build_posting(job_id, title, job.get("absolute_url"), body, posted, loc))
        return results


class LeverAdapter(BaseATSAdapter):
    """Lever Postings API. 예: 네오위즈(site='neowiz')."""

    def __init__(self, site, company_name, source=None, session=None):
        super().__init__(source or site, company_name, session)
        self.site = site

    def fetch(self):
        results = []
        url = f"https://api.lever.co/v0/postings/{self.site}?mode=json&limit=200"
        res = self.session.get(url, timeout=15)
        res.raise_for_status()
        for job in res.json():
            title = job.get("text", "")
            parts = [job.get("descriptionPlain", "") or ""]
            for lst in job.get("lists", []):
                parts.append(lst.get("text", ""))
                parts.append(_html_to_text(lst.get("content", "")))
            body = "\n".join(p for p in parts if p)
            if not self.is_finance_job(title, body):
                continue
            job_id = f"{self.source}_{job.get('id')}"
            loc = (job.get("categories") or {}).get("location")
            results.append(self.build_posting(job_id, title, job.get("hostedUrl"), body, None, loc))
        return results


class GreetingHRAdapter(BaseATSAdapter):
    """greetinghr(그리팅) ATS. 예: 카카오게임즈(subdomain='kakaogamesrecruit', source='kakaogames').

    공고목록 API가 제목·게시일·마감일(dueDate)을 제공하고, 공고 상세 페이지는
    SSR이라 requests만으로 JD 본문 확보가 가능하다(2026-07-09 실측: Content 블록
    2,600자). 재무 필터를 통과한 공고만 상세를 받아 요청 수를 최소화한다.
    workspace_id를 모르면 채용 도메인 HEAD 응답 헤더/쿠키에서 동적으로 해석한다.
    """

    def __init__(self, subdomain, company_name, source, session=None, workspace_id=None):
        super().__init__(source, company_name, session)
        self.subdomain = subdomain
        self.workspace_id = workspace_id

    def _resolve_workspace_id(self):
        if self.workspace_id:
            return self.workspace_id
        try:
            res = self.session.head(f"https://{self.subdomain}.career.greetinghr.com/", timeout=10)
            wid = res.headers.get("X-Greeting-Workspace-Id")
            if not wid:
                for c in res.cookies:
                    if c.name == "workspace-id":
                        wid = c.value
                        break
            self.workspace_id = wid
        except Exception:
            self.workspace_id = None
        return self.workspace_id

    @staticmethod
    def _deadline_from_due(due_date, today=None):
        """목록 dueDate('2026-08-02T14:59:59Z' — KST 자정 직전의 UTC 표기)를 'YYYY-MM-DD'로.

        '2033-01-31'처럼 1년 넘게 남은 날짜는 사실상 상시채용 표기라 None으로 둔다
        (마감임박 배지·알림 계산을 오염시키지 않도록)."""
        if not due_date or len(due_date) < 10:
            return None
        day = due_date[:10]
        try:
            d = date.fromisoformat(day)
        except ValueError:
            return None
        base = today or now_kst().date()
        if (d - base).days > 365:
            return None
        return day

    @staticmethod
    def _extract_body_from_html(page_html):
        """상세(SSR) 페이지에서 JD 본문 텍스트 추출. 마크업 미인식 시 빈 문자열.

        본문은 'OpeningContent_...' 류의 Content 클래스 블록 중 가장 긴 것에 있다
        (클래스 해시가 빌드마다 바뀌므로 부분 일치로 잡는다)."""
        soup = BeautifulSoup(page_html, "html.parser")
        blocks = soup.select("[class*='Content']")
        if not blocks:
            return ""
        best = max(blocks, key=lambda el: len(el.get_text(strip=True)))
        text = best.get_text("\n").strip()
        # 빈 껍데기/네비 블록 방어 — 본문이라기엔 너무 짧으면 버린다
        return text if len(text) > 80 else ""

    def _fetch_opening_body(self, origin_url):
        """공고 상세 페이지 본문 (분류 정확도용). 실패해도 수집은 계속(빈 문자열)."""
        try:
            res = self.session.get(origin_url, timeout=15)
            if res.status_code != 200:
                return ""
            return self._extract_body_from_html(res.text)
        except Exception:
            return ""

    def fetch(self):
        results = []
        wid = self._resolve_workspace_id()
        if not wid:
            return results
        url = f"https://api.greetinghr.com/ats/v1.1/career/workspaces/{wid}/openings?page=0&pageSize=100"
        res = self.session.get(url, timeout=15)
        res.raise_for_status()
        for job in res.json().get("data", {}).get("datas", []):
            title = job.get("title", "")
            if not self.is_finance_job(title):
                continue
            opening_id = job.get("openingId")
            job_id = f"{self.source}_{opening_id}"
            origin = f"https://{self.subdomain}.career.greetinghr.com/ko/o/{opening_id}"
            posted = (job.get("openDate") or "")[:10] or None
            deadline = self._deadline_from_due(job.get("dueDate"))
            body = self._fetch_opening_body(origin)
            results.append(self.build_posting(job_id, title, origin, body or title, posted, None, deadline=deadline))
        return results
