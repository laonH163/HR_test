import re
import json

class HybridClassificationEngine:
    # 대시보드에 실리는 자격요건·우대사항 줄에서 걸러낼 연락처 패턴
    # (이메일 / 휴대폰 / 유선번호). 공개 페이지 노출을 원천 차단한다.
    _CONTACT_RE = re.compile(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
        r"|01[0-9][-.\s]?\d{3,4}[-.\s]?\d{4}"
        r"|0\d{1,2}[-.\s]\d{3,4}[-.\s]\d{4}"
    )

    # 수집처 상세 페이지 상단 요약표의 '경력' 라벨 + 값 (라벨과 값이 '경력'을 겹쳐 쓴다).
    # 게임잡: "경력   경력 2년 이상   고용형태 …" / 사람인: "경력\n경력 5~12년\n학력 …"
    _EXP_LABEL_RE = re.compile(r"경력[\s|]*경력[\s]*([^\n|]{1,24})")

    # 자격요건 구역 경계 — 헤더 표기가 수집처마다 달라 변형을 함께 등재한다.
    _REQ_START_MARKERS = ("자격요건", "자격 요건", "지원자격", "지원 자격", "필수요건", "필수 요건")
    _REQ_END_MARKERS = ("우대사항", "우대 사항", "우대조건", "복지 및 혜택", "복리후생",
                        "채용절차", "전형절차", "접수기간", "기타사항")
    # 종료 마커를 못 찾았을 때의 구역 상한 (실측: 자격요건 구역은 길어야 1천자대)
    _REQ_SECTION_MAX_CHARS = 2000

    # 공고 본문이 끝나고 '사이트 꼬리'가 시작되는 지점을 알리는 문구.
    # 태그·자격증 추출은 이 앞까지만 본다. 실측(2026-07-21):
    #  - 사람인: 기업정보 구역의 "정확한 정보는 기업공시 시스템 또는 …" 면책문구가
    #    활성 13건 전부에 '공시' 태그를 붙였다.
    #  - 게임잡: 저작권 문구 뒤 '…에서 진행중인 채용' 타 공고 목록에 섞인
    #    'IR/공시 담당자' 제목이 무관한 회계 공고에 '공시'를 붙였다.
    # 섹션 헤더(자격요건 등)로 구간을 오리는 방식은 헤더가 탭 라벨로 여러 번 나와
    # 본문이 잘게 찢기고 정상 태그(담당업무의 '세무조사', 게임잡 키워드의 'K-IFRS')까지
    # 잃었다. 그래서 '꼬리만 잘라내는' 방식으로 간다 — 아래 문구들은 JD 본문에는
    # 사실상 등장하지 않아 오탐 위험이 낮다.
    #  - 게임잡은 상세 페이지에 '기업뉴스' 블록까지 실어, "게임업체들이 지속가능 경영(ESG)
    #    공시 의무화를…" 같은 기사 문장이 무관한 결산 공고에 '공시' 태그를 붙였다.
    _SITE_TAIL_MARKERS = (
        "저작권자", "무단전재", "진행중인 채용", "이 기업의 다른 공고", "기업뉴스",
        "정확한 정보는 기업공시", "실시간 정보와 상이할 수 있", "면접후기",
        "에서 게재한 자료에 대한 오류",
    )

    def __init__(self):
        # 1. 근무형태 3단 분류 사전
        self.work_patterns = {
            "풀재택": [r"풀재택", r"전면재택", r"100%\s*(재택|리모트|원격)", r"상시재택", r"완전재택", r"완전\s*리모트", r"상시\s*리모트"],
            "하이브리드 (주2~3회 재택)": [r"하이브리드", r"주\s*\d\s*(회|일)\s*재택", r"주\s*\d\s*(회|일)\s*리모트", r"일주일에\s*\d\s*(회|일)\s*재택", r"부분\s*재택", r"재택\s*혼용", r"리모트\s*근무", r"재택\s*가능"],
            # 출근 근무를 '명시'한 표현만. 근무지 주소·'출근시간' 같은 일반 문구는
            # 어느 공고에나 있어 근거가 못 되므로 넣지 않는다.
            "전면출근": [r"전면\s*출근", r"사무실.{0,10}출근", r"오피스.{0,10}출근",
                     r"출근\s*필수", r"매일\s*출근", r"상주\s*근무", r"전\s*직원\s*출근",
                     r"재택\s*(근무)?\s*(는)?\s*(없|불가|미실시|미운영)"]
        }

        # 2. 기업 규모 매타 사전 (매출 규모 억 단위, 사원수 명 단위 / 주요 게임사 데이터 하이브리드 기본값 탑재)
        # revenue: 연매출(억), size: 임직원수(명). 자체수집 20사 커버.
        # 더블유게임즈·그라비티 및 신규 7사는 2024 회계연도 DART 공시 기준 갱신(2026-06-01).
        # (그라비티·NHN size는 별도/본사 기준 — 해외 자회사 포함 연결 전체와 다름)
        self.company_meta_presets = {
            "더블유게임즈": {"revenue": 6335, "size": 394},
            "시프트업": {"revenue": 1600, "size": 290},
            "넥슨": {"revenue": 35000, "size": 1500},
            "넥슨코리아": {"revenue": 35000, "size": 1500},
            "넥슨게임즈": {"revenue": 2561, "size": 1459},
            "크래프톤": {"revenue": 19000, "size": 1600},
            "엔씨소프트": {"revenue": 17000, "size": 4000},
            "넷마블": {"revenue": 25000, "size": 800},
            "카카오게임즈": {"revenue": 10000, "size": 450},
            "네오위즈": {"revenue": 3600, "size": 900},
            "네오플": {"revenue": 13784, "size": 1402},
            "데브시스터즈": {"revenue": 1600, "size": 360},
            "컴투스": {"revenue": 7000, "size": 1000},
            "펄어비스": {"revenue": 3800, "size": 800},
            "그라비티": {"revenue": 5008, "size": 414},
            "조이시티": {"revenue": 1429, "size": 365},
            "라인게임즈": {"revenue": 435, "size": 147},
            "NHN": {"revenue": 24561, "size": 893},
            "위메이드": {"revenue": 6089, "size": 500},
            "스마일게이트": {"revenue": 13700, "size": 1200},
        }

    def classify_work_type(self, text):
        """본문 텍스트 내 키워드를 파싱하여 근무 형태 자동 분류.

        근거가 없으면 '전면출근'이 아니라 '미확인'을 돌려준다. 이전에는 재택 키워드가
        없으면 무조건 '전면출근'을 반환해, 실측상 활성 60건 전부가 '전면출근'으로
        표시됐다 — 판정이 아니라 기본값이 사실처럼 보인 것이다(2026-07-21 교정).
        대시보드는 이미 '미확인'을 필터·회색 표기로 지원한다."""
        norm_text = text.lower()

        # 1. 풀재택 검사
        for pattern in self.work_patterns["풀재택"]:
            if re.search(pattern, norm_text):
                return "풀재택"

        # 2. 하이브리드 검사
        for pattern in self.work_patterns["하이브리드 (주2~3회 재택)"]:
            if re.search(pattern, norm_text):
                return "하이브리드 (주2~3회 재택)"

        # 3. 출근 근무를 명시한 경우에만 '전면출근'으로 확정
        for pattern in self.work_patterns["전면출근"]:
            if re.search(pattern, norm_text):
                return "전면출근"

        # 4. 근거 없음 — 단정하지 않는다
        return "미확인"

    def _match_experience(self, norm_text, allow_bare_range=False):
        """공백 제거 텍스트에서 연차 범위를 찾는다. 못 찾으면 None(→ 다음 단계로 폴백).

        allow_bare_range: '7-10년'처럼 '경력' 앵커 없이 나온 범위도 연차로 인정할지.
        제목·'경력' 라벨 값처럼 **문맥이 이미 연차로 확정된 짧은 텍스트**에서만 켠다.
        본문 전체에서 켜면 '계약기간 3-5년'·'사업기간 5-10년' 같은 무관한 기간까지
        연차로 오독한다(코덱스 교차검토 지적, 2026-07-21).

        반환값은 항상 튜플이거나 None이다 — (0, None)처럼 값이 0인 결과도 튜플이라
        참이므로 호출부는 `if hit:`으로 분기해도 안전하다. 이 계약을 깨지 말 것."""
        # 경력 무관
        if "경력무관" in norm_text or "경력년수무관" in norm_text:
            return 0, None

        # 1) 경력 3~5년, 5년~10년 형태
        m = re.search(r"(\d+)년[~-](\d+)년", norm_text)
        if m:
            rng = self._exp_range(m)
            if rng:
                return rng

        # 1-1) 경력 1~3년차, 3-5년차 형태
        m = re.search(r"(\d+)[~-](\d+)년차", norm_text)
        if m:
            rng = self._exp_range(m)
            if rng:
                return rng

        # 1-2) '경력 7-10년'·'5~12년'처럼 앞쪽 '년'이 생략된 범위 표기.
        #      실측(2026-07-21): 원티드 '재무회계 경력 7-10년'이 어떤 패턴에도 안 걸려
        #      0년(경력 무관)으로 저장되고 있었다. 사람인 요약의 '경력 5~12년'도 동일.
        #      본문에서는 반드시 '경력' 앵커를 요구한다 — 앵커 없이 훑으면 '계약기간 3-5년'
        #      같은 무관한 기간을 연차로 읽는다.
        patterns = [r"경력[^\d]{0,3}(\d+)[~-](\d+)년"]
        if allow_bare_range:
            patterns.append(r"(\d+)[~-](\d+)년")
        for pattern in patterns:
            m = re.search(pattern, norm_text)
            if m:
                rng = self._exp_range(m)
                if rng:
                    return rng

        # 2) 3년 이상, 3년↑ 형태
        m = re.search(r"(\d+)년(?:이상|차이상|↑)", norm_text)
        if m:
            return int(m.group(1)), None

        # 3) 5년 이하 형태 ('↓'는 사람인 요약표의 '5년 ↓' 표기 — '이하'와 같은 뜻)
        m = re.search(r"(\d+)년(?:이하|차이하|↓)", norm_text)
        if m:
            return 0, int(m.group(1))

        # 3-1) "3년 전후", "3년 내외" 형태
        m = re.search(r"(\d+)년(?:내외|전후)", norm_text)
        if m:
            val = int(m.group(1))
            return max(0, val - 1), val + 1

        # 4) 단순 경력 년 수 언급 (상한은 임의로 단정하지 않고 '이상'으로 처리)
        m = re.search(r"경력(\d+)년", norm_text)
        if m:
            return int(m.group(1)), None

        return None

    @staticmethod
    def _exp_range(match):
        """범위 매치를 (min, max)로 환산 — 상식 밖 값은 버린다(None).

        '2024-2025년 실적'처럼 연도 표기가 연차로 둔갑하는 것을 막는 상한선."""
        low, high = int(match.group(1)), int(match.group(2))
        if low > high or high > 40:
            return None
        return low, high

    def _experience_label_value(self, text):
        """수집처가 제공하는 '경력' 요약 라벨의 값 — 가장 신뢰도 높은 연차 출처.

        게임잡('경력   경력 2년 이상')·사람인('경력\\n경력 5~12년') 모두 상세 페이지
        상단 요약표에 라벨('경력')과 값('경력 N년 이상')을 나란히 싣는다. 본문 하단의
        '이 기업의 다른 공고' 목록에는 이 이중 표기가 없어(값만 '경력 4년↑' 형태)
        첫 매치는 항상 해당 공고 자신의 요건이 된다.
        실측 근거(2026-07-21): 게임잡 컴투스 공고들이 본문 8,600자 이후에 붙는 타 공고
        목록의 '4-8년차'를 읽어 IR/공시 주니어·시니어가 똑같이 4~8년으로 저장됐다."""
        m = self._EXP_LABEL_RE.search(text or "")
        return m.group(1) if m else None

    def _requirement_section(self, text):
        """'자격요건' 헤더 이후 ~ '우대사항/복지/전형' 이전 구간만 잘라낸다.

        경력 라벨이 없는 수집처에서 본문 뒤쪽(복지·타 공고)의 연차가 섞이는 것을 막는
        2차 방어선. 헤더를 못 찾으면 None을 돌려 전체 본문 단계로 넘긴다."""
        if not text:
            return None
        start = None
        for marker in self._REQ_START_MARKERS:
            idx = text.find(marker)
            if idx >= 0 and (start is None or idx < start):
                start = idx
        if start is None:
            return None
        end = len(text)
        for marker in self._REQ_END_MARKERS:
            idx = text.find(marker, start + 1)
            if idx >= 0 and idx < end:
                end = idx
        # 종료 마커가 없으면 본문 끝까지 잡히는데, 그러면 뒤쪽 '다른 공고 목록'까지
        # 삼켜 이 단계의 존재 의의가 사라진다. 실측상 자격요건 구역은 길어야 1천자대.
        end = min(end, start + self._REQ_SECTION_MAX_CHARS)
        section = text[start:end]
        return section if section.strip() else None

    def extract_experience(self, text, title=None):
        """경력 연차 범위 파싱 (예: "3년 이상", "경력 5년~10년", "신입", "무관").

        탐색 범위를 좁은 순서대로 훑어 '본문 아무 데나 있는 숫자'를 읽는 사고를 막는다:
        제목 → 수집처 '경력' 요약 라벨 → 자격요건 구역 → 전체 본문 → 직급 폴백.
        (2026-07-21 교정 이전에는 전체 본문만 봤고, 그 결과 게임잡 본문 하단의 타 공고
        연차·사람인 공통 레이아웃의 '신입' 문구를 요건으로 오독했다.)

        title의 '신입'(단독) 신호는 본문보다 우선한다 — 본문의 '경력 개발 기회'·
        '인턴 경력 우대' 같은 문구가 신입 공고 판정을 무력화하는 것을 막는다.
        '신입/경력' 병행 제목은 기존 로직(숫자 범위 우선)에 맡긴다."""
        if title:
            norm_title = title.replace(" ", "")
            if "신입" in norm_title and "경력" not in norm_title:
                return 0, 1
            # 제목에 연차가 명시됐으면 본문보다 우선 — 제목은 오염될 여지가 없다
            # (짧고 문맥이 확정적이므로 '(5~15년)'처럼 앵커 없는 범위도 인정)
            hit = self._match_experience(norm_title, allow_bare_range=True)
            if hit:
                return hit

        # 수집처가 구조화해 준 '경력' 요약 라벨
        label_value = self._experience_label_value(text)
        if label_value:
            norm_label = label_value.replace(" ", "")
            # 라벨 값은 '경력' 칸의 내용이 확정이므로 앵커 없는 '5~12년'도 인정
            hit = self._match_experience(norm_label, allow_bare_range=True)
            if hit:
                return hit
            # 라벨 자리의 '무관'은 경력 무관이 확정이다(사람인 '무관(신입포함)').
            # 본문 전체에서는 '학력 무관'과 섞이므로 이 단계에서만 인정한다.
            if "무관" in norm_label:
                return 0, None

        norm_text = text.replace(" ", "")

        # 신입 케이스
        if "신입" in norm_text and not "경력" in norm_text:
            return 0, 1

        # 자격요건 구역 우선 탐색
        section = self._requirement_section(text)
        if section:
            hit = self._match_experience(section.replace(" ", ""))
            if hit:
                return hit

        hit = self._match_experience(norm_text)
        if hit:
            return hit

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

    def strip_site_tail(self, text):
        """공고 본문 뒤에 붙는 '사이트 꼬리'(저작권 문구·면책조항·타 공고 목록)를 잘라낸다.

        머리(요약표·키워드·담당업무)는 그대로 두므로 정상 신호를 잃지 않는다.
        꼬리 문구를 못 찾으면 원문 그대로 돌려준다."""
        if not text:
            return text
        cut = len(text)
        for marker in self._SITE_TAIL_MARKERS:
            idx = text.find(marker)
            if 0 <= idx < cut:
                cut = idx
        return text[:cut]

    def extract_tools_and_skills(self, text):
        """본문에서 세무/회계/재무 관련 전용 도구(ERP) 및 스킬 키워드 추출"""
        norm_text = text.lower()
        tools = []

        erp_tools = ["sap", "더존", "douzone", "oracle", "영림원", "excel", "엑셀", "ifrs", "gap"]
        for tool in erp_tools:
            if tool in norm_text:
                tools.append(tool.upper())

        # 중복 제거 후 결정적 순서로 직렬화.
        # set 순서를 그대로 쓰면 같은 데이터인데도 실행마다 문자열이 달라져
        # index.html diff에 의미 없는 변경이 쌓인다(2026-07-21 지적).
        unique_tools = sorted(set(tools))
        # 근거가 없으면 'EXCEL'을 지어내지 않는다 — 실측상 EXCEL 단독 31건 중 29건이
        # 제목·본문 어디에도 엑셀 언급이 없었다(기본값이 사실로 둔갑한 사례).
        return ", ".join(unique_tools) if unique_tools else None

    def generate_ai_summary(self, title, company, work_type, exp_min, exp_max, tools, category="재무/회계"):
        """분석된 속성 정보들을 종합하여 사용자가 한눈에 이해할 수 있는 3줄 한글 요약 생성.

        category: 직무 대분류(회계/세무/재무·자금/내부통제) — 과거 '재무실' 고정 표기가
        세무·자금 공고까지 재무실로 오표기하던 것을 실제 분류값으로 교정."""
        if exp_min == 0 and exp_max == 1:
            exp_str = "신입 지원 가능"
        elif exp_min > 0 and exp_max:
            exp_str = f"경력 {exp_min}~{exp_max}년"
        elif exp_min > 0:
            exp_str = f"경력 {exp_min}년 이상"
        else:
            exp_str = "경력 무관 (신입 지원 가능)"

        summary_lines = [
            f"1. {company} {category} 직무 - '{title}' 채용 공고",
            f"2. 근무 요건: {work_type} | {exp_str}",
            f"3. 요구 직무 도구 및 핵심 역량: {tools if tools else '공고에 명시 없음'}"
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
        """회사명으로 매출/규모 프리셋을 조회. 정확 매칭 → 정규화 매칭 → 부분 포함 매칭 순.

        계열사 및 자회사의 지주사 역추적 폴백 규칙을 내장하여 매칭률을 보완합니다 (Milestone 5).
        """
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

        # 4) 지능형 계열사 역매칭 폴백 규칙 (프리셋에 없는 신생/계열 법인 매칭)
        fallback_rules = {
            "컴투스": "컴투스",
            "com2us": "컴투스",
            "위메이드": "위메이드",
            "wemade": "위메이드",
            "넥슨": "넥슨",
            "nexon": "넥슨",
            "스마일게이트": "스마일게이트",
            "smilegate": "스마일게이트",
            "하이브": "NHN",  # 하이브IM 등 IT 게임 퍼블리셔 규모의 유추 매칭
            "hybe": "NHN"
        }
        for kw, target in fallback_rules.items():
            if kw in norm.lower():
                return self.company_meta_presets.get(target, default)

        return default

    def analyze_and_classify(self, job_posting):
        """하나의 채용 공고(마스터)를 완벽하게 분석하여 job_categories 용 엔티티를 빌드"""
        raw_text = job_posting["raw_html"]
        company = job_posting["company_name"]
        title = job_posting["title"]

        # 제목+본문 결합 텍스트로 분류 신호를 추출한다.
        # 본문이 풍부한 공고(크래프톤·시프트업·플랫폼)도 제목의 "(3년 이상)"·"(과장급)"·"재택"
        # 신호가 본문엔 없을 수 있어, 제목을 함께 봐야 연차·근무형태 추출이 정확해진다.
        analysis_text = f"{title}\n{raw_text}"

        # 1. 근무 형태 분류
        work_type = self.classify_work_type(analysis_text)

        # 2. 최소/최대 연차 추출 (제목의 '신입' 단독 신호는 본문보다 우선)
        exp_min, exp_max = self.extract_experience(analysis_text, title=title)

        # 3. 연봉 추출
        sal_min, sal_max = self.extract_salary(analysis_text)

        # 4. 사용 도구 및 정밀 스킬 태깅
        tools = self.extract_tools_and_skills(analysis_text)

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

        # 7. 3줄 요약 생성 (직무 대분류를 반영 — '재무실' 고정 표기 오류 교정)
        ai_summary = self.generate_ai_summary(title, company, work_type, exp_min, exp_max, tools, category=primary_category)

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
            # 복리후생·근무조건·전형 섹션이 시작되면 수집을 멈춘다. 없으면 '우대사항'이
            # 본문 끝까지 이어져 '급여제도 : 퇴직연금, 인센티브제'·'출퇴근 : 차량유류비'
            # 같은 복지 항목이 우대사항으로 저장된다(2026-07-21 실측 5건).
            elif any(h in line_strip for h in ["근무조건", "근무 조건", "복지 및 혜택", "복리후생",
                                               "복지혜택", "채용절차", "전형절차", "접수기간",
                                               "제출서류", "유의사항", "기업정보", "기타사항"]):
                current_session = "none"
                continue

            # 목록 형태 추출 (- 또는 * 또는 숫자)
            if line_strip.startswith(("-", "*", "•", "1.", "2.", "3.", "4.", "5.")):
                clean_line = re.sub(r"^[-*•\s\d.]+", "", line_strip).strip()
                # [개인정보 차단] 이 두 리스트는 공개 GitHub Pages 대시보드에 그대로 실린다.
                # 공고 본문의 '○○@회사.com으로 이력서 제출'·담당자 연락처가 불릿으로 들어오면
                # 그대로 박제되므로 연락처가 섞인 줄은 통째로 버린다(2026-07-21 코덱스 지적).
                if self._CONTACT_RE.search(clean_line):
                    continue
                if len(clean_line) > 5 and len(clean_line) < 100:
                    if current_session == "req" and len(key_requirements) < 5:
                        key_requirements.append(clean_line)
                    elif current_session == "pref" and len(preferred_skills) < 5:
                        preferred_skills.append(clean_line)

        # 추출 실패 시 그럴듯한 문구를 지어내지 않는다 — 빈 목록으로 두고 화면이
        # '공고 원문 확인 필요'로 정직하게 표기하게 한다.
        # 실측(2026-07-21): 자격요건 34건·우대사항 43건이 기본 문구였고, 게임잡 17건은
        # 둘 다 기본 문구였다(게임잡 상세요강이 iframe에 있어 본문 파싱이 애초에 불가).
        # '게임 산업 관심도 우수자' 같은 문구가 공고에 실제로 있는 것처럼 보였다.

        # 9. 우대 자격증 및 실무 역량 태깅 (Milestone 5 정교화)
        preferred_certifications = []
        preferred_skills_tags = []

        # 태그·자격증은 사이트 꼬리를 잘라낸 본문에서만 뽑는다 — 면책문구("정확한 정보는
        # 기업공시 시스템…")나 뒤에 붙는 타 공고 목록의 단어가 태그로 둔갑하는 것을 막는다.
        norm_text_lower = f"{title}\n{self.strip_site_tail(raw_text)}".lower()

        # 9-1. 자격증 사전식 정밀 추출
        certs_dict = {
            "CPA": ["cpa", "한국공인회계사", "공인회계사"],
            "AICPA": ["aicpa", "uscpa", "미국공인회계사"],
            "CTA": ["cta", "세무사"],
            "CFA": ["cfa", "재무분석사"],
            "FRM": ["frm", "재무위험관리사"]
        }
        for cert_key, keywords in certs_dict.items():
            if any(kw in norm_text_lower for kw in keywords):
                preferred_certifications.append(cert_key)

        # 9-2. 실무 역량 사전식 정밀 추출
        skills_dict = {
            "IFRS": ["ifrs", "국제회계기준", "k-ifrs"],
            "연결회계": ["연결", "consolidation", "연결결산"],
            "공시": ["공시", "disclosure", "dart"],
            "내부회계": ["내부회계", "내부통제", "sox", "내부회계관리제도"],
            "세무조사": ["세무조사", "tax audit"],
            "자금조달": ["조달", "funding", "차입"],
            "원가회계": ["원가", "cost accounting"]
        }
        for skill_key, keywords in skills_dict.items():
            if any(kw in norm_text_lower for kw in keywords):
                preferred_skills_tags.append(skill_key)

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
            "ai_summary": ai_summary,
            "preferred_certifications": preferred_certifications,
            "preferred_skills_tags": preferred_skills_tags
        }
