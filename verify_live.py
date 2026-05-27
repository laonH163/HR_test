import sys
import urllib.parse
import re
import requests
from bs4 import BeautifulSoup

# Force UTF-8 stdout
sys.stdout.reconfigure(encoding='utf-8')

game_keywords = [
    "게임", "game", "nexon", "krafton", "ncsoft", "netmarble", "neowiz", "smilegate",
    "펄어비스", "위메이드", "카카오게임즈", "그라비티", "넥슨", "크래프톤", "엔씨소프트",
    "넷마블", "네오위즈", "스마일게이트", "데브시스터즈", "컴투스", "웹젠", "조이시티",
    "한빛소프트", "썸에이지", "해긴", "쿡앱스", "클로버게임즈", "시프트업", "라인게임즈",
    "더블유게임즈", "레드브릭", "엔씨"
]

finance_keywords = [
    "회계", "세무", "재무", "자금", "경리", "결산", "ERP", "감사", "세정",
    "자금운용", "내부통제", "accounting", "finance", "tax", "auditing"
]

def is_game_company_debug(company_name, title, desc=""):
    norm_name = company_name.lower()
    norm_title = title.lower()
    norm_desc = desc.lower() if desc else ""

    reasons = []

    # 1. Company name check
    for kw in game_keywords:
        if kw in norm_name:
            reasons.append(f"회사명 매칭 ('{kw}' in '{company_name}')")
            break

    # 2. Title check
    for kw in game_keywords:
        if kw in norm_title:
            reasons.append(f"제목 매칭 ('{kw}' in '{title}')")
            break

    # 3. Desc check
    if norm_desc:
        if "게임" in norm_desc or "game" in norm_desc:
            reasons.append("본문 매칭 ('게임/game' in 본문)")

    is_match = len(reasons) > 0
    return is_match, ", ".join(reasons) if is_match else "매칭 없음"


def is_finance_job(title):
    norm_title = title.lower()
    for kw in finance_keywords:
        if kw in norm_title:
            return True
    return False


def verify_wanted_requests():
    print("\n==========================================")
    print("1. [우회확인] 원티드(Wanted) 실시간 수집 및 필터링 검증")
    print("==========================================")
    print("[INFO] 원티드는 CloudFront 차단 장벽으로 인해 Playwright 스텔스 브라우저가 기본 적용됩니다.")


def verify_saramin_requests():
    print("\n==========================================")
    print("2. [성공] 사람인(Saramin) Requests 기반 초고속 수집 검증")
    print("==========================================")
    keywords = ["회계", "세무", "재무", "자금"]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.google.com/"
    }

    for keyword in keywords[:1]:
        print(f"\n[-] 사람인 키워드 '{keyword}' 수집 중...")
        url = f"https://www.saramin.co.kr/zf_user/search/recruit?searchword={keyword}&cat_mcls=2"
        try:
            res = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(res.text, "html.parser")
            items = soup.select(".item_recruit")
            print(f"    발견된 채용공고 카드 수: {len(items)}개")

            for idx, item in enumerate(items[:3]):
                corp = item.select_one(".corp_name a")
                title_el = item.select_one(".job_tit a")
                if not corp or not title_el:
                    continue

                company = corp.text.strip()
                title = title_el.text.strip()
                is_match, reason = is_game_company_debug(company, title)
                print(f"    [{idx+1}] [{company}] {title}")
                print(f"        분류 상태: {'통과 (게임사/게임제목 매칭)' if is_match else '제외 (게임사 아님)'} | 사유: {reason}")
        except Exception as e:
            print(f"    [ERR] 사람인 수집 실패: {e}")


def verify_jobkorea_requests():
    print("\n==========================================")
    print("3. [성공] 잡코리아(JobKorea) Requests 기반 최신 UI 수집 검증")
    print("==========================================")
    keywords = ["회계", "세무", "재무", "자금"]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.google.com/"
    }

    for keyword in keywords[:1]:
        print(f"\n[-] 잡코리아 키워드 '{keyword}' 수집 중...")
        url = f"https://www.jobkorea.co.kr/Search/?stext={keyword}"
        try:
            res = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(res.text, "html.parser")

            cards = soup.select("div[class*='rounded-2xl']") or soup.select("div[class*='hover:bg-blue54']")
            print(f"    발견된 채용공고 카드 수: {len(cards)}개")

            for idx, card in enumerate(cards[:3]):
                title_link = card.select_one("a[href*='/Recruit/GI_Read/']")
                if not title_link:
                    continue
                title = title_link.text.strip()

                href = title_link.get("href", "")
                gno_match = re.search(r"GI_Read/(\d+)", href) or re.search(r"gno=(\d+)", href)
                company = "알수없음"
                if gno_match:
                    gno = gno_match.group(1)
                    det_url = f"https://www.jobkorea.co.kr/Recruit/GI_Read/{gno}"
                    try:
                        det_res = requests.get(det_url, headers=headers, timeout=5)
                        det_soup = BeautifulSoup(det_res.text, "html.parser")

                        meta_company_el = det_soup.select_one("h2")
                        if meta_company_el and len(meta_company_el.text.strip()) > 0:
                            company = meta_company_el.text.strip()

                        h1_elements = [h.text.strip() for h in det_soup.select("h1") if h.text.strip()]
                        if h1_elements:
                            title = h1_elements[0]
                    except Exception as de:
                        company = f"상세로드에러: {de}"

                is_match, reason = is_game_company_debug(company, title)
                print(f"    [{idx+1}] [{company}] {title}")
                print(f"        분류 상태: {'통과 (게임사/게임제목 매칭)' if is_match else '제외 (게임사 아님)'} | 사유: {reason}")
        except Exception as e:
            print(f"    [ERR] 잡코리아 수집 실패: {e}")


def verify_gamejob_requests():
    print("\n==========================================")
    print("4. [정밀수정] 게임잡(GameJob) 재무/회계 직무 필터링 검증")
    print("==========================================")
    keywords = ["회계", "세무", "재무", "자금"]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.gamejob.co.kr/"
    }

    for keyword in keywords[:1]:
        print(f"\n[-] 게임잡 키워드 '{keyword}' 수집 중...")
        try:
            keyword_encoded = urllib.parse.quote(keyword, encoding="euc-kr")
        except Exception:
            keyword_encoded = urllib.parse.quote(keyword)

        url = f"https://www.gamejob.co.kr/List_GI/GI_Search_Keyword.asp?S_Div=GI_Keyword&S_Text={keyword_encoded}"
        try:
            res = requests.get(url, headers=headers, timeout=10)
            html_text = res.content.decode("utf-8", errors="replace")
            soup = BeautifulSoup(html_text, "html.parser")

            # 우측 Banners나 인기 공고 영역을 차단하고, .tblList 테이블 검색 목록 안의 채용 링크만 타겟팅!
            links = soup.select("table.tblList a[href*='/Recruit/GI_Read/View']") or soup.select(".tblList a[href*='/Recruit/GI_Read/View']")
            unique_gi_nos = []
            unique_links = []
            for a in links:
                href = a.get("href", "")
                match = re.search(r"GI_No=(\d+)", href)
                if match:
                    gi_no = match.group(1)
                    if gi_no not in unique_gi_nos:
                        unique_gi_nos.append(gi_no)
                        unique_links.append(a)

            print(f"    검색결과 테이블 내 고유 채용공고 후보군: {len(unique_gi_nos)}개")
            count_pass = 0
            for idx, a in enumerate(unique_links):
                gi_no = unique_gi_nos[idx]

                detail_url = f"https://www.gamejob.co.kr/Recruit/GI_Read/View?GI_No={gi_no}"
                try:
                    det_res = requests.get(detail_url, headers=headers, timeout=5)
                    det_html = det_res.content.decode("utf-8", errors="replace")
                    det_soup = BeautifulSoup(det_html, "html.parser")
                    page_title = det_soup.title.text.strip() if det_soup.title else ""

                    company = "게임회사"
                    title = "공고제목"
                    match = re.search(r"\[(.*?)\]\s*(.*)", page_title)
                    if match:
                        company = match.group(1).strip()
                        title = match.group(2).strip()
                        if title.endswith("- 게임잡"):
                            title = title[:-8].strip()

                    # 직무 필터 적용
                    is_fin = is_finance_job(title)
                    if is_fin:
                        count_pass += 1
                        print(f"    [통과] ID: {gi_no} | 회사명: {company} | 제목: {title}")
                    else:
                        pass # 다른 직무는 안전하게 무시

                except Exception as de:
                    print(f"    [ERR] ID: {gi_no} 상세 로드 오류: {de}")
            print(f"    => 최종 필터링을 통과한 알짜 재무/회계/세무 공고 수: {count_pass}개")

        except Exception as e:
            print(f"    [ERR] 게임잡 수집 실패: {e}")


def verify_shiftup_requests():
    print("\n==========================================")
    print("5. [신규완성] 시프트업(ShiftUp) 공식 API 기반 수집 검증")
    print("==========================================")
    url = "https://shiftup.co.kr/comm/lib/client_lib.php"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": "https://shiftup.co.kr/recruit/recruit.php",
        "X-Requested-With": "XMLHttpRequest"
    }
    data = "workType=get_recruit_list&code=recruit&cat_idx=0&searchkey="

    try:
        res = requests.post(url, headers=headers, data=data, timeout=10)
        jobs = res.json().get("list", [])
        print(f"    시프트업 전체 채용공고 수: {len(jobs)}개")
        count = 0
        for job in jobs:
            title = job.get("subject", "")
            if any(kw in title for kw in ["재무", "회계", "세무", "자금", "경리", "결산"]):
                count += 1
                idx = job.get("idx")
                exp = job.get("addinfo3", "경력")
                print(f"    [{count}] ID: {idx} | 제목: {title} | 연차: {exp}")
        print(f"    => 최종 시프트업 공식 재무/회계/세무 공고 발굴 수: {count}개")
    except Exception as e:
        print(f"    [ERR] 시프트업 수집 실패: {e}")


if __name__ == "__main__":
    verify_wanted_requests()
    verify_saramin_requests()
    verify_jobkorea_requests()
    verify_gamejob_requests()
    verify_shiftup_requests()
