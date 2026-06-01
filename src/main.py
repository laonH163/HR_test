import argparse
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

def run_scraping_phase():
    """Milestone 1 & 2: 멀티 소스 공고 수집, 정밀 하이브리드 분류 및 델타 변동 분석"""
    print("==================================================")
    print("[Milestone 1 & 2] 채용공고 수집 및 하이브리드 정밀 분류 파이프라인 개시")
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

    # 1. 원티드 수집
    print("[-] 원티드(Wanted) 채용 정보 수집 중...")
    try:
        wanted_jobs = wanted.scrape_finance_jobs()
        print(f"    -> 원티드 수집 성공: {len(wanted_jobs)} 건 발굴")
        all_postings.extend(wanted_jobs)
    except Exception as e:
        print(f"    [ERR] 원티드 수집 실패: {e}", file=sys.stderr)

    # 2. 사람인 수집
    print("[-] 사람인(Saramin) 채용 정보 수집 중...")
    try:
        saramin_jobs = saramin.scrape_finance_jobs()
        print(f"    -> 사람인 수집 성공: {len(saramin_jobs)} 건 발굴")
        all_postings.extend(saramin_jobs)
    except Exception as e:
        print(f"    [ERR] 사람인 수집 실패: {e}", file=sys.stderr)

    # 3. 잡코리아 수집
    print("[-] 잡코리아(JobKorea) 채용 정보 수집 중...")
    try:
        jobkorea_jobs = jobkorea.scrape_finance_jobs()
        print(f"    -> 잡코리아 수집 성공: {len(jobkorea_jobs)} 건 발굴")
        all_postings.extend(jobkorea_jobs)
    except Exception as e:
        print(f"    [ERR] 잡코리아 수집 실패: {e}", file=sys.stderr)

    # 3-1. 게임잡 수집
    print("[-] 게임잡(GameJob) 채용 정보 수집 중...")
    try:
        gamejob_jobs = gamejob.scrape_finance_jobs()
        print(f"    -> 게임잡 수집 성공: {len(gamejob_jobs)} 건 발굴")
        all_postings.extend(gamejob_jobs)
    except Exception as e:
        print(f"    [ERR] 게임잡 수집 실패: {e}", file=sys.stderr)

    # 4~8. 공식 게임사 자체 채용페이지 (ATS 어댑터로 통합)
    #   크래프톤(Greenhouse)·네오위즈(Lever)·카카오게임즈(greetinghr)·펄어비스(정적).
    #   기존 넥슨/엔씨/넷마블/스마일게이트의 채용 도메인은 폐기·이전된 것으로 라이브 확인되어,
    #   잡코리아 기업페이지 우회로 별도 단계에서 보강 예정.
    print("[-] 공식 게임사 자체 채용페이지(ATS 어댑터) 수집 중...")
    try:
        official_jobs = companies.scrape_official_adapters()
        print(f"    -> 공식 자체페이지 수집 성공: {len(official_jobs)} 건 발굴")
        all_postings.extend(official_jobs)
    except Exception as e:
        print(f"    [ERR] 공식 자체페이지 수집 실패: {e}", file=sys.stderr)

    # 8-1. 시프트업 수집
    print("[-] 시프트업(ShiftUp) 공식 채용공고 수집 중...")
    try:
        shiftup_jobs = companies.scrape_shiftup_finance_jobs()
        print(f"    -> 시프트업 공식 수집 성공: {len(shiftup_jobs)} 건 발굴")
        all_postings.extend(shiftup_jobs)
    except Exception as e:
        print(f"    [ERR] 시프트업 공식 수집 실패: {e}", file=sys.stderr)

    # 8-2. [헬스체크] 소스별 수집 건수 점검 — 항상 공고가 있는 플랫폼이 0건이면 스크래퍼 점검 신호.
    #   (게임사 자체수집 0건은 단순 '공고 없음'일 수 있어 경고 대상에서 제외)
    from collections import Counter
    source_counts = Counter(p["source"] for p in all_postings)
    print(f"\n[헬스체크] 소스별 수집 건수: {dict(source_counts)}")
    platform_sources = ["wanted", "saramin", "jobkorea", "gamejob"]
    zero_platforms = [s for s in platform_sources if source_counts.get(s, 0) == 0]
    if zero_platforms:
        print(f"    [WARN] 플랫폼 소스 0건 감지(스크래퍼 점검 필요): {', '.join(zero_platforms)}", file=sys.stderr)

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
    print("\n[-] Delta Analyzer 가동: 수집 종료된 마감 공고 선별 중...")
    closed_count = 0
    try:
        if today_ids:
            closed_count, closed_details = analyzer.analyze_closed_postings(today_ids)
            for closed in closed_details:
                print(f"    -> 마감 감지 완료: [{closed['company_name']}] {closed['title']}")
        print(f"    -> 마감 공고 처리 결과: 총 {closed_count} 건 종료 감지")
    except Exception as e:
        print(f"    [ERR] Delta 분석 실패: {e}", file=sys.stderr)

    # 11. 실행 이력 로그 수립
    try:
        log_entry = {
            "run_date": datetime.now(KST).strftime("%Y-%m-%d"),
            "newly_added": newly_added,
            "modified_count": modified_count,
            "closed_count": closed_count,
            "is_success": 1,
            "error_log": None
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

        # 텔레그램 마크다운 메세지 빌딩
        briefing_text = telegram.build_daily_briefing_message(
            newly_added, modified_count, closed_count, active_postings, weekly_trend
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
