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


class GameJobScraper:
    # 2026-07 개편: 구 검색 URL(List_GI/GI_Search_Keyword.asp)은 키워드를 무시하고
    # 전체 공고판 최신 40건으로 리다이렉트됨 → 재무 공고가 그 40건 안에 있을 때만
    # 우연히 수집되는 복불복(격일 0건 플랩의 근본 원인). 실제 검색은 joblist 페이지가
    # XHR로 호출하는 아래 POST 엔드포인트가 담당한다 (2026-07-09 브라우저 캡처로 확정).
    SEARCH_ENDPOINT = "https://www.gamejob.co.kr/Recruit/_GI_Job_List/"

    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.gamejob.co.kr/"
        }
        # 일시적 네트워크 오류 자동 재시도 + 커넥션 재사용
        self.session = make_session(headers=self.headers)

    def is_finance_job(self, title):
        """직무 타이틀이 핵심 재무/회계/세무/자금 카테고리에 속하는지 검증 (공통 필터 위임)"""
        return filters.is_finance_job(title)

    def is_valid_company_and_job(self, company_name, title):
        """카지노, 리조트, 단순 오락 업종 및 비사무직 직무 필터링 (람정 등 원천 차단)"""
        norm_company = (company_name or "").lower()
        norm_title = (title or "").lower()

        # 1. 회사명/업종 블랙리스트 검사
        for blocked_co in filters.COMPANY_BLACKLIST:
            if blocked_co in norm_company or blocked_co in norm_title:
                return False

        # 2. 직무명 블랙리스트 검사
        for blocked_title in filters.TITLE_BLACKLIST:
            if blocked_title in norm_title:
                return False

        return True

    @staticmethod
    def _build_search_payload(keyword, page=1):
        """joblist 페이지의 XHR과 동일한 폼 페이로드 (브라우저 실캡처 계약 그대로)"""
        return {
            "isDefault": "true",
            "condition[searchtype]": "all",
            "condition[searchstring]": keyword,  # UTF-8 그대로 (구 ASP의 EUC-KR 인코딩 불필요)
            "condition[menucode]": "",
            "condition[tabcode]": "1",
            "page": str(page),
            "direct": "0",
            "order": "1",
            "pagesize": "40",
            "tabcode": "1",
        }

    @staticmethod
    def _parse_row_deadline(row_text, today=None):
        """목록 행 텍스트의 마감 배지("~MM/DD"·"D-N"·상시 등) 환산 — 공용 파서 위임"""
        return parse_deadline_badge(row_text, today)

    @classmethod
    def _parse_search_rows(cls, fragment_html):
        """검색 결과 HTML 조각에서 (GI번호, 회사명, 제목, 마감일) 행 목록을 추출.

        조각 최상위가 div.jobListWrap이면 구조 정상. 컨테이너 자체가 없으면 마크업
        개편/차단으로 보고 None을 반환해 호출부가 '무음 0건'이 아닌 실패로 다루게 한다."""
        soup = BeautifulSoup(fragment_html, "html.parser")
        if not soup.select_one(".jobListWrap"):
            return None

        rows = []
        seen = set()
        for tr in soup.select("tr"):
            a_tag = tr.select_one("a[href*='GI_Read/View']")
            if not a_tag:
                continue
            m = re.search(r"GI_No=(\d+)", a_tag.get("href", ""))
            if not m or m.group(1) in seen:
                continue
            seen.add(m.group(1))

            title = a_tag.get_text(" ", strip=True)
            first_td = tr.select_one("td")
            company = first_td.get_text(" ", strip=True) if first_td else ""
            # 회사명 셀에 제목이 섞여 뽑히는 마크업 변형 방어: 제목과 같으면 비움
            if company == title:
                company = ""
            deadline = cls._parse_row_deadline(tr.get_text(" ", strip=True))
            rows.append({"gi_no": m.group(1), "company": company, "title": title, "deadline": deadline})
        return rows

    def scrape_finance_jobs(self, limit=15):
        """게임잡 재무·회계·세무·자금 키워드 수집 (신형 XHR 검색 엔드포인트 기반)"""
        results = []
        keywords = ["회계", "세무", "재무", "자금"]
        self.is_last_run_success = False
        success_connections = 0
        failed_errors = []
        detail_failures = 0        # 상세 실패했지만 목록 행으로 보존한 건수
        detail_unrecoverable = 0   # 목록 행도 부실해 보존조차 못 한 건수

        xhr_headers = dict(self.headers)
        xhr_headers["X-Requested-With"] = "XMLHttpRequest"
        xhr_headers["Referer"] = "https://www.gamejob.co.kr/Recruit/joblist?menucode=searchtot&searchtype=all"

        for keyword in keywords:
            time.sleep(random.uniform(1.0, 2.5))

            try:
                res = self.session.post(
                    self.SEARCH_ENDPOINT,
                    data=self._build_search_payload(keyword),
                    headers=xhr_headers,
                    timeout=15,
                )
                if res.status_code != 200:
                    failed_errors.append(f"HTTP {res.status_code}")
                    continue

                fragment = res.content.decode("utf-8", errors="replace")
                rows = self._parse_search_rows(fragment)
                if rows is None:
                    # 200이지만 목록 컨테이너가 없음 — 마크업 개편/차단. 무음 0건으로 넘기지 않는다.
                    failed_errors.append("검색 응답에서 jobListWrap 컨테이너 인식 실패 (마크업 개편 의심)")
                    continue
                success_connections += 1

                count = 0
                for row in rows:
                    if count >= limit:
                        break

                    gi_no = row["gi_no"]
                    job_id = f"gamejob_{gi_no}"
                    detail_url = f"https://www.gamejob.co.kr/Recruit/GI_Read/View?GI_No={gi_no}"

                    # 중복 적재 방지 (키워드 간 교차 중복)
                    if any(r["id"] == job_id for r in results):
                        continue

                    # 목록 단계 사전 필터 — 재무 직군이 아니거나 블랙리스트면 상세 요청 자체를 생략
                    if row["title"] and not self.is_finance_job(row["title"]):
                        continue
                    if not self.is_valid_company_and_job(row["company"], row["title"]):
                        continue

                    # 각 공고 상세 페이지 접속 및 정보 수집
                    time.sleep(random.uniform(0.5, 1.2))
                    detail_soup = None
                    try:
                        detail_res = self.session.get(detail_url, headers=self.headers, timeout=10)
                        if detail_res.status_code == 200:
                            detail_html = detail_res.content.decode("utf-8", errors="replace")
                            detail_soup = BeautifulSoup(detail_html, "html.parser")
                    except Exception:
                        detail_soup = None

                    if detail_soup is None:
                        # [상세 실패 보존] 예전에는 여기서 그냥 continue해 이 공고가 오늘 수집분에서
                        # 통째로 빠졌다. 그러면 delta_analyzer가 '오늘 안 보였다'며 기존 활성 공고를
                        # 즉시 마감 처리한다 — 소스는 '완전 성공'으로 보고되므로 부분 실패·0건·일괄
                        # 소멸 어느 방어선에도 안 걸린다(2026-07-21 GPT 3차 검토 지적).
                        # 목록 행만으로 최소 레코드를 만들어 ID를 오늘 수집분에 남긴다. 본문은
                        # 제목뿐이지만 upsert의 본문 축소 방지 가드가 기확보 상세요강을 지키므로
                        # 기존 공고의 분류값이 열화되지도 않는다.
                        # ※ 목록 행에 회사/제목이 없으면 최소 레코드조차 못 만드니, 그때는
                        #   소스를 부분 실패로 표시해 이 소스의 마감 판정 자체를 보류시킨다.
                        if not row["company"] or not row["title"]:
                            detail_unrecoverable += 1
                            continue
                        results.append({
                            "id": job_id,
                            "source": "gamejob",
                            "company_name": row["company"],
                            "title": row["title"],
                            "origin_url": detail_url,
                            "location": "서울/경기",
                            "posted_at": datetime.now(KST).strftime("%Y-%m-%d"),
                            "status": "ACTIVE",
                            "raw_html": row["title"],
                            "first_seen_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
                            "last_updated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
                            "deadline": row["deadline"],
                        })
                        count += 1
                        detail_failures += 1
                        continue

                    try:

                        # 회사명·제목은 목록 행이 1차 소스 — 상세 <title>의 첫 대괄호는 회사명이
                        # 아니라 '[전략실]' '[Finance Div.]' 같은 부서명인 공고가 많아(2026-07-09 실측)
                        # 회사명 오염을 일으킨다. 목록 행의 회사 컬럼이 실제 게시 회사다.
                        company_name = row["company"] or "게임회사"
                        title = row["title"] or "재무 회계 담당자"

                        # 목록 행 값이 비었을 때만 상세 <title> '[회사명] 공고제목' 패턴으로 폴백
                        if not row["company"] or not row["title"]:
                            page_title = detail_soup.title.text.strip() if detail_soup.title else ""
                            match = re.search(r"\[(.*?)\]\s*(.*)", page_title)
                            if match:
                                if not row["company"]:
                                    company_name = match.group(1).strip()
                                if not row["title"]:
                                    title = match.group(2).strip()
                                    if title.endswith("- 게임잡"):
                                        title = title[:-8].strip()

                        # 직무 필터링: 반드시 재무/회계/세무 직군이어야만 승인 (상세 제목 기준 최종 방어선)
                        if not self.is_finance_job(title):
                            continue

                        # 기업 및 직무 블랙리스트 엄격 필터링 (람정, 카지노, 딜러 등)
                        if not self.is_valid_company_and_job(company_name, title):
                            continue

                        # 공고 본문 내용
                        desc_container = detail_soup.select_one(".tbList") or detail_soup.select_one(".viewCol") or detail_soup.select_one("body")
                        full_desc = desc_container.get_text(separator="\n").strip() if desc_container else title

                        posting = {
                            "id": job_id,
                            "source": "gamejob",
                            "company_name": company_name,
                            "title": title,
                            "origin_url": detail_url,
                            "location": "서울/경기",
                            "posted_at": datetime.now(KST).strftime("%Y-%m-%d"),
                            "status": "ACTIVE",
                            "raw_html": full_desc,
                            "first_seen_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
                            "last_updated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
                            "deadline": row["deadline"],  # 목록 행 "~MM/DD"/"D-N" 환산값 (상시는 None)
                        }
                        results.append(posting)
                        count += 1

                    except Exception:
                        continue

            except Exception as e:
                failed_errors.append(str(e))
                continue

        if success_connections == 0 and failed_errors:
            raise RuntimeError(f"게임잡 수집 연결 완전히 실패 (IP 차단/WAF/마크업 개편): {', '.join(set(failed_errors))}")

        self.is_last_run_success = True
        # [부분 실패 표시] 검색 키워드 일부만 통과했으면 '이 소스를 오늘 다 훑었다'고
        # 볼 수 없다. 성공으로 넘기면 delta_analyzer가 소스를 신뢰해, 막힌 키워드로만
        # 잡히던 기존 활성 공고를 즉시 CLOSED 처리한다(2026-07-21 코덱스 교차검토 지적).
        # 마감 판정만 보류시키고 수집분은 그대로 쓴다.
        if detail_failures or detail_unrecoverable:
            print(f"    [WARN] 게임잡 상세 실패 {detail_failures + detail_unrecoverable}건 "
                  f"(목록 행으로 보존 {detail_failures}건 / 보존 불가 {detail_unrecoverable}건)")
        # 보존조차 못 한 건이 있으면 '이 소스를 다 훑었다'고 볼 수 없다 → 마감 판정 보류
        self.is_last_run_partial = bool(failed_errors) or detail_unrecoverable > 0
        unique_postings = {}
        for item in results:
            unique_postings[item["id"]] = item

        return list(unique_postings.values())
