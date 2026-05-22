import argparse
import sys
from datetime import datetime
from pytimekr import pytimekr  # 한국 공휴일 완벽 방어용 라이브러리
from src.database.db_manager import DBManager
from src.scraper.wanted_scraper import WantedScraper
from src.scraper.saramin_scraper import SaraminScraper
from src.scraper.jobkorea_scraper import JobKoreaScraper
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

    # 4. 넥슨 수집
    print("[-] 넥슨(Nexon) 공식 채용공고 수집 중...")
    try:
        nexon_jobs = companies.scrape_nexon_finance_jobs()
        print(f"    -> 넥슨 공식 수집 성공: {len(nexon_jobs)} 건 발굴")
        all_postings.extend(nexon_jobs)
    except Exception as e:
        print(f"    [ERR] 넥슨 공식 수집 실패: {e}", file=sys.stderr)

    # 5. 크래프톤 수집
    print("[-] 크래프톤(Krafton) 공식 채용공고 수집 중...")
    try:
        krafton_jobs = companies.scrape_krafton_finance_jobs()
        print(f"    -> 크래프톤 공식 수집 성공: {len(krafton_jobs)} 건 발굴")
        all_postings.extend(krafton_jobs)
    except Exception as e:
        print(f"    [ERR] 크래프톤 공식 수집 실패: {e}", file=sys.stderr)

    # 6. 엔씨소프트 수집
    print("[-] 엔씨소프트(NCSOFT) 공식 채용공고 수집 중...")
    try:
        ncsoft_jobs = companies.scrape_ncsoft_finance_jobs()
        print(f"    -> 엔씨소프트 공식 수집 성공: {len(ncsoft_jobs)} 건 발굴")
        all_postings.extend(ncsoft_jobs)
    except Exception as e:
        print(f"    [ERR] 엔씨소프트 공식 수집 실패: {e}", file=sys.stderr)

    # 7. 넷마블 수집
    print("[-] 넷마블(Netmarble) 공식 채용공고 수집 중...")
    try:
        netmarble_jobs = companies.scrape_netmarble_finance_jobs()
        print(f"    -> 넷마블 공식 수집 성공: {len(netmarble_jobs)} 건 발굴")
        all_postings.extend(netmarble_jobs)
    except Exception as e:
        print(f"    [ERR] 넷마블 공식 수집 실패: {e}", file=sys.stderr)

    # 8. 스마일게이트 수집
    print("[-] 스마일게이트(Smilegate) 공식 채용공고 수집 중...")
    try:
        smilegate_jobs = companies.scrape_smilegate_finance_jobs()
        print(f"    -> 스마일게이트 공식 수집 성공: {len(smilegate_jobs)} 건 발굴")
        all_postings.extend(smilegate_jobs)
    except Exception as e:
        print(f"    [ERR] 스마일게이트 공식 수집 실패: {e}", file=sys.stderr)

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
            "run_date": datetime.today().strftime("%Y-%m-%d"),
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

        # 텔레그램 마크다운 메세지 빌딩
        briefing_text = telegram.build_daily_briefing_message(
            newly_added, modified_count, closed_count, active_postings
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
        today = datetime.today()
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
