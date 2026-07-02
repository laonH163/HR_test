import unittest

from src.main import dedupe_jobkorea_gi


def _p(pid, source, url, company="테스트"):
    return {"id": pid, "source": source, "origin_url": url, "company_name": company}


class TestJobKoreaGIDedup(unittest.TestCase):
    """잡코리아 검색·기업페이지 이중 수집분 GI번호 병합 검증.

    실측 사례(2026-07-02): GI 49185226이 jobkorea_49185226(넥슨게임즈)와
    neople_49185226(네오플)로 이중 적재되어 대시보드에 이중 노출됐다.
    """

    def test_company_adapter_wins_over_search(self):
        """GI 충돌 시 기업페이지 어댑터(회사명 교차검증됨)가 검색 수집분을 대체."""
        postings = [
            _p("jobkorea_111", "jobkorea", "https://www.jobkorea.co.kr/Recruit/GI_Read/111", "넥슨게임즈"),
            _p("neople_111", "neople", "https://www.jobkorea.co.kr/Recruit/GI_Read/111", "네오플"),
        ]
        result = dedupe_jobkorea_gi(postings)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source"], "neople")

    def test_adapter_first_then_search_dropped(self):
        """어댑터 수집분이 먼저 와도 뒤따르는 검색 수집분은 폐기."""
        postings = [
            _p("webzen_222", "webzen", "https://www.jobkorea.co.kr/Recruit/GI_Read/222"),
            _p("jobkorea_222", "jobkorea", "https://www.jobkorea.co.kr/Recruit/GI_Read/222"),
        ]
        result = dedupe_jobkorea_gi(postings)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source"], "webzen")

    def test_non_jobkorea_postings_untouched(self):
        """잡코리아 외 소스(원티드/크래프톤 등)는 그대로 통과."""
        postings = [
            _p("wanted_1", "wanted", "https://www.wanted.co.kr/wd/1"),
            _p("krafton_2", "krafton", "https://boards.greenhouse.io/krafton/jobs/2"),
            _p("jobkorea_333", "jobkorea", "https://www.jobkorea.co.kr/Recruit/GI_Read/333"),
        ]
        result = dedupe_jobkorea_gi(postings)
        self.assertEqual(len(result), 3)

    def test_distinct_gi_numbers_kept(self):
        """GI번호가 다르면 소스가 겹쳐도 모두 유지."""
        postings = [
            _p("smilegate_444", "smilegate", "https://www.jobkorea.co.kr/Recruit/GI_Read/444"),
            _p("smilegate_555", "smilegate", "https://www.jobkorea.co.kr/Recruit/GI_Read/555"),
        ]
        self.assertEqual(len(dedupe_jobkorea_gi(postings)), 2)


if __name__ == "__main__":
    unittest.main()
