"""게임사별 ATS 어댑터 레지스트리.

각 게임사가 어떤 채용 시스템을 쓰는지와 식별자를 한 곳에 모은다.
새 회사 추가는 여기 한 줄이면 된다.

라이브 검증(2026-06-01)으로 확정된 매핑:
- 크래프톤  → Greenhouse (board=krafton)        : 재무직 다수
- 네오위즈  → Lever (site=neowiz)               : 무인증 JSON
- 카카오게임즈 → greetinghr (workspace=7144)      : 무인증 JSON
- 펄어비스  → 자체 정적 HTML                      : requests 파싱

봇차단/JS 그룹(넥슨·엔씨·넷마블·컴투스·웹젠·위메이드·데브시스터즈)과 스마일게이트는
잡코리아 기업페이지 우회로 별도 추가 예정.
"""
from src.scraper.ats import (
    GreenhouseAdapter,
    LeverAdapter,
    GreetingHRAdapter,
    PearlAbyssAdapter,
)


def build_official_adapters(session=None):
    """공식 자체 채용 페이지 수집 어댑터 목록.

    무인증 API/정적 그룹 — 봇차단·JS 없이 requests로 안정 수집되는 회사들.
    session을 넘기면 커넥션을 공유한다(없으면 각 어댑터가 자체 생성).
    """
    return [
        GreenhouseAdapter("krafton", "크래프톤", source="krafton", session=session),
        LeverAdapter("neowiz", "네오위즈", source="neowiz", session=session),
        GreetingHRAdapter(
            "kakaogamesrecruit", "카카오게임즈", "kakaogames",
            workspace_id="7144", session=session,
        ),
        PearlAbyssAdapter(session=session),
    ]
