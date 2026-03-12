"""
tools/linkedin_auth.py
─────────────────────
One-time helper to get a LinkedIn OAuth 2.0 access token.

Usage:
    python tools/linkedin_auth.py

Steps:
1. Opens your browser to LinkedIn's OAuth consent page
2. You approve the permissions
3. LinkedIn redirects to http://localhost:8080/callback
4. This script captures the code and exchanges it for an access token
5. Prints the token and saves it to .env automatically
"""

import os
import sys
import webbrowser
import urllib.parse
import urllib.request
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv, set_key

load_dotenv()

CLIENT_ID     = os.environ.get("LINKEDIN_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("LINKEDIN_CLIENT_SECRET", "")
REDIRECT_URI  = "http://localhost:8080/callback"
SCOPES        = "w_member_social"
ENV_PATH      = os.path.join(os.path.dirname(__file__), '..', '.env')

# ── Step 1: Build authorization URL ──────────────────────────

def build_auth_url() -> str:
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": "ai_news_agent",
    }
    return "https://www.linkedin.com/oauth/v2/authorization?" + urllib.parse.urlencode(params)


# ── Step 2: Local server to capture the callback ─────────────

auth_code = None
auth_error = None

class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code, auth_error
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
                <html><body style="font-family:sans-serif;text-align:center;padding:60px">
                <h2 style="color:green">Authorization successful!</h2>
                <p>You can close this tab and return to the terminal.</p>
                </body></html>
            """)
        else:
            error = params.get("error", ["unknown_error"])[0]
            desc  = params.get("error_description", ["No description"])[0]
            auth_error = f"{error}: {desc}"
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(f"<html><body><h2>Error: {auth_error}</h2></body></html>".encode())

    def log_message(self, format, *args):
        pass


def wait_for_callback() -> str:
    server = HTTPServer(("localhost", 8080), CallbackHandler)
    server.handle_request()  # Handle exactly one request then stop
    return auth_code


# ── Step 3: Exchange code for access token ───────────────────

def exchange_code_for_token(code: str) -> str:
    token_url = "https://www.linkedin.com/oauth/v2/accessToken"
    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }).encode()

    req = urllib.request.Request(
        token_url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    with urllib.request.urlopen(req) as resp:
        result = json.load(resp)

    return result.get("access_token", "")


# ── Main ─────────────────────────────────────────────────────

if __name__ == "__main__":
    if not CLIENT_ID or not CLIENT_SECRET:
        print("Error: LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET must be set in .env")
        sys.exit(1)

    auth_url = build_auth_url()
    print("\nOpening your browser to LinkedIn's authorization page...")
    print(f"If it doesn't open automatically, visit:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    print("Waiting for LinkedIn to redirect back to localhost:8080...")
    code = wait_for_callback()

    if not code:
        if auth_error:
            print(f"\nLinkedIn returned an error: {auth_error}")
        print("\nCommon causes:")
        print("  1. The redirect URL 'http://localhost:8080/callback' is not added in LinkedIn Dev Portal Auth tab")
        print("  2. The 'Share on LinkedIn' product was not approved yet")
        print("  3. You declined the LinkedIn consent page")
        sys.exit(1)

    print("Authorization code received! Exchanging for access token...")
    token = exchange_code_for_token(code)

    if not token:
        print("Error: Failed to get access token.")
        sys.exit(1)

    # Save access token to .env automatically
    env_file = os.path.normpath(ENV_PATH)
    set_key(env_file, "LINKEDIN_ACCESS_TOKEN", token)

    # Also fetch and save the person URN using the introspect endpoint
    # introspectToken requires HTTP Basic Auth (client_id:client_secret)
    try:
        import base64
        credentials = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
        intro_req = urllib.request.Request(
            "https://api.linkedin.com/v2/introspectToken",
            data=f"token={token}".encode(),
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        with urllib.request.urlopen(intro_req, timeout=10) as resp:
            intro_data = json.load(resp)
        person_urn = intro_data.get("authorizedUser", "")
        if person_urn:
            set_key(env_file, "LINKEDIN_PERSON_URN", person_urn)
            print(f"Person URN saved to .env: {person_urn}")
        else:
            print(f"Could not get person URN automatically.")
            print(f"Please add LINKEDIN_PERSON_URN=urn:li:person:YOUR_ID to .env manually.")
    except Exception as e:
        print(f"Note: Could not fetch person URN ({e}). Add LINKEDIN_PERSON_URN to .env manually.")

    print(f"\nSuccess! Access token saved to .env")
    print(f"Token (valid for 2 months): {token[:40]}...")
    print("\nYou can now run the Publisher Agent to post to LinkedIn.")
