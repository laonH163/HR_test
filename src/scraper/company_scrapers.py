import requests
from bs4 import BeautifulSoup
import random
import time
from datetime import datetime
import json

class CompanyScrapers:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    def scrape_nexon_finance_jobs(self):
        """넥슨 커리어 사이트에서 재무/회계 직군 수집"""
        results = []
        # 넥슨 채용 공고 조회 API (실제 넥슨 채용 웹페이지 백엔드 호출 구조 분석 반영)
        # 키워드 '재무', '회계', '세무', '자금' 검색
        keywords = ["재무", "회계", "세무", "자금"]

        for keyword in keywords:
            time.sleep(random.uniform(1.0, 2.0))
            url = f"https://career.nexon.com/api/recruit/notice/list?keyword={keyword}&page=1&pageSize=10"
            try:
                # 넥슨 채용 목록 조회 API를 시도하고, 차단 시 또는 오류 시에는 예외 복구를 위해 일반 HTML 뷰 형태의 Fallback을 구성합니다.
                response = requests.get(url, headers=self.headers, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    notices = data.get("noticeList", [])
                    for notice in notices:
                        job_id = f"nexon_{notice.get('noticeSn')}"
                        title = notice.get("noticeTitle", "")

                        # 상세 데이터 취득을 위한 넥슨 상세 URL
                        detail_url = f"https://career.nexon.com/api/recruit/notice/detail?noticeSn={notice.get('noticeSn')}"
                        time.sleep(0.5)
                        detail_res = requests.get(detail_url, headers=self.headers, timeout=10)
                        raw_desc = ""
                        if detail_res.status_code == 200:
                            detail_data = detail_res.json()
                            raw_desc = detail_data.get("noticeHtml", "")
                            # HTML 태그 제거하여 텍스트만 추출
                            soup_desc = BeautifulSoup(raw_desc, "html.parser")
                            raw_desc = soup_desc.get_text(separator="\n").strip()

                        posting = {
                            "id": job_id,
                            "source": "nexon",
                            "company_name": "넥슨코리아",
                            "title": title,
                            "origin_url": f"https://career.nexon.com/user/recruit/notice/view?noticeSn={notice.get('noticeSn')}",
                            "location": "경기 성남시 분당구 (판교)",
                            "posted_at": notice.get("noticeRegDate", datetime.today().strftime("%Y-%m-%d")),
                            "status": "ACTIVE",
                            "raw_html": raw_desc if raw_desc else title,
                            "first_seen_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "last_updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }
                        results.append(posting)
                else:
                    # Fallback BeautifulSoup 파서 구축
                    self._fallback_nexon_html(results, keyword)
            except Exception as e:
                # API 실패 시 HTML 뷰 Fallback 시도
                try:
                    self._fallback_nexon_html(results, keyword)
                except Exception:
                    continue

        return results

    def _fallback_nexon_html(self, results, keyword):
        """넥슨 커리어 사이트 HTML 구조 기반 파싱 (API 오류 시 폴백)"""
        url = f"https://career.nexon.com/user/recruit/notice/list?keyword={keyword}"
        response = requests.get(url, headers=self.headers, timeout=10)
        if response.status_code != 200:
            return
        soup = BeautifulSoup(response.text, "html.parser")
        items = soup.select(".notice_list_body tr")
        for item in items:
            title_el = item.select_one(".title a")
            if not title_el:
                continue
            title = title_el.text.strip()
            href = title_el.get("href", "")
            import re
            sn_match = re.search(r"noticeSn=(\d+)", href)
            if not sn_match:
                continue
            sn = sn_match.group(1)

            results.append({
                "id": f"nexon_{sn}",
                "source": "nexon",
                "company_name": "넥슨코리아",
                "title": title,
                "origin_url": f"https://career.nexon.com/user/recruit/notice/view?noticeSn={sn}",
                "location": "경기 성남시 분당구 (판교)",
                "posted_at": datetime.today().strftime("%Y-%m-%d"),
                "status": "ACTIVE",
                "raw_html": title,
                "first_seen_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "last_updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

    def scrape_krafton_finance_jobs(self):
        """크래프톤 커리어 사이트에서 재무/회계 관련 공고를 직접 수집"""
        results = []
        # 크래프톤 공식 채용페이지 (그리팅 아웃소싱 또는 자체 API 형식 사용)
        # 크래프톤 채용 API 연동
        url = "https://krafton.career.greetinghr.com/api/v1/jobs?department=재무&page=1&pageSize=20"

        try:
            # 크래프톤이 사용하는 Greeting HR 채용 솔루션의 공통 API 주소를 타겟팅합니다.
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                jobs = data.get("jobs", [])
                for job in jobs:
                    # 재무/회계 관련 유효성 체크
                    title = job.get("title", "")
                    if not any(kw in title for kw in ["재무", "회계", "세무", "자금", "결산", "ERP"]):
                        continue

                    job_id = f"krafton_{job.get('id')}"
                    desc_soup = BeautifulSoup(job.get("description", ""), "html.parser")
                    raw_desc = desc_soup.get_text(separator="\n").strip()

                    posting = {
                        "id": job_id,
                        "source": "krafton",
                        "company_name": "크래프톤",
                        "title": title,
                        "origin_url": f"https://krafton.career.greetinghr.com/o/{job.get('id')}",
                        "location": job.get("location", "서울 서초구"),
                        "posted_at": job.get("openedAt", datetime.today().strftime("%Y-%m-%d")).split("T")[0],
                        "status": "ACTIVE",
                        "raw_html": raw_desc,
                        "first_seen_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "last_updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                    results.append(posting)
            else:
                self._fallback_krafton_html(results)
        except Exception as e:
            try:
                self._fallback_krafton_html(results)
            except Exception:
                pass

        return results

    def _fallback_krafton_html(self, results):
        """크래프톤 채용 사이트 HTML 구조 직접 크롤링 (API 장애 시 폴백)"""
        url = "https://krafton.career.greetinghr.com/"
        response = requests.get(url, headers=self.headers, timeout=10)
        if response.status_code != 200:
            return
        soup = BeautifulSoup(response.text, "html.parser")
        items = soup.select(".job-list-item")
        for item in items:
            title_el = item.select_one(".job-title")
            if not title_el:
                continue
            title = title_el.text.strip()
            if not any(kw in title for kw in ["재무", "회계", "세무", "자금", "결산"]):
                continue

            href = item.select_one("a").get("href", "")
            import re
            job_id_match = re.search(r"/o/(\d+)", href)
            job_id = job_id_match.group(1) if job_id_match else str(random.randint(1000, 9999))

            results.append({
                "id": f"krafton_{job_id}",
                "source": "krafton",
                "company_name": "크래프톤",
                "title": title,
                "origin_url": f"https://krafton.career.greetinghr.com{href}" if href.startswith("/") else href,
                "location": "서울 강남구/서초구",
                "posted_at": datetime.today().strftime("%Y-%m-%d"),
                "status": "ACTIVE",
                "raw_html": title,
                "first_seen_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "last_updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
