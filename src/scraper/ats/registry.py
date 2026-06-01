"""게임사별 ATS 어댑터 레지스트리.

각 게임사가 어떤 채용 시스템을 쓰는지와 식별자를 한 곳에 모은다.
새 회사 추가는 여기 한 줄이면 된다.

라이브 검증(2026-06-01)으로 확정된 매핑:
- 크래프톤  → Greenhouse (board=krafton)        : 재무직 다수
- 네오위즈  → Lever (site=neowiz)               : 무인증 JSON
- 카카오게임즈 → greetinghr (workspace=7144)      : 무인증 JSON
- 펄어비스  → 자체 정적 HTML                      : requests 파싱
- 넥슨·엔씨·넷마블·컴투스·웹젠·위메이드·데브시스터즈·스마일게이트
            → 잡코리아 기업페이지 우회 (봇차단/JS/외부ATS라 자체 직수집 곤란)
"""
from src.scraper.ats import (
    GreenhouseAdapter,
    LeverAdapter,
    GreetingHRAdapter,
    PearlAbyssAdapter,
    JobKoreaCompanyAdapter,
)

# 잡코리아 우회 그룹: (잡코리아 company_id, 표시 회사명, source 키)
# company_id는 라이브로 회사명 대조 검증 완료(2026-06-01).
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
]


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
        PearlAbyssAdapter(session=session),
    ]
    # fetch_detail=False: 잡코리아 상세 본문은 공고마다 이미지 JD/동적 로딩 등 형식이 제각각이라
    # 추출 시 네비게이션 노이즈가 섞인다(라이브 확인). 제목이 직무·연차·직급을 충분히 담으므로
    # 제목 기반이 더 정확하고 안정적이다.
    adapters += [
        JobKoreaCompanyAdapter(cid, name, src, session=session, fetch_detail=False)
        for cid, name, src in JOBKOREA_COMPANIES
    ]
    return adapters
