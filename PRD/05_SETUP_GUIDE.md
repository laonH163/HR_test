# GameFinanceScraper -- 사용자 가이드 및 최초 연동 단계

> 이 문서는 개발이 완료된 수집 파이프라인을 내 개인 환경에 셋업하고 매일 아침 자동으로 알림을 받기 위해 사용자가 직접 수행해야 하는 실질적인 행동 매뉴얼입니다.

---

## [Step 1] 텔레그램 봇 토큰 및 개인 Chat ID 발급받기 (무료)

텔레그램 알림을 수신하기 위해 나만의 봇과 대화방 ID가 필요합니다.

1. **봇 생성 및 토큰 확보**:
   - 텔레그램 앱에서 **[@BotFather](https://t.me/BotFather)**를 검색하여 대화를 시작합니다.
   - `/newbot` 명령어를 입력합니다.
   - 안내에 따라 봇의 이름(Name)과 유저네임(Username, 반드시 `_bot`으로 끝남)을 설정합니다.
   - 생성 완료 후 제공되는 **HTTP API Token**(`TELEGRAM_BOT_TOKEN`)을 복사해 메모장에 안전하게 보관합니다.
   - 생성한 봇 링크를 눌러 들어가 **대화방에서 '시작(Start)' 버튼을 반드시 누릅니다.** (이 단계가 누락되면 봇이 선제 메시지를 보내지 못합니다).

2. **내 Chat ID 확인**:
   - 텔레그램 앱에서 **[@userinfobot](https://t.me/userinfobot)**을 검색하여 대화를 시작합니다.
   - 시작 버튼을 누르면 즉시 나의 고유 **Id**(`TELEGRAM_CHAT_ID`, 예: `123456789`) 수치를 알려줍니다. 이 숫자를 보관합니다.

---

## [Step 2] 로컬에서 수동 가동 및 텔레그램 연동 최종 테스트

깃허브 Actions에 전면 배포하기 전, 내 PC에서 올바르게 알림이 수신되는지 확인하는 단계입니다.

1. 프로젝트 루트 폴더에 `.env` 파일을 하나 새로 만들고 발급받은 값을 기입합니다:
   ```env
   TELEGRAM_BOT_TOKEN="내_봇_토큰_값"
   TELEGRAM_CHAT_ID="내_챗_아이디_숫자"
   ```
2. 터미널(PowerShell 또는 Bash)에서 아래 명령어를 실행하여 테스트 알림 전송을 E2E 가동해 봅니다:
   ```bash
   # PYTHONPATH 지정 가동
   PYTHONPATH=. python src/main.py --mode all
   ```
3. 스마트폰 텔레그램으로 "신규 등록 공고 2건" 요약 브리핑 카드가 한글로 이쁘게 정상 도착하는지 육안 확인합니다.

---

## [Step 3] GitHub 비공개(Private) 저장소 개설 및 Secrets 등록

내 보안 API 토큰을 소스코드 유출 없이 완전히 격리하면서 매일 아침 자동 구동을 실현하기 위한 연동 단계입니다.

1. **비공개 레포지토리 개설**:
   - 내 [GitHub](https://github.com)에 로그인 후, **새로운 리포지토리(New Repository)**를 생성합니다.
   - 반드시 **Private (비공개)** 옵션을 선택합니다. (DB 데이터 보호 및 개인정보 보호 목적)

2. **Actions Secrets 등록**:
   - 개설된 깃허브 저장소 페이지의 상단 메뉴 중 **Settings** -> 좌측 메뉴의 **Secrets and variables** -> **Actions**를 클릭합니다.
   - 우측 상단의 **New repository secret** 버튼을 누르고 아래 두 개의 값을 개별 추가합니다:
     - Name: `TELEGRAM_BOT_TOKEN` / Value: 발급받은 봇 토큰 기입
     - Name: `TELEGRAM_CHAT_ID` / Value: 발급받은 개인 ID 숫자 기입

---

## [Step 4] 로컬 소스코드 GitHub로 Push (배포 개시)

내 컴퓨터에 빌드된 전체 패키지를 GitHub 저장소에 밀어 넣어 매일 아침 크론 스케줄 가동을 개시하는 단계입니다.

1. 터미널을 열고 프로젝트 루트 폴더에서 아래 명령어들을 차례로 실행합니다:
   ```bash
   # 1. 깃 로컬 저장소 초기화
   git init

   # 2. 커밋 제외 대상 설정 확인 (.env 파일 등이 깃에 올라가지 않도록 방지)
   # .gitignore 파일이 없거나 .env가 안 들어가 있다면 추가:
   echo ".env" >> .gitignore
   echo "data/test_*" >> .gitignore
   echo "__pycache__/" >> .gitignore

   # 3. 소스코드 전체 스테이징 및 첫 커밋
   git add .
   git commit -m "feat: init game finance job scraper pipeline"

   # 4. 내 원격 깃허브 주소 연동 (나의 레포 주소로 치환)
   git remote add origin https://github.com/내계정명/레포지토리명.git
   git branch -M main

   # 5. 최종 업로드 Push
   git push -u origin main
   ```

2. 이제 모든 배포 셋업이 완료되었습니다. 매일 한국 시간 오전 8시에 GitHub Actions 서버가 스스로 가상 크롬 브라우저를 띄워 수집 및 가공 분석을 완수하고, `index.html` 대시보드 리포트를 자동으로 갱신하여 깃허브에 백업 보관함과 동시에 내 폰으로 아름답게 텔레그램 데일리 소식을 발송해 줍니다.
