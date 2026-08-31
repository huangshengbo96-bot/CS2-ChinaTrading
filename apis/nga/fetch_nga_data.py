"""
Fetch NGA (bbs.nga.cn) CS:GO board threads to CSV for sentiment analysis.
Replaces the previous Reddit fetcher (apis/reddit/fetch_reddit_data.py).

Output: apis/nga/nga_data.csv with columns compatible with the old Reddit CSV:
    publish_time, title, publisher, link, summary, score, num_comments, subreddit

Usage (from project root):
    python -m apis.nga.fetch_nga_data            # last 30 days, titles only
    python -m apis.nga.fetch_nga_data --days 365 --with-content

The main workflow reads only from this CSV (filtered by trading_date window),
so it can be re-run any time to refresh the historical data.
"""

import os
import time
import random
import argparse
import datetime
import pandas as pd
from typing import List

from apis.nga.api import NGAAPI, _thread_to_media_news
from util.logger import logger


def fetch_threads(api: NGAAPI, fid: int, days: int, with_content: bool = False) -> List[dict]:
    """Fetch board threads posted within the last `days`, optionally with main-post content."""
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    cutoff_ts = cutoff.timestamp()

    rows = []
    page = 1
    seen_tids = set()

    while page <= 50:  # safety cap
        threads = api.get_forum_threads(fid=fid, page=page, order_by="postdatedesc")
        if not threads:
            break

        newer_than_cutoff = 0
        for t in threads:
            tid = t.get("tid")
            postdate = t.get("postdate") or 0
            if postdate < cutoff_ts:
                continue
            newer_than_cutoff += 1
            if tid in seen_tids:
                continue
            seen_tids.add(tid)

            summary = ""
            if with_content:
                detail = api.get_thread(tid)
                main = detail.get("data", {}).get("__T", {})
                content = main.get("content") or ""
                # strip BB code / quotes roughly, keep first ~500 chars
                content = content.replace("<br/>", " ").replace("[quote]", " ").replace("[/quote]", " ")
                summary = content[:500]
                time.sleep(random.uniform(0.5, 1.2))

            news = _thread_to_media_news(t, summary=summary)
            if news:
                rows.append({
                    "publish_time": news.publish_time,
                    "title": news.title,
                    "publisher": news.publisher,
                    "link": news.link,
                    "summary": news.summary,
                    "score": news.score,
                    "num_comments": news.num_comments,
                    "subreddit": "CS:GO",
                })

        if newer_than_cutoff == 0:
            break  # no more threads in window
        page += 1
        time.sleep(random.uniform(0.5, 1.0))

    return rows


def main():
    parser = argparse.ArgumentParser(description="Fetch NGA CS:GO board threads to CSV")
    parser.add_argument("--fid", type=int, default=NGAAPI.CSGO_FID,
                        help="NGA board id (default: CS:GO = 482)")
    parser.add_argument("--days", type=int, default=30,
                        help="How many days back to fetch (default: 30)")
    parser.add_argument("--with-content", action="store_true",
                        help="Also fetch main-post content as summary (slower)")
    parser.add_argument("--output", type=str, default=None,
                        help="Output CSV path (default: apis/nga/nga_data.csv)")
    args = parser.parse_args()

    csv_path = args.output or os.path.join(os.path.dirname(__file__), "nga_data.csv")

    api = NGAAPI()
    print(f"=== NGA fetch started ({datetime.datetime.now()}) ===")
    print(f"board fid={args.fid}, days={args.days}, with_content={args.with_content}")

    rows = fetch_threads(api, args.fid, args.days, args.with_content)

    # append to existing CSV (deduplicate by link)
    if os.path.exists(csv_path):
        old = pd.read_csv(csv_path)
        old_links = set(old["link"]) if "link" in old.columns else set()
        rows = [r for r in rows if r["link"] not in old_links]
        df = pd.concat([old, pd.DataFrame(rows)], ignore_index=True)
    else:
        df = pd.DataFrame(rows)

    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"saved {len(rows)} new rows (total {len(df)}) to {csv_path}")

    print(f"=== NGA fetch completed ({datetime.datetime.now()}) ===")


if __name__ == "__main__":
    main()
