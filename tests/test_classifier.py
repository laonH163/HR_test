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

    def test_work_type_classification(self):
        """근무 형태 정밀 3단 분류 검증"""
        # 1) 풀재택 케이스
        self.assertEqual(self.engine.classify_work_type("우리는 전면재택 제도를 시행합니다."), "풀재택")
        self.assertEqual(self.engine.classify_work_type("복지: 100% 리모트 재택근무 가능"), "풀재택")

        # 2) 하이브리드 케이스
        self.assertEqual(self.engine.classify_work_type("주 2회 하이브리드 재택근무 제공"), "하이브리드 (주2~3회 재택)")
        self.assertEqual(self.engine.classify_work_type("본 공고는 일주일에 3일 재택근무를 섞어서 일합니다."), "하이브리드 (주2~3회 재택)")

        # 3) 전면출근 케이스 (기본값)
        self.assertEqual(self.engine.classify_work_type("판교 사무실로 매일 출근합니다."), "전면출근")

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

if __name__ == '__main__':
    unittest.main()
