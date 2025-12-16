import os
import json
import hashlib
from datetime import datetime, timedelta
from email.utils import format_datetime
from bs4 import BeautifulSoup
from edgar import get_filings
import time

# --- User Config ---
HEADERS = {
    "User-Agent": "JellysList-FastAlert/1.5 (contact: jellysstocks@gmail.com)"
}

FEED_FILE = "feed.xml"
HASH_FILE = "seen_item4.json"
BACKFILL_DAYS = 7
MAX_FEED_ITEMS = 50
REQUEST_DELAY = 1  # SEC fair-access delay in seconds

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
    # XML-style
    xml_match = re.search(r'<ITEM>4[\s\S]*?<TEXT>(.*?)</TEXT>', text, re.I)
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
    return any(kw.lower() in text.lower() for kw in KEYWORDS)

# --- Main processing ---
items = []

start_date = datetime.utcnow() - timedelta(days=BACKFILL_DAYS)

# Fetch SC 13D and SC 13D/A filings via EdgarTools
for form_type in ["SC 13D", "SC 13D/A"]:
    filings = get_filings(form=form_type, start_date=start_date.strftime("%Y-%m-%d"))
    for filing in filings:
        try:
            time.sleep(REQUEST_DELAY)
            text = filing.get_text()  # EdgarTools fetches primary document text
        except Exception:
            continue

        if not keyword_match(text):
            continue

        item4 = extract_item_4(text)
        if not item4:
            continue

        highlighted = highlight_keywords(item4)
        highlighted = highlight_company(highlighted, filing.company_name)

        item_hash = hash_text(highlighted)
        if seen_hashes.get(filing.accession_number) == item_hash:
            continue
        seen_hashes[filing.accession_number] = item_hash

        label = "NEW" if form_type == "SC 13D" else "AMENDED"
        emoji = "⚡" if label == "NEW" else "🔄"

        items.append({
            "title": f"[{label}] {emoji} {filing.company_name} ({form_type})",
            "link": filing.filing_url,
            "content": highlighted,
            "date": datetime.strptime(filing.filing_date, "%Y-%m-%d")
        })

# --- Generate RSS feed ---
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

print(f"Enhanced feed generated in {FEED_FILE} with {len(items)} item(s) (last {BACKFILL_DAYS} days).")
