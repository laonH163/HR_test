# PLAN: GameFinanceScraper

## Goal

게임 회사 재무(회계/세무/자금) 직군 채용공고의 자동 수집, AI 하이브리드 분류, 텔레그램 데일리 브리핑 및 단일 HTML 대시보드 리포트를 구축하여 무비용 무중단 자동화 서비스를 구현합니다.

## Source Documents

- PRD.md (`PRD/01_PRD.md`)
- VALIDATION.md (`PRD/VALIDATION.md`)
- RECOVERY.md (`PRD/RECOVERY.md`)

## Milestone 1: 멀티 소스 크롤러 및 SQLite 데이터베이스 마스터 구축 (완료)
- **Scope**: 원티드(Wanted), 사람인(Saramin) 재무 공고 수집 모듈 개발, 5대 대형 게임사(넥슨, 크래프톤, 엔씨소프트, 넷마블, 카카오게임즈) 공식 채용 사이트 스크래핑 구현, SQLite3 DB 테이블 생성기 및 1~3초 랜덤 슬립과 커스텀 User-Agent 헤더 기반의 무오류 공고 수집 및 적재 모듈 완성
- **Completion**: `tests/test_scraper.py` 유닛 테스트 구동 시 실제 원본 API 또는 정적 HTML 파서가 성공적으로 작동하여 실시간 라이브 채용공고 20건 이상이 `data/scrap_master.db` 내 `job_postings` 마스터 테이블에 한글 인코딩 오류 없이 고유 ID 기준으로 정상 영속화 저장됨
- **Validation**: `python -m unittest tests/test_scraper.py` 테스트 실행 및 `sqlite3` CLI 터미널 조회 검증 완료

## Milestone 2: 하이브리드 분류기 및 Delta 변동 분석 모듈 완성 (완료)
- **Scope**: 무비용 연산 보장을 위해 정밀 정적 규칙 사전과 경량 한글 키워드 분석을 결합한 연차 제한, 연봉 범위, 재택 형태(3단분류: 풀재택/하이브리드/출근), 회사 매출 및 인원 규모 정제 알고리즘 구현. 어제 축적된 DB 레코드와 오늘 수집된 데이터를 비교하여 공고 상태값(ACTIVE/CLOSED/MODIFIED)을 자동으로 계산하고 업데이트하는 Delta Analyzer 구축
- **Completion**: 수집된 모든 개별 공고에 대하여 1:1 대응되는 정밀 분류 정보가 성공적으로 도출되어 `job_categories` 테이블에 정상적으로 매핑 및 Upsert 적재 처리됨
- **Validation**: `python -m unittest tests/test_classifier.py` 및 `tests/test_analyzer.py` 유닛 테스트 통과 확인

## Milestone 3: 단일 정적 웹 대시보드 리포트 생성기 구축 (완료)
- **Scope**: SQLite DB에 누적된 데이터셋을 읽어와 가독성을 대폭 끌어올린 단일 정적 HTML 템플릿에 데이터 주입 처리하는 Generator 개발. 로컬 파일 단독 더블클릭 구동을 위해 CDN 기반의 Alpine.js와 Tailwind CSS 라이브러리를 바인딩하고 직무 필터링, 검색 바, 연차 슬라이더 필터 기능 구현
- **Completion**: 생성된 `index.html` 단일 정적 웹페이지가 로컬 샌드박스 보안 경고 없이 쾌적하게 동작하며, 반응형으로 제작되어 모바일과 데스크톱 화면에서 일그러짐 없이 표출됨
- **Validation**: 브라우저 실행 수동 동작 테스트 및 Alpine.js 필터링 렌더링 육안 수동 검증

## Milestone 4: 프라이빗 텔레그램 연동 및 GitHub Actions 일일 자동화 배포 완료 (완료)
- **Scope**: 개인 텔레그램 봇 API를 연동하여 매일 아침 전날 대비 신규 공고, 바뀐 공고, 마감된 공고 목록을 아름답고 일목요연하게 텔레그램 카드로 전송하는 모듈 완성. GitHub Actions 크론 스케줄링(`.github/workflows/daily-scraper.yml`)을 설정하여 매일 오전 8시에 스스로 돌며 전체 파이프라인 가동 후 SQLite DB 파일과 index.html을 스스로 Git Commit & Push하여 저장소를 최신화하는 E2E 배포 환경 완비
- **Completion**: 리포지토리 푸시 작동 후 설정된 Secrets 토큰 기반으로 스마트폰 텔레그램 개인 챗봇에서 데일리 브리핑 알림을 오차 10분 이내로 성공적으로 수신 완료함
- **Validation**: `python tests/test_reporter.py` 최종 발송 테스트 통과 및 Actions 가상 러너 E2E 전주기 가동 시뮬레이션 최종 완료

## Milestone 5: 종합 정밀 개선 및 고도화 (진행 예정)
- **목표**: 수집 원천 자료 누락 방지(안전 제일), 중복 공고 디듀프리케이션 표출, 수집 파이프라인 병렬 가속화, 로컬 대시보드 개인화 기능 추가, 분류기 및 연차 추출 고도화 구현.
- **상세 내역**:
  1. **중복 공고 디듀프리케이션(De-duplication)**:
     - 수집(DB 적재)은 각 소스별로 원천 데이터를 누락 없이 100% 저장하여 안전하게 데이터 보존.
     - `HTMLGenerator` 및 `TelegramSender`에서 중복되는 공고를 회사명, 제목, 경력을 기반으로 그룹화(Deduplicate)하여 표출.
     - 대시보드 상에서 한 공고에 `[원티드] [사람인]` 등 멀티 출처 뱃지와 개별 지원 링크를 병렬 제공.
  2. **수집 파이프라인 멀티스레딩 병렬 가속화**:
     - `main.py`에서 `ThreadPoolExecutor`를 활용해 병렬 수집 구현.
     - 단, Playwright 기반인 `WantedScraper`는 Thread-safety 이슈 방지를 위해 메인 스레드에서 격리 실행.
     - requests 기반인 사람인, 잡코리아, 게임잡 및 ATS 어댑터 그룹을 개별 스레드에서 병렬 수집하여 GitHub Actions 구동 시간 단축.
     - 임시 네트워크 장장해 및 차단을 극복하기 위한 안전한 재시도(Retry, 최대 3회) 데코레이터/로직 탑재하여 수집 누락 원천 방지.
  3. **대시보드 로컬 편의 기능 고도화 (Alpine.js + LocalStorage)**:
     - **북마크(즐겨찾기)**: 공고 목록 옆에 별표 버튼을 탑재하고 브라우저 LocalStorage에 보존하여 상단 필터로 "북마크만 보기" 필터 제공.
     - **지원 상태 관리 및 개인 메모**: 각 공고에 대해 `[지원 대기] / [지원 완료] / [서류 통과] / [최종 합격] / [불합격]` 등 상태 토글 및 간단한 메모를 LocalStorage에 저장하여 오프라인 구직 플래너화.
  4. **경력/우대사항 정밀 분류기(Classifier) 및 점진적 DB 마이그레이션**:
     - 연차 추출 정규식을 고도화하여 `"3년 내외"`, `"5년 전후"`, `"경력 1~3년"`, `"10년 이상"`, `"3년↑"`, `"5년이하"` 매칭 지원.
     - 우대 자격증(`CPA`, `AICPA`, `CTA`, `CFA`, `FRM`) 및 핵심 실무 역량(`IFRS`, `연결`, `공시`, `내부회계`, `SOX`, `세무조사`)을 풍부하게 정제 및 분류 태깅.
     - DB 스키마가 바뀔 수 있는 미래 확장을 대비하여, `DBManager.init_db()`에서 테이블 스키마를 검사해 없는 컬럼을 안전하게 동적 추가(`ALTER TABLE`)해 주는 컬럼 마이그레이션 도우미 함수 구현.
- **Completion**: 중복 제거 및 북마크가 적용된 단일 HTML 대시보드와 더 상세해진 텔레그램 데일리 요약 카드가 오류 없이 생성 및 발송되고, 모든 유닛 테스트가 완벽히 통과할 것.
- **Validation**: 유닛 테스트 `python -m unittest discover tests` 가동 및 대시보드 수동 실행 검증.
