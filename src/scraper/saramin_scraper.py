import requests
from bs4 import BeautifulSoup
import re
import random
import time
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
from src.scraper import filters
from src.utils.dateparse import parse_deadline_badge
from src.utils.http import make_session

class SaraminScraper:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.google.com/"
        }
        # 일시적 네트워크 오류 자동 재시도 + 커넥션 재사용
        self.session = make_session(headers=self.headers)

    def is_finance_job(self, title):
        """제목 기준으로 재무/회계/세무/자금 직군인지 판별 (공통 필터 위임)"""
        return filters.is_finance_job(title)

    def is_game_company(self, company_name, title):
        """회사명 또는 공고 제목에 게임 도메인 키워드가 포함되는지 필터링 (공통 필터 위임)"""
        return filters.is_game_company(company_name, title)

    def scrape_finance_jobs(self, limit=15):
        """requests 기반으로 리팩토링된 안정적이고 신속한 사람인 채용공고 수집 엔진"""
        results = []
        keywords = ["게임 회계", "게임 세무", "게임 재무", "게임 자금"]
        self.is_last_run_success = False
        success_connections = 0
        failed_errors = []

        for keyword in keywords:
            time.sleep(random.uniform(1.0, 2.5))
            # 사람인 검색 페이지 (requests 연동)
            search_url = f"https://www.saramin.co.kr/zf_user/search/recruit?searchword={keyword}"
            try:
                res = self.session.get(search_url, headers=self.headers, timeout=15)
                if res.status_code == 200:
                    success_connections += 1
                else:
                    failed_errors.append(f"HTTP {res.status_code}")
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

                    # 상세 설명 가져오기.
                    # ※ relay/view(구 주소)는 상세요강이 없는 중계 페이지다 — 셀렉터가 전부
                    #   빗나가고 body 폴백이 걸려 사람인 공통 레이아웃(전 공고 동일한 4,999자
                    #   네비게이션)이 본문으로 저장됐다. 2026-07-21 실측으로 확인해 정규
                    #   주소(jobs/view)로 교체. 정규 주소엔 .wrap_jv_cont에 요약표(경력·근무형태)와
                    #   상세요강이 함께 들어 있다.
                    detail_url = f"https://www.saramin.co.kr/zf_user/jobs/view?rec_idx={saramin_id}"
                    time.sleep(random.uniform(0.5, 1.2))

                    try:
                        detail_res = self.session.get(detail_url, headers=self.headers, timeout=10)
                        if detail_res.status_code == 200:
                            detail_soup = BeautifulSoup(detail_res.text, "html.parser")
                            # 본문 셀렉터가 전부 빗나가면 '제목만 수집'으로 정직하게 떨어뜨린다.
                            # body 폴백은 절대 두지 않는다 — 공통 레이아웃이 본문으로 둔갑하면
                            # has_body가 참이 되어 화면·분류가 근거 없는 값을 사실처럼 보여준다.
                            main_content = (detail_soup.select_one(".wrap_jv_cont")
                                            or detail_soup.select_one(".jv_detail")
                                            or detail_soup.select_one(".user_content"))
                            desc_text = main_content.get_text(separator="\n").strip() if main_content else title
                        else:
                            desc_text = title
                    except Exception:
                        desc_text = title

                    location_el = item.select_one(".job_condition span:nth-child(1)") or item.select_one(".job_condition span")
                    location = location_el.text.strip() if location_el else "서울"

                    # 목록 마감 배지("~ 07/31(금)"·"D-N"·"오늘마감") → 절대 마감일. 상시채용은 None
                    date_el = item.select_one(".job_date .date") or item.select_one(".job_date")
                    deadline = parse_deadline_badge(date_el.get_text(" ", strip=True) if date_el else "")

                    posting = {
                        "id": job_id,
                        "source": "saramin",
                        "company_name": company_name,
                        "title": title,
                        "origin_url": detail_url,
                        "location": location,
                        "posted_at": datetime.now(KST).strftime("%Y-%m-%d"),
                        "status": "ACTIVE",
                        "raw_html": desc_text,
                        "first_seen_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
                        "last_updated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
                        "deadline": deadline
                    }
                    results.append(posting)
                    count += 1

            except Exception as e:
                failed_errors.append(str(e))
                continue

        if success_connections == 0 and failed_errors:
            raise RuntimeError(f"사람인 수집 연결 완전히 실패 (IP 차단/WAF): {', '.join(set(failed_errors))}")

        self.is_last_run_success = True
        unique_postings = {}
        for item in results:
            unique_postings[item["id"]] = item

        return list(unique_postings.values())
