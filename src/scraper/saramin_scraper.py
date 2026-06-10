import requests
from bs4 import BeautifulSoup
import re
import random
import time
from datetime import datetime
from src.utils.http import make_session

class SaraminScraper:
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
            "엔에이치엔", "네오플", "아이덴티티", "그라비티네오싸이언", "웹젠레드코어", "웹젠블루포트",
            "하이브im", "hybeim", "빅게임스튜디오", "vicgamestudios", "vic game"
        ]
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.google.com/"
        }
        # 비개발/비제조 순수 카지노, 리조트, 오락실, 보드게임카페 등 게임 개발 및 IT도메인이 아닌 기업 블랙리스트
        self.company_blacklist = [
            "람정", "신화월드", "카지노", "casino", "호텔", "hotel", "리조트", "resort",
            "홀덤", "보드게임카페", "보드카페", "멀티방", "오락실"
        ]
        # 원치 않는 비사무/비재무 상세 직무 키워드 블랙리스트
        self.title_blacklist = [
            "딜러", "dealer", "식음료", "f&b", "객실", "안내", "서빙", "바텐더", "벨맨",
            "캐셔", "카운터", "알바", "아르바이트", "legal", "counsel", "compliance", "인사",
            "recru", "채용", "변호사", "준법", "공정거래", "보상", "급여", "pmo", "비서", "총무"
        ]
        # 일시적 네트워크 오류 자동 재시도 + 커넥션 재사용
        self.session = make_session(headers=self.headers)

    def is_finance_job(self, title):
        """제목 기준으로 재무/회계/세무/자금 직군인지 판별 (오탐 극최소화)"""
        if not title:
            return False
        title_lower = title.lower()

        # 비재무/비사무 직무 제외
        for blocked in self.title_blacklist:
            if blocked in title_lower:
                return False

        # 한글 재무/회계/세무/자금 직군 판별 키워드
        finance_keywords_ko = [
            "재무", "회계", "세무", "자금", "경리", "결산", "내부회계", "내부통제",
            "재무기획", "자금운용", "원가", "회계사", "세무사"
        ]
        if any(kw in title for kw in finance_keywords_ko):
            return True

        # 영어 재무/회계/세무/자금 직군 판별 키워드
        finance_keywords_en = [
            "finance", "financial", "accounting", "accountant", "tax",
            "treasury", "payroll", "fp&a"
        ]
        if any(kw in title_lower for kw in finance_keywords_en):
            return True

        # 감사: 재무·회계 맥락 복합어만 인정('고객감사' 등 오탐 배제)
        audit_pattern = r"(내부\s?감사|회계\s?감사|상근\s?감사|외부\s?감사|감사\s?담당|감사팀|감사실|감사역|감사\s?업무)"
        if re.search(audit_pattern, title):
            return True

        # IR(투자자관계/공시): 약어라 단어 경계로만 매칭해 hiring 등 오탐 방지
        if re.search(r"\bir\b", title_lower):
            return True

        # 재무공시/회계공시 등 구체적인 재무 맥락 공시만 매칭 (단독 '공시' 제거 대응)
        if re.search(r"(재무\s?공시|회계\s?공시|기업\s?공시)", title):
            return True

        return False

    def is_game_company(self, company_name, title):
        """회사명 또는 공고 제목에 게임 도메인 키워드가 포함되는지 필터링"""
        norm_name = company_name.lower()
        norm_title = title.lower()

        # 1. 회사명 블랙리스트 사전 검사
        for blocked in self.company_blacklist:
            if blocked in norm_name or blocked in norm_title:
                return False

        # 2. 직무명 블랙리스트 사전 검사
        for blocked_title in self.title_blacklist:
            if blocked_title in norm_title:
                return False

        for kw in self.game_keywords:
            if kw in norm_name or kw in norm_title:
                return True
        return False

    def scrape_finance_jobs(self, limit=15):
        """requests 기반으로 리팩토링된 안정적이고 신속한 사람인 채용공고 수집 엔진"""
        results = []
        keywords = ["회계", "세무", "재무", "자금"]

        for keyword in keywords:
            time.sleep(random.uniform(1.0, 2.5))
            # 사람인 검색 페이지 (requests 연동)
            search_url = f"https://www.saramin.co.kr/zf_user/search/recruit?searchword={keyword}&cat_mcls=2"
            try:
                res = self.session.get(search_url, headers=self.headers, timeout=15)
                if res.status_code != 200:
                    continue

                soup = BeautifulSoup(res.text, "html.parser")
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

                    # 게임 업계 공고 여부 및 재무 직무 여부 사전 분류
                    if not self.is_game_company(company_name, title) or not self.is_finance_job(title):
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
                    time.sleep(random.uniform(0.5, 1.2))

                    try:
                        detail_res = self.session.get(detail_url, headers=self.headers, timeout=10)
                        if detail_res.status_code == 200:
                            detail_soup = BeautifulSoup(detail_res.text, "html.parser")
                            main_content = detail_soup.select_one(".wrap_jv_co") or detail_soup.select_one(".jv_content") or detail_soup.select_one("body")
                            desc_text = main_content.get_text(separator="\n").strip() if main_content else title
                        else:
                            desc_text = title
                    except Exception:
                        desc_text = title

                    location_el = item.select_one(".job_condition span:nth-child(1)") or item.select_one(".job_condition span")
                    location = location_el.text.strip() if location_el else "서울"

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

            except Exception:
                continue

        unique_postings = {}
        for item in results:
            unique_postings[item["id"]] = item

        return list(unique_postings.values())
