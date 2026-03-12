"""
tools/x_browser.py
──────────────────
Posts an X/Twitter thread using a saved Playwright browser session.
Requires running tools/x_login_once.py first to save your session.

Usage (standalone test):  python tools/x_browser.py
Prerequisite:             python tools/x_login_once.py  (run once)
Optional .env:            X_HEADLESS=false

Architecture note (from DOM inspection):
  - addButton and tweetButton ("Post all") are OUTSIDE the modal DOM
  - They sit in a fixed toolbar, always visible, never need scrolling
  - Always exactly 1 of each — direct JS .click() is the most reliable approach
"""

import os
import sys
import asyncio
import re
from dotenv import load_dotenv

SESSION_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..', 'state', 'x_session.json')
)

# X counts all URLs as 23 chars (t.co shortening) regardless of actual length.
# We use this to accurately measure tweet length before posting.
URL_TWITTER_LENGTH = 23


def _enforce_tweet_limit(tweet: str, limit: int = 280) -> str:
    """
    Measures tweet length the way X does:
      - Each URL counts as URL_TWITTER_LENGTH (23) chars regardless of actual length
      - Everything else counts as-is
    Truncates the summary text if over limit, preserving URLs and hashtags.
    """
    urls = re.findall(r'https?://\S+', tweet)
    measured = re.sub(r'https?://\S+', 'x' * URL_TWITTER_LENGTH, tweet)

    if len(measured) <= limit:
        return tweet

    # Over limit — truncate the non-URL, non-hashtag body text
    overage = len(measured) - limit
    # Remove URLs temporarily to find the body
    body = re.sub(r'https?://\S+', '', tweet)
    # Find hashtag section (everything from first # near end)
    hashtag_match = re.search(r'\n#\S+', body)
    if hashtag_match:
        pre_tags  = body[:hashtag_match.start()]
        tags_part = body[hashtag_match.start():]
    else:
        pre_tags  = body
        tags_part = ""

    # Truncate the body text
    truncated = pre_tags[:max(0, len(pre_tags) - overage - 3)].rstrip() + "..."
    result = truncated + tags_part
    # Re-inject URLs
    for url in urls:
        result += f"\n{url}"
    return result.strip()


async def _dispatch_click(page, testid: str) -> bool:
    """
    Clicks a button using Playwright's dispatchEvent('click').
    Unlike .click() which does coordinate hit-testing (and can misfire
    onto nearby elements), dispatchEvent fires directly on the element
    regardless of what's visually overlapping it.
    Returns True if the element was found.
    """
    el = page.locator(f'[data-testid="{testid}"]')
    try:
        await el.wait_for(state="visible", timeout=5000)
        await el.dispatch_event("click")
        return True
    except Exception as e:
        print(f"  [X-Browser] dispatchEvent failed for {testid}: {e}")
        return False


async def _paste_text(page, text: str):
    """
    Write text to clipboard then paste. Reliable for X's contenteditable boxes.
    After pasting, Escape dismisses any autocomplete dropdown (e.g. hashtag suggestions),
    then Space+Backspace commits the last word cleanly.
    """
    await page.evaluate(
        "async (text) => { await navigator.clipboard.writeText(text); }",
        text
    )
    await page.keyboard.press("Control+v")
    await asyncio.sleep(0.4)
    await page.keyboard.press("Escape")   # dismiss hashtag/mention autocomplete
    await asyncio.sleep(0.1)
    await page.keyboard.press("Space")    # commit last word
    await page.keyboard.press("Backspace")  # remove the space
    await asyncio.sleep(0.2)


async def post_x_thread_browser(tweets: list) -> bool:
    """
    Posts a Twitter/X thread using a pre-saved browser session.
    Returns True on success, False on failure.
    """
    headless = os.environ.get("X_HEADLESS", "false").lower() == "true"

    if not tweets:
        print("  [X-Browser] No tweets to post.")
        return False

    if not os.path.exists(SESSION_PATH):
        print("  [X-Browser] No saved session found.")
        print("  [X-Browser] Run: python tools/x_login_once.py")
        return False

    # Enforce 280-char limit on all tweets before opening browser
    tweets = [_enforce_tweet_limit(str(t).strip()) for t in tweets]

    try:
        from playwright.async_api import async_playwright

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

            # ── Type each tweet ──────────────────────────────────────
            for i, tweet_text in enumerate(tweets):
                print(f"  [X-Browser] Writing tweet {i+1}/{len(tweets)}...")

                # Target the correct textbox
                if i == 0:
                    textbox = page.get_by_role("textbox", name="Post text").first
                    await textbox.wait_for(state="attached", timeout=10000)
                else:
                    textbox = page.locator(f'[data-testid="tweetTextarea_{i}"]')
                    try:
                        await textbox.wait_for(state="attached", timeout=8000)
                    except Exception:
                        textbox = page.get_by_role("textbox", name="Post text").last

                await textbox.focus()
                await asyncio.sleep(0.4)
                await _paste_text(page, tweet_text)

                # Debug screenshot
                os.makedirs("output", exist_ok=True)
                await page.screenshot(path=f"output/x_debug_tweet_{i+1}.png")

                # Add next slot
                if i < len(tweets) - 1:
                    initial_count = await page.get_by_role("textbox", name="Post text").count()

                    # Debug: screenshot + DOM state before trying addButton
                    await page.screenshot(path=f"output/x_debug_before_add_{i+1}.png")
                    all_testids = await page.evaluate("""
                        () => Array.from(document.querySelectorAll('[data-testid]'))
                             .map(e => e.getAttribute('data-testid'))
                    """)
                    add_visible = 'addButton' in all_testids
                    tweet_visible = 'tweetButton' in all_testids
                    print(f"  [X-Browser] DOM check — addButton: {add_visible}, tweetButton: {tweet_visible}")
                    print(f"  [X-Browser] All testids: {[t for t in all_testids if t]}")

                    # Wait for addButton to be present and enabled in DOM
                    add_btn = page.locator('[data-testid="addButton"]')
                    try:
                        await add_btn.wait_for(state="visible", timeout=5000)
                    except Exception:
                        print(f"  [X-Browser] addButton not visible at tweet {i+1} — check output/x_debug_before_add_{i+1}.png")
                        break

                    await asyncio.sleep(0.3)  # let React finish processing paste

                    # dispatchEvent fires directly on the element — no hit testing,
                    # no risk of landing on the nearby X/close button
                    print(f"  [X-Browser] Clicking addButton (dispatchEvent)...")
                    await add_btn.dispatch_event("click")

                    # Wait for new textbox to confirm click worked
                    new_box_created = False
                    for _ in range(30):  # up to 3 seconds
                        current_count = await page.get_by_role("textbox", name="Post text").count()
                        if current_count > initial_count:
                            new_box_created = True
                            break
                        await asyncio.sleep(0.1)

                    if not new_box_created:
                        print(f"  [X-Browser] WARNING: addButton click did not create new textbox — posting {i+1} tweets instead.")
                        break

                    print(f"  [X-Browser] Added thread slot {i+2}")
                    await asyncio.sleep(0.3)

            # ── Submit — direct JS click on tweetButton ──────────────
            # tweetButton is outside the modal, always in viewport, never needs scrolling.
            print("  [X-Browser] Submitting thread...")
            await asyncio.sleep(0.5)

            # dispatchEvent on tweetButton — no coordinates, no hit testing
            post_btn = page.locator('[data-testid="tweetButton"]')
            try:
                await post_btn.wait_for(state="visible", timeout=5000)
            except Exception:
                print("  [X-Browser] FATAL: tweetButton not visible.")
                await browser.close()
                return False

            print("  [X-Browser] Clicking Post all (dispatchEvent)...")
            await post_btn.dispatch_event("click")

            print("  [X-Browser] Clicked Post all — waiting for modal to close...")

            # Modal closing = all tweets confirmed posted
            try:
                await page.locator('[data-testid="modal"]').wait_for(
                    state="hidden", timeout=30000
                )
                print("  [X-Browser] ✅ Modal closed — thread posted successfully!")
            except Exception:
                await asyncio.sleep(4)
                print("  [X-Browser] ⚠️  Modal timeout — check your profile to confirm.")

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
        "Test 1/4: AI is reshaping the world. From billion-dollar funding to Pentagon lawsuits. Thread below. #AINews",
        "Test 2/4: Advanced Machine Intelligence raised $1.03B for world-model AI. Yann LeCun says this beats LLMs. #MachineLearning",
        "Test 3/4: Anthropic sued the Pentagon. Nvidia unveiled NemoClaw. Oracle AI bets under scrutiny. #TechPolicy",
        "Test 4/4: Follow @PolyPulse for daily AI threads. #AI #Newsletter",
    ]

    print("--- X BROWSER AUTOMATION TEST ---")
    print(f"Session  : {'EXISTS' if os.path.exists(SESSION_PATH) else 'MISSING'}")
    print(f"Headless : {os.environ.get('X_HEADLESS', 'false')}")
    print(f"Tweets   : {len(test_tweets)}")
    print()

    if not os.path.exists(SESSION_PATH):
        print("ERROR: Run  python tools/x_login_once.py  first.")
        sys.exit(1)

    success = post_x_thread_sync(test_tweets)
    print()
    print("[SUCCESS] Thread posted!" if success else "[FAILED] Check output/x_debug_tweet_*.png screenshots.")