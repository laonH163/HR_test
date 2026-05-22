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

            job_list.append(job_dict)

        # 3. 템플릿 리딩
        with open(self.template_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        # 4. 데이터 인라인 바인딩 치환
        # JSON 데이터 인라인 주입
        json_data_str = json.dumps(job_list, ensure_ascii=False)
        html_content = html_content.replace("const JOBS_DATA = [];", f"const JOBS_DATA = {json_data_str};")

        # 갱신 타임스탬프 주입
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        html_content = html_content.replace('const UPDATE_TIME_STRING = "2026-05-21 12:00:00";', f'const UPDATE_TIME_STRING = "{now_str}";')

        # 5. 최종 대시보드 파일 기록
        with open(self.output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        print(f"    -> HTML 대시보드 생성 및 바인딩 완료: {self.output_path} ({len(job_list)}건 적재)")
        return len(job_list)
