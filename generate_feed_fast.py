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
    "User-Agent": "JellysList-FastAlert/1.1 (contact: jellysstocks@gmail.com)",
    "Accept-Encoding": "gzip, deflate",
    "Host": "www.sec.gov"
}

KEYWORDS = [
    "100%", "100 %", "all shares", "fully acquire", "buyout",
    "takeover", "converted", "merger agreement"
]

HASH_FILE = "seen_item4.json"
FEED_FILE = "feed.xml"
BACKFILL_DAYS = 7      # number of days to look back
REQUEST_DELAY = 0.5    # SEC fair-access delay
MAX_FEED_ITEMS = 50    # maximum items in feed

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
    # XML-style Item 4
    match = re.search(r'<item[_\s]*4.*?>(.*?)</item[_\s]*4>', text, re.I | re.S)
    if match:
        return match.group(1).strip()
    # Plain text fallback
    start = re.search(r'ITEM\s+4[\.\-–—:\s]*PURPOSE\s+OF\s+TRANSACTION', text, re.I)
    if not start:
        return None
    end = re.search(r'ITEM\s+5[\.\-–—:\s]', text[start.end():], re.I)
    return (text[start.end(): start.end()+end.start()].strip() if end else text[start.end():].strip())

def highlight_keywords(text):
    for kw in KEYWORDS:
        pattern = re.compile(re.escape(kw), re.I)
        text = pattern.sub(lambda m: f"<strong>{m.group(0)}</strong>", text)
    return text

def highlight_company(text, company):
    return re.sub(re.escape(company), f"<strong>{company}</strong>", text, flags=re.I)

def keyword_match(text, keywords):
    for kw in keywords:
        if re.search(re.escape(kw), text, re.I):
            return True
    return False

def fetch_filing_text(submission_path):
    """
    Given a submission path, fetches the primary SC 13D/13D-A document text from SEC.
    """
    base_dir = submission_path.rsplit("/", 1)[0]
    index_url = f"https://www.sec.gov/Archives/{base_dir}-index.htm"
    try:
        r = requests.get(index_url, headers=HEADERS, timeout=15)
        time.sleep(REQUEST_DELAY)
        if r.status_code != 200:
            print(f"[WARN] Index page fetch failed: {index_url} ({r.status_code})")
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        table = soup.find("table", class_="tableFile")
        if not table:
            print(f"[WARN] No table found in index page: {index_url}")
            return None
        primary_doc_url = None
        for row in table.find_all("tr")[1:]:
            cols = row.find_all("td")
            if not cols:
                continue
            doc_type = cols[3].text.strip()
            if doc_type.startswith("SC 13D"):
                href = cols[2].a["href"]
                primary_doc_url = f"https://www.sec.gov{href}"
                break
        if not primary_doc_url:
            print(f"[WARN] No SC 13D/13D-A document found in index page: {index_url}")
            return None
        r2 = requests.get(primary_doc_url, headers=HEADERS, timeout=15)
        time.sleep(REQUEST_DELAY)
        if r2.status_code != 200:
            print(f"[WARN] Primary document fetch failed: {primary_doc_url} ({r2.status_code})")
            return None
        text = BeautifulSoup(r2.text, "lxml").get_text("\n")
        return text
    except Exception as e:
        print(f"[ERROR] Exception fetching filing {submission_path}: {e}")
        return None

def get_index_urls_for_date(date):
    """Returns SEC master index URLs for a given date (both .idx and .idx.gz)."""
    base = "https://www.sec.gov/Archives/edgar/daily-index"
    yyyy = date.year
    mm = date.month
    dd = date.strftime("%d")
    if mm <= 3: qtr = "QTR1"
    elif mm <= 6: qtr = "QTR2"
    elif mm <= 9: qtr = "QTR3"
    else: qtr = "QTR4"
    return [
        f"{base}/{yyyy}/{qtr}/master.{yyyy}{mm:02d}{dd}.idx.gz",
        f"{base}/{yyyy}/{qtr}/master.{yyyy}{mm:02d}{dd}.idx"
    ]

def parse_master_index(url):
    """Parses a SEC master index file to find SC 13D and 13D/A filings."""
    import gzip, io
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        time.sleep(REQUEST_DELAY)
        if r.status_code != 200:
            return []
        content = r.content
        if url.endswith(".gz"):
            with gzip.GzipFile(fileobj=io.BytesIO(content)) as f:
                content = f.read()
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
        if form_type not in ("SC 13D", "SC 13D/A"):
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

# --- Main processing ---
items = []

for day_offset in range(BACKFILL_DAYS):
    date = datetime.utcnow() - timedelta(days=day_offset)
    for idx_url in get_index_urls_for_date(date):
        filings = parse_master_index(idx_url)
        for f in filings:
            text = fetch_filing_text(f["path"])
            if not text:
                continue
            if not keyword_match(text, KEYWORDS):
                continue
            item4 = extract_item_4(text)
            if not item4:
                continue
            highlighted = highlight_keywords(item4)
            highlighted = highlight_company(highlighted, f["company"])
            item_hash = hash_text(highlighted)
            if seen_hashes.get(f["path"]) == item_hash:
                continue
            seen_hashes[f["path"]] = item_hash
            label = "NEW" if f["form_type"] == "SC 13D" else "AMENDED"
            emoji = "⚡" if label == "NEW" else "🔄"
            items.append({
                "title": f"[{label}] {emoji} {f['company']} ({f['form_type']})",
                "link": f"https://www.sec.gov/Archives/{f['path']}",
                "content": highlighted,
                "date": datetime.strptime(f["date_filed"], "%Y-%m-%d")
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
        f.write(f"<description><![CDATA[{i['content']}]]></description>\n")
        f.write("</item>\n")
    f.write("</channel></rss>")

# --- Save hash record ---
with open(HASH_FILE, "w", encoding="utf-8") as f:
    json.dump(seen_hashes, f, indent=2)

print(f"Enhanced feed generated in {FEED_FILE} with {len(items)} item(s) (last {BACKFILL_DAYS} days).")
