import os
import json
import sqlite3

from src.utils.dedup import compute_repost_flags, content_key
from src.utils.timeutil import now_kst_str

class HTMLGenerator:
    def __init__(self, db_manager, template_path="templates/dashboard_template.html", output_path="index.html"):
        self.db_manager = db_manager
        self.template_path = template_path
        self.output_path = output_path

    def generate_dashboard(self, closed_history=None):
        """SQLite에서 데이터를 긁어와 단일 HTML 대시보드 파일을 생성.

        closed_history: 재공고 판별용 CLOSED 이력. 파이프라인(main)이 이미 조회한
        값을 넘기면 같은 쿼리를 반복하지 않는다. None이면(--mode report 단독 실행)
        직접 조회한다."""
        # 1. 템플릿 존재 여부 확인
        if not os.path.exists(self.template_path):
            raise FileNotFoundError(f"HTML Template not found: {self.template_path}")

        # 2. SQLite 데이터 조회
        active_postings = self.db_manager.get_all_active_postings()

        # Row → dict 변환 (아래 가공 루프가 제자리 수정하며, 이후 재사용 없음)
        active_dicts = [dict(r) for r in active_postings]

        # 재공고(🔁) 키 계산 — 과거 CLOSED 이력이 있고 현 활성 그룹이 그 이후 재등장한 키.
        # 키 단위 판정이므로 같은 content_key로 병합되는 카드들은 항상 같은 값을 갖는다
        # (JS 병합 시 대표 카드가 무엇이든 배지가 일관됨).
        try:
            if closed_history is None:
                closed_history = self.db_manager.get_closed_key_history()
            repost_flags = compute_repost_flags(active_dicts, closed_history)
        except Exception:
            repost_flags = {}

        # 가공 처리
        job_list = []
        for job_dict in active_dicts:
            # Row 내 None 값이나 NULL 필드 안정적 폴백 처리
            if job_dict.get("min_experience") is None:
                job_dict["min_experience"] = 0
            # tools_used가 비면 비운 채로 둔다 — 예전에는 'EXCEL'을 채워 넣어,
            # 엑셀 언급이 전혀 없는 공고까지 실무 툴이 확인된 것처럼 보였다.

            # 본문 보유 여부 — 제목만 수집된 공고(잡코리아 우회·greetinghr 등)는 근무형태/연차
            # 분류의 판정 근거가 없으므로, 프론트에서 '미확인'으로 정직하게 표기하기 위한 플래그.
            # (raw_html이 제목과 같거나 근소하게 긴 경우 = 본문 없음으로 판정)
            raw_len = job_dict.pop("raw_html_len", 0) or 0
            title_len = len(job_dict.get("title") or "")
            job_dict["has_body"] = raw_len > title_len + 60

            # 자격증 및 실무 역량 태그의 JSON 리스트 가공 처리 (Milestone 5)
            # SQLite에 문자열화된 JSON 형태로 보관되어 있으므로, 디코딩하여 프론트엔드로 전달
            for field in ["preferred_certifications", "preferred_skills_tags"]:
                val = job_dict.get(field)
                if val:
                    try:
                        job_dict[field] = json.loads(val)
                    except Exception:
                        job_dict[field] = []
                else:
                    job_dict[field] = []

            # key_requirements, preferred_skills도 문자열 JSON일 때 처리
            for field in ["key_requirements", "preferred_skills"]:
                val = job_dict.get(field)
                if isinstance(val, str):
                    try:
                        job_dict[field] = json.loads(val)
                    except Exception:
                        job_dict[field] = [val]

            # 재공고(🔁) 플래그 — 프론트는 이 값만 표시하면 됨(로직 미러링 불필요)
            job_key = content_key(job_dict.get("company_name"), job_dict.get("title"))
            job_dict["is_repost"] = job_key in repost_flags
            job_dict["repost_last_closed"] = repost_flags.get(job_key)

            job_list.append(job_dict)

        # 3. 템플릿 리딩
        with open(self.template_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        # 4. 데이터 인라인 바인딩 치환
        # JSON 데이터 인라인 주입
        json_data_str = json.dumps(job_list, ensure_ascii=False)
        # <script> 인라인 주입 시 본문에 포함된 '</script>' 등이 태그를 조기 종료하지 않도록 방어
        # ('<\/'는 JS/JSON에서 '</'와 동일하게 파싱되어 데이터 의미는 보존됨)
        json_data_str = json_data_str.replace("</", "<\\/")
        html_content = html_content.replace("const JOBS_DATA = [];", f"const JOBS_DATA = {json_data_str};")

        # 갱신 타임스탬프 주입 (러너가 UTC여도 한국 시간으로 표기)
        now_str = now_kst_str()
        html_content = html_content.replace('const UPDATE_TIME_STRING = "2026-05-21 12:00:00";', f'const UPDATE_TIME_STRING = "{now_str}";')

        # 최근 7일 수집 추세(시계열) 주입 — 트렌드 위젯용. 실패해도 대시보드는 정상 생성되도록 방어.
        try:
            trend = self.db_manager.get_recent_scrape_stats(7)
        except Exception:
            trend = {"days": 0, "total_new": 0, "total_closed": 0, "daily": []}
        trend_json = json.dumps(trend, ensure_ascii=False).replace("</", "<\\/")
        html_content = html_content.replace("const SCRAPE_TREND = {};", f"const SCRAPE_TREND = {trend_json};")

        # 5. 최종 대시보드 파일 기록
        with open(self.output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        print(f"    -> HTML 대시보드 생성 및 바인딩 완료: {self.output_path} ({len(job_list)}건 적재)")
        return len(job_list)
