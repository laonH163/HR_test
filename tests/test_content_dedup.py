import os
import unittest

from src.utils.dedup import content_key, source_rank
from src.reporter.telegram_sender import TelegramSender


class TestContentKey(unittest.TestCase):
    """교차 소스 중복 판별 키 — 2026-07-08 컴투스 실측 사례 기반"""

    def test_com2us_holdings_cross_source_match(self):
        """컴투스 기업페이지(프리픽스에 홀딩스) vs 게임잡(회사명이 홀딩스) → 같은 키"""
        k1 = content_key("컴투스", "[컴투스홀딩스] 재무관리 팀장 (10년 이상)")
        k2 = content_key("컴투스 홀딩스", "재무관리 팀장 (10년 이상)")
        self.assertEqual(k1, k2)
        self.assertEqual(k1[0], "컴투스홀딩스")  # 더 구체적인 회사명으로 승격

    def test_corp_token_and_prefix_variants_match(self):
        """법인표기((주)/㈜)·'[회사명]' 프리픽스 유무가 갈려도 같은 키 (시프트업 실측)"""
        k1 = content_key("시프트업", "경리/회계 담당자 (계약직)")
        k2 = content_key("(주)시프트업", "[시프트업] 경리/회계 담당자 (계약직)")
        self.assertEqual(k1, k2)

    def test_non_company_prefix_not_promoted(self):
        """'[경력]' 같은 비회사 프리픽스는 회사키로 승격하지 않고 낱말을 제목에 남긴다 (펄어비스 실측).

        대괄호 자체는 벗겨지지만( '[전략실]…' ↔ '전략실…' 병합용 ) 안의 낱말은 보존되므로
        신입/경력 구분은 그대로 살아 있다."""
        k1 = content_key("펄어비스", "[경력] 내부회계 담당자 모집")
        k2 = content_key("(주)펄어비스", "[펄어비스] [경력] 내부회계 담당자 모집")
        self.assertEqual(k1, k2)
        self.assertEqual(k1[0], "펄어비스")
        self.assertIn("경력", k1[1])

    def test_bracket_word_still_distinguishes_postings(self):
        """대괄호를 벗겨도 안의 낱말이 남아 '[신입]'과 '[경력]' 공고는 여전히 별개 키"""
        k_new = content_key("펄어비스", "[신입] 내부회계 담당자 모집")
        k_exp = content_key("펄어비스", "[경력] 내부회계 담당자 모집")
        self.assertNotEqual(k_new, k_exp)

    def test_nx3games_alias_and_department_prefix_merge(self):
        """영문 사명(게임잡) ↔ 한글 법인명(잡코리아) + 부서 프리픽스 차이 병합 (2026-07-21 실측).

        잡코리아는 '[NX3GAMES] 전략실 회계담당자 (주니어)', 게임잡은 '[전략실] 회계담당자 (주니어)'로
        같은 공고를 실어 카드가 둘로 갈렸다."""
        k1 = content_key("㈜엔엑스쓰리게임즈", "[NX3GAMES] 전략실 회계담당자 (주니어)")
        k2 = content_key("NX3GAMES", "[전략실] 회계담당자 (주니어)")
        self.assertEqual(k1, k2)
        self.assertEqual(k1[0], "엔엑스쓰리게임즈")

    def test_alias_does_not_merge_different_postings(self):
        """별칭 통일이 서로 다른 직무까지 묶지는 않는다 — 오병합 방지"""
        k1 = content_key("NX3GAMES", "[전략실] 회계담당자 (주니어)")
        k2 = content_key("NX3GAMES", "[전략실] 회계담당자 (시니어)")
        self.assertNotEqual(k1, k2)

    def test_different_company_same_title_not_merged(self):
        """회사가 다르면 제목이 같아도 다른 키 — 오병합 방지"""
        k1 = content_key("넥슨", "회계 담당자")
        k2 = content_key("넷마블", "회계 담당자")
        self.assertNotEqual(k1, k2)

    def test_holdings_is_not_parent_company(self):
        """컴투스 단독 공고와 컴투스홀딩스 공고는 병합하지 않는다 (별도 법인)"""
        k1 = content_key("컴투스", "재무 담당자")
        k2 = content_key("컴투스 홀딩스", "재무 담당자")
        self.assertNotEqual(k1, k2)

    def test_source_rank_official_over_platform(self):
        self.assertEqual(source_rank("com2us"), 0)
        self.assertEqual(source_rank("shiftup"), 0)
        for platform in ["wanted", "saramin", "jobkorea", "gamejob"]:
            self.assertEqual(source_rank(platform), 1)


class TestTelegramCrossSourceMerge(unittest.TestCase):
    """텔레그램 브리핑에서 교차 소스 중복이 1건으로 병합되고 공식 소스가 우선되는지"""

    def setUp(self):
        os.environ["RUN_DATE_STR"] = "2026-07-08"
        self.sender = TelegramSender()

    def _com2us_pair(self):
        """게임잡(플랫폼)이 먼저, 컴투스 기업페이지(공식)가 나중 — 대표 카드 교체 경로 검증"""
        return [
            {
                "id": "gamejob_282441", "source": "gamejob",
                "company_name": "컴투스 홀딩스",
                "title": "재무관리 팀장 (10년 이상)",
                "origin_url": "https://www.gamejob.co.kr/Recruit/GI_Read/View?GI_No=282441",
                "posted_at": "2026-07-08",
            },
            {
                "id": "com2us_49534055", "source": "com2us",
                "company_name": "컴투스",
                "title": "[컴투스홀딩스] 재무관리 팀장 (10년 이상)",
                "origin_url": "https://www.jobkorea.co.kr/Recruit/GI_Read/49534055",
                "posted_at": "2026-07-08",
            },
        ]

    def test_merged_into_single_new_posting(self):
        text = self.sender.build_daily_briefing_message(2, 0, 0, self._com2us_pair())
        self.assertIn("신규 등록 공고: <b>1 건</b>", text)
        # 두 소스 링크가 모두 살아 있어야 함 (출처 병합)
        self.assertIn("GI_Read/49534055", text)
        self.assertIn("GI_No=282441", text)

    def test_official_source_becomes_primary(self):
        text = self.sender.build_daily_briefing_message(2, 0, 0, self._com2us_pair())
        # 대표 카드가 공식(com2us) 쪽으로 교체되어 회사명은 '컴투스'로 표기
        self.assertIn("[컴투스]", text)
        # 바로가기 링크는 공식 → 플랫폼 순
        self.assertLess(text.index("COM2US"), text.index("GAMEJOB"))


if __name__ == "__main__":
    unittest.main()
