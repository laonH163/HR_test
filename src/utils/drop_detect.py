"""수집량 급감 판정 — main 8-4에서 분리한 순수 함수 (단위 테스트 가능하게).

기준선(history)은 db_manager.get_recent_source_counts가 만드는
{source: [일별 수집 건수, ...]}(최신 날짜순, 오늘 제외 달력 7일)이다.
"""

MIN_BASELINE_DAYS = 3   # 관측일이 이보다 적으면 비교하지 않는다 (오탐 방지)
MIN_AVG = 3             # 평소 평균이 이보다 작으면 30% 계산이 무의미 (원티드 1건급)
DROP_RATIO = 0.3        # 평균 대비 이 비율 '미만'이면 급감 (경계값 정확히 30%는 정상)


def detect_source_drops(history, source_counts, platform_sources):
    """(source_drops, insufficient) 반환.

    source_drops: {source: {"today": 오늘 건수, "avg": 기준선 평균}} — 📉 경고 대상.
    insufficient: [(source, 관측일수), ...] — 오늘 수집은 됐지만 기준선이 모자라
        비교를 쉰 소스(콜드 스타트·7일 초과 공백 뒤). 무음 감시 공백을 로그로
        노출하기 위한 정보이며, 오늘 0건인 소스는 별도의 '0건 플랫폼' 경고가
        담당하므로 여기 포함하지 않는다.
    """
    source_drops = {}
    insufficient = []
    for s in platform_sources:
        past = history.get(s, [])
        today_n = source_counts.get(s, 0)
        if len(past) >= MIN_BASELINE_DAYS:
            avg = sum(past) / len(past)
            if avg >= MIN_AVG and 0 < today_n < avg * DROP_RATIO:
                source_drops[s] = {"today": today_n, "avg": avg}
        elif today_n > 0:
            insufficient.append((s, len(past)))
    return source_drops, insufficient
