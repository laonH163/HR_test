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
from src.utils.known_blocks import (KNOWN_BLOCKED_SOURCES, ZOMBIE_ALERT_DAYS,
                                    blocked_since, describe, split_known_blocked)

# 잡코리아 공고 상세 URL에서 GI번호(공고 고유번호) 추출용 — 정의는 jobkorea_detail이 원본
from src.scraper.jobkorea_detail import GI_READ_RE as JOBKOREA_GI_RE


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

    # 8-2c. [부분 실패 소스] — 검색 키워드 일부만 통과한 플랫폼.
    #  '성공'으로 넘기면 delta_analyzer가 '오늘 이 소스를 다 훑었다'고 신뢰해, 막힌 키워드로만
    #  잡히던 기존 활성 공고를 오늘 결과에 없다는 이유로 즉시 마감 처리한다. 0건 가드는
    #  '수집 0건'만 잡으므로 키워드 1개라도 통과하면 그 방어선을 그냥 지나간다
    #  (2026-07-21 코덱스 교차검토 지적). 수집분은 그대로 쓰되 마감 판정만 보류시킨다.
    partial_sources = set()
    for name, scraper in [("wanted", wanted), ("saramin", saramin),
                          ("jobkorea", jobkorea), ("gamejob", gamejob)]:
        if getattr(scraper, "is_last_run_success", False) and getattr(scraper, "is_last_run_partial", False):
            partial_sources.add(name)
    if partial_sources:
        print(f"    [HOLD] 검색 일부만 성공한 소스 — 마감 판정 보류: {', '.join(sorted(partial_sources))}")

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

    # [알려진 차단 분리] — 새 IP로 바꿔도 어차피 막히는 소스는 재시도 대상이 아니다.
    # 원티드가 매일 실패하는 바람에 매일 파이프라인이 통째로 두 번 돌고 있었다
    # (당일 통계 이중 합산의 상시 원인). 수집 시도 자체는 그대로 해서 차단이 풀리면
    # 자동 복구·자동 감지되게 두고, '재시도 예약'과 '경고 표시'에서만 뺀다.
    known_blocked_failed, retry_targets = split_known_blocked(failed_sources)
    if known_blocked_failed:
        print(f"    [INFO] 알려진 차단 소스(재시도 제외): {', '.join(known_blocked_failed)}")

    # [실패 마커 기록] — CI가 새 러너(새 IP)로 2차 시도할지 판단하는 게이트 파일.
    # IP 차단은 러너 단위로 걸려 같은 프로세스 안의 재시도로는 복구되지 않는다(2026-07-02 run48 실측).
    failed_marker = os.path.join("data", "last_failed_sources.txt")
    # 마커 기록이 실패하면 2차 실행이 예약되지 않는다. 그런데 아래 발송 보류는
    # '2차가 최종 브리핑을 보낸다'는 전제 위에 서 있어, 마커가 없으면 보류만 하고
    # 아무도 안 보내는 완전 무음이 된다(2026-07-22 코덱스 교차검토 지적).
    # → 기록 실패 시 보류 전제를 포기하고 이번 실행이 직접 발송하도록 표시한다.
    retry_marker_ok = True
    try:
        if retry_targets:
            # 임시 파일에 다 쓴 뒤 원자적으로 교체한다. 곧바로 최종 경로에 쓰다가 중간에
            # 실패하면 '내용이 일부 남은 마커'가 생겨, 1차가 직접 발송하는데 2차도 예약돼
            # 브리핑이 두 통 간다(코덱스 지적).
            tmp_marker = failed_marker + ".tmp"
            with open(tmp_marker, "w", encoding="utf-8") as f:
                f.write("\n".join(retry_targets) + "\n")
            os.replace(tmp_marker, failed_marker)
        elif os.path.exists(failed_marker):
            os.remove(failed_marker)
    except Exception as e:
        retry_marker_ok = False
        print(f"    [WARN] 실패 마커 기록 실패 — 2차 실행 예약 불가로 보고 이번 실행이 "
              f"직접 브리핑을 발송한다: {e}", file=sys.stderr)
        # 반쯤 남은 마커가 2차를 부르면 중복 발송이 되므로 최선 노력으로 지운다
        for leftover in (failed_marker + ".tmp", failed_marker):
            try:
                if os.path.exists(leftover):
                    os.remove(leftover)
            except Exception:
                pass

    # 8-2c. [잡코리아 GI 중복 병합] — 검색·기업페이지 이중 수집분을 DB 적재 전에 정리
    all_postings = dedupe_jobkorea_gi(all_postings)

    # 8-2d. [잡코리아 GI 본문 보강] — 상세요강 iframe(SSR)에서 JD 텍스트 확보.
    #       제목만 수집된 GI 공고의 자격요건·우대사항을 채워 분류 정확도를 올린다.
    #       실패해도 치명적이지 않음(제목 기반 현행 유지).
    try:
        from src.scraper.jobkorea_detail import enrich_gi_postings
        enriched_count = enrich_gi_postings(all_postings, db_manager)
        if enriched_count:
            print(f"    [ENRICH] 잡코리아 GI 상세요강 신규 확보: {enriched_count}건")
    except Exception as e:
        print(f"    [WARN] GI 본문 보강 실패(제목 기반으로 진행): {e}", file=sys.stderr)

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
    db_load_failures = 0
    # 파이프라인 필수 단계가 조용히 실패하면(예외를 출력만 하고 계속 진행) 잡은 성공으로
    # 끝나 크래시 알림도 안 뜬다. 실패한 단계를 모아 🩺 수집 상태에 노출한다(코덱스 지적).
    pipeline_errors = []
    today_ids = set()
    deadline_changes = []  # 마감일 연장/단축 상세 (텔레그램 '마감일 변경' 섹션용)

    for posting in all_postings:
        try:
            today_ids.add(posting["id"])
            # 마스터 공고 Upsert
            is_modified, is_new = db_manager.upsert_job_posting(posting)
            if is_new:
                newly_added += 1
            elif is_modified:
                modified_count += 1
                # 마감일이 실제로 바뀐 공고(연장/단축)는 변경 전후를 브리핑에 노출
                change = db_manager.last_change_details or {}
                if change.get("deadline_from"):
                    deadline_changes.append({
                        "company_name": posting["company_name"],
                        "title": posting["title"],
                        "origin_url": posting["origin_url"],
                        "old": change["deadline_from"],
                        "new": change["deadline_to"],
                    })

            # 실시간 정밀 분류 및 categories 테이블 적재
            category_data = classifier.analyze_and_classify(posting)
            db_manager.upsert_job_category(category_data)

        except Exception as e:
            # 여기서 삼키면 '수집은 됐는데 저장은 하나도 안 된' 상태가 정상처럼 보인다.
            # source_counts는 적재 전 all_postings로 세므로 0건 경고도 안 뜨고, 알려진
            # 차단은 '복구됐다'고까지 판단한다(코덱스 지적) → 건수를 세어 브리핑에 노출한다.
            db_load_failures += 1
            print(f"    [ERR] DB 적재 및 분류 에러 ({posting['id']}): {e}", file=sys.stderr)
            traceback.print_exc()

    if db_load_failures:
        pipeline_errors.append(f"DB 적재/분류 실패 {db_load_failures}건")

    # 10. Delta Analyzer 연동 (마감 CLOSED 상태 갱신)
    #     0건 플랫폼은 검색 오동작 의심 소스로 전달 — 해당 소스 공고의 마감 오판(플랩)을 막는다.
    print("\n[-] Delta Analyzer 가동: 수집 종료된 마감 공고 선별 중...")
    closed_count = 0
    try:
        if today_ids:
            closed_count, closed_details = analyzer.analyze_closed_postings(
                today_ids, successful_sources,
                suspect_sources=set(zero_platforms) | partial_sources,
                collected_counts=dict(source_counts))
            for closed in closed_details:
                print(f"    -> 마감 감지 완료: [{closed['company_name']}] {closed['title']}")
        print(f"    -> 마감 공고 처리 결과: 총 {closed_count} 건 종료 감지")
    except Exception as e:
        # 마감 판정이 통째로 안 돌면 이미 마감된 공고가 계속 활성으로 남는다(좀비).
        # 잡은 성공으로 끝나므로 여기서 알리지 않으면 아무도 모른다(코덱스 지적).
        pipeline_errors.append("마감 판정(Delta) 실패")
        print(f"    [ERR] Delta 분석 실패: {e}", file=sys.stderr)

    # 11. 실행 이력 로그 수립 — 실패 소스가 있으면 error_log에 기록해 무음 실패를 남기지 않는다.
    #     is_success는 '실행 자체의 유효성' 기준: 성공 소스가 하나도 없으면 0(전면 실패).
    try:
        error_parts = []
        if failed_sources:
            error_parts.append("수집 실패 소스: " + ", ".join(sorted(set(failed_sources))))
        if zero_platforms:
            error_parts.append("0건 플랫폼(점검 필요): " + ", ".join(zero_platforms))
        if partial_sources:
            # 사후에 '그날 어느 소스가 부분 실패였나'를 조회할 수 있어야 한다 —
            # 마감 보류가 며칠 이어지면 좀비 ACTIVE가 쌓이는데, 기록이 없으면 추적 불가.
            error_parts.append("검색 일부 실패(마감 보류): " + ", ".join(sorted(partial_sources)))
        log_entry = {
            "run_date": datetime.now(KST).strftime("%Y-%m-%d"),
            "newly_added": newly_added,
            "modified_count": modified_count,
            "closed_count": closed_count,
            "is_success": 1 if successful_sources else 0,
            "error_log": "; ".join(error_parts) if error_parts else None,
            "source_counts": dict(source_counts),  # 소스별 수집 건수 (급감 감지 기준선)
            "successful_sources": sorted(successful_sources)  # 하루 기준 경고 보정용
        }
        db_manager.insert_scrape_log(log_entry)
        print("[OK] 수집 이력 로그 적재 완료.")
    except Exception as e:
        print(f"    [ERR] 수집 로그 적재 실패: {e}", file=sys.stderr)

    # 11-b. 재공고(🔁) 판별용 CLOSED 이력 — 대시보드·텔레그램이 공유 (쿼리 1회)
    try:
        closed_history = db_manager.get_closed_key_history()
    except Exception:
        closed_history = None

    # 12. [Milestone 3] HTML 정적 대시보드 리포트 생성 가동
    print("\n[-] HTML 대시보드 생성기(Milestone 3) 가동 중...")
    try:
        total_html_jobs = reporter.generate_dashboard(closed_history=closed_history)
        print(f"    -> HTML 대시보드 빌드 성공: 총 {total_html_jobs}건 활성 적재")
    except Exception as e:
        # 대시보드가 안 갱신되면 DB와 화면이 어긋난 채로 브리핑은 계속 링크를 안내한다.
        pipeline_errors.append("대시보드 생성 실패")
        print(f"    [ERR] HTML 대시보드 생성 실패: {e}", file=sys.stderr)

    # 13. [Milestone 4] 프라이빗 텔레그램 데일리 요약 발송 가동
    #     CI 1차 시도에서 실패 소스가 있으면(SUPPRESS_ALERT_ON_SOURCE_FAILURE=1) 발송을 보류하고,
    #     새 러너(새 IP)의 재시도 실행이 최종 결과를 발송한다 — 같은 날 2통 중복 방지.
    #     ※ 판정 기준은 failed_sources가 아니라 retry_targets다. 알려진 차단 소스는 재시도
    #       마커에 안 들어가 2차 실행이 애초에 예약되지 않으므로, 그걸로 보류했다가는
    #       발송할 실행이 아무도 없어 브리핑이 통째로 사라진다.
    if retry_targets and retry_marker_ok and os.getenv("SUPPRESS_ALERT_ON_SOURCE_FAILURE") == "1":
        print("\n[-] 실패 소스 감지 → 텔레그램 발송 보류 (새 러너 재시도 실행이 최종 발송)")
        print("\n==================================================")
        print(f"[1차 시도 종료] 신규 추가: {newly_added}건 | 변동 수정: {modified_count}건 | 마감 완료: {closed_count}건 | 실패 소스: {len(retry_targets)}곳")
        print("==================================================")
        return

    print("\n[-] 프라이빗 텔레그램 알림 발송(Milestone 4) 가동 중...")

    # 13-a. [하루 기준 경고 보정] 최종 브리핑은 재시도 실행이 보내므로, 이번 시도가
    #       실패한 소스라도 오늘 다른 시도에서 이미 확보됐다면 경고 대상이 아니다.
    #       (2026-07-16 실측: 1차가 잡코리아 전부 정상 수집했는데 재시도 러너만 IP 차단
    #        → '24곳 접속 실패' 오경보 발송. 경고의 의미는 '오늘 자료 미확보'여야 한다.)
    #       ※ 데이터 보호 가드(마감 보류 등)는 시도별 보수 판정 그대로 — 표시만 보정.
    today_str = datetime.now(KST).strftime("%Y-%m-%d")
    try:
        sources_ok_today = db_manager.get_sources_succeeded_today(today_str)
    except Exception:
        sources_ok_today = set()
    # '검색 0건' 경고의 보정 기준은 접속 성공이 아니라 **실제 수집**이어야 한다.
    # 접속 성공을 기준으로 삼으면 '접속은 되는데 0건'인 소스가 제 손으로 자기 경고를
    # 지워 '전 소스 정상'이 찍힌다 — 과거 11회 실재한 상태이고(run 49~55의 원티드·게임잡),
    # 그게 바로 검색이 죽어가던 시점이었다(2026-07-22 코덱스 교차검토 지적).
    try:
        sources_collected_today = db_manager.get_sources_collected_today(today_str)
    except Exception:
        sources_collected_today = set()
    display_failed_sources = sorted(set(failed_sources) - sources_ok_today)
    display_zero_platforms = [s for s in zero_platforms if s not in sources_collected_today]
    recovered = ((set(failed_sources) & sources_ok_today)
                 | (set(zero_platforms) & sources_collected_today))
    if recovered:
        print(f"    [INFO] 오늘 타 시도에서 이미 확보된 소스는 경고 제외: {', '.join(sorted(recovered))}")

    # 13-b. [알려진 차단 표시 분리] 고칠 방법이 없는 차단을 매일 경고로 띄우면 경고 전체가
    #       무뎌진다. 평소엔 정보 한 줄로 내리되 ① 복구되면 즉시 알리고 ② 차단이
    #       ZOMBIE_ALERT_DAYS 넘게 이어지면 다시 경고로 올린다(마감 보류로 보호되는 활성
    #       공고가 실제로는 마감된 좀비일 수 있어 사람 확인이 필요해지는 시점).
    known_blocked_display, display_failed_sources = split_known_blocked(display_failed_sources)
    known_blocked_zero, display_zero_platforms = split_known_blocked(display_zero_platforms)
    known_blocked_notes = []
    for src in sorted(set(known_blocked_display) | set(known_blocked_zero)):
        try:
            last_ok = db_manager.get_last_collected_date(src)
        except Exception:
            last_ok = None
        # 수집 이력이 아예 없으면(DB 교체·로그 정리) 등록된 차단 시작일을 기준으로 센다.
        # 이 폴백이 없으면 days=None → stale=False로 굳어 좀비 경고가 영원히 안 뜬다.
        basis = last_ok or blocked_since(src)
        days = None
        if basis:
            try:
                days = (datetime.now(KST).date() - datetime.strptime(basis, "%Y-%m-%d").date()).days
            except Exception:
                days = None
        # 지킬 공고가 남아 있을 때만 경고로 승격한다. 활성 0건이면 '마감됐는지 확인하라'는
        # 말 자체가 성립하지 않고, 매일 반복되면 그 경고가 다시 소음이 된다.
        # 조회가 실패했을 때 0으로 단정하면 '지킬 게 없다'며 경고를 지워버린다.
        # 모르는 상태는 보수적으로 '있을 수 있다'로 다룬다(코덱스 지적).
        try:
            active_n = db_manager.get_active_count_by_source(src)
        except Exception:
            active_n = None
        known_blocked_notes.append({
            "source": src,
            "summary": describe(src) or "알려진 차단",
            "last_success": last_ok,
            "days": days,
            "active_count": active_n,
            "stale": days is not None and days >= ZOMBIE_ALERT_DAYS and active_n != 0,
        })
    if known_blocked_notes:
        # ※ f-string 안에 같은 따옴표를 중첩하면 Python 3.11에서 SyntaxError다(CI가 3.11)
        # ※ stale(경고 승격)인 항목까지 '경고 아님'으로 찍으면 로그로 상태를 진단할 때
        #   실제와 반대로 보인다(코덱스 지적) — 두 부류를 나눠서 출력한다.
        def _fmt(n):
            return "{}({}일째, 활성 {}건)".format(
                n["source"], n["days"], "?" if n["active_count"] is None else n["active_count"])
        info_notes = [n for n in known_blocked_notes if not n["stale"]]
        stale_notes = [n for n in known_blocked_notes if n["stale"]]
        if info_notes:
            print(f"    [INFO] 알려진 차단(경고 아님): {', '.join(_fmt(n) for n in info_notes)}")
        if stale_notes:
            print(f"    [WARN] 알려진 차단 장기화 — 수동 확인 필요: "
                  f"{', '.join(_fmt(n) for n in stale_notes)}", file=sys.stderr)

    # 알려진 차단 소스가 다시 수집되면 표에서 지워야 하므로 눈에 띄게 알린다(자동 복구 감지).
    # 판정 기준은 '오늘 실제로 공고를 가져왔는가'다 — 접속 성공만으로 복구라고 하면
    # '접속은 되는데 0건'(검색 열화)을 복구로 오인해 정반대 신호를 보낸다.
    recovered_known = []
    for src in KNOWN_BLOCKED_SOURCES:
        try:
            if db_manager.get_last_collected_date(src) == today_str:
                recovered_known.append(src)
        except Exception as e:
            # 조용히 넘기면 '차단이 풀렸다'는 전이 자체가 유실된다 — 그 소스는 실패·0건
            # 목록에도 없어 브리핑이 '전 소스 정상'으로 끝난다(코덱스 지적).
            pipeline_errors.append(f"{src} 복구 여부 확인 실패")
            print(f"    [WARN] {src} 복구 판정 조회 실패: {e}", file=sys.stderr)
    recovered_known.sort()
    # 복구를 알린 소스는 정보 줄을 겹쳐 내보내지 않는다 — 같은 소스에 '해제됐다'와
    # '감시 중'이 나란히 찍히면 신호가 서로 부딪힌다(간헐적으로 뚫리는 날 발생).
    known_blocked_notes = [n for n in known_blocked_notes if n["source"] not in set(recovered_known)]

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
            failed_sources=display_failed_sources, zero_platforms=display_zero_platforms,
            known_blocked=known_blocked_notes, recovered_known=recovered_known,
            pipeline_errors=pipeline_errors,
            known_companies=known_companies,
            mass_close_held=getattr(analyzer, "last_mass_close_held", []),
            source_drops=source_drops,
            deadline_changes=deadline_changes,
            closed_history=closed_history,
            partial_sources=sorted(partial_sources)
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
