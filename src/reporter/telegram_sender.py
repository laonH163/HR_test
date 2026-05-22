import os
import requests
import sys
from dotenv import load_dotenv

# 로컬 디버깅 시 .env 파일 로드 지원
load_dotenv()

class TelegramSender:
    def __init__(self):
        # 환경변수로부터 토큰 및 챗ID 안전 격리 (보안 규정 철저 준수)
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
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

        msg_lines = [
            f"<b>📢 [게임사 재무공고 브리핑]</b>",
            f"일자: {os.getenv('RUN_DATE_STR', datetime_str)}",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"🔥 오늘 감지된 핵심 델타 통계:",
            f"• 신규 등록 공고: <b>{newly_added} 건</b>",
            f"• 주요 업데이트 공고: <b>{modified_count} 건</b>",
            f"• 채용 종료(마감) 공고: <b>{closed_count} 건</b>",
            f"━━━━━━━━━━━━━━━━━━━━\n"
        ]

        if newly_added > 0:
            msg_lines.append("<b>✨ 신규 채용 정보 바로가기:</b>")
            # 오늘 신규로 추가된 ACTIVE 공고 정보 슬라이싱 상위 3건 가시적 나열
            # active_postings는 dict 리스트
            new_jobs = [j for j in active_postings if j.get("posted_at") == os.getenv('RUN_DATE_STR', datetime_str) or newly_added > 0]
            count = 0
            for job in new_jobs:
                if count >= 3:
                    break
                # 특수문자 HTML 이스케이프 방어
                title_clean = job["title"].replace("<", "&lt;").replace(">", "&gt;")
                company_clean = job["company_name"].replace("<", "&lt;").replace(">", "&gt;")
                msg_lines.append(f"• <b>[{company_clean}]</b> {title_clean}")
                msg_lines.append(f"  👉 <a href='{job['origin_url']}'>지원 공고 보러가기</a>")
                count += 1
            msg_lines.append("")

        msg_lines.append("💻 상세 조건 필터링 및 전체 누적 공고 조회가 필요하신 경우, 대시보드 리포트(index.html)를 로컬 더블 클릭하여 편리하게 검색해 보실 수 있습니다.")

        return "\n".join(msg_lines)
