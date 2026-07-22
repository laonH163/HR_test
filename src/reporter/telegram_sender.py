import os
import re
import requests
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

from src.utils.dedup import compute_repost_flags, content_key, normalize_company, source_rank

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

    @staticmethod
    def _md_label(date_str, fallback="?"):
        """'YYYY-MM-DD…' 문자열을 'M/D' 표시 라벨로 변환 (실패 시 fallback).

        마감일 변경·재공고 배지가 같은 규칙을 쓰도록 단일화 — 표기 형식을 바꿀 때
        브리핑 안에서 날짜 표기가 섞이지 않게 한다."""
        try:
            d = datetime.strptime(str(date_str)[:10], "%Y-%m-%d")
            return f"{d.month}/{d.day}"
        except Exception:
            return fallback

    @staticmethod
    def _normalize_company(name):
        """회사명 정규화 — 공백·법인 표기 노이즈 제거 (dedup 키 및 제목 프리픽스 대조용)"""
        return normalize_company(name)

    def _display_title(self, job):
        """제목 맨 앞의 '[회사명]' 프리픽스를 제거한 표시용 제목.
        회사명은 별도로 붙이므로 '[스마일게이트] [스마일게이트] ...' 중복 표기를 막고,
        소스별로 프리픽스 유무가 갈리는 동일 공고의 dedup 키도 일치시킨다."""
        title = (job.get("title") or "").strip()
        m = re.match(r"^\[([^\[\]]{1,30})\]\s*", title)
        if m and self._normalize_company(m.group(1)) == self._normalize_company(job.get("company_name", "")):
            stripped = title[m.end():].strip()
            if stripped:
                return stripped
        return title

    @staticmethod
    def _summarize_failed_sources(failed_sources):
        """실패 소스 요약. 잡코리아 기업페이지 우회 어댑터가 20곳 이상이라 개별 나열하면
        경고가 메시지를 뒤덮으므로, 차단이 도메인 단위로 오는 특성에 맞춰 계열로 묶는다."""
        failed = {str(s).lower() for s in failed_sources}
        try:
            from src.scraper.ats.registry import JOBKOREA_COMPANIES
            jk_family = {"jobkorea", "gamejob"} | {src for _, _, src in JOBKOREA_COMPANIES}
        except Exception:
            jk_family = {"jobkorea", "gamejob"}
        jk_failed = failed & jk_family
        others = sorted(failed - jk_family)
        parts = []
        if len(jk_failed) >= 3:
            parts.append(f"잡코리아 계열 {len(jk_failed)}곳(도메인 차단 추정)")
        else:
            others = sorted(set(others) | jk_failed)
        if others:
            parts.append(", ".join(s.upper() for s in others))
        return " · ".join(parts)

    def build_daily_briefing_message(self, newly_added, modified_count, closed_count, active_postings, weekly_trend=None, failed_sources=None, zero_platforms=None, known_companies=None, mass_close_held=None, source_drops=None, deadline_changes=None, closed_history=None, partial_sources=None, known_blocked=None, recovered_known=None):
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
        # 키 = src/utils/dedup.content_key — 정규화 회사명 + 정규화 제목.
        # '[컴투스홀딩스]' 같은 회사 포함관계 프리픽스는 회사키로 승격해 병합한다.
        # min_experience는 같은 공고인데 소스별 분류가 갈리는 실측 사례
        # (시프트업 경리/회계: 사람인 0 vs 잡코리아 1)로 미병합을 유발해 키에서 제외.
        # 대표 카드는 공식 소스(기업 어댑터) 우선 — 회사명·본문·링크가 가장 정확하다.
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        def deduplicate_postings(postings_list):
            deduped = []
            by_key = {}
            for job in postings_list:
                key = content_key(job.get("company_name"), job.get("title"))
                job_src = job.get("source", "wanted")
                if key in by_key:
                    # 이미 동일 공고가 수집되었으면 출처 정보만 누적 병합
                    existing_job = by_key[key]
                    if not any(s["source"] == job_src for s in existing_job["sources"]):
                        existing_job["sources"].append({
                            "source": job_src,
                            "url": job.get("origin_url", "")
                        })
                    # 공식 소스가 뒤에 왔으면 대표 카드를 공식 쪽 필드로 교체
                    if source_rank(job_src) < source_rank(existing_job.get("source", "wanted")):
                        merged_sources = existing_job["sources"]
                        existing_job.clear()
                        existing_job.update(job)
                        existing_job["sources"] = merged_sources
                    continue
                # 단일 출처 구조 백업
                job_copy = job.copy()
                job_copy["sources"] = [{
                    "source": job_src,
                    "url": job.get("origin_url", "")
                }]
                by_key[key] = job_copy
                deduped.append(job_copy)
            # 바로가기 링크도 공식 → 플랫폼 순으로 정렬 (동순위는 수집 순서 유지)
            for job in deduped:
                job["sources"].sort(key=lambda s: source_rank(s["source"]))
            return deduped

        # 전체 활성 공고 중복 제거 가동
        deduped_active = deduplicate_postings(active_postings)

        # 재공고(🔁) 키 계산 — 과거 CLOSED 이력이 있고, 현 활성 그룹이 그 이후 재등장한 키만
        repost_keys = {}
        if closed_history:
            try:
                repost_keys = compute_repost_flags(active_postings, closed_history)
            except Exception:
                repost_keys = {}

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
                title_clean = self._display_title(job).replace("<", "&lt;").replace(">", "&gt;")
                company_clean = job["company_name"].replace("<", "&lt;").replace(">", "&gt;")
                first_url = job["sources"][0]["url"] if job.get("sources") else job.get("origin_url", "")
                msg_lines.append(f"• <b>[{dd_label}]</b> [{company_clean}] <a href='{first_url}'>{title_clean}</a>")
            msg_lines.append("")

        # 0-b. 마감일 변경(연장/단축) 공고 — 지원 전략에 직결되는 실질 변경만 노출
        #      (마감일 최초 확보는 제외 — upsert가 기존 값이 있었던 실제 변경만 전달한다)
        if deadline_changes:
            msg_lines.append("<b>🔄 마감일 변경 감지:</b>")
            seen_change_keys = set()  # 같은 공고가 여러 소스에서 동시 변경되면 1줄만
            for change in deadline_changes:
                change_key = content_key(change.get("company_name"), change.get("title"))
                if change_key in seen_change_keys:
                    continue
                seen_change_keys.add(change_key)
                try:
                    new_is_later = (datetime.strptime(change["new"], "%Y-%m-%d")
                                    > datetime.strptime(change["old"], "%Y-%m-%d"))
                    verdict = "연장" if new_is_later else "단축⚠️"
                except Exception:
                    verdict = "변경"
                old_label = self._md_label(change.get("old"), str(change.get("old")))
                new_label = self._md_label(change.get("new"), str(change.get("new")))
                title_clean = (change.get("title") or "").replace("<", "&lt;").replace(">", "&gt;")
                company_clean = (change.get("company_name") or "").replace("<", "&lt;").replace(">", "&gt;")
                url = change.get("origin_url", "")
                msg_lines.append(f"• [{company_clean}] <a href='{url}'>{title_clean}</a>: {old_label} → {new_label} ({verdict})")
            msg_lines.append("")

        # 1. 신규 등록 공고가 있을 때 상단 노출
        #    처음 보는 회사(전체 이력에 없던 회사)는 🆕 배지 — 게임업계 재무채용 신규 진입 신호
        known_norm = {normalize_company(c) for c in (known_companies or [])}
        if new_jobs:
            msg_lines.append("<b>✨ 오늘 새로 등록된 신규 채용 정보:</b>")
            for job in new_jobs:
                title_clean = self._display_title(job).replace("<", "&lt;").replace(">", "&gt;")
                company_clean = job["company_name"].replace("<", "&lt;").replace(">", "&gt;")
                new_company_badge = ""
                if known_companies is not None and normalize_company(job["company_name"]) not in known_norm:
                    new_company_badge = "🆕 "
                # 재공고(🔁) — 같은 회사+제목 공고가 과거에 닫혔다가 다시 등장 (장기 미충원/유령공고 신호)
                repost_suffix = ""
                job_key = content_key(job.get("company_name"), job.get("title"))
                if job_key in repost_keys:
                    closed_label = self._md_label(repost_keys[job_key], "")
                    repost_suffix = (f" <i>🔁 재공고 (~{closed_label} 게시이력)</i>"
                                     if closed_label else " <i>🔁 재공고</i>")
                msg_lines.append(f"• {new_company_badge}<b>[{company_clean}]</b> {title_clean}{repost_suffix}")

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
                    title_clean = self._display_title(job).replace("<", "&lt;").replace(">", "&gt;")
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

        # 🩺 수집 상태 섹션 — 경고는 메인 콘텐츠(마감임박·신규·기존)를 해치지 않도록
        # 최하단에 컴팩트하게 모은다. 무음 실패 방지가 목적이므로 정상인 날도 한 줄로 확인시켜 준다.
        # (실측: 원티드가 한 달간 0건이었는데 error_log에만 남아 아무도 몰랐던 사고의 재발 방지)
        health_lines = []
        if failed_sources:
            # CI에서는 새 러너(새 IP) 재시도까지 거친 뒤의 최종 실패만 여기 도달한다.
            health_lines.append(f" • ⚠️ 접속 실패: <b>{self._summarize_failed_sources(failed_sources)}</b>")
        if zero_platforms:
            zp = " · ".join(str(s).upper() for s in sorted(zero_platforms))
            health_lines.append(f" • ⚠️ 검색 0건: <b>{zp}</b>")
        if mass_close_held:
            mh = " · ".join(str(s).upper() for s in sorted(mass_close_held))
            health_lines.append(f" • ⚠️ 공고 일괄 소멸 의심: <b>{mh}</b>")
        if source_drops:
            parts = [f"{str(s).upper()} {v['today']}건(평소 {v['avg']:.0f}건)" for s, v in sorted(source_drops.items())]
            health_lines.append(f" • 📉 수집량 급감: <b>{' · '.join(parts)}</b>")
        if partial_sources:
            # 검색 키워드 일부만 통과한 소스 — 수집은 됐지만 '다 훑었다'고 볼 수 없어
            # 마감 판정을 보류한 상태다. 보류가 며칠 이어지면 이미 마감된 공고가
            # 활성으로 남으므로(좀비), 반드시 눈에 보여야 한다.
            ps = " · ".join(str(s).upper() for s in sorted(partial_sources))
            health_lines.append(f" • ⏸ 검색 일부 실패로 마감 판정 보류: <b>{ps}</b>")
        if recovered_known:
            # 고칠 방법이 없다고 등록해 둔 소스가 다시 수집됐다 = 차단이 풀렸다.
            # 등록 표(src/utils/known_blocks.py)에서 지워야 하므로 조치가 필요한 알림이다.
            rk = " · ".join(str(s).upper() for s in sorted(recovered_known))
            health_lines.append(f" • ✅ 차단 해제 확인: <b>{rk}</b> 수집 재개 "
                                f"— known_blocks 등록 해제 필요")
        # 알려진 차단이 오래 이어지면 정보가 아니라 경고다(활성 공고가 좀비일 수 있음)
        for note in (known_blocked or []):
            if note.get("stale"):
                health_lines.append(
                    f" • ⚠️ <b>{str(note['source']).upper()}</b> 차단 {note['days']}일째 "
                    f"— 남은 활성 공고가 실제로 마감됐는지 수동 확인 필요")

        if health_lines:
            msg_lines.append("🩺 <b>수집 상태 점검:</b>")
            msg_lines.extend(health_lines)
            msg_lines.append("<i>※ 해당 소스는 마감 보류로 보호 중이라 데이터는 안전합니다. 같은 경고가 이틀 이상 반복되면 점검이 필요합니다.</i>")
        else:
            msg_lines.append("🩺 수집 상태: 전 소스 정상")

        # 알려진 차단은 '경고'가 아니라 '정보'다 — 조치할 게 없으므로 정상 표시를 가리지
        # 않고 아래에 한 줄로만 남긴다. 완전히 숨기면 차단 사실 자체를 잊게 된다.
        for note in (known_blocked or []):
            if note.get("stale"):
                continue  # 이미 위에서 경고로 올렸다
            days_txt = f" · {note['days']}일째" if note.get("days") is not None else ""
            msg_lines.append(
                f"<i> • ℹ️ {str(note['source']).upper()}: {note.get('summary', '알려진 차단')}"
                f"{days_txt} — 조치 불요(자동 복구 감시 중)</i>")
        msg_lines.append("")

        msg_lines.append("💻 상세 필터 및 전체 누적 공고 조회가 필요하신 경우, 아래 실시간 대시보드 링크를 터치해 주세요.")
        msg_lines.append("👉 <a href='https://laonH163.github.io/HR_test/'>[실시간 웹 대시보드] 원클릭으로 바로가기</a>")

        return "\n".join(msg_lines)
