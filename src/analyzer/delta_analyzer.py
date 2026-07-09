import sqlite3

from src.utils.timeutil import now_kst_str

class DeltaAnalyzer:
    def __init__(self, db_manager):
        self.db_manager = db_manager

    def analyze_closed_postings(self, today_scraped_ids, successful_sources=None, suspect_sources=None):
        """
        오늘 수집된 고유 ID셋(today_scraped_ids)에 속하지 않으면서,
        현재 DB 내에 'ACTIVE' 상태인 채용공고들을 찾아 'CLOSED'로 자동 마킹 처리.
        단, 수집 성공한 출처(successful_sources) 목록에 포함된 소스의 공고만 마감 처리(차단/실패 방어).

        suspect_sources: '성공했지만 수집 0건'인 플랫폼 검색 소스 집합.
        재무 키워드 4종 검색이 전부 0건인 것은 공고 전멸보다 검색 오동작·soft 차단일
        개연성이 훨씬 높아(실측: 게임잡이 격일로 0건↔수집을 반복하며 같은 공고가
        마감↔부활 플랩, 원티드는 한 달간 0건) 해당 소스 공고는 마감 판정을 보류한다.
        """
        # [안전 장치] 만약 오늘 전체 수집된 건수가 비정상적으로 적은 경우(예: 3건 미만),
        # 크롤러가 네트워크 지연이나 WAF 차단으로 수집을 정상적으로 완수하지 못한 오류 상황으로 간주하고,
        # 기존 유효 공고가 대거 마감되는 오작동을 방지하기 위해 마감 처리를 전면 보류(Skip)합니다.
        if len(today_scraped_ids) < 3:
            print("    [WARN] 오늘 수집된 공고 수가 너무 적어(3건 미만) 크롤링 누락으로 판단됩니다. 마감 처리를 보류합니다.")
            return 0, []

        conn = self.db_manager.get_connection()
        cursor = conn.cursor()

        # 1. 현재 DB에 저장된 활성 공고 조회
        cursor.execute("SELECT id, source, company_name, title FROM job_postings WHERE status = 'ACTIVE'")
        active_jobs = cursor.fetchall()

        closed_count = 0
        closed_details = []
        held_by_suspect = 0

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

            if job_id not in today_scraped_ids:
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
            print(f"    [HOLD] 수집 0건 소스의 기존 공고 {held_by_suspect}건 마감 보류 (검색 오동작 의심: {', '.join(sorted(suspect_sources))})")

        return closed_count, closed_details
