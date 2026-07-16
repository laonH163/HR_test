"""잡코리아 GI 상세요강 본문(iframe) 수집기.

GI 상세(/Recruit/GI_Read/{gno})는 React SPA라 정적 HTML에도, 렌더링된 DOM에도
JD 텍스트가 없다 — 그러나 상세요강은 별도 iframe
(/Recruit/GI_Read_Comt_Ifrm?Gno={gno})에 **서버 렌더링(SSR)** 으로 들어 있어
일반 requests로 확보할 수 있다(2026-07-16 라이브 누적 13/13건 성공:
스마일게이트·넷마블·웹젠·펄어비스·시프트업·잡코리아 검색 수집분,
담당업무·자격요건·우대사항 텍스트 415~1,359자).
※ 과거 '이미지 JD라 OCR 없이는 불가' 결론(2026-07-09)은 이 iframe 경로를
  확인하지 못한 것이었다. 상세요강이 진짜 이미지뿐인 공고는 텍스트가 짧아
  품질 게이트에서 걸러지고, 기존처럼 제목 기반으로 남는다(악화 없음).

파이프라인 후처리(enrich_gi_postings)로 '제목만 수집된' GI 공고의 본문을
보강한다. 실패는 치명적이지 않다 — 보강 실패 시 현행(제목 기반) 그대로 진행.
"""
import random
import re
import sys
import time

from bs4 import BeautifulSoup

from src.scraper.ats.base import DEFAULT_HEADERS
from src.utils.http import make_session
from src.utils.jdtext import has_jd_markers

# 잡코리아 GI 상세 URL에서 공고 고유번호 추출 (gamejob.co.kr의 GI_Read/View는 별개 경로).
# main.dedupe_jobkorea_gi도 이 정규식을 import해 쓴다 — URL 스킴 개편 시 한 곳만 수정.
GI_READ_RE = re.compile(r"jobkorea\.co\.kr/Recruit/GI_Read/(\d+)")

IFRAME_URL = "https://www.jobkorea.co.kr/Recruit/GI_Read_Comt_Ifrm?Gno={gno}"

# 품질 게이트: 이보다 짧으면 본문이 아니라 안내문구/이미지 JD 껍데기로 판정
MIN_BODY_LEN = 120


def html_to_text(raw_html):
    """iframe HTML을 줄 구조를 보존한 평문으로 변환.

    분류기(hybrid_engine)의 자격요건/우대사항 불릿 파싱이 줄 단위로 동작하므로
    get_text(separator=개행)로 줄 구조를 살린다. script/style은 제거.
    """
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in soup.get_text(separator="\n").split("\n")]
    return "\n".join(ln for ln in lines if ln)


def fetch_gi_body(gno, session=None, timeout=12):
    """GI 공고 하나의 상세요강 텍스트를 반환. 확보 실패/품질 미달이면 None."""
    sess = session or make_session(headers=DEFAULT_HEADERS)
    url = IFRAME_URL.format(gno=gno)
    res = sess.get(url, headers={"Referer": f"https://www.jobkorea.co.kr/Recruit/GI_Read/{gno}"},
                   timeout=timeout)
    if res.status_code != 200:
        return None
    text = html_to_text(res.text)
    # 품질 게이트: 섹션 헤더(자격요건 등)가 있고 최소 길이를 넘는 진짜 본문만 채택
    if len(text) < MIN_BODY_LEN or not has_jd_markers(text):
        return None
    return text


def enrich_gi_postings(postings, db_manager, cap=12, fetcher=fetch_gi_body, sleeper=time.sleep):
    """제목만 수집된 잡코리아 GI 공고들의 raw_html을 상세요강 텍스트로 보강한다.

    - DB에 이미 본문이 확보된 공고는 재요청 없이 저장본을 실어 준다
      (오늘 수집분이 제목뿐이어도 upsert가 본문 변경으로 오판하지 않도록).
    - 신규 요청은 cap 건으로 제한 + 요청 간 지터 — 차단 리스크 관리.
    - 반환값: 새로 본문을 확보한 건수.
    """
    candidates = []
    for p in postings:
        m = GI_READ_RE.search(p.get("origin_url") or "")
        if m and not has_jd_markers(p.get("raw_html") or ""):
            candidates.append((p, m.group(1)))
    if not candidates:
        return 0

    try:
        existing_map = db_manager.get_raw_html_map([p["id"] for p, _ in candidates])
    except Exception:
        existing_map = {}

    session = make_session(headers=DEFAULT_HEADERS)
    fetched = 0
    enriched = 0
    for p, gno in candidates:
        stored = existing_map.get(p["id"])
        if stored and has_jd_markers(stored):
            p["raw_html"] = stored  # 기확보 본문 보존 (재요청·MODIFIED 플랩 방지)
            continue
        if fetched >= cap:
            continue
        fetched += 1
        try:
            body = fetcher(gno, session=session)
        except Exception as e:
            print(f"    [WARN] GI 본문 요청 실패 ({p['id']}): {e}", file=sys.stderr)
            body = None
        sleeper(random.uniform(0.6, 1.2))
        if body:
            p["raw_html"] = f"{p['title']}\n{body}"
            enriched += 1
            # 로그에 em-dash(U+2014) 금지 — Windows cp949 콘솔에서 UnicodeEncodeError
            print(f"    [ENRICH] [{p['company_name']}] {p['title']} : 상세요강 {len(body)}자 확보")
    return enriched
