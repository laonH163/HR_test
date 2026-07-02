import os
import requests
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
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
        """텔레그램 메시지 원시 전송 (MarkdownV2 지원) 및 글자 수 제한 방지 Chunking 지원"""
        if not self.is_enabled():
            print("    [WARN] Telegram Credentials not found. Skipping alert.", file=sys.stderr)
            return False

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 글자 수 초과 방어 및 연속 Chunking 전송 처리 (4,096자 제한 철저 대응)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        max_length = 3500
        if len(text) <= max_length:
            return self._send_raw_payload(text)

        print(f"    [INFO] 메시지 글자 수({len(text)}자)가 제한을 초과하여 분할(Chunking) 전송을 시작합니다.")
        lines = text.split("\n")
        chunks = []
        current_chunk = []
        current_length = 0

        # 열린 HTML 태그들의 균형을 지키며 청킹하는 인라인 헬퍼
        # 텔레그램 파서가 깨지지 않도록 단순 볼드(<b>) 등의 최소 마크업 마감 처리 보조
        bold_open = False

        for line in lines:
            # 줄 바꿈 포함 길이 계산
            line_len = len(line) + 1
            if current_length + line_len > max_length and current_chunk:
                # 닫히지 않은 볼드 태그 보정
                chunk_text = "\n".join(current_chunk)
                if bold_open:
                    chunk_text += "</b>"
                chunks.append(chunk_text)

                # 다음 청크 준비
                current_chunk = []
                if bold_open:
                    current_chunk.append("<b>(이어서)</b>")
                    current_length = len("<b>(이어서)</b>\n")
                else:
                    current_length = 0

            current_chunk.append(line)
            current_length += line_len

            # 볼드 태그 열림/닫힘 카운팅 (간단한 HTML 정밀 대응)
            bold_open += line.count("<b>") - line.count("</b>")

        if current_chunk:
            chunks.append("\n".join(current_chunk))

        # 모든 청크 순차 전송
        success_all = True
        for idx, chunk in enumerate(chunks, 1):
            print(f"    -> 분할 메시지 전송 중 ({idx}/{len(chunks)} 청크)...")
            res = self._send_raw_payload(chunk)
            if not res:
                success_all = False
            import time
            time.sleep(0.5) # 연속 요청 시 텔레그램 스로틀링 방지용 최소 쿨타임

        return success_all

    def _send_raw_payload(self, text):
        """실제 텔레그램 HTTP POST 전송을 담당하는 서브 메서드"""
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        }

        try:
            response = requests.post(self.api_url, json=payload, timeout=15)
            if response.status_code == 200:
                print("    -> 텔레그램 프라이빗 브리핑 세그먼트 전송 완료!")
                return True
            else:
                print(f"    [ERR] 텔레그램 API 전송 실패: {response.status_code} | {response.text}", file=sys.stderr)
                return False
        except Exception as e:
            print(f"    [ERR] 텔레그램 통신 장애: {e}", file=sys.stderr)
            return False

    def build_daily_briefing_message(self, newly_added, modified_count, closed_count, active_postings, weekly_trend=None, failed_sources=None):
        """당일 수집된 통계 데이터 및 공고 리스트 기반 가독성 높은 텔레그램 카드 메세지 빌딩 (중복 디듀프리케이션 포함)"""
        KST = ZoneInfo("Asia/Seoul")
        run_date_env = os.getenv('RUN_DATE_STR', '')
        try:
            datetime.strptime(run_date_env, "%Y-%m-%d")
            run_date = run_date_env
        except Exception:
            run_date = datetime.now(KST).strftime("%Y-%m-%d")

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 중복 제거(Deduplication) 로직 가동 (Milestone 5)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        def deduplicate_postings(postings_list):
            deduped = []
            seen_keys = set()
            for job in postings_list:
                comp = job["company_name"].strip()
                tit = job["title"].strip()
                # 회사명, 공고명, 요구 연차가 거의 유사하면 동일 공고로 취급
                exp = job.get("min_experience", 0)
                # 정규화 키: 회사명 공백제거 + 제목 공백제거 + 최소경력
                norm_comp = "".join(comp.split()).lower()
                norm_tit = "".join(tit.split()).lower()

                # 법인 특수기호 등 노이즈 제거 정규화
                for token in ["(주)", "주식회사", "㈜", "（주）"]:
                    norm_comp = norm_comp.replace(token, "")

                key = (norm_comp, norm_tit, exp)

                if key in seen_keys:
                    # 이미 동일 공고가 수집되었으면 출처 정보만 누적 병합
                    for existing_job in deduped:
                        exist_comp = "".join(existing_job["company_name"].split()).lower()
                        for token in ["(주)", "주식회사", "㈜", "（주）"]:
                            exist_comp = exist_comp.replace(token, "")
                        exist_tit = "".join(existing_job["title"].split()).lower()
                        exist_exp = existing_job.get("min_experience", 0)

                        if (exist_comp, exist_tit, exist_exp) == key:
                            # 멀티 소스 출처 및 지원 링크 병합
                            if "sources" not in existing_job:
                                existing_job["sources"] = [{
                                    "source": existing_job.get("source", "wanted"),
                                    "url": existing_job.get("origin_url", "")
                                }]

                            # 신규 출처 중복체크 후 머지
                            job_src = job.get("source", "wanted")
                            if not any(s["source"] == job_src for s in existing_job["sources"]):
                                existing_job["sources"].append({
                                    "source": job_src,
                                    "url": job.get("origin_url", "")
                                })
                            break
                else:
                    seen_keys.add(key)
                    # 단일 출처 구조 백업
                    job_copy = job.copy()
                    job_copy["sources"] = [{
                        "source": job.get("source", "wanted"),
                        "url": job.get("origin_url", "")
                    }]
                    deduped.append(job_copy)
            return deduped

        # 전체 활성 공고 중복 제거 가동
        deduped_active = deduplicate_postings(active_postings)

        # 오늘 추가된 신규 공고 아이디 구하기 (posted_at 날짜가 오늘 날짜와 일치하는 공고 추출)
        new_jobs = [j for j in deduped_active if j.get("posted_at") == run_date]
        deduped_new_count = len(new_jobs)

        # 주요 업데이트 공고도 중복 제거 후 카운트 정밀 정비
        deduped_modified_jobs = [
            j for j in deduped_active
            if j.get("last_updated_at", "").startswith(run_date)
            and not j.get("first_seen_at", "").startswith(run_date)
        ]
        deduped_modified_count = len(deduped_modified_jobs)

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 컴팩트(Compact) 가변형 템플릿 스위칭 기법 구현 (공고 대량 등록 대응)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        is_compact_mode = len(deduped_active) > 15  # 현재 활성 공고가 15개를 넘으면 Compact 뷰로 대전환해 가독성 극대화

        msg_lines = [
            f"<b>📢 [게임사 재무공고 브리핑]</b>",
            f"일자: {run_date}",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"🔥 오늘 감지된 핵심 델타 통계:",
            f"• 신규 등록 공고: <b>{deduped_new_count} 건</b>",
            f"• 주요 업데이트 공고: <b>{deduped_modified_count} 건</b>",
            f"• 채용 종료(마감) 공고: <b>{closed_count} 건</b>",
        ]

        # 수집 실패 소스 경고 — 무음 실패 방지. 실패 소스의 기존 공고는 마감 처리 없이 보존된다.
        if failed_sources:
            fs = ", ".join(sorted({s.upper() for s in failed_sources}))
            msg_lines.append(f"⚠️ 수집 실패 소스: <b>{fs}</b> (기존 공고는 보존됨)")

        # 최근 7일 추세(시계열) 한 줄 — 전달된 경우에만 노출(테스트 시그니처 호환을 위해 선택적)
        if weekly_trend and weekly_trend.get("days"):
            msg_lines.append(
                f"📈 최근 {weekly_trend['days']}일 누적: 신규 <b>{weekly_trend.get('total_new', 0)}건</b> · 마감 <b>{weekly_trend.get('total_closed', 0)}건</b>"
            )

        msg_lines.append("━━━━━━━━━━━━━━━━━━━━\n")

        # 0. 마감 임박(3일 이내) 공고 — 지원 기회를 놓치지 않도록 최상단 노출
        #    deadline은 잡코리아 D-N 배지를 절대일로 환산해 저장한 값(없으면 상시채용/미상)
        try:
            run_dt = datetime.strptime(run_date, "%Y-%m-%d").date()
        except Exception:
            run_dt = None
        urgent_jobs = []
        if run_dt:
            for job in deduped_active:
                d = job.get("deadline")
                if not d:
                    continue
                try:
                    remain = (datetime.strptime(d, "%Y-%m-%d").date() - run_dt).days
                except Exception:
                    continue
                if 0 <= remain <= 3:
                    urgent_jobs.append((remain, job))
            urgent_jobs.sort(key=lambda x: x[0])

        if urgent_jobs:
            msg_lines.append("<b>⏰ 마감 임박 공고 (3일 이내):</b>")
            for remain, job in urgent_jobs:
                dd_label = "오늘 마감!" if remain == 0 else f"D-{remain}"
                title_clean = job["title"].replace("<", "&lt;").replace(">", "&gt;")
                company_clean = job["company_name"].replace("<", "&lt;").replace(">", "&gt;")
                first_url = job["sources"][0]["url"] if job.get("sources") else job.get("origin_url", "")
                msg_lines.append(f"• <b>[{dd_label}]</b> [{company_clean}] <a href='{first_url}'>{title_clean}</a>")
            msg_lines.append("")

        # 1. 신규 등록 공고가 있을 때 상단 노출
        if new_jobs:
            msg_lines.append("<b>✨ 오늘 새로 등록된 신규 채용 정보:</b>")
            for job in new_jobs:
                title_clean = job["title"].replace("<", "&lt;").replace(">", "&gt;")
                company_clean = job["company_name"].replace("<", "&lt;").replace(">", "&gt;")
                msg_lines.append(f"• <b>[{company_clean}]</b> {title_clean}")

                # 멀티 소스 배지/링크 표출 처리 (Milestone 5)
                links_str = []
                for s in job["sources"]:
                    src_upper = s["source"].upper()
                    links_str.append(f"<a href='{s['url']}'>{src_upper}</a>")
                msg_lines.append(f"  👉 바로가기: { ' | '.join(links_str) }")
            msg_lines.append("")

        # 2. 오늘 신규 등록된 공고를 제외한 기존 채용 진행 중인 공고 나열
        new_job_ids = {j["id"] for j in new_jobs}
        existing_active_jobs = [j for j in deduped_active if j["id"] not in new_job_ids]

        if existing_active_jobs:
            if is_compact_mode:
                msg_lines.append(f"<b>💼 기존 수집 채용 중인 공고: {len(existing_active_jobs)}건 활성화 중</b>")
                msg_lines.append("<i>※ 활성 공고가 많아 텍스트를 간결하게 축약합니다. 전체 목록은 대시보드에서 보실 수 있습니다.</i>\n")
            else:
                msg_lines.append("<b>💼 기존에 수집된 현재 채용 진행 중인 공고 목록:</b>")
                for job in existing_active_jobs:
                    title_clean = job["title"].replace("<", "&lt;").replace(">", "&gt;")
                    company_clean = job["company_name"].replace("<", "&lt;").replace(">", "&gt;")
                    msg_lines.append(f"• <b>[{company_clean}]</b> {title_clean}")

                    # 멀티 소스 배지/링크 표출 처리 (Milestone 5)
                    links_str = []
                    for s in job["sources"]:
                        src_upper = s["source"].upper()
                        links_str.append(f"<a href='{s['url']}'>{src_upper}</a>")
                    msg_lines.append(f"  👉 바로가기: { ' | '.join(links_str) }")
                msg_lines.append("")

        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append("💻 상세 필터 및 전체 누적 공고 조회가 필요하신 경우, 아래 실시간 대시보드 링크를 터치해 주세요.")
        msg_lines.append("👉 <a href='https://laonH163.github.io/HR_test/'>[실시간 웹 대시보드] 원클릭으로 바로가기</a>")

        return "\n".join(msg_lines)
