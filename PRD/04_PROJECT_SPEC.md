# GameFinanceScraper -- 프로젝트 스펙

> 이 문서는 AI 개발 엔진이 코드를 빌드하고 최적화할 때 준수해야 할 필수적인 가이드라인 및 규칙 세트입니다.
> 견고하고 비용이 발생하지 않는 지속 가능한 시스템을 만드는 핵심 스펙을 명시합니다.

---

## 기술 스택

이 프로젝트는 비용 0원 유지와 극강의 프라이버시 확보를 목표로 하는 서버리스 지향형 스택을 사용합니다.

| 영역 | 선택 | 이유 |
|------|------|------|
| **언어 및 런타임** | `Python 3.11+` | 강력한 크롤링 생태계(BeautifulSoup, Requests 등) 및 경량 텍스트 파싱 유틸리티 지원 |
| **데이터베이스** | `SQLite3` | 별도의 상시 가동 웹서버나 DB 서버 호스팅 결제 없이 파일 기반으로 로컬에서 무비용 보관 가능 |
| **분류 엔진** | `Regex + Hybrid Rule-Engine` | API 호출 요금이 전혀 없는 순수 인메모리 분류 알고리즘 구축 (비용 0원 달성) |
| **인프라 & 자동화**| `GitHub Actions` | 24시간 매일 정해진 시간 자동화 크론(Cron) 무료 가동 지원 |
| **리포트 뷰어** | `Single-file HTML (Tailwind CSS 4 + Alpine.js via CDN)` | 추가 프론트엔드 호스팅이나 배포 절차 없이 로컬에서 즉시 더블클릭으로 강력한 반응형 인터페이스 사용 가능 |
| **알림 게이트웨이** | `Telegram Bot API` | 별도 알림 비용 결제 없이 완벽히 비공개된 나만의 채널로 빠르고 안정적인 무료 푸시 수신 |

---

## 프로젝트 구조

```
GameFinanceScraper/
├── .github/
│   └── workflows/
│       └── daily-scraper.yml   # Github Actions 스케줄러 설정
├── src/
│   ├── scraper/
│   │   ├── __init__.py
│   │   ├── wanted_scraper.py   # 원티드 공고 스크래핑 모듈
│   │   ├── saramin_scraper.py  # 사람인 공고 스크래핑 모듈
│   │   └── company_scrapers.py # 넥슨/크래프톤 등 공홈 전용 스크래퍼
│   ├── classifier/
│   │   ├── __init__.py
│   │   └── hybrid_engine.py    # 연차/연봉/재택/규모 정밀 분류기
│   ├── analyzer/
│   │   ├── __init__.py
│   │   └── delta_analyzer.py   # 공고 신규/수정/마감 비교 분석기
│   ├── reporter/
│   │   ├── __init__.py
│   │   ├── html_generator.py   # 단일 HTML 대시보드 템플릿 빌더
│   │   └── telegram_sender.py  # 텔레그램 브리핑 메시지 전송 모듈
│   ├── database/
│   │   ├── __init__.py
│   │   └── db_manager.py       # SQLite DB CRUD 및 테이블 이니셜라이저
│   └── main.py                 # 전 프로세스 제어 진입점 (CLI)
├── templates/
│   └── dashboard_template.html # 대시보드 마스터 HTML 템플릿
├── data/
│   └── scrap_master.db         # 스크랩 누적 데이터베이스 파일 (SQLite)
├── .env.example                # 로컬 디버깅용 환경변수 샘플
├── .gitignore                  # 로컬 .env 및 캐시 제외 규칙
├── requirements.txt            # 파이썬 의존 패키지 파일
└── README.md                   # 실행 명령어 가이드
```

---

## 절대 하지 마 (DO NOT)

> AI에게 개발을 시키거나 새로운 파트를 작성할 때, 아래 규칙을 100% 철저하게 지켜야 합니다.

- [ ] **API Key 하드코딩 금지**: 텔레그램 봇 토큰(`TELEGRAM_BOT_TOKEN`) 및 사용자 챗ID(`TELEGRAM_CHAT_ID`)를 절대로 파이썬 코드 내부에 직접 하드코딩하지 마세요. (반드시 `.env` 또는 GitHub Secrets에서 읽어오도록 구성)
- [ ] **DB 구조 임의 파괴 및 덮어쓰기 금지**: 매일 새로 수집할 때마다 기존 데이터베이스 파일을 날리고 새로 만드는(`Drop and Create` 등) 무식한 저장 방식 금지. (반드시 Delta 분석을 통해 상태만 점진적으로 `Upsert` 처리)
- [ ] **웹 크롤러 무제한 대량 동시 요청 금지**: 채용 플랫폼 및 기업 홈페이지를 긁어올 때 딜레이(Sleep) 없이 연속해서 초고속 요청을 보내는 방식 금지. (서버 측 차단 및 IP 밴 방지를 위해 최소 1~3초 임의 간격 슬립 가동)
- [ ] **유료 API에 의존하는 설계 지양**: OpenAI, Claude API 등 매 호출 시 요금이 과금되는 유료 외부 API가 없으면 전체 시스템 가동이 멈추는 핵심 분류 아키텍처 금지. (반드시 자체 정적 규칙과 무료 파이썬 한글 파서 라이브러리 가용 자원을 1순위로 가동)
- [ ] **외부 프레임워크 기반 프론트엔드 빌드 방식 배제**: React, Next.js, Vue 등 대규모 빌드 컴파일 타임 및 무거운 호스팅 서비스가 필요한 프론트엔드 환경 금지. (오직 PC 및 폰 브라우저에서 독립 단독 가동하는 Static Single-File HTML 제작)

---

## 항상 해 (ALWAYS DO)

- [ ] **철저한 예외 처리**: 특정 사이트의 HTML 구조가 리뉴얼되어 크롤링 중 에러가 나더라도 전체 파이프라인이 붕괴하지 않도록 `try-except` 블록을 꼼꼼하게 장착하고 에러 난 소스만 `scrape_logs`에 상세히 기록한 뒤 다음 스크랩으로 우아하게 넘어갈 것
- [ ] **SQLite 트랜잭션 보장**: 다수의 공고 데이터를 한 번에 데이터베이스에 밀어 넣을 때 성능 저하가 없도록 벌크 인서트(`executemany`) 및 단일 세션 트랜잭션 커밋(`Commit`)을 적용할 것
- [ ] **로컬 오프라인 HTML 가독성 극대화**: 생성되는 HTML 대시보드 리포트는 모바일 기기에서도 볼 수 있게 반응형(Tailwind CSS) 레이아웃을 엄격히 적용하며, 별도 로컬 웹서버가 없어도 로컬 디스크 파일 경로에서 온전히 로딩되도록 `cdn` 방식으로만 자원을 로드할 것
- [ ] **크롤러 User-Agent 위장 설정**: 모든 HTTP 요청 시 브라우저에서 보내는 것과 유사하게 위장할 수 있는 `User-Agent` 커스텀 헤더를 필수 장착하여 차단을 회피할 것

---

## 테스트 방법

```bash
# 1. 의존성 패키지 설치
pip install -r requirements.txt

# 2. 로컬 실행용 .env 설정
copy .env.example .env
# .env 파일에서 TELEGRAM_BOT_TOKEN 및 TELEGRAM_CHAT_ID를 설정

# 3. 로컬에서 수집 및 정제 전체 파이프라인 E2E 직접 실행
python src/main.py --mode all

# 4. 수집 완료 후 SQLite 데이터 확인
sqlite3 data/scrap_master.db "SELECT count(*) FROM job_postings;"
```

---

## 배포 방법 (GitHub Actions Serverless)

1. 이 리포지토리를 GitHub의 Private(비공개) 레포지토리로 생성합니다. (내 데이터 보호 목적)
2. 레포지토리 설정의 **Settings -> Secrets and variables -> Actions** 경로로 이동합니다.
3. 다음 두 개의 암호화 값을 추가합니다.
   - `TELEGRAM_BOT_TOKEN`: 텔레그램 봇의 API 토큰
   - `TELEGRAM_CHAT_ID`: 내 개인 알림 수신용 텔레그램 Chat ID
4. `.github/workflows/daily-scraper.yml` 파일이 지정된 주기(매일 아침 8시)에 가동되면, 스크랩 수행 후 결과 파일과 SQLite DB를 스스로 커밋하여 레포지토리를 지속적으로 최신화합니다.

---

## 환경변수

| 변수명 | 설명 | 어디서 발급 |
|--------|------|------------|
| `TELEGRAM_BOT_TOKEN` | 데일리 브리핑 전송용 텔레그램 봇 토큰 | 텔레그램 [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | 알림을 1:1로 직접 전달받을 나의 사용자 ID | 텔레그램 [@userinfobot](https://t.me/userinfobot) |

---

## [NEEDS CLARIFICATION]

- [ ] **모바일 브라우저를 위한 파일 접근성 추가 우회 여부**: 로컬 단일 HTML 방식 대신, 완벽히 프라이빗한 깃허브 페이지스(GitHub Pages) 보안 배포 방식을 지원할 수 있는 가벼운 클라이언트 측 패스워드 인증(HTML 내부에 비밀번호 해시를 숨겨두고 체크하는 가벼운 구현)을 Phase 2에서 포함할 것인지에 대한 여부
