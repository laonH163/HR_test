"""마감 유예(CLOSE_GRACE_DAYS) 회귀 테스트 — 사람인 플랩 방어.

2026-07-22 실사고: 사람인 검색 결과가 실행마다 출렁여(11→12→10건) 결과에서 빠진
공고가 즉시 CLOSED됐다가 다음 실행에서 부활하는 플랩이 반복됐다(run 77: 마감 3건이
1분 뒤 전부 부활). 마지막 관측일로부터 CLOSE_GRACE_DAYS(2일) 미만이면 마감을
보류하는 유예를 delta_analyzer에 넣었다 — 같은 날 재실행 누락은 어떤 경우에도
마감되지 않고, 하루 빠진 공고도 보류된다.
"""
import unittest
import os
from src.database.db_manager import DBManager
from src.analyzer.delta_analyzer import DeltaAnalyzer, CLOSE_GRACE_DAYS


RUN_DATE = "2026-07-24"


def make_posting(job_id, source="saramin"):
    return {
        "id": job_id, "source": source, "company_name": "테스트게임즈",
        "title": "재무회계 담당자", "origin_url": "https://example.com",
        "location": "서울", "posted_at": "2026-07-01", "status": "ACTIVE",
        "raw_html": "본문", "first_seen_at": "2026-07-01 09:00:00",
        "last_updated_at": "2026-07-01 09:00:00",
    }


class TestCloseGrace(unittest.TestCase):
    def setUp(self):
        self.db_path = "data/test_close_grace.db"
        self.db_manager = DBManager(db_path=self.db_path)
        self.analyzer = DeltaAnalyzer(self.db_manager)

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except PermissionError:
                pass

    def _set_last_seen(self, job_id, value):
        conn = self.db_manager.get_connection()
        conn.execute("UPDATE job_postings SET last_seen_date = ? WHERE id = ?", (value, job_id))
        conn.commit()
        conn.close()

    def _log_fair_day(self, run_date, source_counts):
        """해당 날짜에 소스가 정상 동작한 실행 이력('공정한 미관측일' 재료)을 넣는다."""
        self.db_manager.insert_scrape_log({
            "run_date": run_date, "newly_added": 0, "modified_count": 0,
            "closed_count": 0, "is_success": 1, "error_log": None,
            "source_counts": source_counts,
            "successful_sources": sorted(source_counts.keys()),
        })

    def _status(self, job_id):
        conn = self.db_manager.get_connection()
        row = conn.execute("SELECT status, last_seen_date FROM job_postings WHERE id = ?", (job_id,)).fetchone()
        conn.close()
        return row["status"], row["last_seen_date"]

    def _analyze(self, today_ids):
        return self.analyzer.analyze_closed_postings(
            today_ids, successful_sources={"saramin"}, run_date=RUN_DATE)

    def test_intraday_miss_is_never_closed(self):
        """같은 날 앞선 실행에서 관측된 공고(관측일=오늘)는 이번 실행에서 빠져도
        마감되지 않는다 — run 77 플랩(마감 1분 뒤 부활)의 직접 재현."""
        self.db_manager.upsert_job_posting(make_posting("saramin_flap"))
        self._set_last_seen("saramin_flap", RUN_DATE)
        closed, _ = self._analyze({"saramin_1", "saramin_2", "saramin_3"})
        self.assertEqual(closed, 0)
        self.assertEqual(self._status("saramin_flap")[0], "ACTIVE")
        self.assertEqual(self.analyzer.last_grace_held, 1)

    def test_one_day_miss_is_held(self):
        """어제 관측된 공고가 오늘 빠지면 보류 — 하루 걸러 나타나는 플랩 방어."""
        self.db_manager.upsert_job_posting(make_posting("saramin_a"))
        self._set_last_seen("saramin_a", "2026-07-23")
        closed, _ = self._analyze({"saramin_1", "saramin_2", "saramin_3"})
        self.assertEqual(closed, 0)
        self.assertEqual(self._status("saramin_a")[0], "ACTIVE")

    def test_grace_days_miss_is_closed(self):
        """마지막 관측 이후 소스가 정상 동작한 날(공정 미관측일)이 있고 오늘도
        미관측이면 정상 마감된다 — 증거 2일 확보."""
        self.db_manager.upsert_job_posting(make_posting("saramin_old"))
        self._set_last_seen("saramin_old", "2026-07-22")  # 2일 전 관측
        self._log_fair_day("2026-07-23", {"saramin": 5})  # 어제 사람인 정상 동작 + 미관측
        closed, details = self._analyze({"saramin_1", "saramin_2", "saramin_3"})
        self.assertEqual(closed, 1)
        self.assertEqual(details[0]["id"], "saramin_old")
        self.assertEqual(self._status("saramin_old")[0], "CLOSED")

    def test_weekend_gap_does_not_consume_grace(self):
        """금요일 관측 → 주말 실행 없음 → 월요일 첫 검색 누락은 달력상 3일이지만
        보류돼야 한다 — 실행이 없던 날은 미관측의 증거가 아니다(코덱스 지적 재현).
        화요일에도 미관측이면(월요일이 공정 미관측일) 그때 마감된다."""
        self.db_manager.upsert_job_posting(make_posting("saramin_fri"))
        self._set_last_seen("saramin_fri", "2026-07-17")  # 금요일 관측
        # 월요일(7/20): 주말 이틀은 실행 자체가 없었다 — 즉시 마감되면 안 된다
        closed, _ = self.analyzer.analyze_closed_postings(
            {"saramin_1", "saramin_2", "saramin_3"},
            successful_sources={"saramin"}, run_date="2026-07-20")
        self.assertEqual(closed, 0)
        self.assertEqual(self._status("saramin_fri")[0], "ACTIVE")
        # 화요일(7/21): 월요일에 사람인이 정상 동작했는데도 안 보였다 → 증거 성립, 마감
        self._log_fair_day("2026-07-20", {"saramin": 5})
        closed, _ = self.analyzer.analyze_closed_postings(
            {"saramin_1", "saramin_2", "saramin_3"},
            successful_sources={"saramin"}, run_date="2026-07-21")
        self.assertEqual(closed, 1)
        self.assertEqual(self._status("saramin_fri")[0], "CLOSED")

    def test_broken_source_day_is_not_fair_evidence(self):
        """중간 날에 사람인이 0건(검색 오동작 의심)이었다면 그날은 미관측 증거가
        아니다 — 유예가 소진되지 않고 보류가 유지된다."""
        self.db_manager.upsert_job_posting(make_posting("saramin_x"))
        self._set_last_seen("saramin_x", "2026-07-22")
        self._log_fair_day("2026-07-23", {"gamejob": 5})  # 사람인은 이날 0건(결측)
        closed, _ = self._analyze({"saramin_1", "saramin_2", "saramin_3"})
        self.assertEqual(closed, 0)
        self.assertEqual(self._status("saramin_x")[0], "ACTIVE")

    def test_future_last_seen_self_heals(self):
        """미래 날짜 관측일(시계 오차·수동 편집)은 그대로 두면 그 날짜가 지날 때까지
        마감이 봉쇄된다 — 오늘로 재기록해 자가 복구한다(코덱스 지적)."""
        self.db_manager.upsert_job_posting(make_posting("saramin_future"))
        self._set_last_seen("saramin_future", "2030-01-01")
        closed, _ = self._analyze({"saramin_1", "saramin_2", "saramin_3"})
        self.assertEqual(closed, 0)
        status, last_seen = self._status("saramin_future")
        self.assertEqual(status, "ACTIVE")
        self.assertEqual(last_seen, RUN_DATE)

    def test_null_last_seen_starts_grace_today(self):
        """관측 이력이 없는 공고(컬럼 도입 전 데이터)는 즉시 마감하지 않고
        오늘을 기점으로 유예를 시작한다(관측일을 오늘로 기록)."""
        self.db_manager.upsert_job_posting(make_posting("saramin_legacy"))
        closed, _ = self._analyze({"saramin_1", "saramin_2", "saramin_3"})
        self.assertEqual(closed, 0)
        status, last_seen = self._status("saramin_legacy")
        self.assertEqual(status, "ACTIVE")
        self.assertEqual(last_seen, RUN_DATE)

    def test_corrupt_last_seen_self_heals(self):
        """손상된 관측일은 마감 대신 오늘로 재기록해 자가 복구한다."""
        self.db_manager.upsert_job_posting(make_posting("saramin_bad"))
        self._set_last_seen("saramin_bad", "not-a-date")
        closed, _ = self._analyze({"saramin_1", "saramin_2", "saramin_3"})
        self.assertEqual(closed, 0)
        status, last_seen = self._status("saramin_bad")
        self.assertEqual(status, "ACTIVE")
        self.assertEqual(last_seen, RUN_DATE)

    def test_observed_postings_are_stamped(self):
        """오늘 관측된 공고는 last_seen_date가 오늘로 스탬프된다 —
        3건 미만 보류로 조기 반환하는 날에도 스탬프는 남는다."""
        self.db_manager.upsert_job_posting(make_posting("saramin_seen"))
        # 3건 미만 → 마감 판정은 전면 보류되지만 관측 스탬프는 남아야 한다
        self.analyzer.analyze_closed_postings({"saramin_seen"}, run_date=RUN_DATE)
        self.assertEqual(self._status("saramin_seen")[1], RUN_DATE)

    def test_mark_postings_seen_chunks_large_sets(self):
        """관측 스탬프가 SQLite 바인딩 한도(999개)를 넘는 집합도 처리한다."""
        ids = [f"saramin_bulk_{i}" for i in range(1200)]
        for jid in ids:
            self.db_manager.upsert_job_posting(make_posting(jid))
        updated = self.db_manager.mark_postings_seen(ids, RUN_DATE)
        self.assertEqual(updated, 1200)

    def test_grace_days_constant(self):
        """유예 일수가 의도치 않게 바뀌면 플랩 방어(2 미만)나 마감 지연(3 초과)이
        달라진다 — 바꿀 때는 CLAUDE.md의 트레이드오프 설명과 함께 바꿀 것."""
        self.assertEqual(CLOSE_GRACE_DAYS, 2)


if __name__ == "__main__":
    unittest.main()
