import sqlite3
import os
import json
import re

from src.utils.jdtext import body_degraded

class DBManager:
    def __init__(self, db_path="data/scrap_master.db"):
        self.db_path = db_path
        # 데이터베이스 폴더가 없다면 자동 생성
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        # 직전 upsert의 변경 상세 (마감일 연장/단축 알림용)
        self.last_change_details = {}
        self.init_db()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # FK 제약(ON DELETE CASCADE 등)은 SQLite 연결마다 명시적으로 켜야 적용됨
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _normalize_for_diff(self, text):
        """MODIFIED 판정용 정규화. 공백/개행과 날짜·시각 같은 노이즈를 제거해
        실제 의미 있는 본문 변경만 변동으로 잡도록 한다. 숫자(연봉 등)는 보존한다
        — 놓치면 안 되는 핵심 변경이므로 의도적으로 남긴다."""
        if not text:
            return ""
        t = re.sub(r"\s+", " ", text)
        # 날짜(YYYY-MM-DD / YYYY.MM.DD)와 시각(HH:MM) — 마감일 자동표기·조회시각 노이즈 제거
        t = re.sub(r"\d{4}[-.]\d{1,2}[-.]\d{1,2}", "", t)
        t = re.sub(r"\b\d{1,2}:\d{2}\b", "", t)
        return t.strip()

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

        # [안전 점진적 마이그레이션] 테이블 생성 이후 미래지향적 확장을 위해 안전하게 새 컬럼 추가
        self._add_column_if_not_exists("job_categories", "preferred_certifications", "TEXT") # 자격증 태그 (JSON)
        self._add_column_if_not_exists("job_categories", "preferred_skills_tags", "TEXT")     # 실무 역량 태그 (JSON)
        self._add_column_if_not_exists("job_postings", "deadline", "TEXT")  # 마감일 YYYY-MM-DD (D-N 배지 환산, 상시채용은 NULL)
        self._add_column_if_not_exists("scrape_logs", "source_counts", "TEXT")  # 소스별 수집 건수 JSON (수집량 급감 감지용)
        self._add_column_if_not_exists("scrape_logs", "successful_sources", "TEXT")  # 성공 소스 JSON (하루 기준 경고 보정용)

    def _add_column_if_not_exists(self, table_name, column_name, column_type):
        """기존 테이블에 컬럼이 없을 때 안전하게 ALTER TABLE을 가동하는 마이그레이션 도우미"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [info[1] for info in cursor.fetchall()]
            if column_name not in columns:
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
                conn.commit()
                print(f"    [DB Migration] {table_name} 테이블에 '{column_name}' 컬럼을 안전하게 마이그레이션 추가했습니다.")
        except Exception as e:
            import sys
            print(f"    [DB ERR] 마이그레이션 추가 실패 ({table_name}.{column_name}): {e}", file=sys.stderr)
        finally:
            conn.close()

    def upsert_job_posting(self, posting):
        """
        job_posting 정보를 Upsert하고, 변경사항이 존재한다면 True를 반환.
        posting은 dict 타입이어야 함.

        호출 직후 last_change_details에서 변경 상세를 읽을 수 있다:
        {"deadline_from": 기존값, "deadline_to": 새값} — 기존 마감일이 있었는데
        실제로 바뀐(연장/단축) 경우에만 채워진다(최초 확보는 제외).
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        self.last_change_details = {}

        # 기존 공고 존재 여부 확인
        cursor.execute("SELECT title, raw_html, status, deadline FROM job_postings WHERE id = ?", (posting["id"],))
        existing = cursor.fetchone()

        is_modified = False

        if existing:
            # [본문 축소 방지 가드] 이미 상세요강을 확보한 공고인데 오늘 수집분이
            # 제목/스니펫 수준으로 열화됐으면(상세 접근 실패·개편이 원인일 개연성) 기존
            # 본문을 보존한다. 판정 규칙은 src/utils/jdtext.body_degraded 참조.
            # ※ posting dict에도 보존본을 되돌려준다(의도된 변이) — 호출자(main.py)의
            #   분류기가 열화 본문으로 재분류해 job_categories를 덮어쓰는 것까지 막는다.
            incoming_raw = posting["raw_html"]
            if body_degraded(existing["raw_html"], incoming_raw):
                incoming_raw = existing["raw_html"]
                posting["raw_html"] = incoming_raw
                print(f"    [GUARD] 본문 축소 감지 → 기확보 상세요강 보존: {posting['id']}")

            # 상태 비교 (제목이나 내용 혹은 상태가 바뀌었는지 점검)
            # 델타 분석을 위해 raw_html 내용의 변경 감지 — 단, 공백·날짜 같은 노이즈는
            # 정규화로 무시하여 의미 있는 본문 변경(자격요건·연봉 등)만 MODIFIED로 잡는다.
            content_changed = self._normalize_for_diff(existing["raw_html"]) != self._normalize_for_diff(incoming_raw)
            # 제목 변경은 raw_html과 독립적으로 감지 — 가드가 본문을 보존한 날에도
            # 제목 개정('경력 5년+' 추가 등)이 유실되지 않도록.
            title_changed = existing["title"] != posting["title"]
            # 마감일 변경(연장/단축)은 지원 전략에 직결되는 실질 변경이므로 MODIFIED로 잡는다.
            # 단, 수집처가 마감일 정보를 아예 안 주는 경우(None)는 기존 값을 지우지 않는다.
            new_deadline = posting.get("deadline")
            deadline_changed = new_deadline is not None and new_deadline != existing["deadline"]
            if deadline_changed and existing["deadline"]:
                # 기존 마감일이 실제로 바뀐 경우만 상세 기록 (None→값 최초 확보는 변경 알림 대상 아님)
                self.last_change_details = {
                    "deadline_from": existing["deadline"],
                    "deadline_to": new_deadline,
                }
            if content_changed or deadline_changed or title_changed or existing["status"] != posting["status"]:
                cursor.execute("""
                    UPDATE job_postings
                    SET title = ?, origin_url = ?, location = ?, status = ?, raw_html = ?, last_updated_at = ?,
                        deadline = COALESCE(?, deadline)
                    WHERE id = ?
                """, (
                    posting["title"], posting["origin_url"], posting.get("location"),
                    posting["status"], incoming_raw, posting["last_updated_at"],
                    new_deadline, posting["id"]
                ))
                is_modified = True
        else:
            # 신규 삽입
            cursor.execute("""
                INSERT INTO job_postings (id, source, company_name, title, origin_url, location, posted_at, status, raw_html, first_seen_at, last_updated_at, deadline)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                posting["id"], posting["source"], posting["company_name"], posting["title"],
                posting["origin_url"], posting.get("location"), posting["posted_at"],
                posting["status"], posting["raw_html"], posting["first_seen_at"], posting["last_updated_at"],
                posting.get("deadline")
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
                key_requirements, preferred_skills, tools_used, ai_summary,
                preferred_certifications, preferred_skills_tags
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ai_summary=excluded.ai_summary,
                preferred_certifications=excluded.preferred_certifications,
                preferred_skills_tags=excluded.preferred_skills_tags
        """, (
            category["job_id"], category["primary_category"], category.get("min_experience"), category.get("max_experience"),
            category.get("salary_min"), category.get("salary_max"), category["work_type"],
            category.get("company_revenue"), category.get("company_size"),
            json.dumps(category.get("key_requirements", []), ensure_ascii=False),
            json.dumps(category.get("preferred_skills", []), ensure_ascii=False),
            category.get("tools_used"), category["ai_summary"],
            json.dumps(category.get("preferred_certifications", []), ensure_ascii=False),
            json.dumps(category.get("preferred_skills_tags", []), ensure_ascii=False)
        ))

        conn.commit()
        conn.close()

    def insert_scrape_log(self, log):
        """크롤링 실행 이력 저장 (소스별 수집 건수 JSON 포함 — 급감 감지용)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO scrape_logs (run_date, newly_added, modified_count, closed_count, is_success, error_log, source_counts, successful_sources)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            log["run_date"], log["newly_added"], log["modified_count"],
            log["closed_count"], log["is_success"], log.get("error_log"),
            json.dumps(log.get("source_counts") or {}, ensure_ascii=False),
            json.dumps(sorted(log.get("successful_sources") or []), ensure_ascii=False)
        ))
        conn.commit()
        conn.close()

    def get_sources_succeeded_today(self, run_date):
        """오늘(run_date) 실행들 중 어느 시도에서든 '수집에 성공한' 소스 집합.

        최종 브리핑은 재시도 실행이 보내므로, 이번 시도가 실패한 소스라도 같은 날
        앞선 시도에서 이미 확보됐다면 '접속 실패' 경고 대상이 아니다(하루 기준 보정).
        successful_sources 컬럼이 없는 과거 행은 source_counts의 수집 건수>0으로 폴백."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT source_counts, successful_sources FROM scrape_logs WHERE run_date = ?",
            (run_date,),
        )
        succeeded = set()
        for row in cursor.fetchall():
            try:
                for s in json.loads(row["successful_sources"] or "[]"):
                    succeeded.add(s)
            except Exception:
                pass
            try:
                for s, n in json.loads(row["source_counts"] or "{}").items():
                    if n and n > 0:
                        succeeded.add(s)
            except Exception:
                pass
        conn.close()
        return succeeded

    def get_last_success_date(self, source):
        """해당 소스가 마지막으로 수집에 성공한 날짜(YYYY-MM-DD). 이력이 없으면 None.

        '알려진 차단'이 며칠째 이어지는지 세는 데 쓴다. 차단이 길어지면 그 소스의 기존
        활성 공고가 마감 보류로 계속 보호되어 좀비가 되므로 사람이 확인해야 한다.
        successful_sources가 없는 과거 행은 source_counts의 수집 건수>0으로 폴백한다
        (get_sources_succeeded_today와 같은 판정 기준)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT run_date, source_counts, successful_sources FROM scrape_logs
            ORDER BY run_date DESC, run_id DESC
            """
        )
        target = str(source).lower()
        found = None
        for row in cursor.fetchall():
            ok = False
            try:
                ok = target in {str(s).lower() for s in json.loads(row["successful_sources"] or "[]")}
            except Exception:
                pass
            if not ok:
                try:
                    counts = {str(k).lower(): v for k, v in json.loads(row["source_counts"] or "{}").items()}
                    ok = bool(counts.get(target))
                except Exception:
                    pass
            if ok:
                found = row["run_date"]
                break
        conn.close()
        return found

    def get_recent_source_counts(self, runs=7):
        """최근 성공 실행들의 소스별 수집 건수 이력 — {source: [건수, ...]} (최신순).

        플랫폼 수집량이 평소 대비 급감했는지 판정하는 기준선. source_counts 컬럼이
        비어 있는 과거 실행은 건너뛴다."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT source_counts FROM scrape_logs
            WHERE is_success = 1 AND source_counts IS NOT NULL AND source_counts != '{}'
            ORDER BY run_id DESC LIMIT ?
            """,
            (runs,),
        )
        history = {}
        for row in cursor.fetchall():
            try:
                counts = json.loads(row["source_counts"])
            except Exception:
                continue
            for source, n in counts.items():
                history.setdefault(source, []).append(n)
        conn.close()
        return history

    def get_all_active_postings(self):
        """현재 활성화된 모든 공고 및 매핑된 분석 카테고리 데이터 조회 (HTML 대시보드 렌더링용)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        # raw_html은 대시보드/텔레그램에서 쓰지 않으므로 제외 (페이로드 축소 + 인라인 주입 리스크 제거)
        # 단, 본문 보유 여부 판정용으로 길이만 내려준다(제목만 수집된 공고의 분류 신뢰도 표기용)
        cursor.execute("""
            SELECT p.id, p.source, p.company_name, p.title, p.origin_url, p.location,
                   p.posted_at, p.status, p.first_seen_at, p.last_updated_at, p.deadline,
                   LENGTH(p.raw_html) AS raw_html_len,
                   c.primary_category, c.min_experience, c.max_experience,
                   c.salary_min, c.salary_max, c.work_type, c.company_revenue, c.company_size,
                   c.key_requirements, c.preferred_skills, c.tools_used, c.ai_summary,
                   c.preferred_certifications, c.preferred_skills_tags
            FROM job_postings p
            LEFT JOIN job_categories c ON p.id = c.job_id
            WHERE p.status = 'ACTIVE'
            ORDER BY p.posted_at DESC, p.id DESC
        """)
        rows = cursor.fetchall()
        conn.close()
        return rows

    def get_raw_html_map(self, ids):
        """공고 id 목록의 저장된 raw_html 조회 — GI 본문 보강 시 기확보분 재사용용"""
        if not ids:
            return {}
        conn = self.get_connection()
        cursor = conn.cursor()
        placeholders = ",".join("?" * len(ids))
        cursor.execute(
            f"SELECT id, raw_html FROM job_postings WHERE id IN ({placeholders})",
            list(ids),
        )
        result = {row["id"]: row["raw_html"] for row in cursor.fetchall()}
        conn.close()
        return result

    def get_closed_key_history(self):
        """CLOSED 공고의 (회사명, 제목, 마지막 관측시각) 목록 — 재공고(🔁) 판별 원료.

        같은 회사+제목이 여러 번 닫혔으면 가장 최근 관측만 남긴다.
        content_key 정규화·판별 로직은 src/utils/dedup.compute_repost_flags가 담당."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT company_name, title, MAX(last_updated_at) AS closed_at
            FROM job_postings
            WHERE status = 'CLOSED'
            GROUP BY company_name, title
            """
        )
        history = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return history

    def get_companies_seen_before(self, cutoff_date):
        """cutoff_date('YYYY-MM-DD') 이전에 처음 관측된 회사명 목록 — 신규 진입사 판별용.

        상태 불문(CLOSED 포함) 전체 이력 기준: 과거에 한 번이라도 재무 공고를 냈던
        회사는 '기존 회사'다. first_seen_at('YYYY-MM-DD HH:MM:SS')과의 문자열 비교로
        cutoff 당일 신규 적재분은 제외된다."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT DISTINCT company_name FROM job_postings WHERE first_seen_at < ?",
            (cutoff_date,),
        )
        companies = [r[0] for r in cursor.fetchall()]
        conn.close()
        return companies

    def get_recent_scrape_stats(self, days=7):
        """최근 N일 수집 추세 집계(성공 실행 기준). HTML 트렌드 위젯·주간 인사이트용.

        같은 날 여러 번 실행됐을 수 있으므로 run_date로 합산한 뒤 최신 N일을 반환한다.
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT run_date,
                   SUM(newly_added)    AS newly_added,
                   SUM(modified_count) AS modified_count,
                   SUM(closed_count)   AS closed_count
            FROM scrape_logs
            WHERE is_success = 1
            GROUP BY run_date
            ORDER BY run_date DESC
            LIMIT ?
            """,
            (days,),
        )
        daily = [dict(r) for r in cursor.fetchall()]
        conn.close()

        total_new = sum((d["newly_added"] or 0) for d in daily)
        total_closed = sum((d["closed_count"] or 0) for d in daily)
        return {
            "days": len(daily),
            "total_new": total_new,
            "total_closed": total_closed,
            "daily": daily,  # 최신순
        }
