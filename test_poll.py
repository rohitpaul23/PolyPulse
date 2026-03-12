import urllib.request
import json

urls = [
    'https://image.pollinations.ai/prompt/robot?nologo=true',
    'https://image.pollinations.ai/prompt/robot?model=flux&nologo=true',
    'https://image.pollinations.ai/prompt/robot?model=turbo&nologo=true'
]

for url in urls:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        response = urllib.request.urlopen(req)
        print(f"SUCCESS ({response.getcode()}): {url}")
    except Exception as e:
        print(f"FAILED: {url} - {e}")
