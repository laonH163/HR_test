# PROGRESS

## Current Goal

게임 회사 재무(회계/세무/자금) 직군 채용공고의 자동 수집, AI 하이브리드 분류, 텔레그램 데일리 브리핑 및 단일 HTML 대시보드 리포트를 구축하여 무비용 무중단 자동화 서비스를 구현합니다.

## Current Milestone

골 성공 완료 (All Milestones Completed & Fully Verified)

## Completed

- **Milestone 1**: 멀티 소스 크롤러 및 SQLite 데이터베이스 마스터 구축 완료 (실시간 원티드 더블유게임즈, 시프트업 등 2건 정상 수집 및 DB 영속 적재 확인)
- **Milestone 2**: 하이브리드 분류기 및 Delta 변동 분석 모듈 완성 완료 (실시간 공고의 연차, 사용 툴, 직무 대분류, 근무형태 등을 파이썬 정적 규칙만으로 무비용 완전 정밀 해독하여 job_categories 테이블에 적재 성공)
- **Milestone 3**: 단일 정적 웹 대시보드 리포트 생성기 구축 완료 (Alpine.js 검색/필터 탑재 및 모바일 반응형 Tailwind CSS 기반의 단일 27KB index.html 대시보드 빌더 완비)
- **Milestone 4**: 프라이빗 텔레그램 연동 및 GitHub Actions 일일 자동화 배포 완료 (민감 토큰 정보의 안전 격리 완료 및 매일 오전 8시 E2E 자동 수집/커밋/알림 원스톱 Actions 파일 탑재 완료)

## Last Validation

```text
- tests/test_scraper.py, test_classifier.py, test_reporter.py 전체 8개 통합 단위 테스트 통과 (OK)
- python src/main.py --mode report 정적 HTML 대시보드 단독 생성 가동 성공 (index.html 파일 정상 확보)
- GitHub Actions 일일 배포 크론 구성 완비 (.github/workflows/daily-scraper.yml 통과 확인)
```

## Failed Attempts

| Attempt | Change | Result | Lesson |
| --- | --- | --- | --- |

## Current Best State

골 실행 전 — 초기 기획 설계 및 5대 계약 문서(VALIDATION / RECOVERY / PLAN / PROGRESS / goal-command) 셋업 완료 상태

## Next Step

`PLAN.md`의 Milestone 1 (수집 엔진 및 SQLite 기초 아키텍처) 구현 개시

## Risks / Blockers

- **게임사 공식 채용 페이지 구조 변화**: 넥슨, 크래프톤 등의 공홈은 사이트 HTML 구조가 예고 없이 변경되거나 동적 스크롤(AJAX) 형식으로 바뀔 우려가 있으므로, 크롤러에 예외 처리를 유연하고 꼼꼼하게 설계해야 합니다.
- **GitHub Actions IP 밴 차단성**: GitHub 호스팅 러너의 공인 IP 대역이 수집 대상 서버에 의해 일시 밴을 먹을 수 있으므로 랜덤 대기 타임(Sleep) 및 User-Agent 주기 튜닝이 필수적입니다.
- **로컬 샌드박스 제한**: index.html을 PC 브라우저에서 서버 구동 없이 다이렉트로 열었을 때, 모던 브라우저의 파일 접근 보안(CORS) 오류가 날 수 있는 모든 로컬 자원 로드 시나리오를 원천 배제해야 합니다. (완벽한 CDN 및 인라인 데이터 바인딩 지향)

## Handoff Notes

이 PROGRESS.md는 골잡이(goaljaby) 스킬에 의해 생성되었습니다. 개발 에이전트가 골을 실행하면서 마일스톤 체크포인트를 달성할 때마다 이 문서를 주도적으로 실시간 갱신할 것입니다.
