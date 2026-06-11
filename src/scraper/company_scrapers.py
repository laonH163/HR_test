import sys
from datetime import datetime

from bs4 import BeautifulSoup

from src.utils.http import make_session


class CompanyScrapers:
    """게임사 공식 채용 수집 진입점.

    - 시프트업: 자체 비공식 API가 안정 동작하므로 전용 메서드 유지.
    - 그 외 공식 게임사: ATS별 어댑터(src/scraper/ats/)로 통합 수집.
      (기존 넥슨/엔씨/넷마블/크래프톤/스마일게이트 개별 메서드는 채용 도메인 폐기·이전으로
       전부 작동 불가임이 라이브 확인되어 어댑터·잡코리아 우회로 대체됨)
    """

    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        # 일시적 네트워크 오류 자동 재시도 + 커넥션 재사용
        self.session = make_session(headers=self.headers)

    def scrape_shiftup_finance_jobs(self):
        """시프트업(ShiftUp) 공식 채용 사이트에서 재무/회계/세무/자금/경리 공고 직접 수집"""
        results = []
        self.shiftup_last_run_success = False
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
                self.shiftup_last_run_success = True
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
            else:
                self.shiftup_last_run_success = False
        except Exception as e:
            self.shiftup_last_run_success = False
            print(f"    [ERR] 시프트업 채용 API 수집 실패: {e}", file=sys.stderr)
        return results

    def scrape_official_adapters(self):
        """ATS 어댑터 기반 공식 게임사 자체페이지 통합 수집.

        무인증 API/정적: 크래프톤(Greenhouse)·네오위즈(Lever)·카카오게임즈(greetinghr)·펄어비스(정적).
        잡코리아 우회: 넥슨·엔씨·넷마블·컴투스·웹젠·위메이드·데브시스터즈·스마일게이트.
        각 어댑터는 safe_fetch로 격리돼 한 회사 실패가 나머지 수집을 막지 않는다.
        """
        from src.scraper.ats.registry import build_official_adapters
        results = []
        self.last_run_adapters = []
        for adapter in build_official_adapters(session=self.session):
            jobs = adapter.safe_fetch()
            print(f"       · {adapter.company_name}: {len(jobs)}건")
            results.extend(jobs)
            self.last_run_adapters.append(adapter)
        return results
