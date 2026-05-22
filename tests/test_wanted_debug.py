import unittest
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import traceback

class TestWantedDebug(unittest.TestCase):
    def test_wanted_page_structure(self):
        """원티드 클라우드프론트 차단 우회 점검"""
        print("\n=== START WANTED STEALTH BYPASS DEBUGGING ===")
        with sync_playwright() as p:
            # navigator.webdriver 흔적 제거를 위한 크롬 옵션 설정
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox"
                ]
            )

            # 컨텍스트에 가짜 브라우저 메타 정보 완벽 마스킹
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800},
                locale="ko-KR",
                timezone_id="Asia/Seoul"
            )

            page = context.new_page()

            # navigator.webdriver 변수를 완전 제거하는 페이지 인라인 자바스크립트 주입
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)

            try:
                url = "https://www.wanted.co.kr/search?query=회계"
                page.goto(url, timeout=30000)
                page.wait_for_timeout(4000) # 충분한 동적 로딩 대기

                # HTML 전체 취득
                content = page.content()
                soup = BeautifulSoup(content, "html.parser")

                # a 링크 탐색
                wd_links = [a.get("href") for a in soup.select("a") if a.get("href") and "/wd/" in a.get("href")]
                print(f"Bypass Successful! Found {len(wd_links)} wd links.")
                if len(wd_links) > 0:
                    print(f"Sample link: {wd_links[0]}")
                else:
                    # 403 오류 여부 검사
                    title_el = soup.select_one("title")
                    title_text = title_el.text.strip() if title_el else "No Title"
                    print(f"Title: {title_text}")
                    if "satisfied" in title_text.lower():
                        print("Bypass Failed: Still Blocked by CloudFront.")
                    else:
                        print("Not blocked, but no links found. Printing content preview:")
                        print(content[:500])

            except Exception as e:
                print(f"DEBUGGING ERROR: {e}")
                traceback.print_exc()
            finally:
                browser.close()

if __name__ == '__main__':
    unittest.main()
