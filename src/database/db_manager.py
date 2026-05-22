import sqlite3
import os
import json

class DBManager:
    def __init__(self, db_path="data/scrap_master.db"):
        self.db_path = db_path
        # 데이터베이스 폴더가 없다면 자동 생성
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.init_db()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        """데이터베이스 테이블 생성"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # 1. job_postings (채용공고 마스터 테이블)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS job_postings (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                company_name TEXT NOT NULL,
                title TEXT NOT NULL,
                origin_url TEXT NOT NULL,
                location TEXT,
                posted_at TEXT NOT NULL,
                status TEXT NOT NULL,
                raw_html TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_updated_at TEXT NOT NULL
            )
        """)

        # 2. job_categories (AI 정밀 분류 테이블 - 1:1 관계)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS job_categories (
                job_id TEXT PRIMARY KEY,
                primary_category TEXT NOT NULL,
                min_experience INTEGER,
                max_experience INTEGER,
                salary_min INTEGER,
                salary_max INTEGER,
                work_type TEXT NOT NULL,
                company_revenue INTEGER,
                company_size INTEGER,
                key_requirements TEXT NOT NULL, -- JSON String
                preferred_skills TEXT NOT NULL, -- JSON String
                tools_used TEXT,                -- Sap, Douzone 등
                ai_summary TEXT NOT NULL,
                FOREIGN KEY (job_id) REFERENCES job_postings (id) ON DELETE CASCADE
            )
        """)

        # 3. scrape_logs (수집 및 알림 이력 로그)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scrape_logs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_date TEXT NOT NULL,
                newly_added INTEGER NOT NULL,
                modified_count INTEGER NOT NULL,
                closed_count INTEGER NOT NULL,
                is_success INTEGER NOT NULL, -- 0:실패, 1:성공
                error_log TEXT
            )
        """)

        conn.commit()
        conn.close()

    def upsert_job_posting(self, posting):
        """
        job_posting 정보를 Upsert하고, 변경사항이 존재한다면 True를 반환.
        posting은 dict 타입이어야 함.
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        # 기존 공고 존재 여부 확인
        cursor.execute("SELECT title, raw_html, status FROM job_postings WHERE id = ?", (posting["id"],))
        existing = cursor.fetchone()

        is_modified = False

        if existing:
            # 상태 비교 (제목이나 내용 혹은 상태가 바뀌었는지 점검)
            # 델타 분석을 위해 raw_html 내용의 변경 감지
            # raw_html 내용이 다르다면 업데이트 대상
            if existing["raw_html"] != posting["raw_html"] or existing["status"] != posting["status"]:
                cursor.execute("""
                    UPDATE job_postings
                    SET title = ?, origin_url = ?, location = ?, status = ?, raw_html = ?, last_updated_at = ?
                    WHERE id = ?
                """, (
                    posting["title"], posting["origin_url"], posting.get("location"),
                    posting["status"], posting["raw_html"], posting["last_updated_at"],
                    posting["id"]
                ))
                is_modified = True
        else:
            # 신규 삽입
            cursor.execute("""
                INSERT INTO job_postings (id, source, company_name, title, origin_url, location, posted_at, status, raw_html, first_seen_at, last_updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                posting["id"], posting["source"], posting["company_name"], posting["title"],
                posting["origin_url"], posting.get("location"), posting["posted_at"],
                posting["status"], posting["raw_html"], posting["first_seen_at"], posting["last_updated_at"]
            ))
            # 신규 삽입은 이 단계에서는 is_modified로 체크하지 않고, DB 수준 신규 건수로 집계 예정

        conn.commit()
        conn.close()
        return is_modified, existing is None

    def upsert_job_category(self, category):
        """AI 분류 데이터 Upsert"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO job_categories (
                job_id, primary_category, min_experience, max_experience,
                salary_min, salary_max, work_type, company_revenue, company_size,
                key_requirements, preferred_skills, tools_used, ai_summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                primary_category=excluded.primary_category,
                min_experience=excluded.min_experience,
                max_experience=excluded.max_experience,
                salary_min=excluded.salary_min,
                salary_max=excluded.salary_max,
                work_type=excluded.work_type,
                company_revenue=excluded.company_revenue,
                company_size=excluded.company_size,
                key_requirements=excluded.key_requirements,
                preferred_skills=excluded.preferred_skills,
                tools_used=excluded.tools_used,
                ai_summary=excluded.ai_summary
        """, (
            category["job_id"], category["primary_category"], category.get("min_experience"), category.get("max_experience"),
            category.get("salary_min"), category.get("salary_max"), category["work_type"],
            category.get("company_revenue"), category.get("company_size"),
            json.dumps(category.get("key_requirements", []), ensure_ascii=False),
            json.dumps(category.get("preferred_skills", []), ensure_ascii=False),
            category.get("tools_used"), category["ai_summary"]
        ))

        conn.commit()
        conn.close()

    def insert_scrape_log(self, log):
        """크롤링 실행 이력 저장"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO scrape_logs (run_date, newly_added, modified_count, closed_count, is_success, error_log)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            log["run_date"], log["newly_added"], log["modified_count"],
            log["closed_count"], log["is_success"], log.get("error_log")
        ))
        conn.commit()
        conn.close()

    def get_all_active_postings(self):
        """현재 활성화된 모든 공고 및 매핑된 분석 카테고리 데이터 조회 (HTML 대시보드 렌더링용)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.*, c.primary_category, c.min_experience, c.max_experience,
                   c.salary_min, c.salary_max, c.work_type, c.company_revenue, c.company_size,
                   c.key_requirements, c.preferred_skills, c.tools_used, c.ai_summary
            FROM job_postings p
            LEFT JOIN job_categories c ON p.id = c.job_id
            WHERE p.status = 'ACTIVE'
            ORDER BY p.posted_at DESC, p.id DESC
        """)
        rows = cursor.fetchall()
        conn.close()
        return rows
