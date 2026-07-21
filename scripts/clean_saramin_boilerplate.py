# -*- coding: utf-8 -*-
"""사람인 '공통 레이아웃 본문' 오염 행 정리 (일회성 보수 스크립트).

배경 (2026-07-21 실측)
----------------------
사람인 스크래퍼가 상세요강이 없는 중계 주소(relay/view)를 긁고 body 폴백까지 두는 바람에,
전 공고가 **완전히 동일한 4,999자 사이트 네비게이션**을 본문으로 저장하고 있었다.
ACTIVE 13건의 raw_html SHA-256이 모두 같았다. 그 결과:
  - 경력·근무형태·태그 분류가 전부 근거 없는 값 (예: 대리·과장급 공고가 '신입 0~1년')
  - 본문 길이가 길어 has_body=True → 대시보드가 '미확인'으로 감추지도 못함

스크래퍼는 정규 주소(jobs/view) + body 폴백 제거로 교정했다. 이 스크립트는 **이미 저장된**
오염 행을 '제목만 수집' 상태로 되돌려, 다음 정기 실행이 정상 본문으로 덮어쓸 수 있게 한다.
(오염 본문을 그대로 두면 db_manager의 본문 축소 방지 가드가 이 4,999자를 '기확보 본문'으로
보고 지켜버려, 새로 확보한 정상 본문이 짧을 경우 영구 고착된다.)

사용법
------
    python scripts/clean_saramin_boilerplate.py            # dry-run (변경 없음)
    python scripts/clean_saramin_boilerplate.py --apply    # 실제 반영 (.bak 백업 생성)
"""
import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.utils.jdtext import has_jd_markers  # noqa: E402

DB_PATH = os.path.join("data", "scrap_master.db")

# 사람인 공통 레이아웃에만 나오는 지문 — 상세요강 본문에는 등장하지 않는 전역 네비게이션 문구.
# 두 개 이상 걸리고 실본문 헤더가 하나도 없을 때만 '본문 아님'으로 판정한다(보수적 이중 조건).
NAV_FINGERPRINTS = ("커리어의 시작, 사람인", "중장년 채용", "기업서비스", "역세권별", "인적성")

# src.utils.jdtext.JD_MARKERS(담당업무·자격요건·우대사항·주요업무)에 더해, 정상 본문임을
# 알려주는 헤더를 넓게 인정한다. jdtext의 4종은 '본문 축소 가드'용으로 좁게 유지되는 값이라
# 여기에 그대로 기대면, 그 4종을 안 쓰고 '지원자격'만 쓰는 정상 본문을 지울 위험이 있다
# (코덱스 교차검토 지적, 2026-07-21). 삭제는 되돌리기 어려우므로 인정 범위를 넓게 잡는다.
EXTRA_BODY_MARKERS = ("지원자격", "지원 자격", "필수요건", "필수 요건", "모집부문", "모집 부문",
                      "근무조건", "근무 조건", "모집분야", "모집 분야", "전형절차", "제출서류")


def is_boilerplate(raw_html):
    """상세요강이 아니라 사람인 공통 레이아웃인지 판정."""
    if not raw_html:
        return False
    if has_jd_markers(raw_html):
        return False  # 담당업무·자격요건 등 실본문 헤더가 있으면 정상 본문
    normalized = "".join(raw_html.split())
    if any("".join(marker.split()) in normalized for marker in EXTRA_BODY_MARKERS):
        return False
    hits = sum(1 for fp in NAV_FINGERPRINTS if fp in raw_html)
    return hits >= 2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="실제로 DB에 반영 (미지정 시 dry-run)")
    args = parser.parse_args()

    if not os.path.exists(DB_PATH):
        print(f"[오류] DB를 찾을 수 없습니다: {DB_PATH}")
        return 1

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, status, title, raw_html FROM job_postings WHERE source = 'saramin'"
    ).fetchall()

    targets = [r for r in rows if is_boilerplate(r["raw_html"])]
    print(f"사람인 전체 {len(rows)}행 중 오염(공통 레이아웃) {len(targets)}행")
    for r in targets:
        print(f"  - {r['id']:22s} {r['status']:7s} {len(r['raw_html'] or ''):6d}자 → 제목({len(r['title'])}자)로 초기화 : {r['title'][:36]}")

    if not targets:
        print("정리할 행이 없습니다.")
        conn.close()
        return 0

    if not args.apply:
        print("\n[dry-run] 변경하지 않았습니다. 실제 반영하려면 --apply 를 붙이세요.")
        conn.close()
        return 0

    conn.close()
    backup = f"{DB_PATH}.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(DB_PATH, backup)
    print(f"\n백업 생성: {backup}")

    conn = sqlite3.connect(DB_PATH)
    for r in targets:
        conn.execute("UPDATE job_postings SET raw_html = ? WHERE id = ?", (r["title"], r["id"]))
    conn.commit()

    remaining = conn.execute(
        "SELECT COUNT(*) FROM job_postings WHERE source='saramin' AND LENGTH(raw_html) = 4999"
    ).fetchone()[0]
    conn.close()
    print(f"{len(targets)}행 초기화 완료. 남은 4,999자 사람인 행: {remaining}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
