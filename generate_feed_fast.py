import feedparser
import requests
from datetime import datetime, timedelta
from email.utils import format_datetime
import time
import os

# --- Config ---
FEED_FILE = "feed.xml"
MAX_FEED_ITEMS = 100  # RSS feed items
REQUEST_DELAY = 1     # SEC fair-access delay in seconds

FEEDS = [
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=SC+13D&owner=include&count=100&output=atom",
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=SC+13D/A&owner=include&count=100&output=atom"
]

HEADERS = {
    "User-Agent": "JellysList-FastAlert/1.0 (contact: jellysstocks@gmail.com)"
}

# --- Fetch and merge feed entries ---
items = []

for feed_url in FEEDS:
    feed = feedparser.parse(feed_url)
    time.sleep(REQUEST_DELAY)
    for entry in feed.entries:
        published = datetime(*entry.published_parsed[:6])
        items.append({
            "title": entry.title,
            "link": entry.link,
            "date": published
        })

# --- Keep only entries from last 7 days ---
seven_days_ago = datetime.utcnow() - timedelta(days=7)
items = [i for i in items if i["date"] >= seven_days_ago]

# --- Generate RSS feed ---
with open(FEED_FILE, "w", encoding="utf-8") as f:
    f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    f.write('<rss version="2.0"><channel>\n')
    f.write('<title>SEC Schedule 13D and 13D/A Filings</title>\n')
    f.write('<link>https://www.sec.gov</link>\n')
    f.write('<description>All SC 13D and 13D/A filings from the last 7 days</description>\n')

    for i in sorted(items, key=lambda x: x["date"], reverse=True)[:MAX_FEED_ITEMS]:
        f.write("<item>\n")
        f.write(f"<title>{i['title']}</title>\n")
        f.write(f"<link>{i['link']}</link>\n")
        f.write(f"<pubDate>{format_datetime(i['date'])}</pubDate>\n")
        f.write(f"<description><![CDATA[<a href='{i['link']}'>View Filing</a>]]></description>\n")
        f.write("</item>\n")

    f.write("</channel></rss>")

print(f"Feed generated in {FEED_FILE} with {len(items)} item(s).")
