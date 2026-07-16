# -*- coding: utf-8 -*-
"""2026-07-16 고도화 3종 검증
1) 재공고(🔁) 판별(compute_repost_flags) — 좀비 CLOSED 오탐 방지 규칙 포함
2) 마감일 변경 상세(upsert last_change_details) + 텔레그램 '마감일 변경' 섹션
3) 잡코리아 GI iframe 본문 파서 + 보강 패스 + 본문 축소 방지 가드
"""
import os
import tempfile
import unittest

from src.database.db_manager import DBManager
from src.reporter.telegram_sender import TelegramSender
from src.scraper.jobkorea_detail import enrich_gi_postings, html_to_text
from src.utils.dedup import compute_repost_flags
from src.utils.jdtext import has_jd_markers


def make_posting(job_id, company="컴투스", title="재무회계 담당자", deadline=None,
                 raw_html="자격요건: 회계 결산 가능자", first_seen="2026-07-16 08:00:00",
                 origin_url="https://www.jobkorea.co.kr/Recruit/GI_Read/111"):
    return {
        "id": job_id, "source": "jobkorea", "company_name": company, "title": title,
        "origin_url": origin_url, "location": "판교", "posted_at": "2026-07-16",
        "status": "ACTIVE", "raw_html": raw_html,
        "first_seen_at": first_seen, "last_updated_at": first_seen,
        "deadline": deadline,
    }


class TestRepostFlags(unittest.TestCase):
    def test_repost_detected_when_reappears_after_close(self):
        """과거 마감 후 재등장한 공고는 재공고로 판별"""
        closed = [{"company_name": "컴투스", "title": "재무회계 담당자", "closed_at": "2026-06-15 08:00:00"}]
        active = [{"company_name": "컴투스", "title": "재무회계 담당자", "first_seen_at": "2026-07-16 08:00:00"}]
        flags = compute_repost_flags(active, closed)
        self.assertEqual(len(flags), 1)
        self.assertEqual(list(flags.values())[0], "2026-06-15")

    def test_zombie_closed_row_not_flagged(self):
        """다른 소스 행이 계속 활성이던 키(그룹 최초 관측이 마감 이전)는 오탐하지 않음"""
        closed = [{"company_name": "컴투스", "title": "재무회계 담당자", "closed_at": "2026-06-15 08:00:00"}]
        active = [
            {"company_name": "컴투스", "title": "재무회계 담당자", "first_seen_at": "2026-05-25 08:00:00"},
            {"company_name": "컴투스", "title": "재무회계 담당자", "first_seen_at": "2026-07-16 08:00:00"},
        ]
        self.assertEqual(compute_repost_flags(active, closed), {})

    def test_no_history_no_flags(self):
        active = [{"company_name": "컴투스", "title": "재무회계 담당자", "first_seen_at": "2026-07-16 08:00:00"}]
        self.assertEqual(compute_repost_flags(active, []), {})

    def test_prefix_promoted_key_matches(self):
        """'[컴투스홀딩스]' 프리픽스 승격 키도 재공고 매칭이 일치해야 함"""
        closed = [{"company_name": "컴투스", "title": "[컴투스홀딩스] 재무관리 팀장", "closed_at": "2026-06-01 08:00:00"}]
        active = [{"company_name": "컴투스 홀딩스", "title": "재무관리 팀장", "first_seen_at": "2026-07-16 08:00:00"}]
        self.assertEqual(len(compute_repost_flags(active, closed)), 1)

    def test_min_gap_filters_flap(self):
        """마감 하루 뒤 재등장(수집 플랩·gno 갱신)은 재공고로 표시하지 않음"""
        closed = [{"company_name": "컴투스", "title": "재무회계 담당자", "closed_at": "2026-07-15 08:00:00"}]
        active = [{"company_name": "컴투스", "title": "재무회계 담당자", "first_seen_at": "2026-07-16 08:00:00"}]
        self.assertEqual(compute_repost_flags(active, closed), {})

    def test_briefing_shows_repost_badge(self):
        sender = TelegramSender()
        job = make_posting("jobkorea_1")
        # 신규 공고 posted_at 판정이 오늘 날짜 기반이므로 RUN_DATE_STR로 고정
        os.environ["RUN_DATE_STR"] = "2026-07-16"
        try:
            text = sender.build_daily_briefing_message(
                1, 0, 0, [job],
                closed_history=[{"company_name": "컴투스", "title": "재무회계 담당자",
                                 "closed_at": "2026-06-15 08:00:00"}],
            )
        finally:
            del os.environ["RUN_DATE_STR"]
        self.assertIn("🔁 재공고", text)
        self.assertIn("6/15", text)


class TestDeadlineChangeDetail(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = DBManager(db_path=os.path.join(self.tmp, "t.db"))

    def test_deadline_change_recorded(self):
        """기존 마감일이 실제로 바뀌면 last_change_details에 전후가 기록됨"""
        self.db.upsert_job_posting(make_posting("a1", deadline="2026-07-20"))
        is_modified, _ = self.db.upsert_job_posting(make_posting("a1", deadline="2026-07-31"))
        self.assertTrue(is_modified)
        self.assertEqual(self.db.last_change_details.get("deadline_from"), "2026-07-20")
        self.assertEqual(self.db.last_change_details.get("deadline_to"), "2026-07-31")

    def test_first_acquisition_not_recorded_as_change(self):
        """None → 값 최초 확보는 변경 상세 기록 대상이 아님 (MODIFIED로는 잡힘)"""
        self.db.upsert_job_posting(make_posting("a2", deadline=None))
        is_modified, _ = self.db.upsert_job_posting(make_posting("a2", deadline="2026-07-31"))
        self.assertTrue(is_modified)
        self.assertEqual(self.db.last_change_details, {})

    def test_briefing_deadline_change_section(self):
        sender = TelegramSender()
        text = sender.build_daily_briefing_message(
            0, 1, 0, [],
            deadline_changes=[{"company_name": "넥슨", "title": "재무회계 담당자",
                               "origin_url": "https://x", "old": "2026-07-20", "new": "2026-07-31"}],
        )
        self.assertIn("마감일 변경 감지", text)
        self.assertIn("7/20 → 7/31", text)
        self.assertIn("연장", text)

    def test_briefing_deadline_shortened_warns(self):
        sender = TelegramSender()
        text = sender.build_daily_briefing_message(
            0, 1, 0, [],
            deadline_changes=[{"company_name": "넥슨", "title": "재무회계 담당자",
                               "origin_url": "https://x", "old": "2026-07-31", "new": "2026-07-20"}],
        )
        self.assertIn("단축", text)


class TestShrinkGuardAndEnrich(unittest.TestCase):
    RICH_BODY = "재무회계 담당자\n담당업무\n- 월 결산\n자격요건\n- 회계 지식 5년 이상 보유하신 분"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = DBManager(db_path=os.path.join(self.tmp, "t.db"))

    def test_shrink_guard_preserves_rich_body(self):
        """상세요강 확보 후 제목만 재수집돼도 본문이 보존되고 MODIFIED 오탐 없음"""
        self.db.upsert_job_posting(make_posting("g1", raw_html=self.RICH_BODY))
        degraded = make_posting("g1", raw_html="재무회계 담당자")
        is_modified, is_new = self.db.upsert_job_posting(degraded)
        self.assertFalse(is_new)
        self.assertFalse(is_modified)
        stored = self.db.get_raw_html_map(["g1"])["g1"]
        self.assertIn("자격요건", stored)
        # 보존본이 posting dict에도 되돌아와야 분류기(job_categories)가 열화되지 않음
        self.assertIn("자격요건", degraded["raw_html"])

    def test_shrink_guard_big_collapse_without_markers(self):
        """마커 없는 대형 본문(사람인·크래프톤형)도 1/3 이하 붕괴 시 보존됨"""
        big_body = "재무회계 담당자\n" + ("게임 회사 결산 및 공시 업무를 수행합니다. " * 30)
        self.db.upsert_job_posting(make_posting("g2", raw_html=big_body))
        is_modified, _ = self.db.upsert_job_posting(make_posting("g2", raw_html="재무회계 담당자 스니펫"))
        self.assertFalse(is_modified)
        self.assertGreater(len(self.db.get_raw_html_map(["g2"])["g2"]), 400)

    def test_legit_rewrite_not_stuck(self):
        """분량이 유지되는 정당한 개정(마커 소실 포함)은 정상 반영 — 구본 영구 고착 방지"""
        old_body = "재무회계 담당자\n자격요건\n- " + ("회계 지식 " * 50)
        new_body = "재무회계 담당자\nResponsibilities\n- " + ("accounting experience " * 40)
        self.db.upsert_job_posting(make_posting("g3", raw_html=old_body))
        is_modified, _ = self.db.upsert_job_posting(make_posting("g3", raw_html=new_body))
        self.assertTrue(is_modified)
        self.assertIn("Responsibilities", self.db.get_raw_html_map(["g3"])["g3"])

    def test_title_change_survives_guard(self):
        """가드가 본문을 보존한 날에도 제목 개정은 MODIFIED로 잡히고 DB에 반영됨"""
        self.db.upsert_job_posting(make_posting("g4", raw_html=self.RICH_BODY))
        renamed = make_posting("g4", title="재무회계 담당자(경력 5년+)", raw_html="재무회계 담당자(경력 5년+)")
        is_modified, _ = self.db.upsert_job_posting(renamed)
        self.assertTrue(is_modified)
        conn = self.db.get_connection()
        row = conn.execute("SELECT title, raw_html FROM job_postings WHERE id='g4'").fetchone()
        conn.close()
        self.assertEqual(row["title"], "재무회계 담당자(경력 5년+)")
        self.assertIn("자격요건", row["raw_html"])  # 본문은 여전히 보존

    def test_html_to_text_preserves_lines(self):
        html = "<div>담당업무</div><p>- 월 결산</p><br>자격요건<li>- 회계 지식</li><script>bad()</script>"
        text = html_to_text(html)
        self.assertIn("담당업무", text)
        self.assertNotIn("bad()", text)
        self.assertGreaterEqual(len(text.split("\n")), 3)  # 줄 구조 보존(불릿 파싱용)

    def test_enrich_uses_stored_body_without_refetch(self):
        """DB에 본문이 있으면 재요청 없이 저장본을 실어 줌"""
        self.db.upsert_job_posting(make_posting("jobkorea_111", raw_html=self.RICH_BODY))
        posting = make_posting("jobkorea_111", raw_html="재무회계 담당자")
        calls = []
        enriched = enrich_gi_postings(
            [posting], self.db,
            fetcher=lambda gno, session=None: calls.append(gno) or "가짜본문",
            sleeper=lambda s: None,
        )
        self.assertEqual(enriched, 0)
        self.assertEqual(calls, [])
        self.assertIn("자격요건", posting["raw_html"])

    def test_enrich_fetches_new_posting(self):
        """미확보 공고는 iframe 본문을 받아 제목과 결합"""
        posting = make_posting("jobkorea_222", raw_html="재무회계 담당자",
                               origin_url="https://www.jobkorea.co.kr/Recruit/GI_Read/222")
        body = "담당업무\n- 자금 운용\n자격요건\n- 경력 7년"
        enriched = enrich_gi_postings(
            [posting], self.db,
            fetcher=lambda gno, session=None: body,
            sleeper=lambda s: None,
        )
        self.assertEqual(enriched, 1)
        self.assertTrue(posting["raw_html"].startswith("재무회계 담당자\n"))
        self.assertIn("자금 운용", posting["raw_html"])

    def test_enrich_cap_limits_requests(self):
        postings = [
            make_posting(f"jobkorea_{i}", raw_html="재무회계 담당자",
                         origin_url=f"https://www.jobkorea.co.kr/Recruit/GI_Read/{i}")
            for i in range(5)
        ]
        calls = []
        enrich_gi_postings(postings, self.db, cap=2,
                           fetcher=lambda gno, session=None: calls.append(gno) or None,
                           sleeper=lambda s: None)
        self.assertEqual(len(calls), 2)

    def test_non_gi_and_rich_postings_skipped(self):
        wanted = make_posting("wanted_1", origin_url="https://www.wanted.co.kr/wd/1",
                              raw_html="재무회계 담당자")
        rich = make_posting("jobkorea_333", raw_html=self.RICH_BODY)
        calls = []
        enrich_gi_postings([wanted, rich], self.db,
                           fetcher=lambda gno, session=None: calls.append(gno) or "본문",
                           sleeper=lambda s: None)
        self.assertEqual(calls, [])

    def test_jd_markers(self):
        self.assertTrue(has_jd_markers("자격요건: 회계"))
        self.assertTrue(has_jd_markers("자격 요건: 회계"))  # 띄어쓴 변형도 인정
        self.assertFalse(has_jd_markers("재무회계 담당자 채용"))
        self.assertFalse(has_jd_markers(None))
        # 잡코리아 SPA 껍데기 라벨(지원자격·모집요강)은 본문으로 오판하지 않음 (2026-07-16 실측)
        self.assertFalse(has_jd_markers("지원자격 경력 학력무관 모집요강 모집분야 ○명 고용형태"))


if __name__ == "__main__":
    unittest.main()
