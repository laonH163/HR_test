"""공통 HTTP 세션 유틸리티.

requests 기반 스크래퍼들이 일시적 네트워크 오류(타임아웃/5xx/429)에 견디도록
자동 재시도(backoff)와 커넥션 재사용을 제공한다. GitHub Actions 러너의 일시적
IP 스로틀이나 네트워크 흔들림으로 한 소스 전체가 0건이 되는 상황을 줄이는 것이 목적.
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def make_session(retries=2, backoff=0.5, headers=None):
    """자동 재시도 + 커넥션 풀링이 적용된 requests 세션을 생성한다.

    - status_forcelist에 해당하면 지수 backoff 후 재시도
    - raise_on_status=False: 재시도 소진 후에도 예외 대신 응답을 반환하여
      기존 status_code 분기 로직과 그대로 호환됨
    - headers를 넘기면 세션 기본 헤더로 설정(개별 요청에서 재정의 가능)
    """
    session = requests.Session()
    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    if headers:
        session.headers.update(headers)
    return session
