import unittest

from bs4 import BeautifulSoup

from src.scraper.ats.base import BaseATSAdapter
from src.scraper.ats.jobkorea_company import _META_CUT, _norm_company, JobKoreaCompanyAdapter


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


class TestJobKoreaCompanyGuardrail(unittest.TestCase):
    """잡코리아 company_id 오매핑 차단용 회사명 교차검증(가드레일) 로직 검증.

    실제 라이브 title 샘플(2026-06-22)을 사용. 네트워크 비의존(soup 직접 구성).
    """

    def _verify(self, company_name, title, aliases=None):
        adapter = JobKoreaCompanyAdapter(
            "0", company_name, "test", verify_aliases=aliases, fetch_detail=False
        )
        soup = BeautifulSoup(f"<html><head><title>{title}</title></head></html>", "html.parser")
        return adapter._verify_company(soup)

    def test_legit_companies_pass(self):
        """등록명과 페이지 회사명이 같은 정상 케이스(법인표기 차이 포함)는 통과."""
        cases = [
            ("넥슨", "(주)넥슨코리아 채용 - 2026년 진행 중인 공고 총 29건 | 잡코리아"),
            ("넷마블", "넷마블(주) 채용 - 2026년 진행 중인 공고 총 4건 | 잡코리아"),
            ("스마일게이트", "주식회사스마일게이트 채용 - 진행 중인 공고 | 잡코리아"),
            ("데브시스터즈", "데브시스터즈㈜ 채용 - 진행 중인 공고 | 잡코리아"),
            ("넥슨게임즈", "㈜넥슨게임즈 채용 - 진행 중인 공고 확인하기 | 잡코리아"),
        ]
        for name, title in cases:
            self.assertTrue(self._verify(name, title), f"통과해야 함: {name} / {title}")

    def test_alias_companies_pass(self):
        """페이지 회사명이 등록명과 표기가 다른 정상 케이스는 별칭으로 통과."""
        self.assertTrue(self._verify("엔씨소프트", "NC 채용 - 2026년 진행 중인 공고 총 64건 | 잡코리아",
                                     aliases=["NC", "엔씨소프트"]))
        self.assertTrue(self._verify("NHN", "엔에이치엔㈜ 채용 - 2026년 진행 중인 공고 총 5건 | 잡코리아",
                                     aliases=["엔에이치엔", "NHN"]))

    def test_mismapped_companies_rejected(self):
        """company_id가 엉뚱한 회사를 가리키면(오매핑) 반드시 거부 — DB 오염 차단."""
        cases = [
            ("빅게임스튜디오", "앱클론(주) 채용 - 2026년 진행 중인 공고 확인하기 | 잡코리아"),
            ("스마일게이트RPG", "(주)에프앤자산평가 채용 - 진행 중인 공고 | 잡코리아"),
            ("위메이드맥스", "일미래센터 채용 - 진행 중인 공고 확인하기 | 잡코리아"),
        ]
        for name, title in cases:
            self.assertFalse(self._verify(name, title), f"거부해야 함: {name} / {title}")

    def test_norm_company_strips_corp_tokens(self):
        """정규화가 법인표기·공백·괄호를 제거하는지."""
        self.assertEqual(_norm_company("(주)넥슨코리아"), "넥슨코리아")
        self.assertEqual(_norm_company("주식회사 스마일게이트"), "스마일게이트")
        self.assertEqual(_norm_company("㈜넥슨게임즈"), "넥슨게임즈")


class TestJobKoreaClosedFilter(unittest.TestCase):
    """잡코리아 기업페이지의 마감(종료) 공고를 ACTIVE로 적재하지 않는지 검증.

    기업페이지는 진행중 공고와 과거 마감 공고를 함께 나열한다. 마감 공고를 적재하면
    영구히 마감 처리되지 않는 좀비 공고가 되므로 수집 단계에서 제외해야 한다.
    """

    def _collect(self, list_html):
        adapter = JobKoreaCompanyAdapter("0", "테스트", "test", fetch_detail=False)
        soup = BeautifulSoup(list_html, "html.parser")
        results = []
        adapter._extract_page(soup, set(), results)
        return [r["title"] for r in results]

    def test_closed_postings_excluded(self):
        """'마감 (~날짜)' 배지가 붙은 종료 공고는 제외, 'D-N' 활성 공고만 수집."""
        html = """
        <a href="/Recruit/GI_Read/111">[웹젠] 자금(신입/경력) 경력 경기 무관 D-8 재무담당자</a>
        <a href="/Recruit/GI_Read/222">자금 및 내부회계 담당자 (경력) 경력 서울 무관 마감 (~2025.12.18) 재무담당자</a>
        <a href="/Recruit/GI_Read/333">공시/IR 매니저 채용 신입·경력 서울 무관 마감 (~2026.05.11) IR</a>
        """
        titles = self._collect(html)
        self.assertIn("[웹젠] 자금(신입/경력)", titles)
        self.assertEqual(len(titles), 1, f"활성 1건만 수집되어야 함: {titles}")

    def test_always_open_postings_included(self):
        """'상시채용' 등 마감일 없는 활성 공고는 수집."""
        html = '<a href="/Recruit/GI_Read/444">[컴투스] 재무 담당자 경력 서울 상시채용 재무담당자</a>'
        self.assertEqual(len(self._collect(html)), 1)

    def test_settlement_title_not_treated_as_closed(self):
        """제목에 '마감'이 들어가도 '마감 (~' 배지가 아니면 종료로 오판하지 않음 (결산/월마감 등)."""
        html = '<a href="/Recruit/GI_Read/555">월 결산 마감 회계 담당자 경력 서울 D-15 회계담당자</a>'
        self.assertEqual(len(self._collect(html)), 1)


if __name__ == "__main__":
    unittest.main()
