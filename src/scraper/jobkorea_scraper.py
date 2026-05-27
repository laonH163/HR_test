import requests
from bs4 import BeautifulSoup
import re
import random
import time
from datetime import datetime

class JobKoreaScraper:
    def __init__(self):
        # 대한민국 모든 게임 회사, 계열사, 지주사 및 글로벌 게임 도메인 명칭 마스터 사전 (누락 0% 보강)
        self.game_keywords = [
            "게임", "game", "nexon", "krafton", "ncsoft", "netmarble", "neowiz", "smilegate",
            "펄어비스", "위메이드", "카카오게임즈", "그라비티", "넥슨", "크래프톤", "엔씨소프트",
            "넷마블", "네오위즈", "스마일게이트", "데브시스터즈", "컴투스", "웹젠", "조이시티",
            "한빛소프트", "썸에이지", "해긴", "쿡앱스", "클로버게임즈", "시프트업", "라인게임즈",
            "더블유게임즈", "레드브릭", "엔씨", "com2us", "wemade", "gravity", "kakaogames",
            "pearlabyss", "webzen", "shiftup", "linegames", "joycity", "액션스퀘어",
            "위메이드맥스", "위메이드플레이", "컴투스홀딩스", "컴투스플랫폼", "NHN", "nhn",
            "엔에이치엔", "네오플", "아이덴티티", "그라비티네오싸이언", "웹젠레드코어", "웹젠블루포트"
        ]
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.google.com/"
        }

    def is_game_company(self, company_name, title):
        """회사명 또는 공고 제목에 게임업계 키워드가 포함되는지 필터링"""
        norm_name = company_name.lower()
        norm_title = title.lower()

        for kw in self.game_keywords:
            if kw in norm_name or kw in norm_title:
                return True
        return False

    def scrape_finance_jobs(self, limit=15):
        """requests 및 최신 개편 CSS 선택자를 적용하여 리팩토링된 잡코리아 수집 엔진"""
        results = []
        keywords = ["회계", "세무", "재무", "자금"]

        for keyword in keywords:
            time.sleep(random.uniform(1.0, 2.5))
            # 잡코리아 검색 연동
            search_url = f"https://www.jobkorea.co.kr/Search/?stext={keyword}"
            try:
                res = requests.get(search_url, headers=self.headers, timeout=15)
                if res.status_code != 200:
                    continue

                soup = BeautifulSoup(res.text, "html.parser")

                # 최신 잡코리아 검색 결과 카드 컨테이너 선택
                job_cards = soup.select("div[class*='rounded-2xl']") or soup.select("div[class*='hover:bg-blue54']")

                # 만약 카드 단위 셀렉터가 실패할 경우를 위한 튼튼한 폴백
                if not job_cards:
                    gi_links = soup.select("a[href*='/Recruit/GI_Read/']")
                    job_cards = []
                    for link in gi_links:
                        parent = link.parent
                        while parent and parent.name != "div":
                            parent = parent.parent
                        if parent and parent not in job_cards:
                            job_cards.append(parent)

                count = 0
                for card in job_cards:
                    if count >= limit:
                        break

                    title_link = card.select_one("a[href*='/Recruit/GI_Read/']")
                    if not title_link:
                        continue

                    href = title_link.get("href", "")
                    gno_match = re.search(r"GI_Read/(\d+)", href) or re.search(r"gno=(\d+)", href)
                    if not gno_match:
                        continue
                    jk_id = gno_match.group(1)
                    job_id = f"jobkorea_{jk_id}"

                    # 중복 방어
                    if any(r["id"] == job_id for r in results):
                        continue

                    title = title_link.text.strip()
                    company_name = "잡코리아 채용 기업"

                    # 카드 레벨에서 1차 정보 수집
                    company_link = card.select_one("a[href*='/Company/']") or card.select_one("a[target='_blank']")
                    if company_link and company_link != title_link:
                        company_name = company_link.text.strip()

                    # 상세 페이지 접속하여 정밀 보정 및 본문 수집
                    detail_url = f"https://www.jobkorea.co.kr/Recruit/GI_Read/{jk_id}"
                    time.sleep(random.uniform(0.5, 1.2))

                    try:
                        detail_res = requests.get(detail_url, headers=self.headers, timeout=10)
                        if detail_res.status_code == 200:
                            detail_soup = BeautifulSoup(detail_res.text, "html.parser")

                            # 공고 본문 정보 파싱
                            main_content = detail_soup.select_one(".recruit-detail-con") or detail_soup.select_one("#content") or detail_soup.select_one("body")
                            desc_text = main_content.get_text(separator="\n").strip() if main_content else title

                            # 제목 및 회사명 오정제 정밀 보정
                            # 잡코리아 개편 구조: H2는 회사명, H1은 채용 타이틀
                            meta_company_el = detail_soup.select_one("h2")
                            if meta_company_el and len(meta_company_el.text.strip()) > 0:
                                company_name = meta_company_el.text.strip()

                            h1_elements = [h.text.strip() for h in detail_soup.select("h1") if h.text.strip()]
                            if h1_elements:
                                title = h1_elements[0]
                        else:
                            desc_text = title
                    except Exception:
                        desc_text = title

                    # 최종 보정 후 다시 게임사 여부 점검 (안전장치)
                    if not self.is_game_company(company_name, title) and "게임" not in desc_text.lower() and "game" not in desc_text.lower():
                        continue

                    location_el = card.select_one(".loc") or card.select_one(".option span")
                    location = location_el.text.strip() if location_el else "서울"

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

        unique_postings = {}
        for item in results:
            unique_postings[item["id"]] = item

        return list(unique_postings.values())
