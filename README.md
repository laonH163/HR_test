# 게임업계 재무·회계·세무 채용공고 수집기 (GameFinanceScraper)

게임회사 공식 채용 채널과 주요 채용 플랫폼을 매일 수집해 **재무·회계·세무·자금 직무만** 골라내고,
텔레그램 브리핑과 웹 대시보드로 제공하는 자동화 파이프라인입니다.

- **대시보드**: https://laonh163.github.io/HR_test/
- **실행 주기**: 매일 08:00 KST (GitHub Actions) — 주말·한국 법정공휴일은 자동 스킵

## 주요 기능

| 기능 | 설명 |
|------|------|
| 멀티 소스 수집 | 채용 플랫폼 4곳 + 게임사 공식 채널 27곳 이상 |
| 직무 필터링 | 재무·회계·세무·자금·경리·IR·내부회계 등만 통과 (개발직·HR·카지노 딜러류 차단) |
| 교차 소스 중복 병합 | 같은 공고가 여러 곳에 올라오면 1건으로 병합, 공식 채널 우선 표시 |
| 마감일 추적 | D-N 배지·마감 배지를 절대 날짜로 환산, 마감 3일 전 텔레그램 경고 |
| 델타 감지 | 신규·본문 변경·마감을 매일 비교 감지 (검색 오동작 시 마감 오판 보류) |
| 텔레그램 브리핑 | 신규(🆕 신규 진입사 배지)·업데이트·마감·수집 이상 경고를 매일 1통으로 |
| 자동 분류 | 경력 연차·근무형태(재택 여부)·자격증(CPA 등)·실무 태그(IFRS·연결 등) 추출 |

## 수집 소스

- **채용 플랫폼 검색**: 원티드(Playwright), 사람인, 잡코리아, 게임잡
- **공식 ATS API**: 크래프톤(Greenhouse), 네오위즈(Lever), 카카오게임즈·111퍼센트·슈퍼센트·에피드게임즈(greetinghr — 마감일·본문 포함)
- **자체 채용 페이지**: 펄어비스(정적), 시프트업(자체 API)
- **잡코리아 기업페이지 우회**(자체 페이지가 봇차단/SPA인 회사): 넥슨·엔씨소프트·넷마블·컴투스·웹젠·위메이드·스마일게이트 등 20여 사 — 회사명 교차검증 가드레일로 오매핑 차단

## 동작 흐름

```
수집(병렬) → 잡코리아 GI 중복 병합 → 소스 헬스체크 → SQLite 적재(Upsert)
→ 하이브리드 분류(연차·근무형태·태그) → 마감 델타 분석 → HTML 대시보드 생성
→ 텔레그램 브리핑 발송
```

수집 실패에는 3중 방어가 있습니다: ① 소스별 재시도(최대 3회) ② 실패 소스의 기존 공고는
마감 처리 보류 ③ IP 차단형 실패 시 **새 러너(새 IP)에서 자동 2차 시도** 후 최종 결과만 발송.
"성공했지만 0건"인 플랫폼도 검색 오동작으로 간주해 마감 판정을 보류하고 브리핑에 경고를 띄웁니다.

## 로컬 실행

```bash
pip install -r requirements.txt
playwright install chromium          # 원티드 수집용

# 주말/공휴일 가드 우회 강제 수집 (DB 적재 + 대시보드 + 텔레그램)
python -m src.main --force

# 대시보드만 재생성 (수집 없음)
python -m src.main --mode report

# 테스트
PYTHONPATH=. python -m unittest discover -s tests
```

텔레그램 발송에는 환경변수 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`가 필요합니다(.env 지원).
없으면 발송만 건너뛰고 나머지는 정상 동작합니다.

## 프로젝트 구조

```
src/
  main.py                  # 파이프라인 오케스트레이션 (수집→적재→분류→델타→리포트)
  scraper/
    filters.py             # 재무 직무·게임사 판별 공통 필터 (단일 소스 오브 트루스)
    wanted|saramin|jobkorea|gamejob_scraper.py   # 플랫폼 검색 수집기
    ats/                   # 게임사 공식 채널 어댑터 (Greenhouse/Lever/greetinghr/잡코리아 우회 등)
  classifier/hybrid_engine.py   # 연차·근무형태·자격증·스킬 태그 추출
  analyzer/delta_analyzer.py    # 마감(CLOSED) 판정 — 오판 방지 보류 로직 포함
  database/db_manager.py        # SQLite Upsert·마이그레이션·조회
  reporter/                     # HTML 대시보드 생성·텔레그램 브리핑
  utils/                        # 공용 유틸 (중복 병합 키, 마감 배지 파서, KST 시각, HTTP 세션)
templates/dashboard_template.html  # 대시보드 템플릿 (병합 키 로직이 JS로 미러링되어 있음)
tests/                        # 회귀 테스트 (픽스처 기반, 73+)
data/scrap_master.db          # 공고 마스터 DB (매일 자동 커밋)
docs/MAINTENANCE.md           # 유지보수 기록 — 구조 결정·함정·검증 루틴
```

## 유지보수

스크래퍼·필터를 수정할 때의 필수 검증 루틴과 알려진 함정(사이트 개편 이력, 병합 키 이중
미러링, 이미지 JD 한계 등)은 [docs/MAINTENANCE.md](docs/MAINTENANCE.md)에 정리되어 있습니다.
