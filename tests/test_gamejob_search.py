import unittest
from datetime import date

from src.scraper.gamejob_scraper import GameJobScraper

# 2026-07-09 실제 _GI_Job_List 응답 구조를 축약한 픽스처
FIXTURE_FRAGMENT = """
<div class="jobListWrap">
  <table>
    <tr>
      <td>주식회사 컴투스</td>
      <td><a href="/Recruit/GI_Read/View?GI_No=282441">[컴투스 홀딩스] 재무관리 팀장 (10년 이상)</a></td>
      <td>경력10년↑</td><td>서울 &gt; 금천구</td><td>정규직</td><td>상시</td><td>1일 전 등록</td>
    </tr>
    <tr>
      <td>㈜위메이드</td>
      <td><a href="/Recruit/GI_Read/View?GI_No=283001">국내외 자회사 결산 및 감사대응(계약직)</a></td>
      <td>경력1년↑</td><td>경기 &gt; 성남시</td><td>계약직</td><td>~07/31</td><td>6일 전 등록</td>
    </tr>
    <tr>
      <td>기어세컨드</td>
      <td><a href="/Recruit/GI_Read/View?GI_No=283999">HR 담당자</a></td>
      <td>경력무관</td><td>서울</td><td>정규직</td><td>D-3</td><td>오늘 등록</td>
    </tr>
    <tr><td>광고 배너 행 (GI 링크 없음)</td></tr>
  </table>
</div>
"""


class TestGameJobSearchParsing(unittest.TestCase):
    """신형 XHR 검색(_GI_Job_List) 응답 파싱 회귀 테스트 — 2026-07 개편 대응"""

    def test_rows_extracted_with_company_title_deadline(self):
        rows = GameJobScraper._parse_search_rows(FIXTURE_FRAGMENT)
        self.assertEqual(len(rows), 3)

        com2us = rows[0]
        self.assertEqual(com2us["gi_no"], "282441")
        self.assertEqual(com2us["company"], "주식회사 컴투스")
        self.assertEqual(com2us["title"], "[컴투스 홀딩스] 재무관리 팀장 (10년 이상)")
        self.assertIsNone(com2us["deadline"])  # '상시'는 마감일 없음

        wemade = rows[1]
        self.assertEqual(wemade["deadline"][5:], "07-31")  # "~07/31" 절대일 환산

    def test_broken_markup_returns_none_not_empty(self):
        """컨테이너 자체가 없으면 '무음 0건'이 아니라 실패(None)로 구분해야 한다"""
        self.assertIsNone(GameJobScraper._parse_search_rows("<html><body>완전히 다른 페이지</body></html>"))

    def test_legit_empty_result_returns_empty_list(self):
        """컨테이너는 있는데 행이 없으면 정상적인 '검색 결과 0건'"""
        empty = '<div class="jobListWrap"><p>검색 결과가 없습니다.</p></div>'
        self.assertEqual(GameJobScraper._parse_search_rows(empty), [])

    def test_deadline_parsing_variants(self):
        today = date(2026, 7, 9)
        p = GameJobScraper._parse_row_deadline
        self.assertEqual(p("... 정규직 ~07/31 6일 전 등록", today), "2026-07-31")
        self.assertEqual(p("... D-3 오늘 등록", today), "2026-07-12")
        self.assertIsNone(p("... 정규직 상시 1일 전 등록", today))
        self.assertIsNone(p("... 채용시 마감", today))
        # 연말 → 연초 마감은 내년으로 해석
        self.assertEqual(p("~01/15", date(2026, 12, 20)), "2027-01-15")

    def test_search_payload_contract(self):
        """브라우저 실캡처와 동일한 폼 계약 유지 (엔드포인트 회귀 감지용)"""
        payload = GameJobScraper._build_search_payload("회계")
        self.assertEqual(payload["condition[searchstring]"], "회계")
        self.assertEqual(payload["pagesize"], "40")
        self.assertEqual(payload["condition[searchtype]"], "all")


if __name__ == "__main__":
    unittest.main()
