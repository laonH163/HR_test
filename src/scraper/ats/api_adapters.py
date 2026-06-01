"""무인증 공개 API 기반 ATS 어댑터 (Greenhouse / Lever / greetinghr).

세 ATS 모두 인증 없이 표준 JSON API를 제공하므로 requests만으로 안정적으로
수집된다(봇차단·JS 렌더링 불필요). 같은 ATS를 쓰는 새 게임사는 식별자만 추가하면 된다.

라이브 검증(2026-06-01):
- Greenhouse 크래프톤(board=krafton): 200, 재무직 3건(별도/연결회계 등)
- Lever 네오위즈(site=neowiz): 200, 34건(현재 재무직 0)
- greetinghr 카카오게임즈(workspace=7144): 헤더로 workspace id 해석 가능
"""
import html

from bs4 import BeautifulSoup

from src.scraper.ats.base import BaseATSAdapter


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
        if res.status_code != 200:
            return results
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
        if res.status_code != 200:
            return results
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

    공고목록 API는 제목만 제공하므로 본문 분류는 제목 기준이다(상세 본문 보강은 후속 과제).
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

    def fetch(self):
        results = []
        wid = self._resolve_workspace_id()
        if not wid:
            return results
        url = f"https://api.greetinghr.com/ats/v1.1/career/workspaces/{wid}/openings?page=0&pageSize=100"
        res = self.session.get(url, timeout=15)
        if res.status_code != 200:
            return results
        for job in res.json().get("data", {}).get("datas", []):
            title = job.get("title", "")
            if not self.is_finance_job(title):
                continue
            opening_id = job.get("openingId")
            job_id = f"{self.source}_{opening_id}"
            origin = f"https://{self.subdomain}.career.greetinghr.com/ko/o/{opening_id}"
            posted = (job.get("openDate") or "")[:10] or None
            results.append(self.build_posting(job_id, title, origin, title, posted, None))
        return results
