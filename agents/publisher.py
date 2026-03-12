import os
import sys
import json
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from state.schema import NewsAgentState

# ─────────────────────────────────────────────────────────────
#  Helper: Save to local Markdown + JSON files (always runs)
# ─────────────────────────────────────────────────────────────

def save_to_files(state: NewsAgentState) -> dict:
    """
    Always saves the newsletter output to the output/ directory.
    Returns a dict with the saved file paths.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir = os.path.join(project_root, "output")
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # 1. Full Markdown blog
    md_path = os.path.join(output_dir, f"newsletter_{today}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(state.full_blog_post or "")
    print(f"  [File] Saved Markdown newsletter: {md_path}")

    # 2. Social media snippets
    social_path = os.path.join(output_dir, f"social_{today}.json")
    social_data = {
        "date": today,
        "x_thread": state.x_thread_full,
        "linkedin_post": state.linkedin_post,
    }
    with open(social_path, "w", encoding="utf-8") as f:
        json.dump(social_data, f, indent=2, ensure_ascii=False)
    print(f"  [File] Saved social snippets: {social_path}")

    return {"newsletter_md": md_path, "social_json": social_path}


# ─────────────────────────────────────────────────────────────
#  Helper: Post X / Twitter Thread
# ─────────────────────────────────────────────────────────────

def post_x_thread(tweets: list) -> bool:
    """
    Posts an X/Twitter thread.
    Strategy:
      Tier 1 — Official Tweepy API (requires paid plan, may return 402)
      Tier 2 — Browser automation via Playwright (free, stealth mode)
    Returns True on first success, False if all tiers fail.
    """
    if not tweets:
        print("  [X] No tweets to post.")
        return False

    # ── Tier 1: Official API ──────────────────────────────────
    api_key       = os.environ.get("TWITTER_API_KEY")
    api_secret    = os.environ.get("TWITTER_API_SECRET")
    access_token  = os.environ.get("TWITTER_ACCESS_TOKEN")
    access_secret = os.environ.get("TWITTER_ACCESS_SECRET")

    if all([api_key, api_secret, access_token, access_secret]):
        try:
            import tweepy
            client = tweepy.Client(
                consumer_key=api_key,
                consumer_secret=api_secret,
                access_token=access_token,
                access_token_secret=access_secret,
            )
            print(f"  [X-API] Posting thread of {len(tweets)} tweets...")
            previous_tweet_id = None
            for i, tweet_text in enumerate(tweets, 1):
                tweet_text = str(tweet_text)[:280]
                if previous_tweet_id:
                    response = client.create_tweet(
                        text=tweet_text,
                        in_reply_to_tweet_id=previous_tweet_id
                    )
                else:
                    response = client.create_tweet(text=tweet_text)
                previous_tweet_id = response.data["id"]
                print(f"  [X-API] Posted tweet {i}/{len(tweets[:10])}")
            print("  [X-API] Thread posted successfully!")
            return True
        except Exception as e:
            if "402" in str(e):
                print("  [X-API] 402 Payment Required — API plan doesn't support posting.")
            else:
                print(f"  [X-API] Failed: {e}")
            print("  [X-API] Falling back to browser automation...")
    else:
        print("  [X-API] Credentials not configured, trying browser automation...")

    # ── Tier 2: Browser automation ────────────────────────────
    email    = os.environ.get("TWITTER_EMAIL")
    password = os.environ.get("TWITTER_PASSWORD")

    if not email or not password:
        print("  [X-Browser] Skipping: TWITTER_EMAIL and TWITTER_PASSWORD not set in .env")
        return False

    try:
        from tools.x_browser import post_x_thread_sync
        print(f"  [X-Browser] Posting thread of {len(tweets)} tweets via browser...")
        return post_x_thread_sync(tweets)
    except Exception as e:
        print(f"  [X-Browser] Failed: {e}")
        return False


# ─────────────────────────────────────────────────────────────
#  Helper: Post LinkedIn
# ─────────────────────────────────────────────────────────────

def post_linkedin(text: str) -> bool:
    """
    Posts a text update to LinkedIn using UGC Share API v2.
    Requires LINKEDIN_ACCESS_TOKEN in .env.
    Returns True on success, False on failure.
    """
    access_token = os.environ.get("LINKEDIN_ACCESS_TOKEN")

    if not access_token:
        print("  [LinkedIn] Skipping: LINKEDIN_ACCESS_TOKEN not configured.")
        return False

    try:
        import requests

        # Step 1: Get author URN from .env (set once by linkedin_auth.py)
        person_urn = os.environ.get("LINKEDIN_PERSON_URN", "")
        if not person_urn:
            print("  [LinkedIn] LINKEDIN_PERSON_URN not set. Run: python tools/linkedin_auth.py")
            return False

        # Step 2: Post the share
        payload = {
            "author": person_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            },
        }

        post_resp = requests.post(
            "https://api.linkedin.com/v2/ugcPosts",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "X-Restli-Protocol-Version": "2.0.0",
            },
            json=payload,
            timeout=10,
        )
        post_resp.raise_for_status()
        print(f"  [LinkedIn] Posted successfully!")
        return True

    except Exception as e:
        print(f"  [LinkedIn] Failed to post: {e}")
        return False


# ─────────────────────────────────────────────────────────────
#  Helper: Upload local images to Hashnode CDN
# ─────────────────────────────────────────────────────────────

def _upload_via_uguu(img_path: str, alt_text: str) -> str:
    """
    Upload image to uguu.se — free anonymous temporary file host.
    No account, no API key, no setup required.
    Files are hosted for 48 hours — perfect for daily news cover images
    since readers will see the post the same day it's published.
    Max file size: 128MB. Supports PNG, JPG, GIF, WEBP.
    """
    import requests

    try:
        with open(img_path, "rb") as f:
            resp = requests.post(
                "https://uguu.se/upload",
                files={"files[]": (os.path.basename(img_path), f)},
                timeout=30,
            )
        resp.raise_for_status()
        data = resp.json()

        # Response format: {"success": true, "files": [{"url": "...", "name": "..."}]}
        files = data.get("files", [])
        if files and files[0].get("url"):
            cdn_url = files[0]["url"]
            print(f"  [Uguu] ✅ Image uploaded → {cdn_url}")
            return f"![{alt_text}]({cdn_url})"
        else:
            print(f"  [Uguu] No URL in response: {data}")
            return ""
    except Exception as e:
        print(f"  [Uguu] Upload failed: {e}")
        return ""

def _upload_images_to_hashnode(markdown: str, api_key: str) -> str:
    """
    Scans markdown for local image paths, uploads each to Hashnode CDN,
    and replaces the local path with the returned CDN URL.
    Skips images that are already URLs or don't exist on disk.
    """
    import re
    import requests

    pattern = r'!\[([^\]]*)\]\(([^)]+)\)'

    def upload_and_replace(match):
        alt_text = match.group(1)
        img_path = match.group(2).replace("\\", "/").replace("\\\\", "/")

        # Skip already-remote images
        if img_path.startswith("http://") or img_path.startswith("https://"):
            return match.group(0)

        import os
        if not os.path.exists(img_path):
            print(f"  [Hashnode] Image not found: {img_path} — removing from post")
            return ""  # Remove broken local path rather than leaving it

        try:
            import base64
            ext = os.path.splitext(img_path)[1].lower().lstrip(".")
            mime_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                        "png": "image/png", "gif": "image/gif",
                        "webp": "image/webp"}
            mime = mime_map.get(ext, "image/png")

            with open(img_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("utf-8")

            # Hashnode GraphQL uploadImageByURL / use presigned S3 upload
            # Correct approach: upload via their uploadImage GraphQL mutation
            gql_upload = """
            mutation UploadImage($input: UploadImageInput!) {
              uploadImage(input: $input) {
                imageURL
              }
            }
            """
            variables = {
                "input": {
                    "imageData": f"data:{mime};base64,{img_b64}"
                }
            }
            resp = requests.post(
                "https://gql.hashnode.com/",
                headers={
                    "Authorization": api_key,
                    "Content-Type": "application/json",
                },
                json={"query": gql_upload, "variables": variables},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

            # Check GraphQL errors
            if "errors" in data:
                print(f"  [Hashnode] Upload GraphQL error: {data['errors']}")
                # Fallback: use Imgur (truly free, no auth needed for small images)
                return _upload_via_uguu(img_path, alt_text)

            cdn_url = (data.get("data", {}) or {}).get("uploadImage", {}).get("imageURL")
            if cdn_url:
                print(f"  [Hashnode] ✅ Image uploaded → {cdn_url}")
                return f"![{alt_text}]({cdn_url})"
            else:
                print(f"  [Hashnode] No URL in response: {data} — trying Imgur fallback")
                return _upload_via_uguu(img_path, alt_text)

        except Exception as e:
            print(f"  [Hashnode] Image upload failed ({img_path}): {e} — trying Imgur fallback")
            return _upload_via_uguu(img_path, alt_text)

    return re.sub(pattern, upload_and_replace, markdown)


# ─────────────────────────────────────────────────────────────
#  Helper: Publish to Hashnode
# ─────────────────────────────────────────────────────────────

def publish_hashnode(markdown: str, x_thread: list = None) -> str | None:
    """
    Publishes the blog post markdown to Hashnode via GraphQL API.
    Extracts the title from the first # heading in the markdown.
    Returns the live post URL on success, None on failure.

    Requires in .env:
        HASHNODE_API_KEY       — personal access token
        HASHNODE_PUBLICATION_ID — from your blog's settings URL
    """
    api_key        = os.environ.get("HASHNODE_API_KEY")
    publication_id = os.environ.get("HASHNODE_PUBLICATION_ID")

    if not api_key or not publication_id:
        print("  [Hashnode] Skipping: HASHNODE_API_KEY or HASHNODE_PUBLICATION_ID not set.")
        return None

    # ── Extract title from first # heading ───────────────────
    title = "PolyPulse Daily AI Briefing"
    subtitle = ""
    body_lines = []
    for i, line in enumerate(markdown.splitlines()):
        if line.startswith("# ") and not title != "PolyPulse Daily AI Briefing":
            title = line[2:].strip()
        elif line.startswith("# ") and title == "PolyPulse Daily AI Briefing":
            title = line[2:].strip()
        elif line.startswith("## The Executive Summary"):
            # grab next non-empty line as subtitle
            for j in range(i+1, min(i+4, len(markdown.splitlines()))):
                candidate = markdown.splitlines()[j].strip()
                if candidate and not candidate.startswith("#"):
                    subtitle = candidate[:150]
                    break
            body_lines.append(line)
        else:
            body_lines.append(line)

    # Remove the title line from body to avoid duplication
    body_md = "\n".join(
        l for l in markdown.splitlines() if not l.startswith("# " + title)
    )

    # Upload any local images to Hashnode CDN and replace paths with CDN URLs
    print("  [Hashnode] Checking for local images to upload...")
    body_md = _upload_images_to_hashnode(body_md, api_key)

    today = datetime.now().strftime("%B %d, %Y")

    # ── GraphQL mutation ──────────────────────────────────────
    # publishPost is the current Hashnode API v2 mutation
    query = """
    mutation PublishPost($input: PublishPostInput!) {
      publishPost(input: $input) {
        post {
          id
          title
          url
          slug
        }
      }
    }
    """

    variables = {
        "input": {
            "title": title,
            "subtitle": subtitle or f"Your daily AI briefing — {today}",
            "publicationId": publication_id,
            "contentMarkdown": body_md,
            "tags": [
                {"slug": "artificial-intelligence", "name": "Artificial Intelligence"},
                {"slug": "machine-learning",        "name": "Machine Learning"},
                {"slug": "technology",              "name": "Technology"},
                {"slug": "startups",                "name": "Startups"},
            ],
            "metaTags": {
                "title":       title,
                "description": subtitle or f"Top AI stories for {today}",
            },
            "publishedAt": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    }

    try:
        import requests
        response = requests.post(
            "https://gql.hashnode.com/",
            headers={
                "Authorization": api_key,
                "Content-Type": "application/json",
            },
            json={"query": query, "variables": variables},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        # Check for GraphQL errors
        if "errors" in data:
            print(f"  [Hashnode] GraphQL error: {data['errors']}")
            return None

        post_url = data["data"]["publishPost"]["post"]["url"]
        post_id  = data["data"]["publishPost"]["post"]["id"]
        print(f"  [Hashnode] ✅ Published successfully!")
        print(f"  [Hashnode] URL: {post_url}")
        return post_url

    except Exception as e:
        print(f"  [Hashnode] Failed to publish: {e}")
        return None




# ─────────────────────────────────────────────────────────────
#  Main Agent Function
# ─────────────────────────────────────────────────────────────

def run_publisher(state: NewsAgentState) -> NewsAgentState:
    """
    Takes the final NewsAgentState and publishes to configured platforms.
    Always saves to local files regardless of API configuration.
    """
    print("--- PUBLISHER AGENT RUNNING ---")

    if not state.full_blog_post:
        print("No blog post found in state. Skipping publisher.")
        state.current_stage = "publisher"
        return state

    # 1. Always save to files
    print("\n[Step 1] Saving newsletter to local files...")
    save_to_files(state)


    to_be_published = True
    if to_be_published:
        # 2. Publish to Hashnode — get live URL for X thread final tweet
        print("\n[Step 2] Publishing to Hashnode...")
        hashnode_url = publish_hashnode(state.full_blog_post, state.x_thread_full)

        # 3. Inject Hashnode URL into the final tweet if we got one
        tweets = list(state.x_thread_full or [])
        if hashnode_url and tweets:
            last = tweets[-1]
            # Only inject if URL not already present
            if "http" not in last:
                tweets[-1] = last.rstrip() + f"\n\n🔗 {hashnode_url}"
                print(f"  [Publisher] Injected Hashnode URL into final tweet.")
    else:
        tweets = list(state.x_thread_full or [])

    # 4. Post X thread
    to_be_posted_X = False
    if to_be_posted_X:  
        print("\n[Step 4] Posting to X / Twitter...")
        x_success = post_x_thread(tweets)
    else:
        x_success = False

    # 5. Post LinkedIn
    print("\n[Step 5] Posting to LinkedIn...")
    print("  [LinkedIn] Skipped by user request.")
    li_success = False

    # Summary
    print("\n--- PUBLISHER SUMMARY ---")
    print(f"  Files saved : Yes")
    print(f"  X / Twitter : {'Posted' if x_success else 'Skipped/Failed'}")

    state.current_stage = "publisher"
    return state


# ─────────────────────────────────────────────────────────────
#  Test entrypoint
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    load_dotenv()

    test_state_path = os.path.join(
        os.path.dirname(__file__), '..', 'test', 'writer_state_output.json'
    )

    if not os.path.exists(test_state_path):
        print(f"Error: Could not find mock data at {test_state_path}")
        sys.exit(1)

    print(f"Loading writer state from: {test_state_path}")
    with open(test_state_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    state = NewsAgentState(
        full_blog_post=data.get("full_blog_post", ""),
        x_thread_full=data.get("x_thread_full", []),
        linkedin_post=data.get("linkedin_post", ""),
        current_stage=data.get("current_stage", "writer"),
    )

    print(f"  Blog post    : {len(state.full_blog_post)} chars")
    print(f"  X tweets     : {len(state.x_thread_full)}")
    print(f"  LinkedIn     : {len(state.linkedin_post)} chars")

    run_publisher(state)
