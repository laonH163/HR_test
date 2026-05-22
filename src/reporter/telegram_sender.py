import os
import requests
import sys
from dotenv import load_dotenv

# 로컬 디버깅 시 .env 파일 로드 지원
load_dotenv()

class TelegramSender:
    def __init__(self):
        # 환경변수로부터 토큰 및 챗ID 안전 격리 (보안 규정 철저 준수)
        raw_token = os.getenv("TELEGRAM_BOT_TOKEN")
        raw_chat_id = os.getenv("TELEGRAM_CHAT_ID")

        # 앞뒤 불필요한 줄바꿈(\n), 따옴표(" or '), 공백 자동 제거 (보안 우회 대응)
        self.bot_token = raw_token.strip().strip('"').strip("'") if raw_token else None
        self.chat_id = raw_chat_id.strip().strip('"').strip("'") if raw_chat_id else None
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage" if self.bot_token else None

    def is_enabled(self):
        """환경변수가 주입되어 전송 준비가 끝났는지 체크"""
        return bool(self.bot_token and self.chat_id)

    def send_formatted_message(self, text):
        """텔레그램 메시지 원시 전송 (MarkdownV2 지원)"""
        if not self.is_enabled():
            print("    [WARN] Telegram Credentials not found. Skipping alert.", file=sys.stderr)
            return False

        # HTML 스타일 마크다운 호환 전송 지원
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        }

        try:
            response = requests.post(self.api_url, json=payload, timeout=15)
            if response.status_code == 200:
                print("    -> 텔레그램 프라이빗 브리핑 전송 완료!")
                return True
            else:
                print(f"    [ERR] 텔레그램 API 전송 실패: {response.status_code} | {response.text}", file=sys.stderr)
                return False
        except Exception as e:
            print(f"    [ERR] 텔레그램 통신 장애: {e}", file=sys.stderr)
            return False

    def build_daily_briefing_message(self, newly_added, modified_count, closed_count, active_postings):
        """당일 수집된 통계 데이터 및 공고 리스트 기반 가독성 높은 텔레그램 카드 메세지 빌딩"""
        date_str = datetime_str = os.getenv("GITHUB_RUN_ID", "로컬") # 가동 컨텍스트
        run_date = os.getenv('RUN_DATE_STR', datetime_str)

        msg_lines = [
            f"<b>📢 [게임사 재무공고 브리핑]</b>",
            f"일자: {run_date}",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"🔥 오늘 감지된 핵심 델타 통계:",
            f"• 신규 등록 공고: <b>{newly_added} 건</b>",
            f"• 주요 업데이트 공고: <b>{modified_count} 건</b>",
            f"• 채용 종료(마감) 공고: <b>{closed_count} 건</b>",
            f"━━━━━━━━━━━━━━━━━━━━\n"
        ]

        # 오늘 추가된 신규 공고 아이디 구하기
        new_jobs = []
        if newly_added > 0:
            # posted_at 날짜가 오늘 날짜와 일치하는 공고 추출
            new_jobs = [j for j in active_postings if j.get("posted_at") == run_date]
            # 만약 날짜 매칭으로 신규 공고가 안 잡힐 때를 대비한 방어적 폴백
            if not new_jobs:
                new_jobs = active_postings[:newly_added]

        # 1. 신규 등록 공고가 있을 때 상단 노출
        if new_jobs:
            msg_lines.append("<b>✨ 오늘 새로 등록된 신규 채용 정보:</b>")
            for job in new_jobs:
                title_clean = job["title"].replace("<", "&lt;").replace(">", "&gt;")
                company_clean = job["company_name"].replace("<", "&lt;").replace(">", "&gt;")
                msg_lines.append(f"• <b>[{company_clean}]</b> {title_clean}")
                msg_lines.append(f"  👉 <a href='{job['origin_url']}'>지원 공고 바로가기</a>")
            msg_lines.append("")

        # 2. 오늘 신규 등록된 공고를 제외한 기존 채용 진행 중인 공고 나열
        new_job_ids = {j["id"] for j in new_jobs}
        existing_active_jobs = [j for j in active_postings if j["id"] not in new_job_ids]

        if existing_active_jobs:
            msg_lines.append("<b>💼 기존에 수집된 현재 채용 진행 중인 공고 목록:</b>")
            for job in existing_active_jobs:
                title_clean = job["title"].replace("<", "&lt;").replace(">", "&gt;")
                company_clean = job["company_name"].replace("<", "&lt;").replace(">", "&gt;")
                msg_lines.append(f"• <b>[{company_clean}]</b> {title_clean}")
                msg_lines.append(f"  👉 <a href='{job['origin_url']}'>지원 공고 바로가기</a>")
            msg_lines.append("")

        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append("💻 상세 필터 및 전체 누적 공고 조회가 필요하신 경우, 아래 링크를 통해 실시간으로 확인하실 수 있습니다.")
        msg_lines.append("👉 <a href='https://github.com/laonH163/HR_test/blob/main/index.html'>[추천] GitHub 모바일 앱/웹으로 대시보드 바로보기</a>")

        return "\n".join(msg_lines)
