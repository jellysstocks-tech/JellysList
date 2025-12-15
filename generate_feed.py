import feedparser
import requests
import re
import time
from bs4 import BeautifulSoup
from datetime import datetime
from email.utils import format_datetime
import json
import hashlib
import os

# --- User Config ---
HEADERS = {
    "User-Agent": "JellysList/1.0 (contact: jellysstocks@gmail.com)"
}

FEEDS = [
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=SC%2013D&owner=include&count=40&output=atom",
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=SC%2013D/A&owner=include&count=40&output=atom"
]

KEYWORDS = [
    "100%", "100 %", "all shares", "fully acquire", "buyout",
    "takeover", "converted", "merger agreement"
]

HASH_FILE = "seen_item4.json"

# --- Load previous hashes for deduplication ---
if os.path.exists(HASH_FILE):
    with open(HASH_FILE, "r", encoding="utf-8") as f:
        seen_hashes = json.load(f)
else:
    seen_hashes = {}

# --- Helper Functions ---
def extract_item_4(text):
    """Extracts Item 4 text from the filing document."""
    start = re.search(r'ITEM\s+4[\.\-–—:\s]*PURPOSE\s+OF\s+TRANSACTION', text, re.I)
    if not start:
        return None
    end = re.search(r'ITEM\s+5[\.\-–—:\s]', text[start.end():], re.I)
    return text[start.end(): start.end() + end.start()].strip() if end else text[start.end():].strip()

def get_primary_doc(index_url):
    """Finds the primary SC 13D/13D/A document URL from the filing index page."""
    r = requests.get(index_url, headers=HEADERS)
    soup = BeautifulSoup(r.text, "html.parser")
    table = soup.find("table", class_="tableFile")
    if not table:
        return None
    for row in table.find_all("tr")[1:]:
        cols = row.find_all("td")
        if cols and cols[3].text.strip().startswith("SC 13D"):
            return "https://www.sec.gov" + cols[2].a["href"]
    return None

def highlight_keywords(text, keywords):
    """Wrap all keyword occurrences in <strong> tags for highlighting."""
    for kw in keywords:
        pattern = re.compile(re.escape(kw), re.IGNORECASE)
        text = pattern.sub(lambda m: f"<strong>{m.group(0)}</strong>", text)
    return text

def hash_text(text):
    """Return SHA256 hash of text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

# --- Main processing ---
items = []

for feed_url in FEEDS:
    feed = feedparser.parse(feed_url)
    for entry in feed.entries:
        doc_url = get_primary_doc(entry.link)
        if not doc_url:
            continue

        # Respect SEC fair access
        time.sleep(1)

        # Fetch document text
        doc = requests.get(doc_url, headers=HEADERS)
        text = BeautifulSoup(doc.text, "lxml").get_text("\n")

        # Keyword filter (any match in entire filing)
        if not any(k.lower() in text.lower() for k in KEYWORDS):
            continue

        # Extract Item 4
        item4 = extract_item_4(text)
        if not item4:
            continue

        # Highlight keywords
        highlighted_item4 = highlight_keywords(item4, KEYWORDS)

        # Determine NEW vs AMENDED
        form_type = "AMENDED" if "13D/A" in entry.title else "NEW"

        # Deduplicate amendments
        item_hash = hash_text(highlighted_item4)
        previous_hash = seen_hashes.get(doc_url)
        if previous_hash == item_hash:
            continue  # unchanged, skip

        # Update hash record
        seen_hashes[doc_url] = item_hash

        # Add to feed
        items.append({
            "title": f"[{form_type}] {entry.title}",
            "link": doc_url,
            "content": highlighted_item4,
            "date": entry.published_parsed
        })

# --- Generate RSS feed ---
with open("feed.xml", "w", encoding="utf-8") as f:
    f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    f.write('<rss version="2.0"><channel>\n')
    f.write('<title>SEC Schedule 13D Item 4 (Keyword Filtered)</title>\n')
    f.write('<link>https://www.sec.gov</link>\n')
    f.write('<description>Item 4 from Schedule 13D and 13D/A filings containing specified keywords</description>\n')

    for i in items[:50]:
        f.write("<item>\n")
        f.write(f"<title>{i['title']}</title>\n")
        f.write(f"<link>{i['link']}</link>\n")
        f.write(f"<pubDate>{format_datetime(datetime(*i['date'][:6]))}</pubDate>\n")
        f.write(f"<description><![CDATA[{i['content']}]]></description>\n")
        f.write("</item>\n")

    f.write("</channel></rss>")

# --- Save hash record ---
with open(HASH_FILE, "w", encoding="utf-8") as f:
    json.dump(seen_hashes, f, indent=2)

print(f"Feed generated with {len(items)} items.")
