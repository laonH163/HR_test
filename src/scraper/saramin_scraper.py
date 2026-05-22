import random
import time
import re
from datetime import datetime
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

class SaraminScraper:
    def __init__(self):
        self.game_keywords = ["게임", "game", "nexon", "krafton", "ncsoft", "netmarble", "neowiz", "smilegate", "펄어비스", "위메이드", "카카오게임즈", "그라비티", "넥슨", "크래프톤", "엔씨", "넷마블", "네오위즈", "스마일게이트", "데브시스터즈", "컴투스"]

    def is_game_company(self, company_name, title):
        """회사명 또는 공고 제목에 게임 도메인 키워드가 포함되는지 필터링"""
        norm_name = company_name.lower()
        norm_title = title.lower()

        for kw in self.game_keywords:
            if kw in norm_name or kw in norm_title:
                return True
        return False

    def scrape_finance_jobs(self, limit=15):
        """스텔스 우회 기능이 장착된 사람인 채용공고 수집"""
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
                search_url = f"https://www.saramin.co.kr/zf_user/search/recruit?searchword={keyword}&cat_mcls=2"
                try:
                    page.goto(search_url, timeout=30000)
                    page.wait_for_timeout(3000)

                    # 스크롤 2회 다운
                    for _ in range(2):
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        time.sleep(1.0)

                    content = page.content()
                    soup = BeautifulSoup(content, "html.parser")
                    job_items = soup.select(".item_recruit")

                    count = 0
                    for item in job_items:
                        if count >= limit:
                            break

                        corp_area = item.select_one(".corp_name a")
                        title_area = item.select_one(".job_tit a")

                        if not corp_area or not title_area:
                            continue

                        company_name = corp_area.text.strip()
                        title = title_area.text.strip()

                        # 게임 업계 공고 여부 사전 분류
                        if not self.is_game_company(company_name, title):
                            continue

                        href = title_area.get("href", "")
                        job_id_match = re.search(r"rec_idx=(\d+)", href)
                        if not job_id_match:
                            continue
                        saramin_id = job_id_match.group(1)
                        job_id = f"saramin_{saramin_id}"

                        # 중복 제거
                        if any(r["id"] == job_id for r in results):
                            continue

                        # 상세 설명 가져오기
                        detail_url = f"https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx={saramin_id}"
                        detail_page = context.new_page()
                        time.sleep(random.uniform(0.5, 1.5))
                        detail_page.goto(detail_url, timeout=20000)
                        detail_page.wait_for_timeout(2000)

                        detail_html = detail_page.content()
                        detail_soup = BeautifulSoup(detail_html, "html.parser")

                        # 본문 영역 파싱
                        main_content = detail_soup.select_one(".wrap_jv_co") or detail_soup.select_one("body")
                        desc_text = main_content.get_text(separator="\n").strip() if main_content else title

                        location_el = item.select_one(".job_condition span:nth-child(1)")
                        location = location_el.text.strip() if location_el else "서울"

                        detail_page.close()

                        posting = {
                            "id": job_id,
                            "source": "saramin",
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

                except Exception as e:
                    continue

            browser.close()

        unique_postings = {}
        for item in results:
            unique_postings[item["id"]] = item

        return list(unique_postings.values())
