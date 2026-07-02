import os
import unittest
from datetime import date

from src.database.db_manager import DBManager
from src.reporter.telegram_sender import TelegramSender
from src.scraper.ats.jobkorea_company import _deadline_from_dday


class TestDeadlineParsing(unittest.TestCase):
    """잡코리아 D-N 배지 → 절대 마감일 환산 검증."""

    def test_dday_badge_converted_to_absolute_date(self):
        raw = "[웹젠] 자금(신입/경력) 경력 경기 무관 D-8 재무담당자"
        self.assertEqual(_deadline_from_dday(raw, today=date(2026, 7, 2)), "2026-07-10")

    def test_no_badge_returns_none(self):
        """상시채용/채용시 마감 등 배지 없는 공고는 None."""
        self.assertIsNone(_deadline_from_dday("[컴투스] 재무 담당자 경력 서울 상시채용"))
        self.assertIsNone(_deadline_from_dday(""))
        self.assertIsNone(_deadline_from_dday(None))

    def test_dday_zero(self):
        self.assertEqual(_deadline_from_dday("회계 담당 D-0 마감임박", today=date(2026, 7, 2)), "2026-07-02")


class TestDeadlineUpsert(unittest.TestCase):
    """deadline 컬럼 마이그레이션·저장·변경 감지 검증."""

    def setUp(self):
        self.db_path = "data/test_deadline_master.db"
        self.db = DBManager(db_path=self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except PermissionError:
                pass

    def _posting(self, deadline=None, raw="본문"):
        return {
            "id": "webzen_1", "source": "webzen", "company_name": "웹젠",
            "title": "자금 담당자", "origin_url": "https://example.com", "location": "경기",
            "posted_at": "2026-07-02", "status": "ACTIVE", "raw_html": raw,
            "first_seen_at": "2026-07-02 09:00:00", "last_updated_at": "2026-07-02 09:00:00",
            "deadline": deadline,
        }

    def _stored_deadline(self):
        conn = self.db.get_connection()
        row = conn.execute("SELECT deadline FROM job_postings WHERE id='webzen_1'").fetchone()
        conn.close()
        return row["deadline"]

    def test_deadline_stored_on_insert(self):
        self.db.upsert_job_posting(self._posting(deadline="2026-07-10"))
        self.assertEqual(self._stored_deadline(), "2026-07-10")

    def test_deadline_change_marks_modified(self):
        """마감일 연장은 본문이 같아도 MODIFIED로 잡혀야 함."""
        self.db.upsert_job_posting(self._posting(deadline="2026-07-10"))
        is_modified, is_new = self.db.upsert_job_posting(self._posting(deadline="2026-07-20"))
        self.assertFalse(is_new)
        self.assertTrue(is_modified)
        self.assertEqual(self._stored_deadline(), "2026-07-20")

    def test_none_deadline_preserves_existing(self):
        """수집처가 마감일을 안 주는 날(None)에도 기존 저장값은 유지."""
        self.db.upsert_job_posting(self._posting(deadline="2026-07-10"))
        is_modified, _ = self.db.upsert_job_posting(self._posting(deadline=None))
        self.assertFalse(is_modified)
        self.assertEqual(self._stored_deadline(), "2026-07-10")


class TestTelegramUrgentSection(unittest.TestCase):
    """텔레그램 마감임박(3일 이내) 섹션 노출 검증."""

    def _job(self, jid, deadline, title="자금 담당자"):
        return {
            "id": jid, "company_name": "웹젠", "title": title,
            "origin_url": f"https://example.com/{jid}", "posted_at": "2026-06-20",
            "deadline": deadline,
        }

    def test_urgent_jobs_listed(self):
        os.environ["RUN_DATE_STR"] = "2026-07-02"
        sender = TelegramSender()
        postings = [
            self._job("a1", "2026-07-03", title="자금 담당자 임박"),   # D-1 → 노출
            self._job("a2", "2026-07-20", title="회계 담당자 여유"),   # D-18 → 미노출
            self._job("a3", None, title="세무 담당자 상시"),           # 상시 → 미노출
        ]
        text = sender.build_daily_briefing_message(0, 0, 0, postings)
        self.assertIn("마감 임박 공고", text)
        self.assertIn("자금 담당자 임박", text)
        self.assertIn("D-1", text)
        # 여유/상시 공고는 임박 섹션 밖(기존 목록)에만 있어야 함
        urgent_section = text.split("마감 임박 공고")[1].split("\n\n")[0]
        self.assertNotIn("회계 담당자 여유", urgent_section)

    def test_no_urgent_section_when_none(self):
        os.environ["RUN_DATE_STR"] = "2026-07-02"
        sender = TelegramSender()
        text = sender.build_daily_briefing_message(0, 0, 0, [self._job("b1", None)])
        self.assertNotIn("마감 임박 공고", text)


if __name__ == "__main__":
    unittest.main()
