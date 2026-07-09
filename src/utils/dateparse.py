"""공고 목록의 배지형 마감 표기 → 절대 마감일(YYYY-MM-DD) 변환.

게임잡("~07/31", "D-3", "상시", "채용시")과 사람인("~ 07/31(금)", "상시채용",
"오늘마감") 목록이 같은 계열의 표기를 쓴다. 마감일이 아닌 표기는 None을
반환해 DB의 기존 값을 보존한다(upsert가 COALESCE로 처리).
"""
import re
from datetime import date, timedelta

from src.utils.timeutil import now_kst

_ABS_RE = re.compile(r"~\s*(\d{1,2})\s*/\s*(\d{1,2})")
_DDAY_RE = re.compile(r"\bD-(\d+)\b")
_TODAY_CLOSE_RE = re.compile(r"오늘\s*마감")
_TOMORROW_CLOSE_RE = re.compile(r"내일\s*마감")


def parse_deadline_badge(text, today=None):
    """배지 텍스트에서 마감일을 'YYYY-MM-DD'로 환산. 상시/채용시 등은 None.

    "~07/31"은 연도가 없어 오늘 기준으로 추론한다(연말→연초로 넘어가는 마감은 내년으로)."""
    if not text:
        return None
    if today is None:
        today = now_kst().date()

    m = _DDAY_RE.search(text)
    if m:
        return (today + timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d")

    if _TODAY_CLOSE_RE.search(text):
        return today.strftime("%Y-%m-%d")
    if _TOMORROW_CLOSE_RE.search(text):
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")

    m = _ABS_RE.search(text)
    if not m:
        return None
    month, day = int(m.group(1)), int(m.group(2))
    try:
        d = date(today.year, month, day)
    except ValueError:
        return None
    # 오늘이 연말인데 마감이 01/15처럼 크게 과거로 계산되면 내년 마감으로 해석
    if (d - today).days < -300:
        try:
            d = date(today.year + 1, month, day)
        except ValueError:
            return None
    return d.strftime("%Y-%m-%d")
