import unittest
import os
from src.reporter.telegram_sender import TelegramSender

class TestTelegramReporter(unittest.TestCase):
    def test_briefing_message_building(self):
        """텔레그램 마크다운 한글 브리핑 메시지 정상 합성 검증"""
        sender = TelegramSender()

        sample_postings = [
            {
                "id": "wanted_111",
                "company_name": "더블유게임즈",
                "title": "재무회계 마스터",
                "origin_url": "https://wanted.co.kr/wd/111",
                "posted_at": "2026-05-21"
            }
        ]

        # 환경변수 모의 설정 주입
        os.environ["RUN_DATE_STR"] = "2026-05-21"
        os.environ["GITHUB_RUN_ID"] = "test-run"

        text = sender.build_daily_briefing_message(1, 0, 0, sample_postings)

        # 주요 정형 표기 구성 검증 (HTML 태그 및 통계 포함 여부)
        self.assertIn("게임사 재무공고 브리핑", text)
        self.assertIn("신규 등록 공고: <b>1 건</b>", text)
        self.assertIn("더블유게임즈", text)
        self.assertIn("https://wanted.co.kr/wd/111", text)

if __name__ == '__main__':
    unittest.main()
