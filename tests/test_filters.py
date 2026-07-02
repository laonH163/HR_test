import unittest

from src.scraper import filters


class TestUnifiedFinanceFilter(unittest.TestCase):
    """공통 필터 모듈의 통합 결정 사항 고정 테스트.

    특히 기존 4벌 복붙 시절 소스마다 달랐던 '채용'/'안내' 블랙리스트 판정을
    라이브 검증된 방침(복합어만 차단)으로 통일했음을 보증한다.
    """

    def test_recruit_word_in_finance_title_passes(self):
        """'채용'이 제목 끝에 붙은 정상 재무 공고는 모든 소스에서 통과해야 함."""
        positives = [
            "하이브IM 세무조정 담당자 채용",
            "재무회계 담당자 채용",
            "회계팀 신입 채용 공고",
            "재무팀 채용 안내",
        ]
        for title in positives:
            self.assertTrue(filters.is_finance_job(title), f"통과해야 함: {title}")

    def test_hr_recruiter_roles_blocked(self):
        """HR 리크루터/비사무 직무는 복합어 블랙리스트로 차단."""
        negatives = [
            "채용담당자 (재무 부문 채용 지원)",   # HR 리크루터
            "재무 서비스센터 안내데스크 운영",     # 프런트 직무
            "인사(보상) 담당자",
            "급여 정산 아웃소싱 상담원",
        ]
        for title in negatives:
            self.assertFalse(filters.is_finance_job(title), f"걸러져야 함: {title}")

    def test_casino_hotel_context_blocked(self):
        """카지노/호텔/리조트 업종은 회사명·컨텍스트 어느 쪽에 있어도 차단."""
        self.assertFalse(filters.is_game_company("람정제주개발", "카지노 회계 담당자"))
        self.assertFalse(filters.is_game_company("게임호텔앤리조트", "재무 담당"))
        self.assertFalse(filters.is_game_company("일반기업", "호텔 서빙 및 게임 딜러"))

    def test_game_company_by_name_or_context(self):
        """회사명 또는 컨텍스트의 게임 키워드로 게임사 판별 (대소문자 무시)."""
        self.assertTrue(filters.is_game_company("넥슨코리아", "재무팀 자금 담당자"))
        self.assertTrue(filters.is_game_company("NEXON Korea", ""))
        self.assertTrue(filters.is_game_company("일반서비스", "게임 개발 스튜디오에서 회계를 구합니다"))
        self.assertFalse(filters.is_game_company("대형제조업", "생산 관리 세무 조정 담당자"))


if __name__ == "__main__":
    unittest.main()
