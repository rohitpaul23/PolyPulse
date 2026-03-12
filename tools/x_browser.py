"""
tools/x_browser.py
──────────────────
Posts an X/Twitter thread using a saved Playwright browser session.
Requires running tools/x_login_once.py first to save your session.

Usage (standalone test):  python tools/x_browser.py
Prerequisite:             python tools/x_login_once.py  (run once)
Optional .env:            X_HEADLESS=false
"""

import os
import sys
import asyncio
from dotenv import load_dotenv

SESSION_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..', 'state', 'x_session.json')
)


async def _paste_text(page, text: str):
    """
    Write text to the browser clipboard then paste with Ctrl+V.
    More reliable than .type() for X's contenteditable compose box.
    """
    await page.evaluate(
        "async (text) => { await navigator.clipboard.writeText(text); }",
        text
    )
    await page.keyboard.press("Control+v")
    await asyncio.sleep(0.5)


async def _scroll_modal_to_bottom(page):
    """
    Find the modal's inner scrollable container and scroll it to the very bottom.
    X's compose modal uses an inner scrollable div that standard scroll methods often miss.
    """
    await page.evaluate("""
        () => {
            const btn = document.querySelector('[data-testid="tweetButton"]');
            if (!btn) return;
            let el = btn.parentElement;
            while (el && el !== document.body) {
                const s = window.getComputedStyle(el);
                if (s.overflowY === 'scroll' || s.overflowY === 'auto') {
                    el.scrollTop = el.scrollHeight + 500;
                    return;
                }
                el = el.parentElement;
            }
        }
    """)


async def post_x_thread_browser(tweets: list) -> bool:
    """
    Posts a Twitter/X thread using a pre-saved browser session.
    The saved session lets us skip login entirely (no bot detection risk).
    Returns True on success, False on failure.
    """
    # Default to headful / visible browser
    headless = os.environ.get("X_HEADLESS", "false").lower() == "true"

    if not tweets:
        print("  [X-Browser] No tweets to post.")
        return False

    if not os.path.exists(SESSION_PATH):
        print("  [X-Browser] No saved session found.")
        print("  [X-Browser] Run: python tools/x_login_once.py")
        return False

    try:
        from playwright.async_api import async_playwright

        # Use playwright-stealth if available
        try:
            from playwright_stealth import Stealth
            playwright_ctx = Stealth().use_async(async_playwright())
        except Exception:
            playwright_ctx = async_playwright()

        async with playwright_ctx as p:
            browser = await p.chromium.launch(
                headless=headless,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
            )

            # Load session + grant clipboard permissions at context level
            context = await browser.new_context(
                storage_state=SESSION_PATH,
                viewport={"width": 1280, "height": 900},
                permissions=["clipboard-read", "clipboard-write"],
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                locale="en-US",
                timezone_id="America/New_York",
            )
            page = await context.new_page()

            # ── Load X and verify session ────────────────────────────
            print("  [X-Browser] Loading X with saved session...")
            await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)

            if "/home" not in page.url:
                print(f"  [X-Browser] Session expired. URL: {page.url}")
                print("  [X-Browser] Re-run: python tools/x_login_once.py")
                await browser.close()
                return False

            print("  [X-Browser] Session valid — logged in!")

            # ── Open compose modal ───────────────────────────────────
            print("  [X-Browser] Opening compose box...")
            compose_btn = page.locator('[data-testid="SideNav_NewTweet_Button"]')
            await compose_btn.wait_for(state="visible", timeout=10000)
            await compose_btn.evaluate("el => el.click()")
            await asyncio.sleep(2)

            # ── Type each tweet in the thread ───────────────────────
            for i, tweet_text in enumerate(tweets):
                tweet_text = str(tweet_text).strip()
                print(f"  [X-Browser] Writing tweet {i+1}/{len(tweets)}...")

                if i == 0:
                    textbox = page.get_by_role("textbox", name="Post text").first
                    await textbox.wait_for(state="attached", timeout=10000)
                    await textbox.focus()
                    await asyncio.sleep(0.5)
                else:
                    textbox = page.locator(f'[data-testid="tweetTextarea_{i}"]')
                    try:
                        await textbox.wait_for(state="attached", timeout=8000)
                        await textbox.focus()
                        await asyncio.sleep(0.5)
                    except Exception:
                        textbox = page.get_by_role("textbox", name="Post text").last
                        await textbox.focus()
                        await asyncio.sleep(0.5)

                await _paste_text(page, tweet_text)
                await asyncio.sleep(0.8)

                await page.keyboard.press("Space")
                await page.keyboard.press("Backspace")
                await asyncio.sleep(0.3)

                # Debug screenshot
                os.makedirs("output", exist_ok=True)
                await page.screenshot(path=f"output/x_debug_tweet_{i+1}.png")

                # Add next tweet slot AFTER pasting
                if i < len(tweets) - 1:
                    initial_count = await page.get_by_role("textbox", name="Post text").count()
                    
                    try:
                        await textbox.focus()
                        await asyncio.sleep(0.2)
                        
                        found_add_btn = False
                        for _ in range(15):
                            await page.keyboard.press("Tab")
                            await asyncio.sleep(0.1)
                            active_testid = await page.evaluate("() => document.activeElement ? document.activeElement.getAttribute('data-testid') : null")
                            if active_testid == "addButton":
                                found_add_btn = True
                                break
                        
                        if found_add_btn:
                            await page.keyboard.press("Enter")
                        else:
                            for _ in range(15):
                                await page.keyboard.press("Tab")
                                await asyncio.sleep(0.1)
                                active_label = await page.evaluate("() => document.activeElement ? document.activeElement.getAttribute('aria-label') : null")
                                if active_label and "Add post" in active_label:
                                    await page.keyboard.press("Enter")
                                    break
                    except Exception as e:
                        print(f"  [X-Browser] Error navigating to add slot button: {e}")
                    
                    new_box_created = False
                    for _ in range(20):
                        current_count = await page.get_by_role("textbox", name="Post text").count()
                        if current_count > initial_count:
                            new_box_created = True
                            break
                        await asyncio.sleep(0.1)
                        
                    if not new_box_created:
                        print(f"  [X-Browser] WARNING: Tried to add slot {i+2} but textbox count didn't increase!")
                        print(f"  [X-Browser] Posting {i+1} tweets instead.")
                        break
                        
                    print(f"  [X-Browser] Added thread slot {i+2}")

            # ── Submit — same Tab approach as the + button ────────
            # addButton (+) is already working reliably.
            # "Post all" is exactly ONE Tab after addButton.
            # So: tab from last textbox → stop on addButton → one more Tab → Enter.
            print("  [X-Browser] Submitting thread...")
            await asyncio.sleep(1)

            try:
                await page.get_by_role("textbox", name="Post text").last.focus()
            except Exception:
                pass
            await asyncio.sleep(0.2)

            found_post = False
            for step in range(20):
                await page.keyboard.press("Tab")
                await asyncio.sleep(0.1)
                testid = await page.evaluate(
                    "() => document.activeElement?.getAttribute('data-testid')"
                )
                if testid == "addButton":
                    # One more Tab lands on "Post all"
                    print(f"  [X-Browser] addButton at step {step+1} — Tab once more for Post all...")
                    await page.keyboard.press("Tab")
                    await asyncio.sleep(0.15)
                    now_testid   = await page.evaluate("() => document.activeElement?.getAttribute('data-testid')")
                    now_disabled = await page.evaluate("() => document.activeElement?.hasAttribute('disabled')")
                    if now_testid == "tweetButton" and not now_disabled:
                        print("  [X-Browser] On Post all — pressing Enter...")
                        await page.keyboard.press("Enter")
                        found_post = True
                        break
                    else:
                        # Tab order shifted — keep scanning
                        print(f"  [X-Browser] After addButton landed on: {now_testid}, continuing...")

            if not found_post:
                # Fallback: scan up to 200 tabs directly for tweetButton
                print("  [X-Browser] Fallback: scanning 200 tabs for tweetButton...")
                try:
                    await page.get_by_role("textbox", name="Post text").last.focus()
                except Exception:
                    pass
                for step in range(200):
                    await page.keyboard.press("Tab")
                    await asyncio.sleep(0.08)
                    testid   = await page.evaluate("() => document.activeElement?.getAttribute('data-testid')")
                    disabled = await page.evaluate("() => document.activeElement?.hasAttribute('disabled')")
                    if testid == "tweetButton" and not disabled:
                        print(f"  [X-Browser] tweetButton at step {step+1} — pressing Enter...")
                        await page.keyboard.press("Enter")
                        found_post = True
                        break

            if not found_post:
                print("  [X-Browser] FATAL: Could not reach Post all button.")
                await browser.close()
                return False

            # WAIT FOR THE MODAL TO FULLY CLOSE - true confirmation
            try:
                await page.locator('[data-testid="modal"]').wait_for(state="hidden", timeout=30000)
                print("  [X-Browser] Modal closed. Thread posted successfully!")
            except Exception as e:
                print(f"  [X-Browser] WARNING: Modal did not close within timeout. Post status unclear.")
            

            await page.screenshot(path="output/x_debug_AFTER_post_all.png")
            print("  [X-Browser] Screenshot saved: output/x_debug_AFTER_post_all.png")
            print("  [X-Browser] Pausing 10s — inspect the browser window now...")
            await asyncio.sleep(10)


            await browser.close()
            return True

    except Exception as e:
        msg = str(e)
        if "timeout" in msg.lower():
            print(f"  [X-Browser] Timeout: {msg[:300]}")
        else:
            print(f"  [X-Browser] Error: {e}")
        return False


def post_x_thread_sync(tweets: list) -> bool:
    """Synchronous wrapper for use from publisher.py."""
    return asyncio.run(post_x_thread_browser(tweets))


# ── Standalone test ────────────────────────────────────────────
if __name__ == "__main__":
    load_dotenv()

    test_tweets = [
        "Test 1/4: AI is reshaping the world. From billion-dollar funding to Pentagon lawsuits. Thread below. #AI",
        "Test 2/4: Advanced Machine Intelligence raised $1.03B for world-model AI. Yann LeCun says this beats LLMs.",
        "Test 3/4: Anthropic sued the Pentagon. Nvidia unveiled NemoClaw. Oracle AI bets under scrutiny.",
        "Test 4/4: Follow for daily AI threads. Full newsletter every morning.",
    ]

    print("--- X BROWSER AUTOMATION TEST ---")
    print(f"Session  : {'EXISTS' if os.path.exists(SESSION_PATH) else 'MISSING'}")
    print(f"Headless : {os.environ.get('X_HEADLESS', 'true')}")
    print(f"Tweets   : {len(test_tweets)}")
    print()

    if not os.path.exists(SESSION_PATH):
        print("ERROR: Run  python tools/x_login_once.py  first.")
        sys.exit(1)

    success = post_x_thread_sync(test_tweets)
    print()
    print("[SUCCESS] Thread posted!" if success else "[FAILED] Check output/x_debug_tweet_*.png screenshots.")
