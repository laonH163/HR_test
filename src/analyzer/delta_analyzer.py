import sqlite3
from datetime import date

from src.utils.timeutil import now_kst_str, today_kst_str

# 마감 확정에 필요한 '미관측 증거일' 수 — 오늘 + 공정한 미관측일 (CLOSE_GRACE_DAYS - 1)일.
# 검색 결과가 실행마다 출렁여 공고가 하루 빠졌다 돌아오는 플랩(2026-07-22 실측:
# 사람인 run 77에서 3건이 마감 1분 뒤 부활)을 막는다.
# '공정한 미관측일' = 그 소스가 정상 동작했는데도 공고가 안 보인 실행일
# (db_manager.count_fair_miss_days). 달력일로 세면 주말·공휴일·소스 실패일이
# 유예를 소진해 월요일 첫 검색 누락만으로 즉시 마감된다(코덱스 지적) — 실행이
# 없던 날은 증거가 아니다. 같은 날 재실행 누락(관측일=오늘)은 어떤 경우에도 마감 금지.
# 대가: 진짜 마감의 감지·알림이 정상 운영 기준 1일(실행 공백만큼 더) 늦어진다.
CLOSE_GRACE_DAYS = 2

class DeltaAnalyzer:
    def __init__(self, db_manager):
        self.db_manager = db_manager

    def analyze_closed_postings(self, today_scraped_ids, successful_sources=None, suspect_sources=None, collected_counts=None, run_date=None):
        """
        오늘 수집된 고유 ID셋(today_scraped_ids)에 속하지 않으면서,
        현재 DB 내에 'ACTIVE' 상태인 채용공고들을 찾아 'CLOSED'로 자동 마킹 처리.
        단, 수집 성공한 출처(successful_sources) 목록에 포함된 소스의 공고만 마감 처리(차단/실패 방어).

        suspect_sources: '성공했지만 수집 0건'인 플랫폼 검색 소스 집합.
        재무 키워드 4종 검색이 전부 0건인 것은 공고 전멸보다 검색 오동작·soft 차단일
        개연성이 훨씬 높아(실측: 게임잡이 격일로 0건↔수집을 반복하며 같은 공고가
        마감↔부활 플랩, 원티드는 한 달간 0건) 해당 소스 공고는 마감 판정을 보류한다.

        collected_counts: {source: 오늘 수집 건수}. 기업 어댑터의 '일괄 소멸' 방어용 —
        ① 한 소스의 기존 활성 공고가 2건 이상인데 오늘 0건 수집이면, 또는
        ② 여러 소스(4곳 이상)가 같은 날 동시에 전멸하면(잡코리아 계열 마크업 개편처럼
        도메인 단위 사고의 전형) 사이트 개편 의심으로 그 소스 마감을 보류한다.
        보류된 소스 목록은 self.last_mass_close_held로 노출된다(경고 표시용).
        공고 1건짜리 소스가 정상적으로 마감되는 일상 케이스는 그대로 마감된다.

        run_date: 'YYYY-MM-DD'. 마감 유예(연속 미관측 일수) 계산 기준일 —
        파이프라인이 시작 시 확정한 날짜를 넘긴다. 생략하면 오늘(KST).
        """
        self.last_mass_close_held = []
        self.last_grace_held = 0
        run_date = run_date or today_kst_str()

        # [관측 스탬프] 오늘 수집된 공고의 last_seen_date를 먼저 기록한다.
        # 3건 미만 보류로 조기 반환하는 날에도 '본 것'은 남겨야, 다음 날 유예 계산이
        # 실제 관측 이력 위에서 돈다.
        if today_scraped_ids:
            self.db_manager.mark_postings_seen(today_scraped_ids, run_date)
        # [안전 장치] 만약 오늘 전체 수집된 건수가 비정상적으로 적은 경우(예: 3건 미만),
        # 크롤러가 네트워크 지연이나 WAF 차단으로 수집을 정상적으로 완수하지 못한 오류 상황으로 간주하고,
        # 기존 유효 공고가 대거 마감되는 오작동을 방지하기 위해 마감 처리를 전면 보류(Skip)합니다.
        if len(today_scraped_ids) < 3:
            print("    [WARN] 오늘 수집된 공고 수가 너무 적어(3건 미만) 크롤링 누락으로 판단됩니다. 마감 처리를 보류합니다.")
            return 0, []

        conn = self.db_manager.get_connection()
        cursor = conn.cursor()

        # 1. 현재 DB에 저장된 활성 공고 조회
        cursor.execute("SELECT id, source, company_name, title, last_seen_date FROM job_postings WHERE status = 'ACTIVE'")
        active_jobs = cursor.fetchall()

        try:
            run_day = date.fromisoformat(run_date)
        except ValueError:
            run_day = None  # 기준일이 손상되면 유예 판정 불가 — 아래에서 전부 보류(보수적)

        # (source, 마지막 관측일)별 공정 미관측일 수 캐시 — 공고마다 DB를 다시 읽지 않는다
        fair_miss_cache = {}

        closed_count = 0
        closed_details = []
        held_by_suspect = 0

        # [일괄 소멸 가드] 소스별 활성 건수를 세어, '성공했는데 0건 수집 + 활성 다수' 소스를 찾는다
        mass_close_held = set()
        if collected_counts is not None:
            active_by_source = {}
            for job in active_jobs:
                active_by_source[job["source"]] = active_by_source.get(job["source"], 0) + 1
            zeroed = [
                s for s, n in active_by_source.items()
                if collected_counts.get(s, 0) == 0
                and (successful_sources is None or s in successful_sources)  # 실패 소스는 기존 방어선이 담당
                and not (suspect_sources and s in suspect_sources)           # 플랫폼 0건 보류와 중복 방지
            ]
            # ① 활성 2건 이상이 한 번에 전부 사라지는 소스는 개편 의심
            mass_close_held = {s for s in zeroed if active_by_source[s] >= 2}
            # ② 4곳 이상 동시 전멸은 도메인 단위 사고 의심 — 1건짜리 소스까지 전부 보류
            if len(zeroed) >= 4:
                mass_close_held = set(zeroed)
        self.last_mass_close_held = sorted(mass_close_held)

        # 2. 오늘 수집 대상에서 누락된 건 식별
        for job in active_jobs:
            job_id = job["id"]
            source = job["source"]

            # 성공적으로 완료된 수집 소스 리스트가 지정되어 있고, 이 공고의 소스가 거기에 없으면 마감 처리를 건너뜀 (안전 방어선)
            if successful_sources is not None and source not in successful_sources:
                continue

            # '성공 + 0건' 소스는 검색 오동작 의심 — 이 소스 공고의 마감 판정 보류 (플랩 방지)
            if suspect_sources and source in suspect_sources:
                if job_id not in today_scraped_ids:
                    held_by_suspect += 1
                continue

            # [일괄 소멸 가드] 개편 의심 소스의 공고도 마감 보류
            if source in mass_close_held:
                held_by_suspect += 1
                continue

            if job_id not in today_scraped_ids:
                # [마감 유예] 오늘 미관측 + 마지막 관측일 이후 '공정한 미관측일'이
                # (CLOSE_GRACE_DAYS - 1)일 이상 쌓여야 마감을 확정한다.
                # 검색 결과 변동으로 하루 빠졌다 돌아오는 공고(사람인 플랩)의
                # 마감 오보·부활 반복을 막는다. 같은 날 재실행 누락은 항상 보류.
                last_seen = job["last_seen_date"]
                days_missed = None
                if run_day is not None and last_seen:
                    try:
                        days_missed = (run_day - date.fromisoformat(last_seen)).days
                    except ValueError:
                        days_missed = None  # 손상된 관측일 — 아래에서 오늘로 재기록(자가 복구)
                if days_missed is None or days_missed < 0:
                    # 관측 이력이 없거나(컬럼 도입 전 데이터) 손상·미래 날짜 — 오늘을
                    # 기점으로 유예를 새로 시작한다. 즉시 마감보다 보수적인 쪽.
                    # 미래 날짜를 그대로 두면 그 날짜가 지날 때까지 마감이 봉쇄된다(코덱스 지적).
                    cursor.execute(
                        "UPDATE job_postings SET last_seen_date = ? WHERE id = ?",
                        (run_date, job_id))
                    self.last_grace_held += 1
                    continue
                if days_missed == 0:
                    # 오늘 앞선 실행에서 관측됨 — 같은 날 플랩, 무조건 보류
                    self.last_grace_held += 1
                    continue
                cache_key = (source, last_seen)
                if cache_key not in fair_miss_cache:
                    fair_miss_cache[cache_key] = self.db_manager.count_fair_miss_days(
                        source, last_seen, run_date)
                if fair_miss_cache[cache_key] < CLOSE_GRACE_DAYS - 1:
                    self.last_grace_held += 1
                    continue

                # 상태를 'CLOSED'로 변경하고 업데이트 시각 기재
                cursor.execute("""
                    UPDATE job_postings
                    SET status = 'CLOSED', last_updated_at = ?
                    WHERE id = ?
                """, (now_kst_str(), job_id))

                closed_count += 1
                closed_details.append({
                    "id": job_id,
                    "company_name": job["company_name"],
                    "title": job["title"]
                })

        conn.commit()
        conn.close()

        if held_by_suspect:
            held_srcs = sorted(set(suspect_sources or [])) + self.last_mass_close_held
            print(f"    [HOLD] 오동작 의심 소스의 기존 공고 {held_by_suspect}건 마감 보류 ({', '.join(held_srcs)})")
        if self.last_grace_held:
            # 정상 동작(플랩 방어)이라 경고가 아니라 정보다 — 연속 미관측이
            # CLOSE_GRACE_DAYS에 도달하면 다음 실행에서 자연히 마감된다.
            print(f"    [HOLD] 미관측 {CLOSE_GRACE_DAYS}일 미만 공고 {self.last_grace_held}건 마감 유예 (플랩 방어)")

        return closed_count, closed_details
