"""수집량 급감 감지 기준선(get_recent_source_counts) 회귀 테스트.

2026-07-22 실사고: '최근 7회 실행' 기준이라 같은 날 검증 반복 7회가 기준선을
독점했다(run 74~80 전부 7/22). 달력 날짜 기준 + 하루 1값(최댓값) 축약으로 교정.
GPT 검토(2026-07-24) 제안 테스트 목록을 그대로 구현한 것.
"""
import unittest
import os
from src.database.db_manager import DBManager


class TestSourceCountBaseline(unittest.TestCase):
    def setUp(self):
        self.db_path = "data/test_source_baseline.db"
        self.db_manager = DBManager(db_path=self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except PermissionError:
                pass

    def _log(self, run_date, source_counts, is_success=1):
        self.db_manager.insert_scrape_log({
            "run_date": run_date, "newly_added": 0, "modified_count": 0,
            "closed_count": 0, "is_success": is_success, "error_log": None,
            "source_counts": source_counts,
        })

    def test_current_day_runs_are_excluded(self):
        """오늘 로그가 아무리 많아도(재실행 10회) 기준선에 못 들어간다."""
        for _ in range(10):
            self._log("2026-07-22", {"saramin": 3})
        history = self.db_manager.get_recent_source_counts(before_date="2026-07-22", days=7)
        self.assertEqual(history, {})

    def test_same_day_retries_collapse_to_one_daily_value(self):
        """같은 날 재실행 여러 번은 소스별 최댓값 하나로 축약된다."""
        for n in (10, 8, 12):
            self._log("2026-07-21", {"saramin": n})
        history = self.db_manager.get_recent_source_counts(before_date="2026-07-22", days=7)
        self.assertEqual(history.get("saramin"), [12])

    def test_partial_retry_does_not_erase_complete_run(self):
        """같은 날 마지막 실행이 일부 소스만 수집한 부분 실행이어도
        앞선 정상 실행의 값이 유지된다 ('마지막 값'이 아니라 '최댓값'인 이유)."""
        self._log("2026-07-21", {"jobkorea": 5, "gamejob": 17})
        self._log("2026-07-21", {"saramin": 10})  # 부분 실행 (run 78 패턴)
        history = self.db_manager.get_recent_source_counts(before_date="2026-07-22", days=7)
        self.assertEqual(history.get("jobkorea"), [5])
        self.assertEqual(history.get("gamejob"), [17])
        self.assertEqual(history.get("saramin"), [10])

    def test_days_without_runs_are_not_backfilled(self):
        """실행이 없던 날짜를 메우려고 구간 밖(7일 초과) 로그를 끌어오지 않는다.
        before=7/22, days=7 → 정확히 [7/15, 7/22) 범위만."""
        self._log("2026-07-14", {"saramin": 99})  # 구간 밖 — 포함되면 안 됨
        self._log("2026-07-15", {"saramin": 9})   # 구간 경계(포함)
        self._log("2026-07-21", {"saramin": 10})
        history = self.db_manager.get_recent_source_counts(before_date="2026-07-22", days=7)
        self.assertEqual(history.get("saramin"), [10, 9])

    def test_source_missing_is_not_zero_or_observation(self):
        """그날 로그에 없는 소스는 0으로 채우지도, 표본 수에 넣지도 않는다."""
        self._log("2026-07-19", {"saramin": 11})               # jobkorea 결측
        self._log("2026-07-20", {"saramin": 10, "jobkorea": 4})
        self._log("2026-07-21", {"saramin": 12, "jobkorea": 5})
        history = self.db_manager.get_recent_source_counts(before_date="2026-07-22", days=7)
        self.assertEqual(history.get("jobkorea"), [5, 4])  # 2일 관측 — 0 없음
        self.assertEqual(history.get("saramin"), [12, 10, 11])

    def test_minimum_samples_means_distinct_dates(self):
        """같은 날짜 재시도 3회로는 표본 3개가 안 된다 — main.py의 len(past)>=3
        게이트가 '관측 3일 이상'을 뜻하게 만드는 근거."""
        for n in (10, 11, 12):
            self._log("2026-07-21", {"saramin": n})
        history = self.db_manager.get_recent_source_counts(before_date="2026-07-22", days=7)
        self.assertEqual(len(history.get("saramin", [])), 1)
        # 서로 다른 3일이면 표본 3개
        self._log("2026-07-19", {"saramin": 9})
        self._log("2026-07-20", {"saramin": 10})
        history = self.db_manager.get_recent_source_counts(before_date="2026-07-22", days=7)
        self.assertEqual(len(history["saramin"]), 3)

    def test_failed_runs_are_excluded(self):
        """is_success=0(전면 실패) 로그는 기준선에 넣지 않는다."""
        self._log("2026-07-21", {"saramin": 2}, is_success=0)
        self._log("2026-07-20", {"saramin": 10})
        history = self.db_manager.get_recent_source_counts(before_date="2026-07-22", days=7)
        self.assertEqual(history.get("saramin"), [10])

    def test_zero_and_invalid_counts_do_not_lower_baseline(self):
        """0건·비정상 값은 기준선을 낮추지 않는다 (방어적 필터)."""
        self._log("2026-07-21", {"saramin": 0, "jobkorea": "n/a", "gamejob": True})
        self._log("2026-07-20", {"saramin": 10})
        history = self.db_manager.get_recent_source_counts(before_date="2026-07-22", days=7)
        self.assertEqual(history.get("saramin"), [10])
        self.assertNotIn("jobkorea", history)
        self.assertNotIn("gamejob", history)

    def test_non_dict_json_row_is_skipped(self):
        """유효 JSON이지만 객체가 아닌 행([]·null·숫자)은 행 단위로 건너뛴다 —
        한 행 오염이 그날 급감 감지 전체를 죽이면 안 된다(코덱스 지적)."""
        self._log("2026-07-20", {"saramin": 10})
        conn = self.db_manager.get_connection()
        # 현재 insert 경로로는 못 만드는 오염 행을 직접 주입
        conn.execute(
            "INSERT INTO scrape_logs (run_date, newly_added, modified_count, closed_count,"
            " is_success, error_log, source_counts) VALUES ('2026-07-21', 0, 0, 0, 1, NULL, '[]')")
        conn.execute(
            "INSERT INTO scrape_logs (run_date, newly_added, modified_count, closed_count,"
            " is_success, error_log, source_counts) VALUES ('2026-07-21', 0, 0, 0, 1, NULL, 'null')")
        conn.commit()
        conn.close()
        history = self.db_manager.get_recent_source_counts(before_date="2026-07-22", days=7)
        self.assertEqual(history.get("saramin"), [10])

    def test_2026_07_22_regression_dataset(self):
        """실제 run 60~80 데이터(scrap_master.db 실측)를 그대로 재현.
        옛 로직(최근 7행)이라면 7/22 반복 실행이 기준선을 독점했을 데이터셋."""
        rows = [
            ("2026-07-15", {"wanted": 1, "gamejob": 17, "saramin": 9, "jobkorea": 4}),   # run 60
            ("2026-07-16", {"wanted": 1, "gamejob": 17, "saramin": 11, "jobkorea": 4}),  # run 61
            ("2026-07-16", {"gamejob": 17, "saramin": 11, "jobkorea": 4}),               # run 62
            ("2026-07-16", {"saramin": 11}),                                             # run 63
            ("2026-07-16", {"gamejob": 17, "saramin": 11, "jobkorea": 4}),               # run 64
            ("2026-07-16", {"gamejob": 17, "jobkorea": 4, "saramin": 13}),               # run 65
            ("2026-07-17", {"gamejob": 16, "saramin": 11, "jobkorea": 4}),               # run 66
            ("2026-07-17", {"gamejob": 16, "saramin": 11, "jobkorea": 4}),               # run 67
            ("2026-07-20", {"gamejob": 16, "saramin": 10, "jobkorea": 4}),               # run 68
            ("2026-07-20", {"gamejob": 16, "saramin": 10, "jobkorea": 4}),               # run 69
            ("2026-07-21", {"saramin": 11, "gamejob": 17, "jobkorea": 5}),               # run 70
            ("2026-07-21", {"saramin": 13}),                                             # run 71
            ("2026-07-21", {"gamejob": 16, "saramin": 14, "jobkorea": 6}),               # run 72
            ("2026-07-21", {"gamejob": 16, "saramin": 12, "jobkorea": 6}),               # run 73
        ]
        # 7/22 검증 반복 7회 (run 74~80) — 전부 제외돼야 한다
        rows += [
            ("2026-07-22", {"gamejob": 17, "saramin": 11, "jobkorea": 5}),
            ("2026-07-22", {"gamejob": 17, "saramin": 11, "jobkorea": 5}),
            ("2026-07-22", {"gamejob": 17, "saramin": 12, "jobkorea": 5}),
            ("2026-07-22", {"gamejob": 17, "saramin": 11, "jobkorea": 5}),
            ("2026-07-22", {"saramin": 10}),
            ("2026-07-22", {"gamejob": 17, "saramin": 10, "jobkorea": 5}),
            ("2026-07-22", {"gamejob": 17, "saramin": 10, "jobkorea": 5}),
        ]
        for run_date, counts in rows:
            self._log(run_date, counts)

        history = self.db_manager.get_recent_source_counts(before_date="2026-07-22", days=7)
        # 최신 날짜순: 7/21, 7/20, 7/17, 7/16, 7/15 (하루 최댓값)
        self.assertEqual(history.get("saramin"), [14, 10, 11, 13, 9])
        self.assertEqual(history.get("jobkorea"), [6, 4, 4, 4, 4])
        self.assertEqual(history.get("gamejob"), [17, 16, 16, 17, 17])
        self.assertEqual(history.get("wanted"), [1, 1])  # 7/16, 7/15만 관측


if __name__ == "__main__":
    unittest.main()
