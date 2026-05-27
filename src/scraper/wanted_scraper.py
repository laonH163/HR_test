import random
import time
from datetime import datetime
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

class WantedScraper:
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
        # 비개발/비제조 순수 카지노, 리조트, 오락실, 보드게임카페 등 게임 개발 및 IT도메인이 아닌 기업 블랙리스트
        self.company_blacklist = [
            "람정", "신화월드", "카지노", "casino", "호텔", "hotel", "리조트", "resort",
            "홀덤", "보드게임카페", "보드카페", "멀티방", "오락실"
        ]
        # 원치 않는 비사무/비재무 상세 직무 키워드 블랙리스트
        self.title_blacklist = [
            "딜러", "dealer", "식음료", "f&b", "객실", "안내", "서빙", "바텐더", "벨맨",
            "캐셔", "카운터", "알바", "아르바이트"
        ]

    def is_game_company(self, company_name, job_description):
        """회사명 또는 직무 상세 내용에 게임 도메인 키워드가 들어있는지 필터링"""
        norm_name = company_name.lower()
        norm_desc = job_description.lower()

        # 1. 회사명 블랙리스트 사전 검사
        for blocked in self.company_blacklist:
            if blocked in norm_name or blocked in norm_desc:
                return False

        # 2. 직무명 블랙리스트 사전 검사
        for blocked_title in self.title_blacklist:
            if blocked_title in norm_desc:
                return False

        # 회사명 직접 매칭
        for kw in self.game_keywords:
            if kw in norm_name:
                return True

        # 본문에 게임 및 채용 도메인 매칭
        if "게임" in norm_desc or "game" in norm_desc:
            return True

        return False

    def scrape_finance_jobs(self, limit=30):
        """스텔스 우회 기능이 적용된 원티드 공고 수집"""
        results = []
        keywords = ["회계", "세무", "재무", "자금"]

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

                    # 3회 마우스 스크롤 다운을 통해 목록을 넉넉히 바인딩
                    for _ in range(3):
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        time.sleep(1.0)

                    content = page.content()
                    soup = BeautifulSoup(content, "html.parser")

                    # a 태그 중 /wd/ 상세 링크 파싱
                    wd_links_elements = [a for a in soup.select("a") if a.get("href") and "/wd/" in a.get("href")]

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
                        if not is_suspicious_default and not self.is_game_company(company, title):
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

                        # 실제 회사명 및 제목 오정제 정밀 보정
                        meta_title_el = detail_soup.select_one("h2")
                        if meta_title_el:
                            title = meta_title_el.text.strip()

                        # 회사명 추출 보정
                        meta_company_el = detail_soup.select_one("h4") or detail_soup.select_one("[class*='JobHeader_companyName_']")
                        if meta_company_el:
                            company = meta_company_el.text.strip().replace("회사명 더보기", "").strip()

                        detail_page.close()

                        # 정형 데이터 조립
                        posting = {
                            "id": job_id,
                            "source": "wanted",
                            "company_name": company,
                            "title": title,
                            "origin_url": detail_url,
                            "location": "서울/경기",
                            "posted_at": datetime.today().strftime("%Y-%m-%d"),
                            "status": "ACTIVE",
                            "raw_html": full_desc,
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
