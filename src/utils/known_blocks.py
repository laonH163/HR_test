"""'알려진 차단' 소스 관리 — 우리 코드로는 고칠 수 없는 접근 차단을 명시적으로 등록한다.

왜 필요한가:
  운영 원칙이 '경고가 없으면 할 일 없음'인데, 고칠 방법이 없는 실패가 매일 경고로
  뜨면 경고 전체가 무뎌진다(늑대 소년). 그렇다고 조용히 숨기면 차단이 풀린 것도,
  차단이 길어져 생기는 부작용도 모르게 된다.

  그래서 '알려진 차단'은 ① 평소엔 경고가 아니라 정보 한 줄로 내리고
  ② 수집이 복구되면 즉시 눈에 띄게 알리고 ③ 차단이 길어지면 다시 경고로 올린다.

등록된 소스에 적용되는 것:
  - 텔레그램 '접속 실패'·'검색 0건' 경고에서 제외하고 'ℹ️ 알려진 차단' 정보 줄로 대체
  - 새 러너(새 IP) 재시도 게이트에서 제외 — IP를 바꿔도 어차피 막히므로 매일 파이프라인을
    통째로 한 번 더 돌리는 낭비를 없앤다(부수 효과: 당일 통계 이중 합산도 사라짐)
  - 마지막 성공일로부터 ZOMBIE_ALERT_DAYS 경과 시 '수동 확인 필요' 경고로 승격

적용되지 않는 것(중요):
  - 수집 시도 자체는 그대로 한다. 차단이 풀리면 자동 복구·자동 감지되어야 하기 때문
  - 마감 판정 보류 등 데이터 보호 가드는 그대로 유지한다 — 표시 정책만 바꾼다
"""

# 소스명 → 차단 정보. 차단이 풀린 게 확인되면 이 표에서 지운다(텔레그램이 복구를 알려준다).
KNOWN_BLOCKED_SOURCES = {
    "wanted": {
        "since": "2026-07-16",
        "summary": "러너 IP 차단(원티드 WAF)",
        "detail": (
            "GitHub Actions 러너 IP가 원티드 CloudFront WAF에 차단됨. "
            "2026-07-22 진단(run 29886002374): 검색 페이지 HTML·검색 API"
            "(/api/chaos/search/v1/position)·상세 API(/api/chaos/jobs/v1/{id}/details) "
            "3경로 전부 HTTP 403 'Request blocked' — 지역 차단이 아니라 WAF 룰 차단이며, "
            "같은 시각 로컬(가정용 IP)에서는 동일 요청이 전부 200이었다. "
            "경로가 아니라 IP 단위 차단이라 스크래퍼를 어떤 방식으로 바꿔도 해결되지 않는다. "
            "실효 대안은 self-hosted 러너 또는 프록시뿐."
        ),
    },
}

# 알려진 차단이 이 일수를 넘겨 이어지면 정보가 아니라 경고로 승격한다.
# 근거: 차단이 길어지면 그 소스의 기존 활성 공고는 마감 보류로 계속 보호되므로,
#       실제로는 마감됐는데 대시보드에 살아 있는 '좀비'가 된다. 사람이 눈으로 확인해야 한다.
ZOMBIE_ALERT_DAYS = 14


def is_known_blocked(source):
    """해당 소스가 '알려진 차단'으로 등록돼 있는가"""
    return str(source).lower() in KNOWN_BLOCKED_SOURCES


def split_known_blocked(sources):
    """소스 목록을 (알려진 차단, 그 외)로 분리해 각각 정렬된 리스트로 돌려준다."""
    known, others = [], []
    for s in sources or []:
        (known if is_known_blocked(s) else others).append(s)
    return sorted(set(known)), sorted(set(others))


def describe(source):
    """텔레그램 한 줄 표시용 요약 문구 (등록되지 않은 소스면 None)"""
    info = KNOWN_BLOCKED_SOURCES.get(str(source).lower())
    return info.get("summary") if info else None
