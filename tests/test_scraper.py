import unittest
import os
import sqlite3
from src.database.db_manager import DBManager
from src.scraper.wanted_scraper import WantedScraper
from src.scraper.saramin_scraper import SaraminScraper
from src.scraper.jobkorea_scraper import JobKoreaScraper
from src.scraper.company_scrapers import CompanyScrapers

class TestScraperAndDatabase(unittest.TestCase):
    def setUp(self):
        # 테스트용 임시 SQLite 데이터베이스 생성
        self.db_path = "data/test_scrap_master.db"
        self.db_manager = DBManager(db_path=self.db_path)

    def tearDown(self):
        # 가동 테스트 후 데이터베이스 파일 정리
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except PermissionError:
                pass

    def test_database_initialization(self):
        """데이터베이스 및 테이블 정상 생성 여부 확인"""
        self.assertTrue(os.path.exists(self.db_path))

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 테이블 스키마 확인
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='job_postings';")
        self.assertIsNotNone(cursor.fetchone())

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='job_categories';")
        self.assertIsNotNone(cursor.fetchone())

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='scrape_logs';")
        self.assertIsNotNone(cursor.fetchone())

        conn.close()

    def test_db_manager_upsert(self):
        """DB에 공고 Upsert 시 신규 및 업데이트 플래그 연산 검증"""
        posting = {
            "id": "test_123",
            "source": "wanted",
            "company_name": "테스트게임즈",
            "title": "재무회계 담당자 채용",
            "origin_url": "https://wanted.co.kr/wd/123",
            "location": "판교",
            "posted_at": "2026-05-21",
            "status": "ACTIVE",
            "raw_html": "자격요건: 회계 결산 가능자",
            "first_seen_at": "2026-05-21 12:00:00",
            "last_updated_at": "2026-05-21 12:00:00"
        }

        # 1. 최초 저장 테스트
        is_modified, is_new = self.db_manager.upsert_job_posting(posting)
        self.assertTrue(is_new)
        self.assertFalse(is_modified)

        # 2. 내용 수정 시 변동 상태 업데이트 테스트
        posting_modified = posting.copy()
        posting_modified["raw_html"] = "자격요건: 회계 결산 가능자 및 우대사항 세무조정"
        is_modified, is_new = self.db_manager.upsert_job_posting(posting_modified)
        self.assertFalse(is_new)
        self.assertTrue(is_modified)

    def test_modified_ignores_noise(self):
        """공백·날짜 같은 노이즈만 바뀐 경우 MODIFIED로 잡지 않되, 실제 본문 변경은 포착하는지 검증"""
        base = {
            "id": "noise_1",
            "source": "wanted",
            "company_name": "테스트게임즈",
            "title": "재무회계 담당자",
            "origin_url": "https://wanted.co.kr/wd/999",
            "location": "판교",
            "posted_at": "2026-05-21",
            "status": "ACTIVE",
            "raw_html": "자격요건:\n회계 결산 가능자\n공고 마감일 2026-05-21",
            "first_seen_at": "2026-05-21 12:00:00",
            "last_updated_at": "2026-05-21 12:00:00"
        }
        _, is_new = self.db_manager.upsert_job_posting(base)
        self.assertTrue(is_new)

        # 1) 공백 변형 + 날짜만 바뀐 경우 → 의미 없는 노이즈이므로 MODIFIED 아님
        noise = base.copy()
        noise["raw_html"] = "자격요건:   회계 결산 가능자    공고 마감일 2026-05-28"
        is_modified, is_new = self.db_manager.upsert_job_posting(noise)
        self.assertFalse(is_new)
        self.assertFalse(is_modified)

        # 2) 실제 본문(자격요건) 변경 → MODIFIED로 잡혀야 함 (연봉·요건 변경은 절대 놓치면 안 됨)
        real = base.copy()
        real["raw_html"] = "자격요건:\n회계 결산 가능자 및 SAP 사용 필수\n공고 마감일 2026-05-21"
        is_modified, is_new = self.db_manager.upsert_job_posting(real)
        self.assertFalse(is_new)
        self.assertTrue(is_modified)

    def test_wanted_filtering(self):
        """원티드 스크래퍼의 게임 회사 및 직무 필터링 로직 검증"""
        scraper = WantedScraper()

        # 게임 회사 매칭 케이스
        self.assertTrue(scraper.is_game_company("넥슨코리아", "재무팀 자금 담당자 채용"))
        self.assertTrue(scraper.is_game_company("데브시스터즈", "회계 공고"))
        self.assertTrue(scraper.is_game_company("일반서비스", "게임 개발 스튜디오에서 회계를 구합니다"))

        # 게임사 도메인이 전혀 없는 케이스 필터링
        self.assertFalse(scraper.is_game_company("대형제조업", "생산 관리 세무 조정 담당자 채용"))

        # 직무 필터링 검증
        self.assertTrue(scraper.is_finance_job("재무 회계 담당자"))
        self.assertTrue(scraper.is_finance_job("[Finance Div.] Tax Manager (3년 이상)"))
        self.assertTrue(scraper.is_finance_job("회계감사 및 내부회계관리제도 구축"))
        self.assertTrue(scraper.is_finance_job("IR Manager"))

        self.assertFalse(scraper.is_finance_job("Server Programmer (we are hiring now)"))
        self.assertFalse(scraper.is_finance_job("고객감사 이벤트 기획자"))
        self.assertFalse(scraper.is_finance_job("마케팅 및 브랜드 홍보 담당자"))

    def test_saramin_and_jobkorea_finance_filtering(self):
        """사람인 및 잡코리아 스크래퍼의 직무 필터링 로직 검증"""
        s_scraper = SaraminScraper()
        jk_scraper = JobKoreaScraper()

        for scraper in [s_scraper, jk_scraper]:
            self.assertTrue(scraper.is_finance_job("자금 운용 및 세무 조정 담당자"))
            self.assertTrue(scraper.is_finance_job("Accounting & Finance Leader"))
            self.assertTrue(scraper.is_finance_job("내부 감사 및 통제 전문가"))

            self.assertFalse(scraper.is_finance_job("UI/UX Designer"))
            self.assertFalse(scraper.is_finance_job("감사패 및 판촉물 제작 디자이너"))
            self.assertFalse(scraper.is_finance_job("QA 담당 및 마케팅 매니저"))

if __name__ == '__main__':
    unittest.main()
