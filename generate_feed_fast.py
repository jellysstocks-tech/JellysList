import requests
import gzip
import io
from datetime import datetime, timedelta
from email.utils import format_datetime
import os

FEED_FILE = "feed.xml"
HEADERS = {
    "User-Agent": "JellysList-FastAlert/2.0 (contact: jellysstocks@gmail.com)"
}
BACKFILL_DAYS = 7
MAX_FEED_ITEMS = 100

def get_index_urls(date):
    """Return both .idx.gz and .idx URLs for a given date."""
    base = "https://www.sec.gov/Archives/edgar/daily-index"
    yyyy = date.year
    mm = f"{date.month:02d}"
    dd = f"{date.day:02d}"
    return [
        f"{base}/{yyyy}/QTR{((date.month-1)//3)+1}/master.{yyyy}{mm}{dd}.idx.gz",
        f"{base}/{yyyy}/QTR{((date.month-1)//3)+1}/master.{yyyy}{mm}{dd}.idx"
    ]

def parse_idx(url):
    """Download and parse a .idx or .idx.gz file, returning SC 13D/13D/A filings."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        content = r.content
        if url.endswith(".gz"):
            with gzip.GzipFile(fileobj=io.BytesIO(content)) as f:
                content = f.read()
        text = content.decode("latin1")
        filings = []
        lines = text.splitlines()
        start = False
        for line in lines:
            if line.startswith("CIK|"):  # header line found
                start = True
                continue
            if not start:
                continue
            parts = line.split("|")
            if len(parts) != 5:
                continue
            cik, company, form_type, date_filed, path = parts
            if form_type in ("SC 13D", "SC 13D/A"):
                filings.append({
                    "company": company,
                    "form_type": form_type,
                    "date_filed": date_filed,
                    "link": f"https://www.sec.gov/Archives/{path}"
                })
        return filings
    except Exception:
        return []

# --- Gather filings ---
all_filings = []
today = datetime.utcnow()
for day_offset in range(BACKFILL_DAYS):
    date = today - timedelta(days=day_offset)
    filings_for_day = []
    for url in get_index_urls(date):
        filings_for_day = parse_idx(url)
        if filings_for_day:
            break
    all_filings.extend(filings_for_day)

# --- Generate RSS feed ---
with open(FEED_FILE, "w", encoding="utf-8") as f:
    f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    f.write('<rss version="2.0"><channel>\n')
    f.write('<title>SEC Schedule 13D / 13D/A Filings (Last 7 Days)</title>\n')
    f.write('<link>https://www.sec.gov</link>\n')
    f.write('<description>All SC 13D and SC 13D/A filings from the last 7 days.</description>\n')

    for item in sorted(all_filings, key=lambda x: x["date_filed"], reverse=True)[:MAX_FEED_ITEMS]:
        f.write("<item>\n")
        f.write(f"<title>{item['company']} ({item['form_type']})</title>\n")
        f.write(f"<link>{item['link']}</link>\n")
        f.write(f"<pubDate>{format_datetime(datetime.strptime(item['date_filed'], '%Y-%m-%d'))}</pubDate>\n")
        f.write(f"<description><![CDATA>{item['company']} filed {item['form_type']} on {item['date_filed']}<br><a href='{item['link']}'>Full Filing</a>]]></description>\n")
        f.write("</item>\n")

    f.write("</channel></rss>\n")

print(f"Feed generated in {FEED_FILE} with {len(all_filings)} item(s) (last {BACKFILL_DAYS} days).")
