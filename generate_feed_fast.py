import requests
import re
import time
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from email.utils import format_datetime
import json
import hashlib
import os
import gzip
import io

# --- User Config ---
HEADERS = {
    "User-Agent": "JellysList-FastAlert/1.1 (contact: jellysstocks@gmail.com)"
}

KEYWORDS = [
    "100%", "100 %", "all shares", "fully acquire", "buyout",
    "takeover", "converted", "merger agreement"
]

HASH_FILE = "seen_item4.json"
FEED_FILE = "feed.xml"       # keep your current feed name here
BACKFILL_DAYS = 5            # Backfill test
REQUEST_DELAY = 0.5          # SEC fair-access delay
MAX_FEED_ITEMS = 50          # Keep feed manageable

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
    start = re.search(r'ITEM\s+4[\.\-–—:\s]*PURPOSE\s+OF\s+TRANSACTION', text, re.I)
    if not start:
        return None
    end = re.search(r'ITEM\s+5[\.\-–—:\s]', text[start.end():], re.I)
    return text[start.end(): start.end() + end.start()].strip() if end else text[start.end():].strip()

def highlight_keywords(text):
    for kw in KEYWORDS:
        pattern = re.compile(re.escape(kw), re.IGNORECASE)
        text = pattern.sub(lambda m: f"<strong>{m.group(0)}</strong>", text)
    return text

def highlight_company(text, company):
    return re.sub(re.escape(company), f"<strong>{company}</strong>", text, flags=re.IGNORECASE)

def get_index_urls_for_date(date):
    base = "https://www.sec.gov/Archives/edgar/daily-index"
    yyyy = date.strftime("%Y")
    mm = date.strftime("%m")
    dd = date.strftime("%d")
    return [
        f"{base}/{yyyy}/{mm}/master.{yyyy}{mm}{dd}.idx",
        f"{base}/{yyyy}/{mm}/master.{yyyy}{mm}{dd}.idx.gz"
    ]

def parse_master_index(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        content = r.content
        if url.endswith(".gz"):
            with gzip.GzipFile(fileobj=io.BytesIO(content)) as f:
                content = f.read()
            content = content.decode("latin1")
        else:
            content = content.decode("latin1")
    except Exception:
        return []

    entries = []
    in_data = False
    for line in content.splitlines():
        if line.startswith("CIK|"):
            in_data = True
            continue
        if not in_data:
            continue
        parts = line.split("|")
        if len(parts) < 5:
            continue
        cik, company, form_type, date_filed, path = parts
        if form_type not in ["SC 13D", "SC 13D/A"]:
            continue
        filing_dt = datetime.strptime(date_filed, "%Y-%m-%d")
        if filing_dt < datetime.utcnow() - timedelta(days=BACKFILL_DAYS):
            continue
        entries.append({
            "cik": cik,
            "company": company,
            "form_type": form_type,
            "date_filed": date_filed,
            "path": path
        })
    return entries

def fetch_filing_text(path):
    url = f"https://www.sec.gov/Archives/{path}"
    r = requests.get(url, headers=HEADERS, timeout=15)
    time.sleep(REQUEST_DELAY)
    return BeautifulSoup(r.text, "lxml").get_text("\n")

# --- Main processing ---
items = []

for day_offset in range(BACKFILL_DAYS):
    date = datetime.utcnow() - timedelta(days=day_offset)
    index_urls = get_index_urls_for_date(date)

    for idx_url in index_urls:
        filings = parse_master_index(idx_url)
        for f in filings:
            try:
                text = fetch_filing_text(f["path"])
            except Exception:
                continue

            # Keyword filter
            if not any(k.lower() in text.lower() for k in KEYWORDS):
                continue

            # Extract Item 4
            item4 = extract_item_4(text)
            if not item4:
                continue

            # Highlight keywords & company
            highlighted = highlight_keywords(item4)
            highlighted = highlight_company(highlighted, f["company"])

            # Deduplication
            item_hash = hash_text(highlighted)
            if seen_hashes.get(f["path"]) == item_hash:
                continue
            seen_hashes[f["path"]] = item_hash

            # Filing type label & emoji
            label = "NEW" if f["form_type"] == "SC 13D" else "AMENDED"
            emoji = "⚡" if label == "NEW" else "🔄"

            items.append({
                "title": f"[{label}] {emoji} {f['company']} ({f['form_type']})",
                "link": f"https://www.sec.gov/Archives/{f['path']}",
                "index_link": f"https://www.sec.gov/Archives/edgar/data/{f['cik']}/{f['path'].split('/')[-1]}",
                "content": highlighted,
                "date": datetime.strptime(f["date_filed"], "%Y-%m-%d")
            })

# --- Generate RSS feed ---
with open(FEED_FILE, "w", encoding="utf-8") as f:
    f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    f.write('<rss version="2.0"><channel>\n')
    f.write('<title>SEC Schedule 13D Item 4 (Fast Alert Enhanced)</title>\n')
    f.write('<link>https://www.sec.gov</link>\n')
    f.write('<description>Item 4 from SC 13D and 13D/A filings containing buyout-related keywords, enhanced for fast alerts</description>\n')

    # Sort by timestamp descending, keep only most recent items
    for i in sorted(items, key=lambda x: x["date"], reverse=True)[:MAX_FEED_ITEMS]:
        f.write("<item>\n")
        f.write(f"<title>{i['title']}</title>\n")
        f.write(f"<link>{i['link']}</link>\n")
        f.write(f"<pubDate>{format_datetime(i['date'])}</pubDate>\n")
        f.write(f"<description><![CDATA[{i['content']}<br><a href='{i['index_link']}'>Full Filing Index</a>]]></description>\n")
        f.write("</item>\n")

    f.write("</channel></rss>")

# --- Save hash record ---
with open(HASH_FILE, "w", encoding="utf-8") as f:
    json.dump(seen_hashes, f, indent=2)

print(f"Enhanced feed generated with {len(items)} items (last {BACKFILL_DAYS} days).")
