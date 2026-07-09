import unittest

from bs4 import BeautifulSoup

from src.scraper.wanted_scraper import WantedScraper


def _soup(html):
    return BeautifulSoup(html, "html.parser")


class TestWantedDetailCorrection(unittest.TestCase):
    """상세 페이지 제목·회사명 보정 — 2026-07-09 DOM 개편(첫 h2='포지션 상세') 대응 회귀 테스트"""

    def test_h1_is_trusted_title(self):
        """현행 DOM: h1이 공고 제목, JobHeader 링크가 회사명"""
        soup = _soup("""
            <html><head><title>[데브즈유나이티드게임즈] 재무담당자 (팀장급) 채용 공고 | 원티드</title></head>
            <body><header class="JobHeader_JobHeader__TZkW3">
                <a class="JobHeader_JobHeader__Tools__Company__Link__NoBQI">데브즈유나이티드게임즈</a>
                <h1 class="wds-58fmok">재무담당자 (팀장급)</h1></header>
            <h2>포지션 상세</h2><h2>태그</h2></body></html>
        """)
        title, company = WantedScraper._correct_from_detail(soup, "카드제목", "카드회사")
        self.assertEqual(title, "재무담당자 (팀장급)")
        self.assertEqual(company, "데브즈유나이티드게임즈")

    def test_section_heading_h2_never_overwrites_title(self):
        """h1이 없어도 '포지션 상세' 같은 h2 섹션 헤딩으로 제목을 덮어쓰지 않는다 (한 달 0건 원인)"""
        soup = _soup("""
            <html><head><title>[컴투스] 별도 결산 담당자 채용 공고 | 원티드</title></head>
            <body><h2>포지션 상세</h2><h2>마감일</h2></body></html>
        """)
        title, company = WantedScraper._correct_from_detail(soup, "별도 결산 담당자", "컴투스")
        # <title> 태그 패턴 폴백으로 정확한 제목·회사명 복원
        self.assertEqual(title, "별도 결산 담당자")
        self.assertEqual(company, "컴투스")

    def test_no_trusted_source_keeps_card_values(self):
        """h1도 <title> 패턴도 없으면 카드에서 뽑은 원래 값을 유지한다"""
        soup = _soup("<html><head><title>이상한 페이지</title></head><body><h2>포지션 상세</h2></body></html>")
        title, company = WantedScraper._correct_from_detail(soup, "재무 회계 담당자", "게임회사")
        self.assertEqual(title, "재무 회계 담당자")
        self.assertEqual(company, "게임회사")


if __name__ == "__main__":
    unittest.main()
