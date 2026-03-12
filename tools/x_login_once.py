"""
tools/x_login_once.py
---------------------
Saves your X session cookies so the publisher can post
tweets automatically without logging in.

Run once (or when cookies expire):
    python tools/x_login_once.py

Steps:
1. Open https://x.com in Chrome and make sure you're logged in
2. Press F12 -> Application -> Cookies -> https://x.com
3. This script will guide you to copy auth_token and ct0
"""

import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

SESSION_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..', 'state', 'x_session.json')
)


def save_session(auth_token: str, ct0: str):
    """Save auth cookies in Playwright's storage_state format."""
    Path(os.path.dirname(SESSION_PATH)).mkdir(parents=True, exist_ok=True)
    session = {
        "cookies": [
            {
                "name": "auth_token",
                "value": auth_token,
                "domain": ".x.com",
                "path": "/",
                "secure": True,
                "httpOnly": True,
                "sameSite": "None",
            },
            {
                "name": "ct0",
                "value": ct0,
                "domain": ".x.com",
                "path": "/",
                "secure": True,
                "httpOnly": False,
                "sameSite": "Lax",
            },
        ],
        "origins": []
    }
    with open(SESSION_PATH, "w") as f:
        json.dump(session, f, indent=2)
    print(f"\nSession saved: {SESSION_PATH}")


if __name__ == "__main__":
    print("=== X Session Cookie Extractor ===\n")
    print("Step 1: Open Chrome and go to https://x.com (make sure you are logged in)")
    print("Step 2: Press F12 to open DevTools")
    print("Step 3: Click 'Application' tab -> 'Cookies' -> 'https://x.com'")
    print("Step 4: Find 'auth_token' row -> double-click its Value -> copy it")
    print("Step 5: Find 'ct0' row -> double-click its Value -> copy it")
    print()

    auth_token = input("Paste auth_token value here: ").strip()
    if not auth_token:
        print("auth_token is required.")
        sys.exit(1)

    ct0 = input("Paste ct0 value here: ").strip()
    if not ct0:
        print("ct0 is required.")
        sys.exit(1)

    save_session(auth_token, ct0)
    print("Done! Run 'python tools/x_browser.py' to test posting.")
