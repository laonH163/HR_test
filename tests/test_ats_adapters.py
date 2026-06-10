import unittest

from src.scraper.ats.base import BaseATSAdapter
from src.scraper.ats.jobkorea_company import _META_CUT


class TestATSAdapterFilters(unittest.TestCase):
    """ATS 어댑터의 재무 직무 필터와 제목 추출 로직 검증 (네트워크 비의존 순수 로직)."""

    def setUp(self):
        # make_session은 requests.Session 객체만 생성(네트워크 호출 없음)
        self.adapter = BaseATSAdapter(source="test", company_name="테스트")

    def test_finance_titles_pass(self):
        """실제 게임사 재무 공고 제목은 통과해야 함"""
        positives = [
            "[컴투스] 재무기획(FP&A) 담당자 (4년-7년)",
            "[Finance Div.] Tax Manager (3년 이상)",
            "[웹젠] 자금(신입/경력)",
            "[스마일게이트][윤리경영] 내부감사 및 경영진단 담당 (과장급)",
            "[NC][단기계약직] Payroll 업무 보조 및 운영",
            "[Finance Div.] IR Manager (7년 이상)",
            "연결회계팀원(회계사)",
            "하이브IM 세무조정 담당자 채용",
            "빅게임스튜디오 원가회계 담당자 영입"
        ]
        for title in positives:
            self.assertTrue(self.adapter.is_finance_job(title), f"통과해야 함: {title}")

    def test_non_finance_titles_filtered(self):
        """비재무 제목은 걸러져야 함 — 특히 'hiring'의 'ir' 부분문자열 오탐 방지"""
        negatives = [
            "Server Programmer (we are hiring now)",  # hiring 속 'ir' 오탐 방지
            "[슈터본부] 백엔드 엔지니어",
            "UI/UX 디자이너",
            "게임 기획자 모집",
            "Product Owner (7년 이상)",
            "Senior Animator",
            "고객감사 이벤트 운영 담당",  # '감사' 부분매칭 오탐 방지
            "감사패 제작 디자이너",
            "[Finance Div.][Legal Dept.] Legal Counsel",
            "[Finance Div.] 공정거래 공시 Compliance Specialist",
            "인사(보상)/전산자산 각 부문별 모집"
        ]
        for title in negatives:
            self.assertFalse(self.adapter.is_finance_job(title), f"걸러져야 함: {title}")

    def test_build_posting_has_required_keys(self):
        """build_posting이 DB 파이프라인 필수 키를 모두 채우는지"""
        posting = self.adapter.build_posting(
            "test_1", "재무 담당자", "https://example.com/1", "본문", "2026-06-01", "서울"
        )
        required = ["id", "source", "company_name", "title", "origin_url", "location",
                    "posted_at", "status", "raw_html", "first_seen_at", "last_updated_at"]
        for key in required:
            self.assertIn(key, posting)
        self.assertEqual(posting["status"], "ACTIVE")
        self.assertEqual(posting["source"], "test")

    def test_jobkorea_title_extraction(self):
        """잡코리아 목록 텍스트에서 메타(경력/지역/마감일/직무분류) 제거 후 제목만 분리"""
        raw = "마케팅 정산 담당자 모집 (계약직) 신입 서울 D-22 회계담당자"
        title = _META_CUT.split(raw, maxsplit=1)[0].strip()
        self.assertEqual(title, "마케팅 정산 담당자 모집 (계약직)")

        raw2 = "[플랫폼본부] 웹 프론트엔드 엔지니어 (계약직) new 경력 경기 무관 상시채용"
        title2 = _META_CUT.split(raw2, maxsplit=1)[0].strip()
        self.assertEqual(title2, "[플랫폼본부] 웹 프론트엔드 엔지니어 (계약직)")


if __name__ == "__main__":
    unittest.main()
