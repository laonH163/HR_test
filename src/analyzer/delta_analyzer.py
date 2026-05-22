import sqlite3
from datetime import datetime

class DeltaAnalyzer:
    def __init__(self, db_manager):
        self.db_manager = db_manager

    def analyze_closed_postings(self, today_scraped_ids):
        """
        오늘 수집된 고유 ID셋(today_scraped_ids)에 속하지 않으면서,
        현재 DB 내에 'ACTIVE' 상태인 채용공고들을 찾아 'CLOSED'로 자동 마킹 처리.
        """
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()

        # 1. 현재 DB에 저장된 활성 공고 조회
        cursor.execute("SELECT id, company_name, title FROM job_postings WHERE status = 'ACTIVE'")
        active_jobs = cursor.fetchall()

        closed_count = 0
        closed_details = []

        # 2. 오늘 수집 대상에서 누락된 건 식별
        for job in active_jobs:
            job_id = job["id"]
            if job_id not in today_scraped_ids:
                # 상태를 'CLOSED'로 변경하고 업데이트 시각 기재
                cursor.execute("""
                    UPDATE job_postings
                    SET status = 'CLOSED', last_updated_at = ?
                    WHERE id = ?
                """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), job_id))

                closed_count += 1
                closed_details.append({
                    "id": job_id,
                    "company_name": job["company_name"],
                    "title": job["title"]
                })

        conn.commit()
        conn.close()

        return closed_count, closed_details
