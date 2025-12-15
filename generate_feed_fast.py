import feedparser
import requests
import re
import time
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from email.utils import format_datetime
import json
import hashlib
import os

# --- User Config ---
HEADERS = {
    "User-Agent": "JellysList-FastAlert/1.5 (contact: jellysstocks@gmail.com)"
}

FEED_FILE = "feed.xml"
HASH_FILE = "seen_item4.json"
MAX_FEED_ITEMS = 50
REQUEST_DELAY = 1  # SEC fair-access delay in seconds

FEEDS = [
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=SC%2013D&owner=include&count=100&output=atom",
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=SC%2013D/A&owner=include&count=100&output=atom"
]

KEYWORDS = [
    "100%", "100 %", "all shares", "fully acquire", "buyout",
    "takeover", "converted", "merger agreement"
]

# --- Load previous hashes ---
if os.path.exists(HASH_FILE):
    with open(HASH_FILE, "r", encoding="utf-8") as f:
        seen_hashes = json.load(f)
else:
    seen_hashes = {}

# --- Helper Functions ---
def hash_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def extract_item_4(text):
    """Extract Item 4 from filing text."""
    # Try XML-style tags first
    xml_match = re.search(r'<ITEM[_\s]*4[^>]*>(.*?)</ITEM[_\s]*4>', text, re.I | re.S)
    if xml_match:
        return xml_match.group(1).strip()
    # Fallback: plain text filings
    start = re.search(r'ITEM\s+4[\.\-–—:\s]*PURPOSE\s+OF\s+TRANSACTION', text, re.I)
    if not start:
        return None
    end = re.search(r'ITEM\s+5[\.\-–—:\s]', text[start.end():], re.I)
    return (text[start.end(): start.end() + end.start()].strip() if end else text[start.end():].strip())

def highlight_keywords(text):
    for kw in KEYWORDS:
        text = re.sub(re.escape(kw), lambda m: f"<strong>{m.group(0)}</strong>", text, flags=re.I)
    return text

def highlight_company(text, company):
    return re.sub(re.escape(company), f"<strong>{company}</strong>", text, flags=re.I)

def keyword_match(text):
    return any(re.search(re.escape(k), text, re.I) for k in KEYWORDS)

def fetch_primary_doc(entry):
    """
    Construct the primary doc URL from the Atom entry.
    This works for XML filings where tableFile parsing fails.
    """
    # Example: replace '-index.htm' with '/xslSCHEDULE_13D_X01/primary_doc.xml'
    url = entry.link
    primary_url = url.replace('-index.htm', '/xslSCHEDULE_13D_X01/primary_doc.xml')
    try:
        r = requests.get(primary_url, headers=HEADERS, timeout=15)
        time.sleep(REQUEST_DELAY)
        if r.status_code == 200:
            return BeautifulSoup(r.text, "lxml").get_text("\n")
    except Exception:
        return None
    return None

# --- Main processing ---
items = []

for feed_url in FEEDS:
    feed = feedparser.parse(feed_url)
    for entry in feed.entries:
        text = fetch_primary_doc(entry)
        if not text:
            continue
        if not keyword_match(text):
            continue
        item4 = extract_item_4(text)
        if not item4:
            continue
        highlighted = highlight_keywords(item4)
        highlighted = highlight_company(highlighted, entry.title)
        item_hash = hash_text(highlighted)
        if seen_hashes.get(entry.id) == item_hash:
            continue
        seen_hashes[entry.id] = item_hash
        form_type = "AMENDED" if "13D/A" in entry.title else "NEW"
        emoji = "⚡" if form_type == "NEW" else "🔄"
        items.append({
            "title": f"[{form_type}] {emoji} {entry.title}",
            "link": entry.link.replace('-index.htm', '/xslSCHEDULE_13D_X01/primary_doc.xml'),
            "content": highlighted,
            "date": datetime(*entry.published_parsed[:6])
        })

# --- Generate RSS feed ---
with open(FEED_FILE, "w", encoding="utf-8") as f:
    f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    f.write('<rss version="2.0"><channel>\n')
    f.write('<title>SEC Schedule 13D Item 4 (Fast Alert)</title>\n')
    f.write('<link>https://www.sec.gov</link>\n')
    f.write('<description>Item 4 from SC 13D and 13D/A filings containing buyout-related keywords</description>\n')
    for i in sorted(items, key=lambda x: x["date"], reverse=True)[:MAX_FEED_ITEMS]:
        f.write("<item>\n")
        f.write(f"<title>{i['title']}</title>\n")
        f.write(f"<link>{i['link']}</link>\n")
        f.write(f"<pubDate>{format_datetime(i['date'])}</pubDate>\n")
        f.write(f"<description><![CDATA[{i['content']}<br><a href='{i['link']}'>Full Filing</a>]]></description>\n")
        f.write("</item>\n")
    f.write("</channel></rss>")

# --- Save hash record ---
with open(HASH_FILE, "w", encoding="utf-8") as f:
    json.dump(seen_hashes, f, indent=2)

print(f"Feed generated in {FEED_FILE} with {len(items)} item(s).")p
