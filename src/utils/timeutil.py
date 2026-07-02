"""KST 기준 시각 헬퍼.

GitHub Actions 러너는 UTC라서 naive datetime.now()를 쓰면 시각이 9시간 어긋나고,
텔레그램 브리핑의 신규/변경 판정(posted_at == 오늘, last_updated_at.startswith(오늘))이
자정~오전 9시 사이에 하루 밀리는 버그가 생긴다. 모든 시각 생성은 이 모듈을 거친다.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def now_kst():
    """KST aware datetime."""
    return datetime.now(KST)


def now_kst_str():
    """'YYYY-MM-DD HH:MM:SS' (KST) — first_seen_at/last_updated_at 용."""
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def today_kst_str():
    """'YYYY-MM-DD' (KST) — posted_at/run_date 용."""
    return datetime.now(KST).strftime("%Y-%m-%d")
