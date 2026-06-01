import requests
from bs4 import BeautifulSoup
import re
import random
import time
import urllib.parse
from datetime import datetime
from src.utils.http import make_session

class GameJobScraper:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.gamejob.co.kr/"
        }
        # 핵심 재무/회계/세무/자금 직무 키워드 정의 (무관한 게임 개발, PM, 디자인 직군 필터링용)
        self.finance_keywords = [
            "회계", "세무", "재무", "자금", "경리", "결산", "ERP", "감사", "세정",
            "자금운용", "내부통제", "accounting", "finance", "tax", "auditing"
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
        # 일시적 네트워크 오류 자동 재시도 + 커넥션 재사용
        self.session = make_session(headers=self.headers)

    def is_finance_job(self, title):
        """직무 타이틀이 핵심 재무/회계/세무/자금 카테고리에 속하는지 검증"""
        norm_title = title.lower()
        for kw in self.finance_keywords:
            if kw in norm_title:
                return True
        return False

    def is_valid_company_and_job(self, company_name, title):
        """카지노, 리조트, 단순 오락 업종 및 비사무직 직무 필터링 (람정 등 원천 차단)"""
        norm_company = company_name.lower()
        norm_title = title.lower()

        # 1. 회사명 블랙리스트 검사
        for blocked_co in self.company_blacklist:
            if blocked_co in norm_company or blocked_co in norm_title:
                return False

        # 2. 직무명 블랙리스트 검사
        for blocked_title in self.title_blacklist:
            if blocked_title in norm_title:
                return False

        return True

    def scrape_finance_jobs(self, limit=15):
        """EUC-KR 검색어 전송 및 UTF-8 응답 파싱, 그리고 직무 타이틀 필터가 반영된 게임잡 수집기"""
        results = []
        keywords = ["회계", "세무", "재무", "자금"]

        for keyword in keywords:
            time.sleep(random.uniform(1.0, 2.5))

            try:
                keyword_encoded = urllib.parse.quote(keyword, encoding="euc-kr")
            except Exception:
                keyword_encoded = urllib.parse.quote(keyword)

            search_url = f"https://www.gamejob.co.kr/List_GI/GI_Search_Keyword.asp?S_Div=GI_Keyword&S_Text={keyword_encoded}"

            try:
                res = self.session.get(search_url, headers=self.headers, timeout=15)
                html_text = res.content.decode("utf-8", errors="replace")

                if res.status_code != 200:
                    continue

                soup = BeautifulSoup(html_text, "html.parser")

                # 배너 및 우측 인기 공고를 엄격히 배제하고, 검색결과 목록 테이블(.tblList)의 링크만 수집합니다.
                gi_elements = soup.select("table.tblList a[href*='/Recruit/GI_Read/View']") or soup.select(".tblList a[href*='/Recruit/GI_Read/View']")

                unique_gi_nos = []
                for el in gi_elements:
                    href = el.get("href", "")
                    gno_match = re.search(r"GI_No=(\d+)", href)
                    if not gno_match:
                        continue
                    gi_no = gno_match.group(1)
                    if gi_no not in unique_gi_nos:
                        unique_gi_nos.append(gi_no)

                count = 0
                for gi_no in unique_gi_nos:
                    if count >= limit:
                        break

                    job_id = f"gamejob_{gi_no}"
                    detail_url = f"https://www.gamejob.co.kr/Recruit/GI_Read/View?GI_No={gi_no}"

                    # 중복 적재 방지
                    if any(r["id"] == job_id for r in results):
                        continue

                    # 각 공고 상세 페이지 접속 및 정보 수집
                    time.sleep(random.uniform(0.5, 1.2))
                    try:
                        detail_res = self.session.get(detail_url, headers=self.headers, timeout=10)
                        detail_html = detail_res.content.decode("utf-8", errors="replace")

                        if detail_res.status_code != 200:
                            continue

                        detail_soup = BeautifulSoup(detail_html, "html.parser")

                        # 타이틀 파싱 '[회사명] 공고제목' 형식 분석
                        page_title = detail_soup.title.text.strip() if detail_soup.title else ""
                        company_name = "게임회사"
                        title = "재무 회계 담당자"

                        match = re.search(r"\[(.*?)\]\s*(.*)", page_title)
                        if match:
                            company_name = match.group(1).strip()
                            title = match.group(2).strip()
                            if title.endswith("- 게임잡"):
                                title = title[:-8].strip()
                        else:
                            h1_el = detail_soup.select_one("h1") or detail_soup.select_one(".tit")
                            if h1_el:
                                title = h1_el.text.strip()
                            co_el = detail_soup.select_one(".co-name") or detail_soup.select_one(".company-name")
                            if co_el:
                                company_name = co_el.text.strip()

                        # 직무 필터링: 반드시 재무/회계/세무 직군이어야만 승인
                        if not self.is_finance_job(title):
                            continue

                        # 기업 및 직무 블랙리스트 엄격 필터링 (람정, 카지노, 딜러 등)
                        if not self.is_valid_company_and_job(company_name, title):
                            continue

                        # 공고 본문 내용
                        desc_container = detail_soup.select_one(".tbList") or detail_soup.select_one(".viewCol") or detail_soup.select_one("body")
                        full_desc = desc_container.get_text(separator="\n").strip() if desc_container else title

                        location = "서울/경기"

                        posting = {
                            "id": job_id,
                            "source": "gamejob",
                            "company_name": company_name,
                            "title": title,
                            "origin_url": detail_url,
                            "location": location,
                            "posted_at": datetime.today().strftime("%Y-%m-%d"),
                            "status": "ACTIVE",
                            "raw_html": full_desc,
                            "first_seen_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "last_updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }
                        results.append(posting)
                        count += 1

                    except Exception:
                        continue

            except Exception:
                continue

        unique_postings = {}
        for item in results:
            unique_postings[item["id"]] = item

        return list(unique_postings.values())
