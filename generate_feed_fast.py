import requests
import re
from bs4 import BeautifulSoup
from datetime import datetime
from email.utils import format_datetime
import json
import hashlib
import os

# --- User Config ---
KEYWORDS = ["100%", "100 %", "all shares", "fully acquire", "buyout",
            "takeover", "converted", "merger agreement"]
HASH_FILE = "seen_item4.json"
FEED_FILE = "feed.xml"

# --- Load previous hashes ---
if os.path.exists(HASH_FILE):
    with open(HASH_FILE, "r", encoding="utf-8") as f:
        seen_hashes = json.load(f)
else:
    seen_hashes = {}

# --- Helper Functions ---
def hash_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def extract_item_4_from_xml(xml):
    match = re.search(r'<item[_\s]*4.*?>(.*?)</item[_\s]*4>', xml, re.I | re.S)
    if match:
        return match.group(1).strip()
    match2 = re.search(r'<TEXT>(.*?)</TEXT>', xml, re.I | re.S)
    if match2:
        return match2.group(1).strip()
    return None

def highlight_keywords(text):
    for kw in KEYWORDS:
        text = re.sub(kw, lambda m: f"<strong>{m.group(0)}</strong>", text, flags=re.I)
    return text

def highlight_company(text, company):
    return re.sub(re.escape(company), f"<strong>{company}</strong>", text, flags=re.I)

# --- Known filing for test ---
known_filing = {
    "company": "Example Corp",
    "form_type": "SC 13D",
    "date_filed": "2025-12-11",
    "url": "https://www.sec.gov/Archives/edgar/data/1040130/000121390025120354/xslSCHEDULE_13D_X01/primary_doc.xml"
}

# --- Fetch filing ---
items = []

try:
    r = requests.get(known_filing["url"], headers={"User-Agent": "JellysList-FastAlert-Test"})
    xml_text = r.text
    item4 = extract_item_4_from_xml(xml_text)

    if item4 and any(k.lower() in item4.lower() for k in KEYWORDS):
        highlighted = highlight_keywords(item4)
        highlighted = highlight_company(highlighted, known_filing["company"])

        item_hash = hash_text(highlighted)
        if seen_hashes.get(known_filing["url"]) != item_hash:
            seen_hashes[known_filing["url"]] = item_hash

            items.append({
                "title": f"[NEW] ⚡ {known_filing['company']} ({known_filing['form_type']})",
                "link": known_filing["url"],
                "content": highlighted,
                "date": datetime.strptime(known_filing["date_filed"], "%Y-%m-%d")
            })
except Exception as e:
    print(f"[WARN] Known filing skipped: {e}")

# --- Generate RSS feed ---
with open(FEED_FILE, "w", encoding="utf-8") as f:
    f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    f.write('<rss version="2.0"><channel>\n')
    f.write('<title>SEC Schedule 13D Item 4 (Fast Alert)</title>\n')
    f.write('<link>https://www.sec.gov</link>\n')
    f.write('<description>Item 4 from SC 13D and 13D/A filings containing buyout-related keywords</description>\n')

    for i in sorted(items, key=lambda x: x["date"], reverse=True):
        f.write("<item>\n")
        f.write(f"<title>{i['title']}</title>\n")
        f.write(f"<link>{i['link']}</link>\n")
        f.write(f"<pubDate>{format_datetime(i['date'])}</pubDate>\n")
        f.write(f"<description><![CDATA[{i['content']}]]></description>\n")
        f.write("</item>\n")

    f.write("</channel></rss>")

# --- Save hash record ---
with open(HASH_FILE, "w", encoding="utf-8") as f:
    json.dump(seen_hashes, f, indent=2)

print(f"Test feed generated in {FEED_FILE} with {len(items)} item(s).")
