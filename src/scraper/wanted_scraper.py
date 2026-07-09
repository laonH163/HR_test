import re
import random
import time
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

from src.scraper import filters

# 상세 <title> 형식: "[회사명] 공고제목 채용 공고 | 원티드" (회사명·'채용 공고'는 없을 수 있음)
_DETAIL_PAGE_TITLE_RE = re.compile(r"^(?:\[([^\[\]]+)\]\s*)?(.+?)(?:\s*채용\s*공고)?\s*\|\s*원티드\s*$")


class WantedScraper:
    def __init__(self):
        pass

    @staticmethod
    def _correct_from_detail(detail_soup, title, company):
        """상세 페이지에서 제목·회사명을 보정한다. 신뢰할 수 있는 소스가 있을 때만 덮어쓴다.

        2026-07-09 실측: 원티드 상세 DOM 개편으로 첫 <h2>가 공고 제목이 아니라
        '포지션 상세' 같은 섹션 헤딩이 됨 — h2로 덮어쓰면 최종 재무직 검증에서
        전 카드가 탈락해 한 달간 수집 0건이었다. 이제 h1 → <title> 태그 순으로만 보정."""
        # 1) 제목: h1(공고 제목 전용 요소) 우선
        h1_el = detail_soup.select_one("h1")
        if h1_el and h1_el.text.strip():
            title = h1_el.text.strip()
        else:
            # 2) 폴백: <title> 태그 "[회사명] 제목 채용 공고 | 원티드" 패턴
            page_title = detail_soup.title.text.strip() if detail_soup.title else ""
            m = _DETAIL_PAGE_TITLE_RE.match(page_title)
            if m and m.group(2):
                title = m.group(2).strip()

        # 회사명: JobHeader 회사 링크(클래스 해시가 붙어 부분 일치) → 레거시 셀렉터 → <title> 대괄호
        meta_company_el = (detail_soup.select_one("a[class*='JobHeader__Tools__Company__Link']") or
                           detail_soup.select_one("[class*='JobHeader_companyName_']") or
                           detail_soup.select_one("h4"))
        if meta_company_el and meta_company_el.text.strip():
            company = meta_company_el.text.strip().replace("회사명 더보기", "").strip()
        else:
            page_title = detail_soup.title.text.strip() if detail_soup.title else ""
            m = _DETAIL_PAGE_TITLE_RE.match(page_title)
            if m and m.group(1):
                company = m.group(1).strip()

        return title, company

    def is_finance_job(self, title):
        """제목 기준으로 재무/회계/세무/자금 직군인지 판별 (공통 필터 위임)"""
        return filters.is_finance_job(title)

    def is_game_company(self, company_name, job_description):
        """회사명 또는 직무 컨텍스트에 게임 도메인 키워드가 있는지 필터링 (공통 필터 위임)"""
        return filters.is_game_company(company_name, job_description)

    def scrape_finance_jobs(self, limit=30):
        """스텔스 우회 기능이 적용된 원티드 공고 수집"""
        results = []
        keywords = ["게임 회계", "게임 세무", "게임 재무", "게임 자금"]
        self.is_last_run_success = False
        success_connections = 0
        failed_errors = []

        with sync_playwright() as p:
            # navigator.webdriver 탐지 우회를 위한 크롬 인자 주입
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox"
                ]
            )

            # 가짜 모바일/데스크톱 에이전트 및 환경 구성
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
                locale="ko-KR",
                timezone_id="Asia/Seoul"
            )

            page = context.new_page()

            # navigator.webdriver 변수를 동적 삭제 처리하여 WAF 탐지 회피
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)

            for keyword in keywords:
                time.sleep(random.uniform(1.5, 3.0))
                search_url = f"https://www.wanted.co.kr/search?query={keyword}"
                try:
                    page.goto(search_url, timeout=30000)
                    page.wait_for_timeout(3000)

                    # CloudFront 차단 여부 체크 (제목에 block 등 탐지 문구 여부)
                    title_text = page.title()
                    if "satisfied" in title_text.lower() or "blocked" in title_text.lower():
                        failed_errors.append("CloudFront WAF Blocked")
                        continue

                    # 3회 마우스 스크롤 다운을 통해 목록을 넉넉히 바인딩
                    for _ in range(3):
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        time.sleep(1.0)

                    content = page.content()
                    soup = BeautifulSoup(content, "html.parser")

                    # a 태그 중 /wd/ 상세 링크 파싱
                    wd_links_elements = [a for a in soup.select("a") if a.get("href") and "/wd/" in a.get("href")]
                    success_connections += 1

                    count = 0
                    for a_tag in wd_links_elements:
                        if count >= limit:
                            break

                        href = a_tag.get("href", "")
                        import re
                        job_id_match = re.search(r"/wd/(\d+)", href)
                        if not job_id_match:
                            continue
                        wanted_id = job_id_match.group(1)
                        job_id = f"wanted_{wanted_id}"

                        # 중복 수집 체크
                        if any(r["id"] == job_id for r in results):
                            continue

                        # 카드 내의 타이틀 및 회사명 탐색
                        title = "재무 회계 담당자"
                        company = "게임회사"

                        # 텍스트 정보 파싱 (최신 원티드 카드 UI 클래스명 완벽 대응)
                        corp_el = (a_tag.select_one("[class*='JobCard_companyName_']") or
                                   a_tag.select_one("span[class*='companyName']") or
                                   a_tag.select_one("span") or
                                   a_tag.select_one(".company-name"))

                        title_el = (a_tag.select_one("[class*='JobCard_title_']") or
                                    a_tag.select_one("strong[class*='title']") or
                                    a_tag.select_one("strong") or
                                    a_tag.select_one(".position-title"))

                        if corp_el:
                            company = corp_el.text.strip()
                        if title_el:
                            title = title_el.text.strip()

                        # 🔍 [원격 교차 검증 디버그 로그] 원티드에서 감지한 모든 원본 카드 덤프 출력
                        print(f"        [WANTED RAW CARD DETECTED] 회사명: {company} | 제목: {title}")

                        # 만약 회사명이나 제목 추출에 실패한 경우, 상세 페이지 URL 분석을 위해 무조건 진입 허용 (방어 필터링 우회)
                        if company == "게임회사" or title == "재무 회계 담당자":
                            is_suspicious_default = True
                        else:
                            is_suspicious_default = False

                        # 게임 업계 공고인지 사전 필터링 (suspicious 상태면 상세 페이지 검증을 위해 무조건 진행)
                        if not is_suspicious_default:
                            # 게임 회사 및 재무 직무인지 사전 체크 (마케팅 등 걸러내어 상세 페이지 탐색 최소화)
                            if not self.is_game_company(company, title) or not self.is_finance_job(title):
                                continue

                        # 상세 페이지로 이동해 본문 내용 긁어오기
                        detail_url = f"https://www.wanted.co.kr/wd/{wanted_id}"
                        detail_page = context.new_page()
                        time.sleep(random.uniform(0.5, 1.5))
                        detail_page.goto(detail_url, timeout=20000)
                        detail_page.wait_for_timeout(2000)

                        detail_html = detail_page.content()
                        detail_soup = BeautifulSoup(detail_html, "html.parser")

                        # 원티드 공고 본문 텍스트 통일 파싱
                        desc_container = detail_soup.select_one("[class*='JobDescription_']") or detail_soup.select_one("body")
                        full_desc = desc_container.get_text(separator="\n").strip() if desc_container else title

                        # 실제 회사명 및 제목 오정제 정밀 보정 (신뢰 소스가 있을 때만 덮어씀)
                        card_title = title
                        title, company = self._correct_from_detail(detail_soup, title, company)

                        detail_page.close()

                        # 상세 페이지에서 읽어온 최종 보정된 제목으로 한 번 더 직무 검증 수행 (최종 방어선)
                        if not self.is_finance_job(title):
                            # 탈락이 로그에 안 남으면 '성공 0건' 무음 고장이 됨(2026-07-09 실측:
                            # 상세 h2 개편으로 전 카드가 여기서 소리 없이 탈락, 한 달간 0건)
                            print(f"        [WANTED DROP] 최종 제목검증 탈락: '{title}' (카드 제목: '{card_title}')")
                            continue

                        # 정형 데이터 조립
                        posting = {
                            "id": job_id,
                            "source": "wanted",
                            "company_name": company,
                            "title": title,
                            "origin_url": detail_url,
                            "location": "서울/경기",
                            "posted_at": datetime.now(KST).strftime("%Y-%m-%d"),
                            "status": "ACTIVE",
                            "raw_html": full_desc,
                            "first_seen_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
                            "last_updated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
                        }
                        results.append(posting)
                        count += 1

                except Exception as e:
                    failed_errors.append(str(e))
                    continue

            browser.close()

        if success_connections == 0 and failed_errors:
            raise RuntimeError(f"원티드 수집 연결 완전히 실패 (IP 차단/WAF): {', '.join(set(failed_errors))}")

        self.is_last_run_success = True
        unique_postings = {}
        for item in results:
            unique_postings[item["id"]] = item

        return list(unique_postings.values())
