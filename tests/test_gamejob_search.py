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


class _Resp:
    def __init__(self, status_code, body=""):
        self.status_code = status_code
        self.content = body.encode("utf-8")
        self.text = body


class _StubSession:
    """검색은 성공하고 상세만 실패시키는 세션 — 상세 실패 경로 재현용"""

    def __init__(self, fragment, detail_status=500, detail_raises=False):
        self.fragment = fragment
        self.detail_status = detail_status
        self.detail_raises = detail_raises
        self.headers = {}

    def post(self, url, **kwargs):
        return _Resp(200, self.fragment)

    def get(self, url, **kwargs):
        if self.detail_raises:
            raise ConnectionError("상세 접속 실패(모의)")
        return _Resp(self.detail_status, "")


class TestGameJobDetailFailurePreservesPosting(unittest.TestCase):
    """상세 페이지 1건이 실패해도 그 공고가 오늘 수집분에서 사라지면 안 된다.

    2026-07-21 GPT 3차 검토 지적: 상세 실패 시 그냥 continue해 공고가 결과에서 빠졌다.
    그러면 delta_analyzer가 '오늘 안 보였다'며 기존 활성 공고를 즉시 CLOSED 처리한다 —
    소스는 '완전 성공'으로 보고되므로 부분 실패·0건·일괄 소멸 어느 방어선에도 안 걸린다."""

    def _run(self, **stub_kwargs):
        scraper = GameJobScraper()
        scraper.session = _StubSession(FIXTURE_FRAGMENT, **stub_kwargs)
        # sleep 제거 — 테스트 속도
        import src.scraper.gamejob_scraper as mod
        orig_sleep = mod.time.sleep
        mod.time.sleep = lambda *a, **k: None
        try:
            return scraper, scraper.scrape_finance_jobs(limit=15)
        finally:
            mod.time.sleep = orig_sleep

    def test_http_error_on_detail_keeps_posting(self):
        scraper, results = self._run(detail_status=500)
        ids = {r["id"] for r in results}
        self.assertIn("gamejob_282441", ids, "상세 실패 공고가 결과에서 사라졌다 → 오탐 마감 발생")
        self.assertIn("gamejob_283001", ids)
        # 목록 행 정보는 살아 있어야 한다
        com2us = next(r for r in results if r["id"] == "gamejob_282441")
        self.assertEqual(com2us["company_name"], "주식회사 컴투스")
        self.assertEqual(com2us["deadline"], None)
        wemade = next(r for r in results if r["id"] == "gamejob_283001")
        self.assertEqual(wemade["deadline"][5:], "07-31")

    def test_exception_on_detail_keeps_posting(self):
        scraper, results = self._run(detail_raises=True)
        self.assertIn("gamejob_282441", {r["id"] for r in results})

    def test_non_finance_row_still_filtered_out(self):
        """상세 실패 보존이 필터를 무력화하면 안 된다 — HR 담당자는 여전히 제외"""
        scraper, results = self._run(detail_status=500)
        self.assertNotIn("gamejob_283999", {r["id"] for r in results})
