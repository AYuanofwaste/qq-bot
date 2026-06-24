import logging, os, json, re
from pathlib import Path
import requests

COOKIES_FILE = Path("D:/opencode/qq-bot/bilibili_cookies.txt")
cookies = {}
with open(COOKIES_FILE, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            cookies[parts[5].strip()] = parts[6].strip()

headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://live.bilibili.com/"}

# Try fetching the live page and extracting initial state
url = "https://live.bilibili.com/"
resp = requests.get(url, headers=headers, cookies=cookies, timeout=15)
print(f"GET {url}")
print(f"Status: {resp.status_code}")
# Look for initial state JSON
matches = re.findall(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});', resp.text, re.DOTALL)
if matches:
    data = json.loads(matches[0])
    print("Found __INITIAL_STATE__")
    print(list(data.keys())[:20])
else:
    print("No __INITIAL_STATE__ found")
    # Try looking for the following live users API URL in the page
    apis = re.findall(r'api[^"\']*', resp.text)
    for api in apis[:20]:
        print(f"  Found API ref: {api}")
