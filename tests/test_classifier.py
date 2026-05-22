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

        # 2) 이상 조건 추출
        min_exp, max_exp = self.engine.extract_experience("자격 요건: 관련 직무 5년 이상 소유자")
        self.assertEqual(min_exp, 5)
        self.assertIsNone(max_exp)

        # 3) 신입 지원 가능
        min_exp, max_exp = self.engine.extract_experience("신입 채용 공고 (초보자 지원 가능)")
        self.assertEqual(min_exp, 0)
        self.assertEqual(max_exp, 1)

    def test_delta_closed_logic(self):
        """델타 변동 분석기의 마감 처리 로직 검증"""
        posting_1 = {
            "id": "wanted_aaa",
            "source": "wanted",
            "company_name": "넥슨코리아",
            "title": "세무 세액 조정 담당",
            "origin_url": "https://wanted.co.kr/wd/aaa",
            "location": "판교",
            "posted_at": "2026-05-21",
            "status": "ACTIVE",
            "raw_html": "자격요건: 세무조정 경력 5년 이상",
            "first_seen_at": "2026-05-21 12:00:00",
            "last_updated_at": "2026-05-21 12:00:00"
        }
        posting_2 = {
            "id": "wanted_bbb",
            "source": "wanted",
            "company_name": "크래프톤",
            "title": "자금 관리 담당자",
            "origin_url": "https://wanted.co.kr/wd/bbb",
            "location": "서초",
            "posted_at": "2026-05-21",
            "status": "ACTIVE",
            "raw_html": "자격요건: 외환 자금 관리 3년 이상",
            "first_seen_at": "2026-05-21 12:00:00",
            "last_updated_at": "2026-05-21 12:00:00"
        }

        # 마스터 테이블에 2개 공고 밀어넣기
        self.db_manager.upsert_job_posting(posting_1)
        self.db_manager.upsert_job_posting(posting_2)

        # 오늘 수집된 ID 셋에는 bbb만 존재 (즉, aaa 공고는 마감 종료된 경우)
        today_ids = {"wanted_bbb"}
        closed_count, closed_details = self.analyzer.analyze_closed_postings(today_ids)

        self.assertEqual(closed_count, 1)
        self.assertEqual(closed_details[0]["id"], "wanted_aaa")

        # 실제 마감으로 마킹되었는지 디비 커밋 상태 재검수
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM job_postings WHERE id = 'wanted_aaa'")
        self.assertEqual(cursor.fetchone()["status"], "CLOSED")
        conn.close()

if __name__ == '__main__':
    unittest.main()
