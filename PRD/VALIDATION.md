# VALIDATION: GameFinanceScraper

## Required Checks

다음 검증 명령들은 전체 골을 완료로 마크하기 전에 반드시 실행하고 통과해야 합니다.

```bash
# 1. 의존성 설치 검증 및 런타임 빌드 체크
python -m pip install -r requirements.txt

# 2. 전체 패키지 단위 테스트 구동 (스크래핑, 디비 적재, 분류기, 상태 분석)
python -m unittest discover -s tests -p "test_*.py"

# 3. 메인 프로세스 CLI 구동력 검증
python src/main.py --help
```

## Targeted Checks

각 마일스톤 종료 시점 및 개별 기능 체크포인트에서 실효적으로 작동해야 하는 검증 단계입니다.

### Milestone 1 (수집 & DB 인프라)
```bash
# 데이터베이스 초기 테이레이아웃 유효성 검사 및 수집 마스터 정상 가동 테스트
python tests/test_scraper.py
python tests/test_db.py
```

### Milestone 2 (하이브리드 분류 및 델타 분석)
```bash
# 정적 규칙 분류 엔진 정밀도 및 이전 수집 결과와의 델타 연산 검사
python tests/test_classifier.py
python tests/test_analyzer.py
```

### Milestone 3 (HTML 대시보드 리포터)
```bash
# index.html 정적 파일 자바스크립트 및 폰트 로드 경로 정합성 수동 검사
# 로컬 파일 크기가 0바이트 이상이며 올바른 HTML 포맷을 갖추었는지 확인
python -c "import os; assert os.path.getsize('index.html') > 0, 'index.html is empty!'"
```

### Milestone 4 (E2E 자동화 & 알림)
```bash
# GitHub Actions 가상 러너 시뮬레이션 및 텔레그램 메시지 API 통신 테스트
python tests/test_reporter.py
```

## Manual Verification

1. **DB 영속성 확인**: `data/scrap_master.db` 파일을 SQLite GUI 도구나 `sqlite3` CLI 명령으로 조회하여, 게임사 명칭 및 채용제목 등의 텍스트가 인코딩 깨짐 없이 한글로 20건 이상 완전 적재되었는지 육안으로 확인합니다.
2. **반응형 뷰어 동작성**: 생성된 `index.html` 파일을 크롬 브라우저로 열어, 우상단의 직무 대분류 필터(회계/세무/재무)를 클릭했을 때 테이블이 비동기(Alpine.js)로 부드럽게 필터링되고, 모바일 너비로 창을 줄였을 때 텍스트 짤림이나 가로 스크롤 과부하 없이 그리드가 한눈에 잡히는지 확인합니다.
3. **텔레그램 알림 형태**: 내 폰으로 들어온 텔레그램 메시지 카드가 `[신규 공고]`, `[마감 공고]`, `[주요 업데이트]` 섹션별로 가시성 높은 이모지와 구분선으로 가독성 좋게 수신되었는지 최종 텍스트 검수를 거칩니다.

## Acceptance Criteria Mapping

| PRD criterion | Validation method | Status |
| --- | --- | --- |
| 플랫폼 및 게임사 공홈 재무공고 누락 없는 수집 | `tests/test_scraper.py`를 통한 원티드/사람인 API 데이터 수신 및 5대 게임사 스크래퍼 기능 검증 | Pending |
| 비용 0원 AI형 하이브리드 자동 정밀 분류 | `tests/test_classifier.py`를 통한 규칙 사전 연계 연차/연봉/재택형태/회사규모 매핑 데이터 정합성 검증 | Pending |
| 전날 데이터 기준 신규, 수정, 마감 델타 분석 | `tests/test_analyzer.py`를 통한 SQLite 공고 상태값(ACTIVE/CLOSED/MODIFIED) 업데이트 연산 검증 | Pending |
| 프라이빗 텔레그램 요약 및 싱글 HTML 리포트 생성 | `tests/test_reporter.py` 실행 및 최종 `index.html` 파일 브라우저 육안 시각 검증 | Pending |
| GitHub Actions 크론 및 무보수 무중단 배포 | GitHub 가상 런타임 환경 시뮬레이션 및 저장소 Push & Secrets 연동 완비 | Pending |

## Not Done If

- Any required check fails (테스트 에러가 하나라도 존재하거나 빌드가 깨지는 경우)
- Scope changed outside PLAN.md (사전에 조율되지 않은 추가 채용 사이트 스크래퍼나 불필요한 회원가입 폼 등을 무리하게 추가한 경우)
- API 토큰, 개인 챗 ID 등의 민감 정보가 소스코드나 퍼블릭 커밋 내에 평문으로 유출된 경우
- HTML 리포트가 로컬 파일 단독 실행 상태에서 외부 CDN 라이브러리 차단이나 절대경로 깨짐으로 인해 화면 렌더링에 실패하는 경우
- 스크랩 수집 성능 안정화를 위한 1~3초 주기 슬립(Sleep) 설정이 누락되어 사이트로부터 IP 밴 또는 접속 제한을 당하는 경우
- 오류를 디버깅이나 근본적 분석 없이 단순히 `try-except pass`로 무조건 뭉개서 넘어가도록 방임한 경우
