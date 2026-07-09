import unittest
from datetime import date

from src.utils.dateparse import parse_deadline_badge


class TestDeadlineBadgeParsing(unittest.TestCase):
    """게임잡·사람인 공용 마감 배지 파서 — 실측 표기 형태 회귀 테스트"""

    def setUp(self):
        self.today = date(2026, 7, 9)

    def test_saramin_absolute_with_weekday(self):
        """사람인 실측: '~ 07/31(금)' — 물결·공백·요일 괄호 포함"""
        self.assertEqual(parse_deadline_badge("~ 07/31(금)", self.today), "2026-07-31")
        self.assertEqual(parse_deadline_badge("~ 09/04(금)", self.today), "2026-09-04")

    def test_gamejob_absolute_compact(self):
        """게임잡 실측: '~07/31' 붙여쓰기"""
        self.assertEqual(parse_deadline_badge("계약직 ~07/31 6일 전 등록", self.today), "2026-07-31")

    def test_dday_badge(self):
        self.assertEqual(parse_deadline_badge("D-3", self.today), "2026-07-12")

    def test_today_and_tomorrow_close(self):
        self.assertEqual(parse_deadline_badge("오늘마감", self.today), "2026-07-09")
        self.assertEqual(parse_deadline_badge("내일 마감", self.today), "2026-07-10")

    def test_open_ended_returns_none(self):
        """상시/채용시/빈 값은 None — DB 기존 마감일을 지우지 않도록"""
        for text in ["상시채용", "상시", "채용시", "", None]:
            self.assertIsNone(parse_deadline_badge(text, self.today))

    def test_year_rollover(self):
        """연말에 '~01/15'는 내년 마감으로 해석"""
        self.assertEqual(parse_deadline_badge("~01/15", date(2026, 12, 20)), "2027-01-15")


if __name__ == "__main__":
    unittest.main()
