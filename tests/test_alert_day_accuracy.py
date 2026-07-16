# -*- coding: utf-8 -*-
"""하루 기준 경고 보정 검증 (2026-07-16 run 84 오경보 실사고 재발 방지)

최종 브리핑은 재시도 실행이 보내므로, 이번 시도가 실패한 소스라도 같은 날
앞선 시도에서 이미 확보됐다면 '접속 실패' 경고 대상이 아니어야 한다.
"""
import os
import tempfile
import unittest

from src.database.db_manager import DBManager


def make_log(run_date="2026-07-16", counts=None, successful=None, error=None):
    return {
        "run_date": run_date, "newly_added": 0, "modified_count": 0,
        "closed_count": 0, "is_success": 1, "error_log": error,
        "source_counts": counts or {}, "successful_sources": successful or [],
    }


class TestSourcesSucceededToday(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = DBManager(db_path=os.path.join(self.tmp, "t.db"))

    def test_union_across_todays_attempts(self):
        """1차 성공 + 재시도 실패 시나리오: 1차 확보 소스가 성공 집합에 남아야 함"""
        # 1차 시도: 잡코리아 계열 정상 수집 (오늘 실사고의 run 62 재현)
        self.db.insert_scrape_log(make_log(
            counts={"jobkorea": 4, "gamejob": 17, "saramin": 11},
            successful=["jobkorea", "gamejob", "saramin", "nexon", "smilegate"]))
        # 재시도: 잡코리아 계열 전멸 (run 63 재현)
        self.db.insert_scrape_log(make_log(
            counts={"saramin": 11}, successful=["saramin"],
            error="수집 실패 소스: jobkorea, nexon, smilegate"))
        ok = self.db.get_sources_succeeded_today("2026-07-16")
        # 1차에서 확보된 소스들은 하루 기준 '성공' — 경고 제외 대상
        for s in ["jobkorea", "gamejob", "nexon", "smilegate", "saramin"]:
            self.assertIn(s, ok)

    def test_legacy_row_falls_back_to_counts(self):
        """successful_sources가 없는 과거 행은 수집 건수>0으로 폴백"""
        conn = self.db.get_connection()
        conn.execute(
            "INSERT INTO scrape_logs (run_date, newly_added, modified_count, closed_count, is_success, source_counts) "
            "VALUES ('2026-07-16', 0, 0, 0, 1, '{\"gamejob\": 17, \"wanted\": 0}')")
        conn.commit()
        conn.close()
        ok = self.db.get_sources_succeeded_today("2026-07-16")
        self.assertIn("gamejob", ok)
        self.assertNotIn("wanted", ok)  # 0건은 성공 근거가 아님

    def test_other_dates_excluded(self):
        """어제의 성공은 오늘 경고를 억제하지 못함"""
        self.db.insert_scrape_log(make_log(run_date="2026-07-15",
                                           counts={"jobkorea": 4}, successful=["jobkorea"]))
        self.assertEqual(self.db.get_sources_succeeded_today("2026-07-16"), set())


if __name__ == "__main__":
    unittest.main()
