import os
import json
import sqlite3
from datetime import datetime

class HTMLGenerator:
    def __init__(self, db_manager, template_path="templates/dashboard_template.html", output_path="index.html"):
        self.db_manager = db_manager
        self.template_path = template_path
        self.output_path = output_path

    def generate_dashboard(self):
        """SQLite에서 데이터를 긁어와 단일 HTML 대시보드 파일을 생성"""
        # 1. 템플릿 존재 여부 확인
        if not os.path.exists(self.template_path):
            raise FileNotFoundError(f"HTML Template not found: {self.template_path}")

        # 2. SQLite 데이터 조회
        active_postings = self.db_manager.get_all_active_postings()

        # Row 데이터를 직렬화 가능한 dict의 리스트로 가공
        job_list = []
        for row in active_postings:
            job_dict = dict(row)
            # Row 내 None 값이나 NULL 필드 안정적 폴백 처리
            if job_dict.get("min_experience") is None:
                job_dict["min_experience"] = 0
            if job_dict.get("tools_used") is None:
                job_dict["tools_used"] = "EXCEL"

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

        # 갱신 타임스탬프 주입
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
