import argparse
import os
import re
import sys
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo  # KST 고정 (GitHub Actions UTC 러너 대응)
from pytimekr import pytimekr  # 한국 공휴일 완벽 방어용 라이브러리

# 모든 날짜/시간 판정의 기준 타임존 (러너가 UTC여도 한국 기준으로 동작)
KST = ZoneInfo("Asia/Seoul")
from src.database.db_manager import DBManager
from src.scraper.wanted_scraper import WantedScraper
from src.scraper.saramin_scraper import SaraminScraper
from src.scraper.jobkorea_scraper import JobKoreaScraper
from src.scraper.gamejob_scraper import GameJobScraper
from src.scraper.company_scrapers import CompanyScrapers
from src.classifier.hybrid_engine import HybridClassificationEngine
from src.analyzer.delta_analyzer import DeltaAnalyzer
from src.reporter.html_generator import HTMLGenerator
from src.reporter.telegram_sender import TelegramSender

# 잡코리아 공고 상세 URL에서 GI번호(공고 고유번호) 추출용
JOBKOREA_GI_RE = re.compile(r"jobkorea\.co\.kr/Recruit/GI_Read/(\d+)")


def dedupe_jobkorea_gi(postings):
    """잡코리아 검색 스크래퍼(id=jobkorea_N)와 기업페이지 어댑터(id={회사}_N)가
    같은 공고(GI번호 동일)를 서로 다른 id로 이중 수집하는 것을 병합한다.

    기업페이지 어댑터 수집분은 회사명 교차검증(가드레일)을 거쳐 회사 귀속이 정확하므로
    그쪽을 우선하고, 검색 수집분(source='jobkorea')을 폐기한다.
    (실측: 넥슨게임즈/네오플처럼 검색 상세페이지 h2 파싱이 회사명을 다르게 잡아
     클라이언트 dedup 키가 어긋나 대시보드에 이중 노출되던 문제의 근본 교정)
    """
    by_gi = {}
    deduped = []
    dropped = 0
    for p in postings:
        m = JOBKOREA_GI_RE.search(p.get("origin_url") or "")
        if not m:
            deduped.append(p)
            continue
        gi = m.group(1)
        if gi not in by_gi:
            by_gi[gi] = len(deduped)
            deduped.append(p)
            continue
        kept = deduped[by_gi[gi]]
        if kept["source"] == "jobkorea" and p["source"] != "jobkorea":
            deduped[by_gi[gi]] = p
        dropped += 1
    if dropped:
        print(f"    [DEDUP] 잡코리아 GI번호 중복 {dropped}건 병합 (기업페이지 어댑터 우선)")
    return deduped


def run_scraping_phase():
    """Milestone 1 & 2: 멀티 소스 공고 수집, 정밀 하이브리드 분류 및 델타 변동 분석"""
    print("==================================================")
    print("[Milestone 1 & 2 & 5] 채용공고 병렬 수집 및 하이브리드 정밀 분류 파이프라인 개시")
    print("==================================================")

    db_manager = DBManager()
    wanted = WantedScraper()
    saramin = SaraminScraper()
    jobkorea = JobKoreaScraper()
    gamejob = GameJobScraper()
    companies = CompanyScrapers()
    classifier = HybridClassificationEngine()
    analyzer = DeltaAnalyzer(db_manager)
    reporter = HTMLGenerator(db_manager)
    telegram = TelegramSender()

    all_postings = []

    # [안전 재시도 데코레이터 함수] - WAF, 임시 커넥션 불안정 시 최대 3회 재시도 (수집 누락 원천 방어)
    def fetch_with_retry(scraper_func, scraper_name, max_retries=3):
        import time, random
        for attempt in range(1, max_retries + 1):
            try:
                jobs = scraper_func()
                print(f"    -> {scraper_name} 수집 성공: {len(jobs)} 건 발굴")
                return jobs
            except Exception as e:
                print(f"    [WARN] {scraper_name} 수집 시도 {attempt}/{max_retries} 실패: {e}", file=sys.stderr)
                if attempt == max_retries:
                    print(f"    [ERR] {scraper_name} 수집 최종 실패", file=sys.stderr)
                    return []
                time.sleep(random.uniform(2.0, 5.0))
        return []

    # 1. 원티드 수집 (Wanted) - Playwright 기반이므로 Thread-safety 보장을 위해 동기식(메인 스레드)에서 우선 구동
    print("[-] 원티드(Wanted) 채용 정보 수집 중 (메인 스레드)...")
    wanted_jobs = fetch_with_retry(wanted.scrape_finance_jobs, "원티드")
    all_postings.extend(wanted_jobs)

    # 2. 나머지 스크래퍼 병렬 구동 (Saramin, JobKorea, GameJob, Official ATS, ShiftUp)
    # ThreadPoolExecutor를 사용해 requests 기반 동기 대기 시간을 병렬화
    parallel_tasks = {
        "사람인": saramin.scrape_finance_jobs,
        "잡코리아": jobkorea.scrape_finance_jobs,
        "게임잡": gamejob.scrape_finance_jobs,
        "공식자체 ATS 어댑터": companies.scrape_official_adapters,
        "시프트업": companies.scrape_shiftup_finance_jobs
    }

    print("\n[-] requests 기반 스크래퍼 병렬 수집 개시 (ThreadPoolExecutor)...")
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=min(len(parallel_tasks), 4)) as executor:
        futures = {
            executor.submit(fetch_with_retry, func, name): name
            for name, func in parallel_tasks.items()
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                jobs = future.result()
                all_postings.extend(jobs)
            except Exception as e:
                print(f"    [ERR] {name} 스레드 구동 실패: {e}", file=sys.stderr)

    # 8-2. [성공한 수집 출처(Source) 수집] — 차단/네트워크 오류로 실패한 소스의 기존 공고를 보존하기 위함
    successful_sources = set()
    if getattr(wanted, "is_last_run_success", False):
        successful_sources.add("wanted")
    if getattr(saramin, "is_last_run_success", False):
        successful_sources.add("saramin")
    if getattr(jobkorea, "is_last_run_success", False):
        successful_sources.add("jobkorea")
    if getattr(gamejob, "is_last_run_success", False):
        successful_sources.add("gamejob")
    if getattr(companies, "shiftup_last_run_success", False):
        successful_sources.add("shiftup")
    if hasattr(companies, "last_run_adapters"):
        for adapter in companies.last_run_adapters:
            if getattr(adapter, "is_last_run_success", False):
                successful_sources.add(adapter.source)

    # 8-2b. [실패 소스 집계] — 재시도 소진 후에도 실패한 소스를 로그·알림으로 가시화
    failed_sources = []
    for name, scraper in [("wanted", wanted), ("saramin", saramin),
                          ("jobkorea", jobkorea), ("gamejob", gamejob)]:
        if not getattr(scraper, "is_last_run_success", False):
            failed_sources.append(name)
    if not getattr(companies, "shiftup_last_run_success", False):
        failed_sources.append("shiftup")
    if hasattr(companies, "last_run_adapters"):
        for adapter in companies.last_run_adapters:
            if not getattr(adapter, "is_last_run_success", False):
                failed_sources.append(adapter.source)
    else:
        failed_sources.append("official_ats(전체)")

    # [실패 마커 기록] — CI가 새 러너(새 IP)로 2차 시도할지 판단하는 게이트 파일.
    # IP 차단은 러너 단위로 걸려 같은 프로세스 안의 재시도로는 복구되지 않는다(2026-07-02 run48 실측).
    failed_marker = os.path.join("data", "last_failed_sources.txt")
    try:
        if failed_sources:
            with open(failed_marker, "w", encoding="utf-8") as f:
                f.write("\n".join(sorted(set(failed_sources))) + "\n")
        elif os.path.exists(failed_marker):
            os.remove(failed_marker)
    except Exception as e:
        print(f"    [WARN] 실패 마커 기록 실패: {e}", file=sys.stderr)

    # 8-2c. [잡코리아 GI 중복 병합] — 검색·기업페이지 이중 수집분을 DB 적재 전에 정리
    all_postings = dedupe_jobkorea_gi(all_postings)

    # 8-3. [헬스체크] 소스별 수집 건수 점검 — 항상 공고가 있는 플랫폼이 0건이면 스크래퍼 점검 신호.
    #   (게임사 자체수집 0건은 단순 '공고 없음'일 수 있어 경고 대상에서 제외)
    from collections import Counter
    source_counts = Counter(p["source"] for p in all_postings)
    print(f"\n[헬스체크] 소스별 수집 건수: {dict(source_counts)}")
    print(f"[헬스체크] 성공적으로 완료된 수집 출처 목록: {sorted(list(successful_sources))}")
    platform_sources = ["wanted", "saramin", "jobkorea", "gamejob"]
    zero_platforms = [s for s in platform_sources if source_counts.get(s, 0) == 0]
    if zero_platforms:
        print(f"    [WARN] 플랫폼 소스 0건 감지(스크래퍼 점검 필요): {', '.join(zero_platforms)}", file=sys.stderr)

    # 8-4. [수집량 급감 감지] — 오늘 로그를 적재하기 전의 이력(=어제까지)과 비교.
    #      플랫폼이 7일 평균 대비 30% 미만이면 검색 열화 의심(서서히 죽는 소스 조기 발견).
    #      0건은 별도의 '0건 플랫폼' 경고가 담당하므로 여기서 제외한다.
    source_drops = {}
    try:
        history = db_manager.get_recent_source_counts(7)
        for s in platform_sources:
            past = history.get(s, [])
            if len(past) >= 3:
                avg = sum(past) / len(past)
                today_n = source_counts.get(s, 0)
                if avg >= 3 and 0 < today_n < avg * 0.3:
                    source_drops[s] = {"today": today_n, "avg": avg}
                    print(f"    [WARN] {s} 수집량 급감: 오늘 {today_n}건 (최근 평균 {avg:.1f}건)", file=sys.stderr)
    except Exception as e:
        print(f"    [WARN] 수집량 추세 비교 실패: {e}", file=sys.stderr)

    # 9. DB 적재 및 정밀 하이브리드 분류
    print("\n[-] SQLite 데이터베이스 마스터 적재 및 정밀 분류 가동 중...")
    newly_added = 0
    modified_count = 0
    today_ids = set()

    for posting in all_postings:
        try:
            today_ids.add(posting["id"])
            # 마스터 공고 Upsert
            is_modified, is_new = db_manager.upsert_job_posting(posting)
            if is_new:
                newly_added += 1
            elif is_modified:
                modified_count += 1

            # 실시간 정밀 분류 및 categories 테이블 적재
            category_data = classifier.analyze_and_classify(posting)
            db_manager.upsert_job_category(category_data)

        except Exception as e:
            print(f"    [ERR] DB 적재 및 분류 에러 ({posting['id']}): {e}", file=sys.stderr)
            traceback.print_exc()

    # 10. Delta Analyzer 연동 (마감 CLOSED 상태 갱신)
    #     0건 플랫폼은 검색 오동작 의심 소스로 전달 — 해당 소스 공고의 마감 오판(플랩)을 막는다.
    print("\n[-] Delta Analyzer 가동: 수집 종료된 마감 공고 선별 중...")
    closed_count = 0
    try:
        if today_ids:
            closed_count, closed_details = analyzer.analyze_closed_postings(
                today_ids, successful_sources, suspect_sources=set(zero_platforms),
                collected_counts=dict(source_counts))
            for closed in closed_details:
                print(f"    -> 마감 감지 완료: [{closed['company_name']}] {closed['title']}")
        print(f"    -> 마감 공고 처리 결과: 총 {closed_count} 건 종료 감지")
    except Exception as e:
        print(f"    [ERR] Delta 분석 실패: {e}", file=sys.stderr)

    # 11. 실행 이력 로그 수립 — 실패 소스가 있으면 error_log에 기록해 무음 실패를 남기지 않는다.
    #     is_success는 '실행 자체의 유효성' 기준: 성공 소스가 하나도 없으면 0(전면 실패).
    try:
        error_parts = []
        if failed_sources:
            error_parts.append("수집 실패 소스: " + ", ".join(sorted(set(failed_sources))))
        if zero_platforms:
            error_parts.append("0건 플랫폼(점검 필요): " + ", ".join(zero_platforms))
        log_entry = {
            "run_date": datetime.now(KST).strftime("%Y-%m-%d"),
            "newly_added": newly_added,
            "modified_count": modified_count,
            "closed_count": closed_count,
            "is_success": 1 if successful_sources else 0,
            "error_log": "; ".join(error_parts) if error_parts else None,
            "source_counts": dict(source_counts)  # 소스별 수집 건수 (급감 감지 기준선)
        }
        db_manager.insert_scrape_log(log_entry)
        print("[OK] 수집 이력 로그 적재 완료.")
    except Exception as e:
        print(f"    [ERR] 수집 로그 적재 실패: {e}", file=sys.stderr)

    # 12. [Milestone 3] HTML 정적 대시보드 리포트 생성 가동
    print("\n[-] HTML 대시보드 생성기(Milestone 3) 가동 중...")
    try:
        total_html_jobs = reporter.generate_dashboard()
        print(f"    -> HTML 대시보드 빌드 성공: 총 {total_html_jobs}건 활성 적재")
    except Exception as e:
        print(f"    [ERR] HTML 대시보드 생성 실패: {e}", file=sys.stderr)

    # 13. [Milestone 4] 프라이빗 텔레그램 데일리 요약 발송 가동
    #     CI 1차 시도에서 실패 소스가 있으면(SUPPRESS_ALERT_ON_SOURCE_FAILURE=1) 발송을 보류하고,
    #     새 러너(새 IP)의 재시도 실행이 최종 결과를 발송한다 — 같은 날 2통 중복 방지.
    if failed_sources and os.getenv("SUPPRESS_ALERT_ON_SOURCE_FAILURE") == "1":
        print("\n[-] 실패 소스 감지 → 텔레그램 발송 보류 (새 러너 재시도 실행이 최종 발송)")
        print("\n==================================================")
        print(f"[1차 시도 종료] 신규 추가: {newly_added}건 | 변동 수정: {modified_count}건 | 마감 완료: {closed_count}건 | 실패 소스: {len(set(failed_sources))}곳")
        print("==================================================")
        return

    print("\n[-] 프라이빗 텔레그램 알림 발송(Milestone 4) 가동 중...")
    try:
        # 데이터베이스 전체 활성 데이터 조회
        active_postings_rows = db_manager.get_all_active_postings()
        active_postings = [dict(r) for r in active_postings_rows]

        # 최근 7일 수집 추세를 함께 실어 발송 (조회 실패 시 None으로 안전 폴백)
        try:
            weekly_trend = db_manager.get_recent_scrape_stats(7)
        except Exception:
            weekly_trend = None

        # 신규 진입사(🆕) 판별용 — 오늘 이전에 이력이 있던 회사 목록 (실패 시 배지 생략)
        try:
            known_companies = db_manager.get_companies_seen_before(datetime.now(KST).strftime("%Y-%m-%d"))
        except Exception:
            known_companies = None

        # 텔레그램 마크다운 메세지 빌딩 (실패·0건·일괄소멸·급감 경고 포함)
        briefing_text = telegram.build_daily_briefing_message(
            newly_added, modified_count, closed_count, active_postings, weekly_trend,
            failed_sources=failed_sources, zero_platforms=zero_platforms,
            known_companies=known_companies,
            mass_close_held=getattr(analyzer, "last_mass_close_held", []),
            source_drops=source_drops
        )

        # 최종 메시지 봇 발송
        telegram.send_formatted_message(briefing_text)
    except Exception as e:
        print(f"    [ERR] 텔레그램 요약 발송 실패: {e}", file=sys.stderr)

    print("\n==================================================")
    print(f"[Milestone 1, 2, 3, 4 E2E 통합 완료] 신규 추가: {newly_added}건 | 변동 수정: {modified_count}건 | 마감 완료: {closed_count}건")
    print("==================================================")

def main():
    parser = argparse.ArgumentParser(description="GameFinanceScraper CLI")
    parser.add_argument(
        "--mode",
        choices=["all", "scrap", "classify", "report"],
        default="scrap",
        help="실행 모드 (기본값: scrap)"
    )
    # 수동 디버깅 등 강제 실행 옵션 지원
    parser.add_argument(
        "--force",
        action="store_true",
        help="주말/공휴일 감지 가드를 우회하여 즉시 강제 수집 실행"
    )

    args = parser.parse_args()

    # 주말 및 한국 공휴일 자동 가드 체크 (force 옵션이 없을 때만 작동)
    if not args.force:
        today = datetime.now(KST)
        # 1. 주말 체크 (5=토요일, 6=일요일)
        if today.weekday() in [5, 6]:
            print(f"📢 [SKIP] 오늘은 주말({today.strftime('%A')})입니다. 수집과 알림을 모두 건너뜁니다.")
            sys.exit(0)

        # 2. 한국 법정 공휴일 체크 (pytimekr 라이브러리 연동)
        try:
            holidays = pytimekr.holidays(today.year)
            # 오늘 날짜가 공휴일 목록에 포함되는지 검사 (date 타입 매칭)
            if today.date() in holidays:
                print(f"📢 [SKIP] 오늘은 대한민국 법정 공휴일({today.strftime('%Y-%m-%d')})입니다. 수집과 알림을 건너뜁니다.")
                sys.exit(0)
        except Exception as e:
            # 혹시 라이브러리 조회 실패 시 수집이 아예 멈추는 걸 예방하기 위한 안전 통과
            print(f"    [WARN] 공휴일 판정기 API 조회 실패: {e}. 일반 평일로 간주하고 진행합니다.")

    if args.mode == "scrap" or args.mode == "all":
        run_scraping_phase()
    elif args.mode == "report":
        print("[-] 단독 모드: HTML 대시보드 리포트 즉시 생성 개시...")
        try:
            db_manager = DBManager()
            reporter = HTMLGenerator(db_manager)
            total = reporter.generate_dashboard()
            print(f"[OK] 대시보드 리포트 단독 생성 완료 (총 {total}건)")
        except Exception as e:
            print(f"[ERR] 대시보드 단독 생성 실패: {e}", file=sys.stderr)
    else:
        print(f"ℹ️ '{args.mode}' 모드는 추후 지원 예정입니다.")

if __name__ == "__main__":
    main()
