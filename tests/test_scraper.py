import unittest
import os
import sqlite3
from src.database.db_manager import DBManager
from src.scraper.wanted_scraper import WantedScraper
from src.scraper.saramin_scraper import SaraminScraper
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

    def test_wanted_filtering(self):
        """원티드 스크래퍼의 게임 회사 필터링 로직 검증"""
        scraper = WantedScraper()

        # 게임 회사 매칭 케이스
        self.assertTrue(scraper.is_game_company("넥슨코리아", "재무팀 자금 담당자 채용"))
        self.assertTrue(scraper.is_game_company("데브시스터즈", "회계 공고"))
        self.assertTrue(scraper.is_game_company("일반서비스", "게임 개발 스튜디오에서 회계를 구합니다"))

        # 게임사 도메인이 전혀 없는 케이스 필터링
        self.assertFalse(scraper.is_game_company("대형제조업", "생산 관리 세무 조정 담당자 채용"))

if __name__ == '__main__':
    unittest.main()
