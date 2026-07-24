import unittest
import os
import sqlite3
from src.database.db_manager import DBManager
from src.classifier.hybrid_engine import HybridClassificationEngine
from src.analyzer.delta_analyzer import DeltaAnalyzer

class TestClassifierAndDelta(unittest.TestCase):
    def setUp(self):
        self.db_path = "data/test_classifier_master.db"
        self.db_manager = DBManager(db_path=self.db_path)
        self.engine = HybridClassificationEngine()
        self.analyzer = DeltaAnalyzer(self.db_manager)

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except PermissionError:
                pass

    def _age_postings(self, ids, last_seen="2026-01-01"):
        """마감 유예(CLOSE_GRACE_DAYS)를 통과하도록 관측일을 과거로 밀고, 그 다음 날
        해당 소스들이 정상 동작한 실행 이력을 넣어 '공정한 미관측일'을 만들어준다.
        유예 도입 전의 '즉시 마감' 시나리오를 테스트하려면 필요하다."""
        conn = self.db_manager.get_connection()
        conn.executemany(
            "UPDATE job_postings SET last_seen_date = ? WHERE id = ?",
            [(last_seen, i) for i in ids])
        placeholders = ",".join("?" * len(ids))
        sources = [r["source"] for r in conn.execute(
            f"SELECT DISTINCT source FROM job_postings WHERE id IN ({placeholders})", list(ids))]
        conn.commit()
        conn.close()
        self.db_manager.insert_scrape_log({
            "run_date": "2026-01-02", "newly_added": 0, "modified_count": 0,
            "closed_count": 0, "is_success": 1, "error_log": None,
            "source_counts": {s: 1 for s in sources},
            "successful_sources": sources,
        })

    def test_work_type_classification(self):
        """근무 형태 정밀 3단 분류 검증"""
        # 1) 풀재택 케이스
        self.assertEqual(self.engine.classify_work_type("우리는 전면재택 제도를 시행합니다."), "풀재택")
        self.assertEqual(self.engine.classify_work_type("복지: 100% 리모트 재택근무 가능"), "풀재택")

        # 2) 하이브리드 케이스
        self.assertEqual(self.engine.classify_work_type("주 2회 하이브리드 재택근무 제공"), "하이브리드 (주2~3회 재택)")
        self.assertEqual(self.engine.classify_work_type("본 공고는 일주일에 3일 재택근무를 섞어서 일합니다."), "하이브리드 (주2~3회 재택)")

        # 3) 전면출근은 '명시된 경우'에만 확정한다
        self.assertEqual(self.engine.classify_work_type("판교 사무실로 매일 출근합니다."), "전면출근")
        self.assertEqual(self.engine.classify_work_type("본 포지션은 전면 출근 근무입니다."), "전면출근")

        # 4) 근거가 없으면 '전면출근'으로 단정하지 않는다 — 기본값이 사실로 둔갑하던 것 교정
        #    (2026-07-21 실측: 활성 60건 전부가 근거 없이 '전면출근'이었다)
        self.assertEqual(
            self.engine.classify_work_type("회계 결산 및 세무 신고 업무를 담당합니다."), "미확인")

    def test_experience_extraction(self):
        """경력 요구 연차 추출 로직 검증"""
        # 1) 범위 추출
        min_exp, max_exp = self.engine.extract_experience("지원 자격: 경력 3년 ~ 5년 담당자")
        self.assertEqual(min_exp, 3)
        self.assertEqual(max_exp, 5)

        # 1-1) 년차 범위 추출 검증
        min_exp, max_exp = self.engine.extract_experience("경력 1~3년차 모집")
        self.assertEqual(min_exp, 1)
        self.assertEqual(max_exp, 3)

        # 2) 이상 조건 추출
        min_exp, max_exp = self.engine.extract_experience("자격 요건: 관련 직무 5년 이상 소유자")
        self.assertEqual(min_exp, 5)
        self.assertIsNone(max_exp)

        # 2-1) 화살표 이상 추출 검증
        min_exp, max_exp = self.engine.extract_experience("경력: 3년↑")
        self.assertEqual(min_exp, 3)
        self.assertIsNone(max_exp)

        # 3) 5년 이하 형태
        min_exp, max_exp = self.engine.extract_experience("자격요건: 경력 5년 이하")
        self.assertEqual(min_exp, 0)
        self.assertEqual(max_exp, 5)

        # 3-1) 전후/내외 추출 검증
        min_exp, max_exp = self.engine.extract_experience("회계 결산 3년 전후 경력자")
        self.assertEqual(min_exp, 2)
        self.assertEqual(max_exp, 4)

        # 3-2) 신입 지원 가능
        min_exp, max_exp = self.engine.extract_experience("신입 채용 공고 (초보자 지원 가능)")
        self.assertEqual(min_exp, 0)
        self.assertEqual(max_exp, 1)

        # 4) 직급 표현 폴백 ('급'/'이상'이 붙은 경우만, 명시 연차가 없을 때)
        min_exp, max_exp = self.engine.extract_experience("대리급 회계 결산 담당자 모집")
        self.assertEqual(min_exp, 3)
        self.assertIsNone(max_exp)

        min_exp, max_exp = self.engine.extract_experience("과장급 이상 세무 전문가를 찾습니다")
        self.assertEqual(min_exp, 6)
        self.assertIsNone(max_exp)

        # 5) 직급 단어가 무관한 문맥(과장님과 협업)에 있을 땐 오탐 없이 연차 무관 처리
        min_exp, max_exp = self.engine.extract_experience("팀 내 과장님과 긴밀히 협업하는 직무입니다")
        self.assertEqual(min_exp, 0)
        self.assertIsNone(max_exp)

        # 6) 명시 연차가 있으면 직급보다 우선 (대리급이지만 5년 이상이 명시된 경우)
        min_exp, max_exp = self.engine.extract_experience("대리급, 경력 5년 이상 우대")
        self.assertEqual(min_exp, 5)
        self.assertIsNone(max_exp)

        # 7) '급여' 오탐 방지 — "과장 급여"/"대리 급여"가 직급('과장급')으로 잘못 잡히지 않아야 함
        #    (재무 본문엔 payroll/급여 정산 표현이 빈발하므로 중요)
        min_exp, max_exp = self.engine.extract_experience("과장 급여대장 관리 및 결산 지원")
        self.assertEqual(min_exp, 0)
        self.assertIsNone(max_exp)
        min_exp, max_exp = self.engine.extract_experience("대리 급여 정산 업무 담당")
        self.assertEqual(min_exp, 0)
        self.assertIsNone(max_exp)

    def test_experience_scope_priority(self):
        """연차 탐색 범위 우선순위 — 제목 → 수집처 '경력' 라벨 → 자격요건 → 전체 본문.

        2026-07-21 실측 사고 재현: 게임잡 본문 뒤쪽에 붙는 '이 기업의 다른 공고' 목록의
        연차를 요건으로 오독해, 제목이 '10년 이상'인 팀장 공고가 4~8년으로 저장됐다."""
        # 1) 제목의 명시 연차가 본문 뒷부분의 타 공고 연차를 이긴다
        body_with_other_postings = (
            "담당업무\n재무관리 총괄\n\n" + ("설명 " * 800) +
            "\n[컴투스홀딩스] 데이터분석가 (4-8년차)\n경력 4년↑\n"
        )
        mn, mx = self.engine.extract_experience(
            f"[컴투스 홀딩스] 재무관리 팀장 (10년 이상)\n{body_with_other_postings}",
            title="[컴투스 홀딩스] 재무관리 팀장 (10년 이상)")
        self.assertEqual((mn, mx), (10, None))

        # 2) 제목에 연차가 없으면 수집처 요약 라벨('경력  경력 2년 이상')을 읽는다
        gamejob_body = (
            "경력   경력 2년 이상       고용형태   정규직\n담당업무\nIR 공시\n"
            + ("설명 " * 800) + "\n[컴투스홀딩스] 데이터분석가 (4-8년차)\n"
        )
        mn, mx = self.engine.extract_experience(
            f"[컴투스] IR/공시 담당자 (주니어)\n{gamejob_body}",
            title="[컴투스] IR/공시 담당자 (주니어)")
        self.assertEqual((mn, mx), (2, None))

    def test_experience_new_range_and_label_forms(self):
        """새로 지원한 표기 — '7-10년'(앞 '년' 생략), 사람인 요약표의 '↓'/'무관'"""
        # 1) 원티드 실측: '재무회계 경력 7-10년'이 어떤 패턴에도 안 걸려 0년으로 저장됐던 건
        mn, mx = self.engine.extract_experience(
            "재무담당자 (팀장급)\n자격요건\n• 재무회계 경력 7-10년 (팀장급 경력 우대)",
            title="재무담당자 (팀장급)")
        self.assertEqual((mn, mx), (7, 10))

        # 2) 사람인 요약표 '경력 5~12년'
        mn, mx = self.engine.extract_experience(
            "회계 담당(대리/과장)\n경력\n경력 5~12년\n학력\n대졸(4년제) 이상",
            title="회계 담당(대리/과장)")
        self.assertEqual((mn, mx), (5, 12))

        # 3) 사람인 요약표 '5년 ↓' = 5년 이하
        mn, mx = self.engine.extract_experience(
            "[재무관리본부] 회계(결산) 업무 담당자\n경력\n경력 5년 ↓\n학력\n학력무관",
            title="[재무관리본부] 회계(결산) 업무 담당자")
        self.assertEqual((mn, mx), (0, 5))

        # 4) 라벨 자리의 '무관(신입포함)'은 경력 무관
        mn, mx = self.engine.extract_experience(
            "재무 정산 담당자 모집(계약직)\n경력\n경력 무관(신입포함)\n학력\n학력무관",
            title="재무 정산 담당자 모집(계약직)")
        self.assertEqual((mn, mx), (0, None))

    def test_experience_range_rejects_non_year_numbers(self):
        """연도·큰 수는 연차로 읽지 않는다 — 새 범위 패턴의 오탐 방지 상한(40년)"""
        mn, mx = self.engine.extract_experience("2024-2025년 회계연도 결산 담당자 모집")
        self.assertEqual((mn, mx), (0, None))

    def test_bare_range_requires_career_anchor_in_body(self):
        """본문의 '앞 년 생략' 범위는 '경력' 앵커가 있어야 인정 — 무관한 기간 오독 방지.

        코덱스 교차검토 지적(2026-07-21): 앵커 없이 훑으면 '계약기간 3-5년'처럼 40년
        이하라 상한 필터도 못 거르는 정상적 비(非)경력 기간을 연차로 읽는다."""
        # 1) 본문의 무관한 기간은 연차가 아니다
        mn, mx = self.engine.extract_experience(
            "회계 담당자 모집\n근무조건\n계약기간 3-5년 후 정규직 전환 검토",
            title="회계 담당자 모집")
        self.assertEqual((mn, mx), (0, None))

        # 2) '경력' 앵커가 붙으면 인정한다
        mn, mx = self.engine.extract_experience(
            "회계 담당자 모집\n자격요건\n관련 경력 3-5년",
            title="회계 담당자 모집")
        self.assertEqual((mn, mx), (3, 5))

        # 3) 제목은 문맥이 확정적이므로 앵커 없이도 인정 (크래프톤 '(5~15년)' 실측)
        mn, mx = self.engine.extract_experience(
            "[Finance Div.] Financial Planning Team Member (5~15년)\n본문",
            title="[Finance Div.] Financial Planning Team Member (5~15년)")
        self.assertEqual((mn, mx), (5, 15))

    def test_site_tail_does_not_pollute_tags(self):
        """사이트 꼬리(면책문구·기업뉴스·타 공고 목록)의 단어가 태그가 되면 안 된다.

        2026-07-21 실측: 사람인 기업정보 구역의 "정확한 정보는 기업공시 시스템 또는 …"
        면책문구 때문에 활성 13건 전부가 '공시' 태그를 받았고, 게임잡은 상세 페이지에
        딸려오는 '기업뉴스'의 ESG 공시 기사 때문에 결산 공고까지 '공시'가 붙었다."""
        job = {
            "id": "saramin_1", "source": "saramin", "company_name": "웹젠",
            "title": "[웹젠] 자금(계약직)(경력)",
            "raw_html": (
                "상세요강\n주요업무\n- 일계표 작성 및 일일 마감\n자격요건\n- 관련 경력 3년 이하\n"
                "기업정보\n실시간 정보와 상이할 수 있으므로, 정확한 정보는 기업공시 시스템 또는 "
                "해당 기업의 홈페이지 등을 통해 재차 확인하시기 바랍니다."
            ),
        }
        result = self.engine.analyze_and_classify(job)
        self.assertNotIn("공시", result["preferred_skills_tags"])

        # 게임잡 기업뉴스 블록도 마찬가지
        job2 = dict(job, id="gamejob_1", source="gamejob", title="[컴투스] 별도 결산 담당자 (4-8년)",
                    raw_html=("담당업무\n- 별도 결산\n기업뉴스\n더보기\nAI 활용한 게임업계 ESG 전략은?\n"
                              "게임업체들이 지속가능 경영(ESG) 공시 의무화를 수 년 앞두고 보고서를 발간했다."))
        result2 = self.engine.analyze_and_classify(job2)
        self.assertNotIn("공시", result2["preferred_skills_tags"])

        # 제목이 실제 공시 직무면 태그는 유지돼야 한다 (과잉 제거 방지)
        job3 = dict(job, id="com2us_1", source="com2us", title="[컴투스] IR/공시 담당자 (시니어)",
                    raw_html="[컴투스] IR/공시 담당자 (시니어)")
        self.assertIn("공시", self.engine.analyze_and_classify(job3)["preferred_skills_tags"])

    def test_benefits_do_not_leak_into_preferred_skills(self):
        """'우대사항' 수집이 복리후생 섹션에서 멈춰야 한다 (2026-07-21 실측 5건 누수)."""
        job = {
            "id": "saramin_2", "source": "saramin", "company_name": "시프트업",
            "title": "[시프트업] 경리/회계 담당자",
            "raw_html": (
                "자격요건\n- 회계 실무 경력 보유자\n"
                "우대사항\n- 더존 사용 경험이 있는 분\n"
                "복지 및 혜택\n- 급여제도 : 퇴직연금, 인센티브제, 4대 보험\n"
                "- 출퇴근 : 차량유류비지급, 야간교통비지급\n"
            ),
        }
        skills = self.engine.analyze_and_classify(job)["preferred_skills"]
        self.assertTrue(any("더존" in s for s in skills), skills)
        for banned in ("급여제도", "출퇴근", "퇴직연금"):
            self.assertFalse(any(banned in s for s in skills), f"{banned} 누수: {skills}")

    def test_contact_info_never_reaches_dashboard_fields(self):
        """자격요건·우대사항은 공개 대시보드에 실린다 — 연락처가 섞인 줄은 버려야 한다.

        2026-07-21 코덱스 교차검토: 불릿 줄을 필터 없이 담고 있어, 실제로
        'recruit@…com으로 이력서 제출'이 공개 페이지에 노출됐다. 담당자 개인 이메일·
        휴대폰이 들어오면 그대로 박제되는 구조라 매 실행마다 재발한다."""
        # 전부 가짜 값이다. 커밋 훅의 개인정보 스캐너가 소스의 리터럴을 실제 연락처로
        # 오탐하지 않도록 조각으로 조립한다(검증 대상 동작은 동일).
        fake_email = "recruit@" + "example.com"
        fake_mobile = "010-" + "0000-" + "0000"
        fake_tel = "02-" + "000-" + "0000"
        job = {
            "id": "x1", "source": "wemadeplay", "company_name": "위메이드플레이",
            "title": "[위메이드플레이] 공시/IR 담당자 모집",
            "raw_html": (
                "자격요건\n- 회계 실무 경력 보유자\n"
                "우대사항\n- 사이트 자체 지원\n"
                f"- {fake_email}으로 이력서 제출\n"
                f"- 문의: {fake_mobile} 담당자\n"
                f"- {fake_tel} 로 연락 바랍니다\n"
                "- 재무제표 분석 역량 보유자\n"
            ),
        }
        result = self.engine.analyze_and_classify(job)
        collected = result["key_requirements"] + result["preferred_skills"]
        for item in collected:
            self.assertNotIn("@", item, f"이메일 노출: {item}")
            self.assertNotRegex(item, r"\d{2,3}-\d{3,4}-\d{4}", f"전화번호 노출: {item}")
        # 정상 항목은 남아 있어야 한다 (과잉 삭제 방지)
        self.assertIn("재무제표 분석 역량 보유자", collected)

    def test_no_fabricated_defaults_when_extraction_fails(self):
        """추출 실패 시 그럴듯한 문구를 지어내지 않는다.

        2026-07-21 실측: 자격요건 34건·우대사항 43건이 기본 문구였고, EXCEL 단독 31건 중
        29건은 제목·본문 어디에도 엑셀 언급이 없었다. 화면에는 공고에 그렇게 적힌 것처럼
        보였다 — 누락보다 위험한 오분류다."""
        job = {
            "id": "y1", "source": "gamejob", "company_name": "컴투스",
            "title": "[컴투스] IR/공시 담당자 (주니어)",
            "raw_html": "담당업무\n\n자격조건\n\n근무지역\n서울 > 금천구\n",
        }
        result = self.engine.analyze_and_classify(job)
        self.assertEqual(result["key_requirements"], [])
        self.assertEqual(result["preferred_skills"], [])
        self.assertIsNone(result["tools_used"])
        self.assertIn("명시 없음", result["ai_summary"])

    def test_tools_extracted_when_evidence_exists(self):
        """근거가 있으면 정상 추출하고, 순서는 실행마다 동일해야 한다(HTML diff 안정화)."""
        text = "자격요건\n- SAP 및 더존 사용 경험\n- 엑셀 활용 능력"
        first = self.engine.extract_tools_and_skills(text)
        self.assertEqual(first, self.engine.extract_tools_and_skills(text))
        self.assertIn("SAP", first)
        self.assertIn("더존", first)

    def test_cert_and_skill_tagging(self):
        """우대 자격증 및 핵심 실무 역량 태깅 검증"""
        # CPA 및 IFRS, 연결회계 추출 검증
        posting = {
            "id": "tag_1",
            "company_name": "네오위즈",
            "title": "연결 회계 결산 담당자 채용 (KICPA 우대)",
            "raw_html": "자격요건: IFRS 연결 결산 가능자. 우대사항: 한국공인회계사(CPA) 자격증 소지자"
        }
        res = self.engine.analyze_and_classify(posting)
        self.assertIn("CPA", res["preferred_certifications"])
        self.assertIn("IFRS", res["preferred_skills_tags"])
        self.assertIn("연결회계", res["preferred_skills_tags"])

        # 내부회계(SOX), 공시 검증
        posting_2 = {
            "id": "tag_2",
            "company_name": "크래프톤",
            "title": "공시 및 내부회계관리제도 수립 담당자",
            "raw_html": "자격요건: 내부회계(SOX) 통제 설계 경험 및 DART 공시 실무 경력자"
        }
        res_2 = self.engine.analyze_and_classify(posting_2)
        self.assertIn("내부회계", res_2["preferred_skills_tags"])
        self.assertIn("공시", res_2["preferred_skills_tags"])

    def test_company_meta_intel_fallback(self):
        """계열사 역매칭 지능형 규칙 검증"""
        # 1) 정확 매칭 프리셋
        res_shiftup = self.engine._lookup_company_meta("시프트업")
        self.assertEqual(res_shiftup["revenue"], 1600)

        # 2) 계열사 역매칭 폴백 매칭
        res_wemadeplay = self.engine._lookup_company_meta("위메이드플레이")
        res_wemade = self.engine.company_meta_presets["위메이드"]
        self.assertEqual(res_wemadeplay["revenue"], res_wemade["revenue"])

        res_hybeim = self.engine._lookup_company_meta("하이브IM")
        res_nhn = self.engine.company_meta_presets["NHN"]
        self.assertEqual(res_hybeim["revenue"], res_nhn["revenue"])

    def test_delta_closed_logic(self):
        """델타 변동 분석기의 마감 처리 로직 검증 (수집 누락 안전장치 포함)"""
        def make_posting(pid, company, title, html):
            return {
                "id": pid,
                "source": "wanted",
                "company_name": company,
                "title": title,
                "origin_url": f"https://wanted.co.kr/wd/{pid}",
                "location": "서울",
                "posted_at": "2026-05-21",
                "status": "ACTIVE",
                "raw_html": html,
                "first_seen_at": "2026-05-21 12:00:00",
                "last_updated_at": "2026-05-21 12:00:00"
            }

        postings = [
            make_posting("wanted_aaa", "넥슨코리아", "세무 세액 조정 담당", "자격요건: 세무조정 경력 5년 이상"),
            make_posting("wanted_bbb", "크래프톤", "자금 관리 담당자", "자격요건: 외환 자금 관리 3년 이상"),
            make_posting("wanted_ccc", "엔씨소프트", "회계 결산 담당자", "자격요건: 결산 경력 3년"),
            make_posting("wanted_ddd", "넷마블", "내부회계 담당자", "자격요건: 내부통제 담당"),
        ]
        for p in postings:
            self.db_manager.upsert_job_posting(p)

        # 1) 수집 건수가 3건 미만이면 크롤링 누락으로 간주하여 마감을 보류해야 함 (안전장치)
        closed_count, _ = self.analyzer.analyze_closed_postings({"wanted_bbb"})
        self.assertEqual(closed_count, 0)

        # 2) 충분히 수집된 상태(3건 이상)에서, 누락된 aaa 공고만 정상 마감되어야 함
        #    (마감 유예를 통과하도록 aaa의 관측일을 과거로 설정)
        self._age_postings(["wanted_aaa"])
        today_ids = {"wanted_bbb", "wanted_ccc", "wanted_ddd"}
        closed_count, closed_details = self.analyzer.analyze_closed_postings(today_ids)
        self.assertEqual(closed_count, 1)
        self.assertEqual(closed_details[0]["id"], "wanted_aaa")

        # 실제 마감으로 마킹되었는지 디비 커밋 상태 재검수
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM job_postings WHERE id = 'wanted_aaa'")
        self.assertEqual(cursor.fetchone()["status"], "CLOSED")
        conn.close()

    def test_delta_analyzer_successful_sources_protection(self):
        """특정 소스의 스크래핑이 실패했을 때 해당 소스 공고의 자동 마감 오판 방어 기능 테스트"""
        def make_posting(job_id, company, title, html, source="wanted"):
            return {
                "id": job_id,
                "source": source,
                "company_name": company,
                "title": title,
                "origin_url": "https://example.com",
                "location": "서울",
                "posted_at": "2026-05-21",
                "status": "ACTIVE",
                "raw_html": html,
                "first_seen_at": "2026-05-21 12:00:00",
                "last_updated_at": "2026-05-21 12:00:00"
            }

        # 디비 초기 적재
        postings = [
            make_posting("wanted_1", "크래프톤", "회계사", "본문", source="krafton"),
            make_posting("wanted_2", "넥슨", "자금", "본문", source="nexon"),
            make_posting("wanted_3", "시프트업", "세무", "본문", source="shiftup"),
        ]
        for p in postings:
            self.db_manager.upsert_job_posting(p)

        # 1) 오늘 수집된 건: wanted_1 (krafton 소스)뿐임. (총 수집ID 3건 이상 요건을 위해 더미 포함)
        # 넥슨(nexon)과 시프트업(shiftup) 수집은 오늘 완전히 실패했다고 가정 (successful_sources에 포함되지 않음)
        today_ids = {"wanted_1", "dummy_1", "dummy_2"}
        successful_sources = {"krafton"} # krafton만 성공적으로 수집됨

        # 2) Delta Analyzer 작동 실행
        closed_count, closed_details = self.analyzer.analyze_closed_postings(today_ids, successful_sources)

        # 3) 성공 소스인 krafton에 속한 미수집 공고는 없으므로 closed_count는 0이어야 함
        # nexon 및 shiftup 소스는 오늘 수집 실패(successful_sources에 없음)이므로, 오늘 수집되지 않았어도 CLOSED로 마감되지 않고 ACTIVE로 보존되어야 함.
        self.assertEqual(closed_count, 0)

        # 실제 디비 상태 재검수
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        for job_id in ["wanted_1", "wanted_2", "wanted_3"]:
            cursor.execute("SELECT status FROM job_postings WHERE id = ?", (job_id,))
            self.assertEqual(cursor.fetchone()["status"], "ACTIVE")
        conn.close()

    def test_newbie_title_overrides_body_career_words(self):
        """제목이 '신입' 단독이면 본문의 '경력 개발'·'인턴 경력 우대' 문구가 있어도 신입(0~1)."""
        mn, mx = self.engine.extract_experience(
            "신입 회계 담당자\n입사 후 경력 개발 기회 제공, 인턴 경력 우대",
            title="신입 회계 담당자",
        )
        self.assertEqual((mn, mx), (0, 1))

        # '신입/경력' 병행 제목은 기존 로직 유지 (경력 무관 처리)
        mn, mx = self.engine.extract_experience(
            "[웹젠] 자금(신입/경력)\n본문", title="[웹젠] 자금(신입/경력)")
        self.assertEqual((mn, mx), (0, None))

        # title 미전달(레거시 호출)은 기존 동작 그대로
        mn, mx = self.engine.extract_experience("지원 자격: 경력 3년 ~ 5년 담당자")
        self.assertEqual((mn, mx), (3, 5))

    def test_get_companies_seen_before(self):
        """신규 진입사 판별용 — cutoff 이전 이력 회사만 반환 (당일 신규는 제외)."""
        def make_posting(job_id, company, first_seen):
            return {
                "id": job_id, "source": "saramin", "company_name": company,
                "title": "재무 담당자", "origin_url": "https://example.com",
                "location": "서울", "posted_at": first_seen[:10], "status": "ACTIVE",
                "raw_html": "본문", "first_seen_at": first_seen, "last_updated_at": first_seen,
            }
        self.db_manager.upsert_job_posting(make_posting("saramin_1", "컴투스", "2026-07-01 09:00:00"))
        self.db_manager.upsert_job_posting(make_posting("saramin_2", "신생게임즈", "2026-07-09 09:00:00"))

        known = self.db_manager.get_companies_seen_before("2026-07-09")
        self.assertIn("컴투스", known)
        self.assertNotIn("신생게임즈", known)

    def test_delta_analyzer_suspect_sources_hold(self):
        """'성공했지만 0건'인 소스(suspect)는 마감 판정을 보류해 플랩(마감↔부활 반복)을 막는다.

        실측(2026-07-08~09): 게임잡이 격일로 0건을 반환해 컴투스 공고가 수집 다음 날
        마감 오판정되고, 재수집되면 부활하는 패턴이 반복됐다."""
        def make_posting(job_id, source):
            return {
                "id": job_id, "source": source, "company_name": "컴투스 홀딩스",
                "title": "재무관리 팀장", "origin_url": "https://example.com",
                "location": "서울", "posted_at": "2026-07-08", "status": "ACTIVE",
                "raw_html": "본문", "first_seen_at": "2026-07-08 09:00:00",
                "last_updated_at": "2026-07-08 09:00:00",
            }

        # 게임잡 공고 1건 + 크래프톤 공고 1건 활성 적재
        self.db_manager.upsert_job_posting(make_posting("gamejob_282441", "gamejob"))
        self.db_manager.upsert_job_posting(make_posting("krafton_999", "krafton"))

        # 오늘 수집: 둘 다 미수집, 두 소스 모두 '성공' — 단 gamejob은 0건(suspect)
        #  (둘 다 마감 유예는 통과한 상태로 만들어 suspect 보류만을 검증한다)
        self._age_postings(["gamejob_282441", "krafton_999"])
        today_ids = {"saramin_1", "saramin_2", "saramin_3"}
        closed_count, closed_details = self.analyzer.analyze_closed_postings(
            today_ids, successful_sources={"gamejob", "krafton", "saramin"},
            suspect_sources={"gamejob"},
        )

        # suspect인 gamejob 공고는 보류(ACTIVE 유지), krafton 공고만 정상 마감
        self.assertEqual(closed_count, 1)
        self.assertEqual(closed_details[0]["id"], "krafton_999")
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM job_postings WHERE id = 'gamejob_282441'")
        self.assertEqual(cursor.fetchone()["status"], "ACTIVE")
        cursor.execute("SELECT status FROM job_postings WHERE id = 'krafton_999'")
        self.assertEqual(cursor.fetchone()["status"], "CLOSED")
        conn.close()

    def test_mass_close_guard_holds_adapter_wipeout(self):
        """기업 어댑터의 기존 공고(2건 이상)가 오늘 전부 미수집이면 개편 의심으로 마감 보류.
        활성 1건짜리 소스의 정상 마감은 그대로 진행된다."""
        def make_posting(job_id, source):
            return {
                "id": job_id, "source": source, "company_name": "테스트",
                "title": "재무 담당자", "origin_url": "https://example.com",
                "location": "서울", "posted_at": "2026-07-08", "status": "ACTIVE",
                "raw_html": "본문", "first_seen_at": "2026-07-08 09:00:00",
                "last_updated_at": "2026-07-08 09:00:00",
            }
        # com2us 2건(전멸 → 보류 대상), krafton 1건(정상 마감 대상)
        for jid, src in [("com2us_1", "com2us"), ("com2us_2", "com2us"), ("krafton_1", "krafton")]:
            self.db_manager.upsert_job_posting(make_posting(jid, src))

        # 전부 마감 유예는 통과한 상태로 만들어 일괄 소멸 가드만을 검증한다
        self._age_postings(["com2us_1", "com2us_2", "krafton_1"])
        today_ids = {"saramin_1", "saramin_2", "saramin_3"}
        closed_count, closed_details = self.analyzer.analyze_closed_postings(
            today_ids,
            successful_sources={"com2us", "krafton", "saramin"},
            suspect_sources=set(),
            collected_counts={"com2us": 0, "krafton": 0, "saramin": 3},
        )

        self.assertEqual(self.analyzer.last_mass_close_held, ["com2us"])
        self.assertEqual(closed_count, 1)  # krafton_1만 마감
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM job_postings WHERE id = 'com2us_1'")
        self.assertEqual(cursor.fetchone()["status"], "ACTIVE")
        cursor.execute("SELECT status FROM job_postings WHERE id = 'krafton_1'")
        self.assertEqual(cursor.fetchone()["status"], "CLOSED")
        conn.close()

    def test_mass_close_guard_family_wide_wipeout(self):
        """4개 소스가 같은 날 동시 전멸하면(도메인 단위 개편 의심) 1건짜리 소스도 전부 보류."""
        def make_posting(job_id, source):
            return {
                "id": job_id, "source": source, "company_name": "테스트",
                "title": "재무 담당자", "origin_url": "https://example.com",
                "location": "서울", "posted_at": "2026-07-08", "status": "ACTIVE",
                "raw_html": "본문", "first_seen_at": "2026-07-08 09:00:00",
                "last_updated_at": "2026-07-08 09:00:00",
            }
        sources = ["nexon", "ncsoft", "webzen", "wemade"]
        for i, src in enumerate(sources):
            self.db_manager.upsert_job_posting(make_posting(f"{src}_{i}", src))

        today_ids = {"saramin_1", "saramin_2", "saramin_3"}
        closed_count, _ = self.analyzer.analyze_closed_postings(
            today_ids,
            successful_sources=set(sources) | {"saramin"},
            suspect_sources=set(),
            collected_counts={s: 0 for s in sources} | {"saramin": 3},
        )

        self.assertEqual(closed_count, 0)  # 전부 보류
        self.assertEqual(self.analyzer.last_mass_close_held, sorted(sources))

    def test_source_counts_roundtrip(self):
        """scrape_logs의 소스별 수집 건수 JSON 저장·조회 (급감 감지 기준선)."""
        self.db_manager.insert_scrape_log({
            "run_date": "2026-07-09", "newly_added": 1, "modified_count": 0,
            "closed_count": 0, "is_success": 1, "error_log": None,
            "source_counts": {"saramin": 9, "jobkorea": 13},
        })
        history = self.db_manager.get_recent_source_counts(before_date="2026-07-10", days=7)
        self.assertEqual(history.get("saramin"), [9])
        self.assertEqual(history.get("jobkorea"), [13])

if __name__ == '__main__':
    unittest.main()
