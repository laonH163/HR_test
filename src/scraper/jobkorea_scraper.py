import random
import time
import re
from datetime import datetime
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

class JobKoreaScraper:
    def __init__(self):
        # 2배 확장된 대한민국 핵심 게임 제작 및 서비스 회사 전 범위 명칭 사전
        self.game_keywords = [
            "게임", "game", "nexon", "krafton", "ncsoft", "netmarble", "neowiz", "smilegate",
            "펄어비스", "위메이드", "카카오게임즈", "그라비티", "넥슨", "크래프톤", "엔씨소프트",
            "넷마블", "네오위즈", "스마일게이트", "데브시스터즈", "컴투스", "웹젠", "조이시티",
            "한빛소프트", "썸에이지", "해긴", "쿡앱스", "클로버게임즈", "시프트업", "라인게임즈",
            "더블유게임즈", "레드브릭", "엔씨"
        ]

    def is_game_company(self, company_name, title):
        """회사명 또는 공고 제목에 게임업계 키워드가 포함되는지 필터링"""
        norm_name = company_name.lower()
        norm_title = title.lower()

        for kw in self.game_keywords:
            if kw in norm_name or kw in norm_title:
                return True
        return False

    def scrape_finance_jobs(self, limit=15):
        """스텔스 우회가 적용된 잡코리아 공고 수집 엔진"""
        results = []
        keywords = ["회계", "세무", "재무", "자금"]

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox"
                ]
            )

            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
                locale="ko-KR",
                timezone_id="Asia/Seoul"
            )

            page = context.new_page()

            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)

            for keyword in keywords:
                time.sleep(random.uniform(1.5, 3.0))
                # 잡코리아 검색 연동
                search_url = f"https://www.jobkorea.co.kr/Search/?stext={keyword}"
                try:
                    page.goto(search_url, timeout=30000)
                    page.wait_for_timeout(3000)

                    # 스크롤 2회 다운으로 충분한 컨텐츠 확보
                    for _ in range(2):
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        time.sleep(1.0)

                    content = page.content()
                    soup = BeautifulSoup(content, "html.parser")
                    # 잡코리아 검색 목록 카드 선택자
                    job_items = soup.select(".list-default .list-post")

                    count = 0
                    for item in job_items:
                        if count >= limit:
                            break

                        corp_area = item.select_one(".post-list-corp a")
                        title_area = item.select_one(".post-list-info a")

                        if not corp_area or not title_area:
                            continue

                        company_name = corp_area.text.strip()
                        title = title_area.text.strip()

                        # 게임 도메인 매칭 검증
                        if not self.is_game_company(company_name, title):
                            continue

                        # 유일 주소 및 ID 획득
                        href = title_area.get("href", "")
                        # 잡코리아 공고 ID 파싱 (예: gno=123456)
                        gno_match = re.search(r"gno=(\d+)", href)
                        if not gno_match:
                            continue
                        jk_id = gno_match.group(1)
                        job_id = f"jobkorea_{jk_id}"

                        # 중복 방어
                        if any(r["id"] == job_id for r in results):
                            continue

                        detail_url = f"https://www.jobkorea.co.kr/Recruit/GI_Read/{jk_id}"
                        detail_page = context.new_page()
                        time.sleep(random.uniform(0.5, 1.5))
                        detail_page.goto(detail_url, timeout=20000)
                        detail_page.wait_for_timeout(2000)

                        detail_html = detail_page.content()
                        detail_soup = BeautifulSoup(detail_html, "html.parser")

                        # 공고 본문 정보 파싱
                        main_content = detail_soup.select_one(".recruit-detail-con") or detail_soup.select_one("body")
                        desc_text = main_content.get_text(separator="\n").strip() if main_content else title

                        location_el = item.select_one(".option .loc")
                        location = location_el.text.strip() if location_el else "서울"

                        detail_page.close()

                        posting = {
                            "id": job_id,
                            "source": "jobkorea",
                            "company_name": company_name,
                            "title": title,
                            "origin_url": detail_url,
                            "location": location,
                            "posted_at": datetime.today().strftime("%Y-%m-%d"),
                            "status": "ACTIVE",
                            "raw_html": desc_text,
                            "first_seen_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "last_updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }
                        results.append(posting)
                        count += 1

                except Exception:
                    continue

            browser.close()

        unique_postings = {}
        for item in results:
            unique_postings[item["id"]] = item

        return list(unique_postings.values())
