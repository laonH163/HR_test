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

    def test_new_company_badge(self):
        """전체 이력에 없던 회사의 신규 공고에는 🆕 배지, 기존 회사에는 없음."""
        sender = TelegramSender()
        os.environ["RUN_DATE_STR"] = "2026-07-09"
        postings = [
            {"id": "saramin_1", "source": "saramin", "company_name": "신생게임즈",
             "title": "재무 담당자", "origin_url": "https://example.com/1", "posted_at": "2026-07-09"},
            {"id": "saramin_2", "source": "saramin", "company_name": "(주)컴투스",
             "title": "회계 담당자", "origin_url": "https://example.com/2", "posted_at": "2026-07-09"},
        ]
        text = sender.build_daily_briefing_message(
            2, 0, 0, postings, known_companies=["컴투스", "넥슨"])
        self.assertIn("🆕 <b>[신생게임즈]</b>", text)
        self.assertNotIn("🆕 <b>[(주)컴투스]</b>", text)  # 법인표기 달라도 기존 회사로 인식

        # known_companies 미전달(레거시)이면 배지 없음
        text2 = sender.build_daily_briefing_message(2, 0, 0, postings)
        self.assertNotIn("🆕", text2)

    def test_mass_close_and_drop_warning_lines(self):
        """일괄 소멸·수집량 급감 경고 라인 노출 (미전달 시 미노출)"""
        sender = TelegramSender()
        os.environ["RUN_DATE_STR"] = "2026-07-09"

        text = sender.build_daily_briefing_message(
            0, 0, 0, [],
            mass_close_held=["com2us", "webzen"],
            source_drops={"saramin": {"today": 2, "avg": 9.4}},
        )
        self.assertIn("수집 상태 점검", text)
        self.assertIn("공고 일괄 소멸 의심", text)
        self.assertIn("COM2US · WEBZEN", text)
        self.assertIn("수집량 급감", text)
        self.assertIn("SARAMIN 2건(평소 9건)", text)
        # 경고는 메인 콘텐츠를 해치지 않도록 대시보드 링크 직전(최하단)에 위치
        self.assertLess(text.index("오늘 감지된 핵심 델타 통계"), text.index("수집 상태 점검"))
        self.assertLess(text.index("수집 상태 점검"), text.index("실시간 웹 대시보드"))

        clean = sender.build_daily_briefing_message(0, 0, 0, [])
        self.assertNotIn("일괄 소멸", clean)
        self.assertNotIn("수집량 급감", clean)
        self.assertIn("수집 상태: 전 소스 정상", clean)  # 정상인 날은 한 줄 확인

    def test_zero_platform_warning_line(self):
        """'성공했지만 0건' 플랫폼 경고가 브리핑에 노출되는지 — 무음 고장 가시화"""
        sender = TelegramSender()
        os.environ["RUN_DATE_STR"] = "2026-07-09"

        text = sender.build_daily_briefing_message(
            0, 0, 0, [], zero_platforms=["wanted", "gamejob"]
        )
        self.assertIn("검색 0건", text)
        self.assertIn("GAMEJOB · WANTED", text)

        # 0건 플랫폼이 없으면 경고 라인도 없어야 함
        clean_text = sender.build_daily_briefing_message(0, 0, 0, [], zero_platforms=[])
        self.assertNotIn("검색 0건", clean_text)

if __name__ == '__main__':
    unittest.main()


class TestPartialSourceWarningSurfaced(unittest.TestCase):
    """검색 일부 실패로 '마감 판정 보류' 중인 소스는 브리핑에 보여야 한다.

    2026-07-21 코덱스 3차 교차검토: partial_sources를 계산해 마감 보류에는 쓰면서
    error_log·텔레그램 어디에도 노출하지 않아, 보류가 며칠 이어져 이미 마감된 공고가
    ACTIVE로 남아도(좀비) 운영자가 알 방법이 없었다. 이 프로젝트 운영 원칙이
    '경고 없으면 할 일 없음'이라 미노출은 곧 무한 방치를 뜻한다."""

    def _build(self, **kwargs):
        from src.reporter.telegram_sender import TelegramSender
        return TelegramSender().build_daily_briefing_message(
            0, 0, 0, [], None, **kwargs)

    def test_partial_source_appears_in_health_section(self):
        msg = self._build(partial_sources=["saramin"])
        self.assertIn("마감 판정 보류", msg)
        self.assertIn("SARAMIN", msg)

    def test_no_partial_keeps_all_clear_line(self):
        msg = self._build(partial_sources=[])
        self.assertIn("전 소스 정상", msg)
        self.assertNotIn("마감 판정 보류", msg)
