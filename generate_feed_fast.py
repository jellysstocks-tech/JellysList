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
    "User-Agent": "JellysList-FastAlert/1.1 (contact: jellysstocks@gmail.com)"
}

FEED_FILE = "feed.xml"
HASH_FILE = "seen_item4.json"
MAX_FEED_ITEMS = 50
REQUEST_DELAY = 1  # SEC fair-access delay in seconds
BACKFILL_DAYS = 7

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
    """Extract Item 4 from filing text (XML or plain text)."""
    # Try XML-style tags first
    xml_match = re.search(r'<item[_\s]*4[^>]*>(.*?)</item[_\s]*4>', text, re.I | re.S)
    if xml_match:
        return xml_match.group(1).strip()
    # Plain-text fallback
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

def get_primary_doc_url(filing_url):
    """Fetch the primary document URL from the filing detail page."""
    try:
        r = requests.get(filing_url, headers=HEADERS, timeout=15)
        time.sleep(REQUEST_DELAY)
        soup = BeautifulSoup(r.text, "html.parser")
        table = soup.find("table", class_="tableFile")
        if not table:
            return None
        for row in table.find_all("tr")[1:]:
            cols = row.find_all("td")
            if not cols:
                continue
            doc_type = cols[3].text.strip()
            if doc_type.startswith("SC 13D"):
                href = cols[2].a["href"]
                return "https://www.sec.gov" + href
    except Exception:
        return None
    return None

# --- Main Processing ---
items = []
cutoff_date = datetime.utcnow() - timedelta(days=BACKFILL_DAYS)

for feed_url in FEEDS:
    feed = feedparser.parse(feed_url)
    for entry in feed.entries:
        entry_date = datetime(*entry.published_parsed[:6])
        if entry_date < cutoff_date:
            continue
        primary_url = get_primary_doc_url(entry.link)
        if not primary_url:
            continue
        try:
            r = requests.get(primary_url, headers=HEADERS, timeout=15)
            time.sleep(REQUEST_DELAY)
            text = BeautifulSoup(r.text, "lxml").get_text("\n")
        except Exception:
            continue

        if not keyword_match(text):
            continue

        item4 = extract_item_4(text)
        if not item4:
            continue

        highlighted = highlight_keywords(item4)
        highlighted = highlight_company(highlighted, entry.title)

        # Deduplicate
        item_hash = hash_text(highlighted)
        if seen_hashes.get(primary_url) == item_hash:
            continue
        seen_hashes[primary_url] = item_hash

        form_type = "AMENDED" if "13D/A" in entry.title else "NEW"
        emoji = "⚡" if form_type == "NEW" else "🔄"

        items.append({
            "title": f"[{form_type}] {emoji} {entry.title}",
            "link": primary_url,
            "content": highlighted,
            "date": entry_date
        })

# --- Generate RSS Feed ---
with open(FEED_FILE, "w", encoding="utf-8") as f:
    f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    f.write('<rss version="2.0"><channel>\n')
    f.write('<title>SEC Schedule 13D Item 4 (Fast Alert Enhanced)</title>\n')
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

print(f"Enhanced feed generated in {FEED_FILE} with {len(items)} item(s).")
