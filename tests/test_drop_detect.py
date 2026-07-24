"""수집량 급감 판정(detect_source_drops) 단위 테스트.

main 8-4에 인라인으로 있던 30% 게이트를 순수 함수로 추출하면서 경계값을 고정한다
— 기존에는 이 로직이 monolithic 함수 안에 있어 단위 테스트가 불가능했다
(2026-07-24 GPT·코덱스 공통 지적).
"""
import unittest
from src.utils.drop_detect import detect_source_drops, MIN_BASELINE_DAYS, MIN_AVG, DROP_RATIO

PLATFORMS = ["wanted", "saramin", "jobkorea", "gamejob"]


class TestDropDetect(unittest.TestCase):
    def test_drop_below_30_percent_is_flagged(self):
        """평균 10건 → 오늘 2건(20%)은 급감."""
        drops, _ = detect_source_drops({"saramin": [10, 10, 10]}, {"saramin": 2}, PLATFORMS)
        self.assertIn("saramin", drops)
        self.assertEqual(drops["saramin"]["today"], 2)
        self.assertAlmostEqual(drops["saramin"]["avg"], 10.0)

    def test_exactly_30_percent_is_not_a_drop(self):
        """경계값: 정확히 평균의 30%(10건 평균 → 오늘 3건)는 정상 — '미만'만 급감.
        이 부등호가 <=로 바뀌면 이 테스트가 잡는다."""
        drops, _ = detect_source_drops({"saramin": [10, 10, 10]}, {"saramin": 3}, PLATFORMS)
        self.assertEqual(drops, {})

    def test_zero_today_is_not_a_drop(self):
        """오늘 0건은 급감이 아니라 별도의 '0건 플랫폼' 경고 담당."""
        drops, insufficient = detect_source_drops({"saramin": [10, 10, 10]}, {"saramin": 0}, PLATFORMS)
        self.assertEqual(drops, {})
        self.assertEqual(insufficient, [])
        # 기준선 부족(2일) + 오늘 0건 조합에서도 부족 목록에 올리지 않는다 —
        # 0건은 '0건 플랫폼' 경고 담당이라 여기서 겹치면 소음이 된다
        drops, insufficient = detect_source_drops({"saramin": [10, 10]}, {"saramin": 0}, PLATFORMS)
        self.assertEqual(drops, {})
        self.assertEqual(insufficient, [])

    def test_small_average_is_skipped(self):
        """평소 평균이 MIN_AVG 미만(원티드 1건급)이면 30% 계산이 무의미 — 건너뛴다."""
        drops, _ = detect_source_drops({"wanted": [1, 1, 1]}, {"wanted": 1}, PLATFORMS)
        self.assertEqual(drops, {})

    def test_insufficient_baseline_is_reported_not_compared(self):
        """관측 2일뿐이면 비교하지 않되, 오늘 수집된 소스는 '기준선 부족'으로 보고
        — 콜드 스타트에서 급감 감지가 무음으로 쉬는 것을 로그로 보이게 한다."""
        drops, insufficient = detect_source_drops({"saramin": [10, 10]}, {"saramin": 2}, PLATFORMS)
        self.assertEqual(drops, {})
        self.assertEqual(insufficient, [("saramin", 2)])

    def test_constants_are_pinned(self):
        """경계 상수가 바뀌면 경고 빈도가 통째로 달라진다 — 의도적 변경만 허용."""
        self.assertEqual(MIN_BASELINE_DAYS, 3)
        self.assertEqual(MIN_AVG, 3)
        self.assertEqual(DROP_RATIO, 0.3)


if __name__ == "__main__":
    unittest.main()
