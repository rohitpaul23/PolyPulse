import asyncio
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import aiohttp

async def fetch_html_playwright(url: str) -> str:
    """Fetch HTML content using Playwright for JS-heavy sites."""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, timeout=30000)
            await page.wait_for_load_state('networkidle', timeout=10000)
            content = await page.content()
            await browser.close()
            return content
    except Exception as e:
        print(f"Playwright fetch failed for {url}: {e}")
        return ""

async def fetch_html_aiohttp(url: str) -> str:
    """Fetch HTML fast using aiohttp."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as response:
                if response.status == 200:
                    return await response.text()
                return ""
    except Exception as e:
        print(f"aiohttp fetch failed for {url}: {e}")
        return ""

async def scrape_article_text(url: str) -> str:
    """Scrape article text from URL, trying aiohttp first, then Playwright."""
    html = await fetch_html_aiohttp(url)
    if not html or len(html) < 500: # if very small or failed, try JS
        html = await fetch_html_playwright(url)
    
    if not html:
        return ""
        
    soup = BeautifulSoup(html, 'html.parser')
    
    # Remove script and style elements
    for script in soup(["script", "style", "nav", "footer", "header", "aside"]):
        script.extract()
        
    # Get text
    text = soup.get_text(separator=' ', strip=True)
    return text


def scrape_og_image(url: str) -> str | None:
    """
    Synchronously scrape the og:image meta tag from a URL.
    Returns the image URL string, or None if not found / request fails.
    """
    import urllib.request
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # Try og:image first
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            return og["content"]
        
        # Try twitter:image as secondary fallback
        tw = soup.find("meta", attrs={"name": "twitter:image"})
        if tw and tw.get("content"):
            return tw["content"]
        
        return None
    except Exception as e:
        print(f"  [Warning] og:image scrape failed for {url}: {e}")
        return None
