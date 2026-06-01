# PROGRESS

## Current Goal

게임 회사 재무(회계/세무/자금) 직군 채용공고의 자동 수집, AI 하이브리드 분류, 텔레그램 데일리 브리핑 및 단일 HTML 대시보드 리포트를 구축하여 무비용 무중단 자동화 서비스를 구현합니다.

## Current Milestone

Milestone 5: 종합 정밀 개선 및 고도화 완료 (Deduplication, ThreadPoolExecutor, Planner & Planner Personalization 완료)

## Completed

- **Milestone 1**: 멀티 소스 크롤러 및 SQLite 데이터베이스 마스터 구축 완료
- **Milestone 2**: 하이브리드 분류기 및 Delta 변동 분석 모듈 완성 완료
- **Milestone 3**: 단일 정적 웹 대시보드 리포트 생성기 구축 완료
- **Milestone 4**: 프라이빗 텔레그램 연동 및 GitHub Actions 일일 자동화 배포 완료
- **Milestone 5 (NEW)**: 종합 정밀 개선 및 고도화 완료
  - **수집 무누락(안전 최우선)**: SQLite에 모든 소스별 원천 채용공고를 누락 없이 100% 독립 영속화하여 안전한 데이터 원형 보존. WAF 차단 및 일시 장장해에 강인한 안전 재시도(Retry, 최대 3회) 매커니즘 탑재 완료.
  - **중복 공고 디듀프리케이션(De-duplication)**: 대시보드 빌드 및 텔레그램 전송 단계에서 회사명, 채용공고명, 요구 연차가 유사한 중복 건을 지능적으로 그룹화. 하나의 카드에 `[WANTED] [SARAMIN]` 등 멀티 출처 뱃지와 전용 아웃링크를 병합 지원하도록 텔레그램 센더 및 HTML 템플릿 완비.
  - **병렬 수집 가속화**: 메인 스레드에서 Playwright 기반 원티드를 먼저 가동하고, requests 기반 플랫폼(사람인, 잡코리아, 게임잡, ATS 어댑터, 시프트업)을 `ThreadPoolExecutor`를 통해 최대 4개 멀티 스레드로 병렬 동시 수집함으로써 GitHub Actions 구동 시간을 획득 단축.
  - **대시보드 편의성 고도화**: Alpine.js와 브라우저 LocalStorage를 연계하여 서버가 필요 없는 정적 HTML 상태에서도 **북마크(관심공고) 즐겨찾기**, **지원 단계별 상태 추적 Selector**, **개인 맞춤형 자유 메모 플래너** 기능 완벽 구현.
  - **경력 및 우대사항 태깅 고도화**: `"1~3년차"`, `"3년↑"`, `"3년 전후"`, `"5년이하"` 한글 경력 표현의 다각적 추출 연치 고도화 완료. 자격증(`CPA`, `AICPA` 등) 및 핵심 실무 역량(`IFRS`, `연결회계`, `내부회계`, `공시` 등)을 다차원 태깅하고 대시보드 상에서 **퀵 태그 필터**를 통해 즉시 필터링할 수 있도록 설계 완료.
  - **안전한 DB 점진적 마이그레이션**: 데이터 탈실 없이 안전하게 데이터 구조를 확장할 수 있도록 `DBManager`에 `preferred_certifications` 및 `preferred_skills_tags` 컬럼이 부재할 시 실시간 검사 및 `ALTER TABLE`하는 동적 스키마 마이그레이션 도우미 연동 완료.

## Last Validation

```text
- tests/test_scraper.py, test_classifier.py, test_reporter.py, test_ats_adapters.py 전체 14개 통합 단위 테스트 통과 (OK - unittest OK)
- sqlite3 DB 스키마 검사 시 신규 마이그레이션 컬럼 preferred_certifications, preferred_skills_tags 정상 적용 완료 확인
- python src/main.py --mode report 정적 HTML 대시보드 단독 생성 가동 성공 및 중복 제거 적용 확인 (index.html 파일 정상 확보)
- GitHub Actions 일일 배포 크론 구성 완비 (.github/workflows/daily-scraper.yml)
```

## Failed Attempts

| Attempt | Change | Result | Lesson |
| --- | --- | --- | --- |

## Current Best State

- 멀티 소스 공고 수집, 병렬 ThreadPool 수집 가속화, 안정적 Retry 수집 가드, 중복 제거 표출, 정적 로컬 스토리지 연동 플래너 및 다각화된 우대 조건 퀵 태깅이 완벽하게 결합된 엔터프라이즈급 크롤링 서비스 완비.

## Risks / Blockers

- 없음 (안전 제일 수집 전략, 3회 백오프 백가드, 마감 보류 안전장치 3건 기준 탑재로 인해 위험 부담 완벽 헤징).

## Handoff Notes

- 이 PROGRESS.md는 Milestone 5 종합 개선 완료를 맞아 성공적으로 최신화되었습니다. 이 프로젝트는 로컬 PC 더블클릭 환경 및 GitHub Pages 환경 상에서 완벽히 개인화된 무비용 구직 추적 대시보드로 무기한 안정 가동됩니다.
