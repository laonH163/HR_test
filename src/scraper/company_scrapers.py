import requests
import sys
from bs4 import BeautifulSoup
import random
import time
from datetime import datetime
import json
from src.utils.http import make_session

class CompanyScrapers:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        # 일시적 네트워크 오류 자동 재시도 + 커넥션 재사용
        self.session = make_session(headers=self.headers)

    def scrape_nexon_finance_jobs(self):
        """넥슨 커리어 사이트에서 재무/회계/세무/자금 직군 수집"""
        results = []
        keywords = ["재무", "회계", "세무", "자금"]

        for keyword in keywords:
            time.sleep(random.uniform(1.0, 2.0))
            url = f"https://career.nexon.com/api/recruit/notice/list?keyword={keyword}&page=1&pageSize=10"
            try:
                response = self.session.get(url, headers=self.headers, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    notices = data.get("noticeList", [])
                    for notice in notices:
                        job_id = f"nexon_{notice.get('noticeSn')}"
                        title = notice.get("noticeTitle", "")

                        detail_url = f"https://career.nexon.com/api/recruit/notice/detail?noticeSn={notice.get('noticeSn')}"
                        time.sleep(0.5)
                        detail_res = self.session.get(detail_url, headers=self.headers, timeout=10)
                        raw_desc = ""
                        if detail_res.status_code == 200:
                            detail_data = detail_res.json()
                            raw_desc = detail_data.get("noticeHtml", "")
                            soup_desc = BeautifulSoup(raw_desc, "html.parser")
                            raw_desc = soup_desc.get_text(separator="\n").strip()

                        posting = {
                            "id": job_id,
                            "source": "nexon",
                            "company_name": "넥슨코리아",
                            "title": title,
                            "origin_url": f"https://career.nexon.com/user/recruit/notice/view?noticeSn={notice.get('noticeSn')}",
                            "location": "경기 판교",
                            "posted_at": notice.get("noticeRegDate", datetime.today().strftime("%Y-%m-%d")),
                            "status": "ACTIVE",
                            "raw_html": raw_desc if raw_desc else title,
                            "first_seen_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "last_updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }
                        results.append(posting)
                else:
                    self._fallback_nexon_html(results, keyword)
            except Exception:
                try:
                    self._fallback_nexon_html(results, keyword)
                except Exception as e:
                    print(f"    [ERR] 넥슨 API/폴백 수집 실패({keyword}): {e}", file=sys.stderr)
                    continue

        return results

    def _fallback_nexon_html(self, results, keyword):
        """넥슨 커리어 사이트 HTML 구조 기반 파싱 (API 오류 시 폴백)"""
        url = f"https://career.nexon.com/user/recruit/notice/list?keyword={keyword}"
        response = self.session.get(url, headers=self.headers, timeout=10)
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
                "location": "경기 판교",
                "posted_at": datetime.today().strftime("%Y-%m-%d"),
                "status": "ACTIVE",
                "raw_html": title,
                "first_seen_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "last_updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

    def scrape_krafton_finance_jobs(self):
        """크래프톤 커리어 사이트에서 재무/회계 관련 공고를 직접 수집"""
        results = []
        url = "https://krafton.career.greetinghr.com/api/v1/jobs?department=재무&page=1&pageSize=20"

        try:
            response = self.session.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                jobs = data.get("jobs", [])
                for job in jobs:
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
        except Exception:
            try:
                self._fallback_krafton_html(results)
            except Exception as e:
                print(f"    [ERR] 크래프톤 API/폴백 수집 실패: {e}", file=sys.stderr)

        return results

    def _fallback_krafton_html(self, results):
        """크래프톤 채용 사이트 HTML 구조 직접 크롤링 (API 장애 시 폴백)"""
        url = "https://krafton.career.greetinghr.com/"
        response = self.session.get(url, headers=self.headers, timeout=10)
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
                "location": "서울 서초구",
                "posted_at": datetime.today().strftime("%Y-%m-%d"),
                "status": "ACTIVE",
                "raw_html": title,
                "first_seen_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "last_updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })

    def scrape_ncsoft_finance_jobs(self):
        """엔씨소프트 공식 채용 홈페이지에서 재무/회계 직군 직접 수집"""
        results = []
        # 엔씨소프트는 채용 페이지 호출용 REST API가 잘 구성되어 있어 안정적 수집이 보장됩니다.
        url = "https://career.ncsoft.com/api/recruit/notices?page=1&pageSize=50"
        try:
            response = self.session.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                notices = data.get("noticeList", [])
                for notice in notices:
                    title = notice.get("title", "")
                    if not any(kw in title for kw in ["재무", "회계", "세무", "자금", "결산", "ERP", "감사", "자금운용"]):
                        continue

                    job_id = f"ncsoft_{notice.get('noticeSn')}"
                    detail_url = f"https://career.ncsoft.com/user/recruit/notice/view?noticeSn={notice.get('noticeSn')}"

                    results.append({
                        "id": job_id,
                        "source": "ncsoft",
                        "company_name": "엔씨소프트",
                        "title": title,
                        "origin_url": detail_url,
                        "location": "경기 판교",
                        "posted_at": notice.get("noticeRegDate", datetime.today().strftime("%Y-%m-%d")),
                        "status": "ACTIVE",
                        "raw_html": notice.get("contents", title),
                        "first_seen_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "last_updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
        except Exception as e:
            print(f"    [ERR] 엔씨소프트 API 수집 실패: {e}", file=sys.stderr)
        return results

    def scrape_netmarble_finance_jobs(self):
        """넷마블 공식 채용 홈페이지에서 재무/회계 직군 수집"""
        results = []
        # 넷마블 채용 OpenAPI 분석 반영 연동
        url = "https://recruit.netmarble.com/api/recruit/list?page=1&pageSize=50"
        try:
            response = self.session.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                notices = data.get("noticeList", [])
                for notice in notices:
                    title = notice.get("title", "")
                    if not any(kw in title for kw in ["재무", "회계", "세무", "자금", "결산", "ERP"]):
                        continue

                    job_id = f"netmarble_{notice.get('noticeSn')}"
                    detail_url = f"https://recruit.netmarble.com/user/recruit/notice/view?noticeSn={notice.get('noticeSn')}"

                    results.append({
                        "id": job_id,
                        "source": "netmarble",
                        "company_name": "넷마블",
                        "title": title,
                        "origin_url": detail_url,
                        "location": "서울 구로",
                        "posted_at": notice.get("noticeRegDate", datetime.today().strftime("%Y-%m-%d")),
                        "status": "ACTIVE",
                        "raw_html": notice.get("contents", title),
                        "first_seen_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "last_updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
        except Exception as e:
            print(f"    [ERR] 넷마블 API 수집 실패: {e}", file=sys.stderr)
        return results

    def scrape_smilegate_finance_jobs(self):
        """스마일게이트 공식 채용 홈페이지에서 재무/회계 직군 수집"""
        results = []
        # 스마일게이트 채용 솔루션 API 분석 연동
        url = "https://smilegate.career.greetinghr.com/api/v1/jobs?page=1&pageSize=40"
        try:
            response = self.session.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                jobs = data.get("jobs", [])
                for job in jobs:
                    title = job.get("title", "")
                    if not any(kw in title for kw in ["재무", "회계", "세무", "자금", "결산", "ERP", "감사"]):
                        continue

                    job_id = f"smilegate_{job.get('id')}"
                    results.append({
                        "id": job_id,
                        "source": "smilegate",
                        "company_name": "스마일게이트",
                        "title": title,
                        "origin_url": f"https://smilegate.career.greetinghr.com/o/{job.get('id')}",
                        "location": "경기 판교",
                        "posted_at": job.get("openedAt", datetime.today().strftime("%Y-%m-%d")).split("T")[0],
                        "status": "ACTIVE",
                        "raw_html": title,
                        "first_seen_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "last_updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
        except Exception as e:
            print(f"    [ERR] 스마일게이트 API 수집 실패: {e}", file=sys.stderr)
        return results

    def scrape_shiftup_finance_jobs(self):
        """시프트업(ShiftUp) 공식 채용 사이트에서 재무/회계/세무/자금/경리 공고 직접 수집"""
        results = []
        url = "https://shiftup.co.kr/comm/lib/client_lib.php"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": "https://shiftup.co.kr/recruit/recruit.php",
            "X-Requested-With": "XMLHttpRequest"
        }
        data = "workType=get_recruit_list&code=recruit&cat_idx=0&searchkey="

        try:
            response = self.session.post(url, headers=headers, data=data, timeout=10)
            if response.status_code == 200:
                data_json = response.json()
                jobs = data_json.get("list", [])
                for job in jobs:
                    title = job.get("subject", "")
                    if not any(kw in title for kw in ["재무", "회계", "세무", "자금", "경리", "결산"]):
                        continue

                    job_id = f"shiftup_{job.get('idx')}"
                    content_html = job.get("content", "")

                    soup_desc = BeautifulSoup(content_html, "html.parser")
                    raw_desc = soup_desc.get_text(separator="\n").strip()

                    experience_str = job.get("addinfo3", "경력")

                    results.append({
                        "id": job_id,
                        "source": "shiftup",
                        "company_name": "시프트업",
                        "title": title,
                        "origin_url": "https://shiftup.co.kr/recruit/recruit.php",
                        "location": "서울 서초구",
                        "posted_at": job.get("wdate", datetime.today().strftime("%Y-%m-%d")).split(" ")[0],
                        "status": "ACTIVE",
                        "raw_html": f"경력 요건: {experience_str}\n\n상세 정보:\n{raw_desc}",
                        "first_seen_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "last_updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
        except Exception as e:
            print(f"    [ERR] 시프트업 채용 API 수집 실패: {e}", file=sys.stderr)
        return results

    def scrape_official_adapters(self):
        """ATS 어댑터 기반 공식 게임사 자체페이지 통합 수집.

        크래프톤(Greenhouse)·네오위즈(Lever)·카카오게임즈(greetinghr)·펄어비스(정적) 등
        무인증 API/정적 그룹을 한 번에 수집한다. 각 어댑터는 safe_fetch로 격리돼
        한 회사 실패가 나머지 수집을 막지 않는다. (시프트업은 위 자체 메서드 유지)
        """
        from src.scraper.ats.registry import build_official_adapters
        results = []
        for adapter in build_official_adapters(session=self.session):
            jobs = adapter.safe_fetch()
            print(f"       · {adapter.company_name}: {len(jobs)}건")
            results.extend(jobs)
        return results
