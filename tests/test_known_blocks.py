"""'알려진 차단' 소스 처리 검증.

고칠 방법이 없는 차단(원티드 = 러너 IP 차단)을 매일 경고로 띄우면 경고가 무뎌지므로
정보 줄로 내린다. 다만 ① 복구되면 즉시 알리고 ② 오래 이어지면 다시 경고로 올려야 한다.
이 세 상태 전환이 정확히 동작하는지, 그리고 일반 실패 경고를 삼키지 않는지 확인한다.
"""
import os
import sqlite3
import tempfile
import unittest

from src.database.db_manager import DBManager
from src.reporter.telegram_sender import TelegramSender
from src.utils.known_blocks import describe, is_known_blocked, split_known_blocked


class TestKnownBlockRegistry(unittest.TestCase):
    def test_wanted_is_registered(self):
        self.assertTrue(is_known_blocked("wanted"))
        self.assertTrue(is_known_blocked("WANTED"))  # 대소문자 무관
        self.assertIsNotNone(describe("wanted"))

    def test_other_sources_not_registered(self):
        for src in ("saramin", "jobkorea", "gamejob", "krafton"):
            self.assertFalse(is_known_blocked(src), src)
        self.assertIsNone(describe("saramin"))

    def test_split_separates_known_from_others(self):
        known, others = split_known_blocked(["wanted", "jobkorea", "saramin"])
        self.assertEqual(known, ["wanted"])
        self.assertEqual(others, ["jobkorea", "saramin"])

    def test_split_handles_empty(self):
        self.assertEqual(split_known_blocked([]), ([], []))
        self.assertEqual(split_known_blocked(None), ([], []))


class TestBriefingKnownBlockDisplay(unittest.TestCase):
    def setUp(self):
        os.environ["RUN_DATE_STR"] = "2026-07-22"
        self.sender = TelegramSender()

    def _build(self, **kwargs):
        return self.sender.build_daily_briefing_message(0, 0, 0, [], None, **kwargs)

    def test_known_block_shows_as_info_not_warning(self):
        """평소: 정보 한 줄로만 나가고 '전 소스 정상' 표시를 가리지 않는다"""
        text = self._build(known_blocked=[{
            "source": "wanted", "summary": "러너 IP 차단(원티드 WAF)",
            "last_success": "2026-07-16", "days": 6, "stale": False,
        }])
        self.assertIn("ℹ️ WANTED", text)
        self.assertIn("조치 불요", text)
        self.assertIn("6일째", text)
        self.assertIn("🩺 수집 상태: 전 소스 정상", text)  # 경고 섹션으로 승격되지 않음
        self.assertNotIn("⚠️ 접속 실패", text)

    def test_stale_known_block_escalates_to_warning(self):
        """차단이 오래되면 경고로 승격 — 남은 활성 공고가 좀비일 수 있어 사람 확인 필요"""
        text = self._build(known_blocked=[{
            "source": "wanted", "summary": "러너 IP 차단(원티드 WAF)",
            "last_success": "2026-07-01", "days": 21, "active_count": 1, "stale": True,
        }])
        self.assertIn("🩺 <b>수집 상태 점검:</b>", text)
        self.assertIn("차단 21일째", text)
        self.assertIn("활성 1건이 실제로 마감됐는지 수동 확인 필요", text)
        self.assertNotIn("조치 불요", text)  # 정보 줄과 중복 표시되지 않아야 함

    def test_recovery_is_announced(self):
        """차단이 풀리면 등록 해제가 필요하므로 눈에 띄게 알린다"""
        text = self._build(recovered_known=["wanted"])
        self.assertIn("✅ 차단 해제 확인", text)
        self.assertIn("WANTED", text)
        self.assertIn("known_blocks 등록 해제 필요", text)

    def test_recovery_only_omits_hold_notice(self):
        """복구 알림만 있는 날에 '마감 보류로 보호 중' 안내문이 붙으면 사실과 어긋난다"""
        text = self._build(recovered_known=["wanted"])
        self.assertNotIn("마감 보류로 보호 중", text)

    def test_failure_warning_keeps_hold_notice(self):
        """실패성 경고가 있을 때는 기존 안내문이 그대로 유지돼야 한다(회귀 방지)"""
        text = self._build(failed_sources=["jobkorea"], recovered_known=["wanted"])
        self.assertIn("마감 보류로 보호 중", text)

    def test_normal_failures_still_warn(self):
        """알려진 차단 처리가 일반 실패 경고를 삼키면 안 된다(무음 실패 방지)"""
        text = self._build(
            failed_sources=["jobkorea"],
            known_blocked=[{"source": "wanted", "summary": "러너 IP 차단",
                            "last_success": "2026-07-16", "days": 6, "stale": False}],
        )
        self.assertIn("⚠️ 접속 실패", text)
        self.assertIn("JOBKOREA", text)
        self.assertIn("ℹ️ WANTED", text)

    def test_unknown_active_count_still_escalates(self):
        """활성 수 조회가 실패해 모르는 상태면 보수적으로 경고를 유지해야 한다"""
        text = self._build(known_blocked=[{
            "source": "wanted", "summary": "러너 IP 차단", "last_success": "2026-07-01",
            "days": 21, "active_count": None, "stale": True,
        }])
        self.assertIn("차단 21일째", text)
        self.assertIn("남은 활성 공고", text)  # 건수를 모르면 뭉뚱그려 표기
        self.assertIn("수동 확인 필요", text)

    def test_pipeline_errors_surface_as_warning(self):
        """수집은 됐는데 저장·마감판정이 조용히 실패한 경우가 브리핑에 드러나야 한다"""
        text = self._build(pipeline_errors=["DB 적재/분류 실패 10건", "마감 판정(Delta) 실패"])
        self.assertIn("⚠️ 파이프라인 단계 실패", text)
        self.assertIn("DB 적재/분류 실패 10건", text)
        self.assertIn("마감 판정(Delta) 실패", text)
        self.assertNotIn("🩺 수집 상태: 전 소스 정상", text)

    def test_no_known_block_keeps_previous_behavior(self):
        text = self._build()
        self.assertIn("🩺 수집 상태: 전 소스 정상", text)
        self.assertNotIn("ℹ️", text)


class TestLastCollectedDate(unittest.TestCase):
    """차단 경과일 계산의 근거가 되는 '마지막 수확일' 조회 검증.

    판정 기준이 '접속 성공'이 아니라 '실제 수집 건수>0'이어야 한다 — 접속만 되고 0건인
    상태를 성공으로 세면 경과일이 매일 리셋돼 좀비 경고가 영원히 안 뜬다.
    """

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE scrape_logs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_date TEXT, newly_added INTEGER, modified_count INTEGER,
                closed_count INTEGER, is_success INTEGER, error_log TEXT,
                source_counts TEXT, successful_sources TEXT
            )""")
        conn.execute("""
            CREATE TABLE job_postings (
                id TEXT PRIMARY KEY, source TEXT, company_name TEXT, title TEXT,
                origin_url TEXT, location TEXT, posted_at TEXT, status TEXT,
                raw_html TEXT, first_seen_at TEXT, last_updated_at TEXT, deadline TEXT
            )""")
        rows = [
            # (run_date, source_counts, successful_sources)
            ("2026-07-15", '{"wanted": 1, "saramin": 10}', '["wanted", "saramin"]'),
            ("2026-07-16", '{"wanted": 1, "saramin": 10}', '["wanted", "saramin"]'),
            ("2026-07-17", '{"saramin": 10}', '["saramin"]'),
            ("2026-07-22", '{"saramin": 11}', '["saramin"]'),
        ]
        for d, sc, ss in rows:
            conn.execute(
                "INSERT INTO scrape_logs (run_date, newly_added, modified_count, closed_count,"
                " is_success, error_log, source_counts, successful_sources)"
                " VALUES (?, 0, 0, 0, 1, NULL, ?, ?)", (d, sc, ss))
        conn.commit()
        conn.close()
        self.db = DBManager(db_path=self.db_path)

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except OSError:
            pass

    def test_returns_latest_collected_date(self):
        self.assertEqual(self.db.get_last_collected_date("wanted"), "2026-07-16")
        self.assertEqual(self.db.get_last_collected_date("saramin"), "2026-07-22")

    def test_returns_none_when_never_collected(self):
        self.assertIsNone(self.db.get_last_collected_date("gamejob"))

    def test_connected_but_zero_result_is_not_success(self):
        """접속 성공 목록에 있어도 수집 0건이면 '마지막 수확일'이 아니다.

        실측 근거: run 49~55에서 원티드·게임잡이 '접속 성공 + 0건'으로 11회 기록됐고,
        그때가 바로 검색이 열화된 시점이었다(복구가 아니었다)."""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO scrape_logs (run_date, newly_added, modified_count, closed_count,"
            " is_success, error_log, source_counts, successful_sources)"
            " VALUES ('2026-07-23', 0, 0, 0, 1, '0건 플랫폼(점검 필요): wanted',"
            " '{\"wanted\": 0, \"saramin\": 11}', '[\"wanted\", \"saramin\"]')")
        conn.commit()
        conn.close()
        # 접속은 성공했지만 0건 → 마지막 수확일은 여전히 7/16이어야 한다
        self.assertEqual(self.db.get_last_collected_date("wanted"), "2026-07-16")

    def test_legacy_row_without_successful_sources_counts(self):
        """successful_sources 컬럼이 없던 과거 행도 수집 건수>0이면 수확으로 인정한다"""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO scrape_logs (run_date, newly_added, modified_count, closed_count,"
            " is_success, error_log, source_counts, successful_sources)"
            " VALUES ('2026-07-20', 0, 0, 0, 1, NULL, '{\"gamejob\": 16}', NULL)")
        conn.commit()
        conn.close()
        self.assertEqual(self.db.get_last_collected_date("gamejob"), "2026-07-20")

    def test_sources_collected_today_excludes_zero_result(self):
        """'접속 성공 + 0건'은 오늘 수확한 소스가 아니다.

        이 구분이 무너지면 0건 소스가 제 손으로 자기 경고를 지워 '전 소스 정상'이
        찍힌다(2026-07-22 코덱스 교차검토 지적, 과거 11회 실재)."""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO scrape_logs (run_date, newly_added, modified_count, closed_count,"
            " is_success, error_log, source_counts, successful_sources)"
            " VALUES ('2026-07-23', 0, 0, 0, 1, NULL,"
            " '{\"wanted\": 0, \"saramin\": 11}', '[\"wanted\", \"saramin\"]')")
        conn.commit()
        conn.close()
        collected = self.db.get_sources_collected_today("2026-07-23")
        self.assertIn("saramin", collected)
        self.assertNotIn("wanted", collected)  # 접속은 성공했지만 수확 0건
        # 대조: 기존 '접속 성공' 기준에는 원티드가 들어간다(경고 보정 목적이 다름)
        self.assertIn("wanted", self.db.get_sources_succeeded_today("2026-07-23"))

    def test_active_count_by_source(self):
        conn = sqlite3.connect(self.db_path)
        for jid, src, status in [("wanted_1", "wanted", "ACTIVE"),
                                 ("wanted_2", "wanted", "CLOSED"),
                                 ("saramin_1", "saramin", "ACTIVE")]:
            conn.execute(
                "INSERT INTO job_postings (id, source, company_name, title, origin_url,"
                " location, posted_at, status, raw_html, first_seen_at, last_updated_at, deadline)"
                " VALUES (?, ?, '회사', '재무 담당자', 'https://example.com', '서울',"
                " '2026-07-16', ?, '', '2026-07-16', '2026-07-16', NULL)", (jid, src, status))
        conn.commit()
        conn.close()
        self.assertEqual(self.db.get_active_count_by_source("wanted"), 1)
        self.assertEqual(self.db.get_active_count_by_source("saramin"), 1)
        self.assertEqual(self.db.get_active_count_by_source("gamejob"), 0)


class TestBlockedSinceFallback(unittest.TestCase):
    """수집 이력이 아예 없을 때 경과일을 셀 기준(등록된 차단 시작일) 검증"""

    def test_since_is_available_for_registered_source(self):
        from src.utils.known_blocks import blocked_since
        self.assertEqual(blocked_since("wanted"), "2026-07-16")
        self.assertIsNone(blocked_since("saramin"))


if __name__ == "__main__":
    unittest.main()
