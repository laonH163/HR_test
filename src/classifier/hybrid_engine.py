import re
import json

class HybridClassificationEngine:
    def __init__(self):
        # 1. 근무형태 3단 분류 사전
        self.work_patterns = {
            "풀재택": [r"풀재택", r"전면재택", r"100%\s*(재택|리모트|원격)", r"상시재택", r"완전재택", r"완전\s*리모트", r"상시\s*리모트"],
            "하이브리드 (주2~3회 재택)": [r"하이브리드", r"주\s*\d\s*(회|일)\s*재택", r"주\s*\d\s*(회|일)\s*리모트", r"일주일에\s*\d\s*(회|일)\s*재택", r"부분\s*재택", r"재택\s*혼용", r"리모트\s*근무", r"재택\s*가능"]
        }

        # 2. 기업 규모 매타 사전 (매출 규모 억 단위, 사원수 명 단위 / 주요 게임사 데이터 하이브리드 기본값 탑재)
        self.company_meta_presets = {
            "더블유게임즈": {"revenue": 3400, "size": 350},
            "시프트업": {"revenue": 1600, "size": 290},
            "넥슨": {"revenue": 35000, "size": 1500},
            "넥슨코리아": {"revenue": 35000, "size": 1500},
            "크래프톤": {"revenue": 19000, "size": 1600},
            "엔씨소프트": {"revenue": 17000, "size": 4000},
            "넷마블": {"revenue": 25000, "size": 800},
            "카카오게임즈": {"revenue": 10000, "size": 450},
            "네오위즈": {"revenue": 3600, "size": 900},
            "데브시스터즈": {"revenue": 1600, "size": 360},
            "컴투스": {"revenue": 7000, "size": 1000},
            "펄어비스": {"revenue": 3800, "size": 800},
            "그라비티": {"revenue": 4600, "size": 500}
        }

    def classify_work_type(self, text):
        """본문 텍스트 내 키워드를 파싱하여 근무 형태 자동 분류"""
        norm_text = text.lower()

        # 1. 풀재택 검사
        for pattern in self.work_patterns["풀재택"]:
            if re.search(pattern, norm_text):
                return "풀재택"

        # 2. 하이브리드 검사
        for pattern in self.work_patterns["하이브리드 (주2~3회 재택)"]:
            if re.search(pattern, norm_text):
                return "하이브리드 (주2~3회 재택)"

        # 3. 기본값: 전면출근 (지정어가 특별히 없을 경우)
        return "전면출근"

    def extract_experience(self, text):
        """경력 연차 범위 파싱 (예: "3년 이상", "경력 5년~10년", "신입", "무관")"""
        norm_text = text.replace(" ", "")

        # 신입 케이스
        if "신입" in norm_text and not "경력" in norm_text:
            return 0, 1

        # 경력 무관
        if "경력무관" in norm_text or "경력년수무관" in norm_text:
            return 0, None

        # "~년차 이상" 또는 "~년차~~년차" 패턴 정규식 매칭
        # 1) 경력 3~5년, 5년~10년 형태
        range_match = re.search(r"(\d+)년[~-](\d+)년", norm_text)
        if range_match:
            return int(range_match.group(1)), int(range_match.group(2))

        # 2) 3년 이상 형태
        over_match = re.search(r"(\d+)년이상", norm_text)
        if over_match:
            return int(over_match.group(1)), None

        # 3) 5년 이하 형태
        under_match = re.search(r"(\d+)년이하", norm_text)
        if under_match:
            return 0, int(under_match.group(1))

        # 4) 단순 경력 년 수 언급 (상한은 임의로 단정하지 않고 '이상'으로 처리)
        single_match = re.search(r"경력(\d+)년", norm_text)
        if single_match:
            val = int(single_match.group(1))
            return val, None

        # 5) 직급 표현 폴백: 명시적 연차 표기가 전혀 없을 때만 직급으로 최소 연차를 추정.
        #    공백 보존 원문(text)에서 매칭하고 '급여'는 negative lookahead로 배제한다.
        #    (norm_text는 공백을 지워 "과장 급여"→"과장급여"→"과장급" 오탐을 만들므로 쓰지 않음)
        #    '급'(직급 표기) 또는 직급명 직후 '이상'만 인정해 "과장님과 협업" 류도 배제.
        rank_to_min_years = [("부장", 12), ("차장", 9), ("과장", 6), ("대리", 3), ("주임", 2)]
        for rank, min_yr in rank_to_min_years:
            if re.search(rank + r"\s?급(?!여)", text) or re.search(rank + r"\s?이상", text):
                return min_yr, None

        # 기본 폴백: 연차 무관 처리
        return 0, None

    def extract_salary(self, text):
        """연봉 범위 추출 (단위: 만원 / 예: "연봉 5,000만원", "4,500 ~ 6,000")"""
        norm_text = text.replace(",", "").replace(" ", "")

        # 1) 5000-6000만원, 5000~6000만원 형태
        range_match = re.search(r"(\d+)[~-](\d+)만원", norm_text)
        if range_match:
            return int(range_match.group(1)), int(range_match.group(2))

        # 2) 5000만원 이상 형태
        over_match = re.search(r"(\d+)만원이상", norm_text)
        if over_match:
            return int(over_match.group(1)), None

        # 3) 회사 내규에 따름 등 연봉 안 써진 경우가 대다수이므로 기본값 NULL 리턴
        return None, None

    def extract_tools_and_skills(self, text):
        """본문에서 세무/회계/재무 관련 전용 도구(ERP) 및 스킬 키워드 추출"""
        norm_text = text.lower()
        tools = []

        erp_tools = ["sap", "더존", "douzone", "oracle", "영림원", "excel", "엑셀", "ifrs", "gap"]
        for tool in erp_tools:
            if tool in norm_text:
                tools.append(tool.upper())

        # 중복 제거 및 콤마 구분자 문자열화
        unique_tools = list(set(tools))
        return ", ".join(unique_tools) if unique_tools else "EXCEL"

    def generate_ai_summary(self, title, company, work_type, exp_min, exp_max, tools):
        """분석된 속성 정보들을 종합하여 사용자가 한눈에 이해할 수 있는 3줄 한글 요약 생성"""
        if exp_min == 0 and exp_max == 1:
            exp_str = "신입 지원 가능"
        elif exp_min > 0 and exp_max:
            exp_str = f"경력 {exp_min}~{exp_max}년"
        elif exp_min > 0:
            exp_str = f"경력 {exp_min}년 이상"
        else:
            exp_str = "경력 무관 (신입 지원 가능)"

        summary_lines = [
            f"1. {company} 재무실 - '{title}' 채용 공고",
            f"2. 근무 요건: {work_type} | {exp_str}",
            f"3. 요구 직무 도구 및 핵심 역량: {tools if tools else 'EXCEL 중심업무'}"
        ]
        return "\n".join(summary_lines)

    def _normalize_company_name(self, company):
        """법인 표기(㈜, (주), 주식회사 등)와 공백을 제거해 프리셋 매칭률을 높임"""
        if not company:
            return ""
        norm = company
        for token in ["㈜", "（주）", "(주)", "주식회사"]:
            norm = norm.replace(token, "")
        return norm.strip().replace(" ", "")

    def _lookup_company_meta(self, company):
        """회사명으로 매출/규모 프리셋을 조회. 정확 매칭 → 정규화 매칭 → 부분 포함 매칭 순."""
        default = {"revenue": None, "size": None}
        if not company:
            return default
        # 1) 원본 그대로 정확 매칭
        if company in self.company_meta_presets:
            return self.company_meta_presets[company]
        # 2) 법인 표기 정규화 후 정확 매칭
        norm = self._normalize_company_name(company)
        for key, meta in self.company_meta_presets.items():
            if self._normalize_company_name(key) == norm:
                return meta
        # 3) 부분 포함 매칭 (예: "넥슨코리아" ↔ "넥슨")
        for key, meta in self.company_meta_presets.items():
            nk = self._normalize_company_name(key)
            if nk and (nk in norm or norm in nk):
                return meta
        return default

    def analyze_and_classify(self, job_posting):
        """하나의 채용 공고(마스터)를 완벽하게 분석하여 job_categories 용 엔티티를 빌드"""
        raw_text = job_posting["raw_html"]
        company = job_posting["company_name"]
        title = job_posting["title"]

        # 1. 근무 형태 분류
        work_type = self.classify_work_type(raw_text)

        # 2. 최소/최대 연차 추출
        exp_min, exp_max = self.extract_experience(raw_text)

        # 3. 연봉 추출
        sal_min, sal_max = self.extract_salary(raw_text)

        # 4. 사용 도구 및 정밀 스킬 태깅
        tools = self.extract_tools_and_skills(raw_text)

        # 5. 직무 분류 대분류 결정 (타이틀과 본문 매칭)
        primary_category = "회계"
        norm_title = title.lower()
        if "세무" in norm_title or "tax" in norm_title or "부가세" in norm_title:
            primary_category = "세무"
        elif "자금" in norm_title or "재무" in norm_title or "treasury" in norm_title or "투자" in norm_title:
            primary_category = "재무/자금"
        elif "통제" in norm_title or "내부회계" in norm_title or "sox" in norm_title:
            primary_category = "내부통제"

        # 6. 회사 메타 프리셋 정보 조회 (법인 표기 정규화 + 부분 매칭 보강)
        preset = self._lookup_company_meta(company)

        # 7. 3줄 요약 생성
        ai_summary = self.generate_ai_summary(title, company, work_type, exp_min, exp_max, tools)

        # 8. 핵심 자격요건 리스트화 (본문 라인 중 대시나 이머지 패턴 기반 리스트 파싱)
        key_requirements = []
        preferred_skills = []

        lines = raw_text.split("\n")
        # 자격요건 세션 및 우대사항 세션 분리 파싱
        current_session = "none"
        for line in lines:
            line_strip = line.strip()
            if any(h in line_strip for h in ["자격요건", "지원자격", "필수요건", "이런 분을 찾습니다", "자격 요건"]):
                current_session = "req"
                continue
            elif any(h in line_strip for h in ["우대사항", "우대 조건", "이런 분이면 더 좋습니다", "우대 요건"]):
                current_session = "pref"
                continue

            # 목록 형태 추출 (- 또는 * 또는 숫자)
            if line_strip.startswith(("-", "*", "•", "1.", "2.", "3.", "4.", "5.")):
                clean_line = re.sub(r"^[-*•\s\d.]+", "", line_strip).strip()
                if len(clean_line) > 5 and len(clean_line) < 100:
                    if current_session == "req" and len(key_requirements) < 5:
                        key_requirements.append(clean_line)
                    elif current_session == "pref" and len(preferred_skills) < 5:
                        preferred_skills.append(clean_line)

        # 비어 있을 경우 기본값 처리
        if not key_requirements:
            key_requirements = ["상세 공고 자격요건 참조", "해당 분야 회계 지식 소유자"]
        if not preferred_skills:
            preferred_skills = ["게임 산업 관심도 우수자", "동종 업계 경험자 우대"]

        return {
            "job_id": job_posting["id"],
            "primary_category": primary_category,
            "min_experience": exp_min,
            "max_experience": exp_max,
            "salary_min": sal_min,
            "salary_max": sal_max,
            "work_type": work_type,
            "company_revenue": preset["revenue"],
            "company_size": preset["size"],
            "key_requirements": key_requirements,
            "preferred_skills": preferred_skills,
            "tools_used": tools,
            "ai_summary": ai_summary
        }
