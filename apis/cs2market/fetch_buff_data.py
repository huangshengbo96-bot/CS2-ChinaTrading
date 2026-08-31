"""
Fetch BUFF (buff.163.com) market data for CS2 items.
Replaces the previous Steam Community Market fetcher (fetch_cs2_data.py).

Output: apis/cs2market/cs2_data.csv with the SAME column format as before:
    name, batch_id, open, close, volume, item_url

Price mapping (BUFF -> legacy format):
    open   = sell_min_price       (最低在售价, CNY)
    close  = sell_reference_price (参考价, CNY)
    volume = sell_num             (在售数量, BUFF 未公开 24h 成交量, 用其在售量作代理)
    item_url = BUFF 商品页 URL

Historical rows are generated from BUFF's CNY price history
(/api/market/goods/price_history/buff/v2). Because a single window caps at
~60 points, several windows (30/90/180/365 days) are fetched and merged so
the CSV covers a full year of history (dense near-term: ~2 points/day),
making it immediately usable for backtesting.

Requires BUFF_COOKIE in .env (login cookie from https://buff.163.com).
"""

import os
import sys
import time
import random
import argparse
import datetime
import requests
import pandas as pd
from dotenv import load_dotenv

BASE_URL = "https://buff.163.com"
API_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://buff.163.com/market/",
    "Origin": "https://buff.163.com",
}

# Default candidate items (same set as the legacy Steam fetcher).
candidate_items = [
    "M4A4 | 龍王 (Dragon King) (Factory New)",
    "Operation Broken Fang Case",
    "Desert Eagle | Mecha Industries (Factory New)",
    "M4A4 | Neo-Noir (Factory New)",
    "Operation Wildfire Case",
    "Desert Eagle | Printstream (Factory New)",
    "Sticker | Bolt Energy (Foil)",
    "M4A1-S | Leaded Glass (Factory New)",
    "Operation Riptide Case",
    "Sticker | Hypnoteyes (Holo)",
    "Glove Case",
    "Sticker | Taste Buddy (Holo)",
    "AK-47 | Bloodsport (Factory New)",
    "AWP | Hyper Beast (Factory New)",
    "M4A4 | Desolate Space (Factory New)",
    "Dreams & Nightmares Case",
    "Sticker | FaZe Clan (Holo) | Paris 2023",
    "M4A1-S | Decimator (Factory New)",
    "Sticker | Team Liquid (Holo) | Paris 2023",
    "AK-47 | Asiimov (Factory New)",
]

DEFAULT_DAYS = 90  # single-window fallback
MERGE_WINDOWS = (30, 90, 180, 365)  # merged windows -> full-year history


def build_session() -> requests.Session:
    """Build a session that passes BUFF's device-fingerprint check.

    BUFF returns "Login Required" if we hit the API directly with a cookie.
    The fix: first GET the homepage (collecting the server-issued
    Device-Id / client_id / csrf_token), THEN attach the user login cookie.
    """
    cookie = os.getenv("BUFF_COOKIE", "").strip()
    if not cookie:
        raise RuntimeError(
            "BUFF_COOKIE is not set. Add it to .env (login to https://buff.163.com, "
            "F12 -> Network -> filter 'api' -> copy the Cookie header)."
        )

    session = requests.Session()
    session.headers.update(API_HEADERS)
    # BUFF must be reached directly; ignore any system HTTP(S)_PROXY (which may
    # point at a proxy that is not running) and any trust_env overrides.
    session.trust_env = False
    session.proxies = {"http": None, "https": None}

    # Step 1: visit homepage to obtain server-issued cookies
    resp = session.get(BASE_URL + "/", timeout=20)
    resp.raise_for_status()

    # Step 2: attach the user's login cookie
    for part in cookie.split(";"):
        part = part.strip()
        if "=" in part:
            key, value = part.split("=", 1)
            session.cookies.set(key.strip(), value.strip(), domain="buff.163.com")

    return session


def _api_get(session: requests.Session, path: str, params: dict, retries: int = 3):
    """GET a BUFF API endpoint with retry and backoff."""
    url = BASE_URL + path
    for attempt in range(retries):
        try:
            resp = session.get(url, params=params, timeout=20)
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}")
            data = resp.json()
            if data.get("code") != "OK":
                # e.g. "Login Required" - session died
                raise RuntimeError(f"code={data.get('code')} msg={data.get('error') or data.get('msg')}")
            return data["data"]
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(random.uniform(2, 5))
            else:
                raise RuntimeError(f"API {path} failed: {e}") from e


def search_goods(session: requests.Session, market_hash_name: str):
    """Find the BUFF goods_id by exact market_hash_name match."""
    data = _api_get(
        session,
        "/api/market/goods",
        {"game": "csgo", "search": market_hash_name, "page_num": 1, "page_size": 20},
    )
    for item in data.get("items", []):
        if item.get("market_hash_name") == market_hash_name:
            return item
    # fuzzy fallback: unique match on the base name
    matches = [i for i in data.get("items", []) if market_hash_name in i.get("market_hash_name", "")]
    if len(matches) == 1:
        return matches[0]
    return None


def get_price_history(session: requests.Session, goods_id: int, days: int = DEFAULT_DAYS):
    """Get BUFF CNY price history lines (in-sale min / buy max / sell num / existence)."""
    data = _api_get(
        session,
        "/api/market/goods/price_history/buff/v2",
        {"game": "csgo", "goods_id": goods_id, "days": days},
    )
    lines = {line["key"]: (line.get("points") or []) for line in data.get("lines", [])}
    return lines


def _merge_points(series_list):
    """Merge multiple [ts_ms, value] point lists, deduplicating by timestamp.

    BUFF's v2 endpoint caps every window at ~60 points, so a single window is
    too sparse for long backtests (days=365 -> one point every ~6 days).
    Fetching several windows ([30, 90, 180, 365]) and merging gives a dense
    recent history (2 points/day) while still covering a full year.
    """
    merged = {}
    for points in series_list:
        for ts_ms, value in points:
            if ts_ms not in merged:
                merged[ts_ms] = value
    return [[ts, merged[ts]] for ts in sorted(merged)]


def get_price_history_merged(session: requests.Session, goods_id: int,
                             windows=(30, 90, 180, 365)):
    """Fetch BUFF CNY price history across several windows and merge them.

    Returns the same line-key -> points mapping as get_price_history, but with
    points merged from all windows (covers ~1 year back from today).
    """
    merged_lines = {}
    for days in windows:
        try:
            lines = get_price_history(session, goods_id, days=days)
        except Exception as e:
            print(f"  window days={days} failed: {e}")
            continue
        for key, points in lines.items():
            merged_lines.setdefault(key, []).append(points)
        time.sleep(random.uniform(0.8, 1.5))
    return {key: _merge_points(points_list) for key, points_list in merged_lines.items()}


def get_goods_info(session: requests.Session, goods_id: int):
    """Get current BUFF goods snapshot (CNY prices)."""
    return _api_get(session, "/api/market/goods/info", {"game": "csgo", "goods_id": goods_id})


def _aggregate_daily(points):
    """Aggregate [ts_ms, value] points into {date_str: [open, close]}."""
    daily = {}
    for ts_ms, value in points:
        dt = datetime.datetime.fromtimestamp(ts_ms / 1000)
        day = dt.strftime("%Y-%m-%d")
        if day not in daily:
            daily[day] = [value, value]  # open = close = first point of the day
        else:
            daily[day][1] = value  # update close with the latest point
    return daily


def build_rows(item, goods_info, history_lines):
    """Build CSV rows (legacy format) from BUFF data.

    - Historical rows: per-day aggregation of the in-sale-min price line.
    - Current row: today's snapshot from goods/info.
    """
    rows = []
    market_hash_name = goods_info.get("market_hash_name") or item.get("market_hash_name")
    goods_id = goods_info.get("id") or item.get("id")
    item_url = f"https://buff.163.com/market/goods?game=csgo&goods_id={goods_id}"

    # volume by day from the sell_num_history line
    sell_num_daily = _aggregate_daily(history_lines.get("sell_num_history", []))
    price_daily = _aggregate_daily(history_lines.get("sell_min_price_history", []))

    all_days = sorted(set(price_daily.keys()) | set(sell_num_daily.keys()))
    for day in all_days:
        open_price, close_price = price_daily.get(day, [None, None])
        volume = sell_num_daily.get(day, [None])[0]
        if open_price is None:
            continue  # skip days with no price point
        rows.append({
            "name": market_hash_name,
            "batch_id": f"{day} 12:00:00",
            "open": round(float(open_price), 2),
            "close": round(float(close_price), 2),
            "volume": int(volume) if volume is not None else 0,
            "item_url": item_url,
        })

    # today's live snapshot (latest available date in history may already cover it)
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    sell_min = goods_info.get("sell_min_price")
    sell_ref = goods_info.get("sell_reference_price")
    sell_num = goods_info.get("sell_num", 0)
    if sell_min is not None and not any(r["batch_id"].startswith(today) for r in rows):
        rows.append({
            "name": market_hash_name,
            "batch_id": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "open": round(float(sell_min), 2),
            "close": round(float(sell_ref if sell_ref else sell_min), 2),
            "volume": int(sell_num or 0),
            "item_url": item_url,
        })

    return rows


def fetch_all(tickers):
    """Fetch BUFF data for all tickers and return combined CSV rows."""
    session = build_session()
    rows = []
    failed = []

    for i, ticker in enumerate(tickers, start=1):
        print(f"[{i}/{len(tickers)}] fetching: {ticker}")
        try:
            item = search_goods(session, ticker)
            if not item:
                print(f"  !! goods not found on BUFF: {ticker}")
                failed.append(ticker)
                continue

            goods_id = item["id"]
            goods_info = get_goods_info(session, goods_id)
            history_lines = get_price_history_merged(session, goods_id)

            item_rows = build_rows(item, goods_info, history_lines)
            rows.extend(item_rows)
            print(f"  OK goods_id={goods_id} rows={len(item_rows)} "
                  f"current_price={goods_info.get('sell_min_price')}")
        except Exception as e:
            print(f"  !! error: {e}")
            failed.append(ticker)

        time.sleep(random.uniform(1.5, 3.5))  # be gentle to the API

    return rows, failed


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Fetch CS2 item prices from BUFF (buff.163.com)")
    parser.add_argument("--config", type=str, default=None,
                        help="Config YAML with tickers (optional; falls back to built-in list)")
    parser.add_argument("--days", type=int, default=None,
                        help="Single history window in days (7/30/90/180/365); "
                             "default: merge windows (30, 90, 180, 365) for a full-year history")
    parser.add_argument("--output", type=str, default=None,
                        help="Output CSV path (default: apis/cs2market/cs2_data.csv)")
    args = parser.parse_args()

    tickers = candidate_items
    if args.config:
        with open(args.config, "r", encoding="utf-8") as f:
            import yaml
            cfg = yaml.safe_load(f)
        if cfg.get("tickers"):
            tickers = cfg["tickers"]

    csv_path = args.output or os.path.join(os.path.dirname(__file__), "cs2_data.csv")

    print(f"=== BUFF fetch started ({datetime.datetime.now()}) ===")
    print(f"target items: {len(tickers)}, history window: "
          f"{[args.days] if args.days else list(MERGE_WINDOWS)} days")

    rows, failed = fetch_all(tickers)

    df = pd.DataFrame(rows, columns=["name", "batch_id", "open", "close", "volume", "item_url"])
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"saved {len(df)} rows to {csv_path}")

    if failed:
        with open("failed_items.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(failed))
        print(f"finally {len(failed)} items failed: {failed}")
    else:
        print("all items collected successfully!")

    print(f"=== BUFF fetch completed ({datetime.datetime.now()}) ===")


if __name__ == "__main__":
    main()
