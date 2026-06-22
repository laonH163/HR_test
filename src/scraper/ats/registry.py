"""게임사별 ATS 어댑터 레지스트리.

각 게임사가 어떤 채용 시스템을 쓰는지와 식별자를 한 곳에 모은다.
새 회사 추가는 여기 한 줄이면 된다.

라이브 검증(2026-06-01 / 2026-06-22 재검증)으로 확정된 매핑:
- 크래프톤  → Greenhouse (board=krafton)        : 재무직 다수
- 네오위즈  → Lever (site=neowiz)               : 무인증 JSON(현재 개발직 위주)
- 카카오게임즈 → greetinghr (workspace=7144)      : 무인증 JSON
- 111퍼센트 → greetinghr (workspace=2836)        : 무인증 JSON, '재무 팀원' 라이브 확인
- 펄어비스  → 자체 정적 HTML                      : requests 파싱
- 넥슨·엔씨·넷마블·컴투스·웹젠·위메이드·데브시스터즈·스마일게이트 외
            → 잡코리아 기업페이지 우회 (봇차단/JS/외부ATS라 자체 직수집 곤란)

[2026-06-22] 잡코리아 company_id는 시간이 지나면 폐지/재배정되어 엉뚱한 회사로
오매핑될 수 있다. JobKoreaCompanyAdapter는 페이지 title 회사명을 교차검증해
불일치 시 자동 폐기한다(verify_aliases로 정상 별칭 허용). 2026-06-10에 추가됐던
3차 6사(컴투스홀딩스·위메이드맥스·위메이드플레이·스마일게이트RPG·하이브IM·
빅게임스튜디오)는 전부 무효(404 또는 앱클론/에프앤자산평가/일미래센터로 오매핑)임이
재검증으로 확인되어 제거했다. 정확한 현행 id 확보 시 재등록할 것.
"""
from src.scraper.ats import (
    GreenhouseAdapter,
    LeverAdapter,
    GreetingHRAdapter,
    PearlAbyssAdapter,
    JobKoreaCompanyAdapter,
)

# 잡코리아 우회 그룹: (잡코리아 company_id, 표시 회사명, source 키)
# company_id는 라이브로 회사명 대조 검증 완료. 어댑터가 매 수집마다 title 회사명을
# 재검증하므로, 폐지/재배정으로 오매핑되면 자동으로 0건 처리되어 오염되지 않는다.
JOBKOREA_COMPANIES = [
    ("1882711", "넥슨", "nexon"),
    ("1926620", "엔씨소프트", "ncsoft"),
    ("1753968", "넷마블", "netmarble"),
    ("1547724", "컴투스", "com2us"),
    ("1798146", "웹젠", "webzen"),
    ("1977592", "위메이드", "wemade"),
    ("16152377", "데브시스터즈", "devsisters"),
    ("16152306", "스마일게이트", "smilegate"),
    # 2차 추가 (id·회사명 라이브 대조 검증 2026-06-01)
    ("1605140", "그라비티", "gravity"),
    ("16152348", "더블유게임즈", "doubleugames"),
    ("1713050", "네오플", "neople"),
    ("1504762", "조이시티", "joycity"),
    ("16154364", "라인게임즈", "linegames"),
    ("1546668", "NHN", "nhn"),
    ("42943938", "넥슨게임즈", "nexongames"),
    # 신규 추가 (id·title 라이브 검증 2026-06-22)
    ("1694830", "엠게임", "mgame"),
    ("42868646", "미투온", "me2on"),
    ("1530478", "액토즈소프트", "actozsoft"),
    # 3차 배치 오매핑 ID를 라이브 재검증으로 교정한 회사들 (2026-06-22)
    # 이전 등록 ID는 404/오매핑(앱클론·에프앤자산평가·일미래센터)이라 폐기하고 현행 ID로 교체.
    ("1522311", "위메이드맥스", "wemademax"),
    ("16152762", "위메이드플레이", "wemadeplay"),
    ("48077192", "빅게임스튜디오", "vicgamestudios"),
    ("49122801", "하이브IM", "hybeim"),
    # 제외: 컴투스홀딩스(잡코리아 독립 기업페이지 없음·자회사 컴투스 1547724에 통합 게시),
    #       스마일게이트RPG(2025-12-30 스마일게이트홀딩스 흡수합병으로 법인 소멸)
]

# 페이지 title 회사명이 등록명과 표기가 달라도 정상인 케이스의 별칭(가드레일 통과용).
# 예: 엔씨소프트 페이지 title은 "NC 채용 ...", NHN은 "엔에이치엔㈜ 채용 ...".
JOBKOREA_ALIASES = {
    "ncsoft": ["NC", "엔씨소프트"],
    "nhn": ["엔에이치엔", "NHN"],
    "hybeim": ["하이브아이엠", "하이브IM", "DRIMAGE", "드림에이지"],  # HYBE IM → DRIMAGE 리브랜딩
}


def build_official_adapters(session=None):
    """공식 자체 채용 페이지 수집 어댑터 목록.

    무인증 API/정적 그룹 + 잡코리아 우회 그룹. session을 넘기면 커넥션을 공유한다.
    (시프트업은 기존 company_scrapers의 자체 API 메서드 유지)
    """
    adapters = [
        GreenhouseAdapter("krafton", "크래프톤", source="krafton", session=session),
        LeverAdapter("neowiz", "네오위즈", source="neowiz", session=session),
        GreetingHRAdapter(
            "kakaogamesrecruit", "카카오게임즈", "kakaogames",
            workspace_id="7144", session=session,
        ),
        # greetinghr 게임사 (subdomain/workspace_id 라이브 검증 2026-06-22)
        GreetingHRAdapter("111percent", "111퍼센트", "111percent",
                          workspace_id="2836", session=session),
        GreetingHRAdapter("supercent", "슈퍼센트", "supercent",
                          workspace_id="2730", session=session),
        GreetingHRAdapter("epidgames", "에피드게임즈", "epidgames",
                          workspace_id="16500", session=session),
        PearlAbyssAdapter(session=session),
    ]
    # fetch_detail=False: 잡코리아 상세 본문은 공고마다 이미지 JD/동적 로딩 등 형식이 제각각이라
    # 추출 시 네비게이션 노이즈가 섞인다(라이브 확인). 제목이 직무·연차·직급을 충분히 담으므로
    # 제목 기반이 더 정확하고 안정적이다.
    adapters += [
        JobKoreaCompanyAdapter(
            cid, name, src, session=session, fetch_detail=False,
            verify_aliases=([name] + JOBKOREA_ALIASES.get(src, [])),
        )
        for cid, name, src in JOBKOREA_COMPANIES
    ]
    return adapters
