"""
NGA (bbs.nga.cn) API client for CS2 market sentiment analysis.
Replaces the previous Reddit (praw) data source.

NGA is the largest Chinese gaming forum; the CS:GO board (fid=482) carries
active discussion about CS2 skins/items/stickers/cases, which we use as the
domestic community sentiment signal.

API notes (from community docs):
  - thread.php?fid=<board>&__output=11  -> UTF-8 JSON thread list
  - read.php?tid=<tid>&__output=11      -> thread + replies
  - User-Agent "NGA_WP_JW" unlocks extra fields
  - search requires login (403), so we fetch the board list and filter
    locally by keywords (English item name parts + Chinese aliases).

Backtesting reads historical data from a pre-fetched CSV (no data leakage),
mirroring the old Reddit module.
"""

import os
import time
import random
import requests
import pandas as pd
from typing import List, Optional
from datetime import datetime, timedelta
from apis.common_model import MediaNews
from util.logger import logger

# ---------------------------------------------------------------------------
# Chinese aliases used to match NGA (Chinese) posts against English tickers.
# Kept deliberately short: the English item name parts are also matched.
# ---------------------------------------------------------------------------
CN_ALIASES = {
    "AK-47": ["AK", "AK47", "AK 47", "ak", "卡拉什"],
    "AWP": ["awp", "大狙", "鸟狙", "aw"],
    "Desert Eagle": ["沙鹰", "deagle", "DE"],
    "M4A4": ["M4", "m4"],
    "M4A1-S": ["M4A1", "消音", "m4a1"],
    "Redline": ["红线"],
    "Asiimov": ["二西莫夫", "a4", "二西"],
    "Bloodsport": ["血腥运动", "血运"],
    "Neo-Noir": ["新黑色", "黑幻"],
    "Printstream": ["印花集", "印花"],
    "Mecha Industries": ["机械工业", "机械"],
    "Hyper Beast": ["暴怒野兽", "野兽"],
    "Desolate Space": ["荒芜空间", "荒芜"],
    "Dragon King": ["龙王", "龙"],
    "Decimator": ["屠戮者"],
    "Leaded Glass": ["铅玻璃", "铅"],
    "Dreams & Nightmares": ["梦境与噩梦", "噩梦", "梦境"],
    "Broken Fang": ["狂牙"],
    "Riptide": ["激流"],
    "Wildfire": ["野火"],
    "Glove Case": ["手套箱", "手套"],
    "Operation": ["行动", "大行动"],
    "Sticker": ["印花", "贴纸"],
    "Case": ["箱子", "武器箱", "箱"],
    "Holo": ["全息"],
    "Foil": ["闪亮", "箔"],
    "FaZe Clan": ["faze", "法泽"],
    "Team Liquid": ["液体", "liquid"],
    "Paris 2023": ["巴黎2023", "巴黎 2023", "巴黎"],
    "Bolt Energy": ["闪电能量"],
    "Taste Buddy": ["味道"],
    "Hypnoteyes": ["催眠"],
    "Factory New": ["崭新"],
    "Field-Tested": ["久经沙场", "久经"],
    "Minimal Wear": ["略有磨损", "略磨"],
    "Well-Worn": ["破损不堪", "破损"],
    "Battle-Scarred": ["战痕累累", "战痕"],
}


class NGAAPI:
    """NGA API Wrapper for CS2 market sentiment."""

    BASE_URL = "https://bbs.nga.cn"
    CSGO_FID = 482  # CS:GO board (CS2 discussions)
    USER_AGENT = "NGA_WP_JW"

    def __init__(self, csv_path: Optional[str] = None):
        """Initialize NGA client.

        Args:
            csv_path: Path to historical NGA CSV (default: nga_data.csv next to this file).
        """
        if csv_path is None:
            csv_path = os.path.join(os.path.dirname(__file__), "nga_data.csv")
        self.csv_path = csv_path
        self._csv_data = None  # cache

    # ------------------------------------------------------------------
    # Live API helpers
    # ------------------------------------------------------------------
    def _get_json(self, path: str, params: dict, retries: int = 3):
        """GET a NGA endpoint and parse UTF-8 JSON."""
        session = requests.Session()
        session.trust_env = False  # ignore system proxy
        session.proxies = {"http": None, "https": None}
        session.headers.update({"User-Agent": self.USER_AGENT})
        params = dict(params)
        params["__output"] = 11  # UTF-8 JSON
        for attempt in range(retries):
            try:
                resp = session.get(self.BASE_URL + path, params=params, timeout=20)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                if attempt < retries - 1:
                    time.sleep(random.uniform(1, 3))
                else:
                    logger.error(f"NGA API {path} failed: {e}")
                    return {}
        return {}

    def get_forum_threads(self, fid: int = CSGO_FID, page: int = 1,
                          order_by: str = "postdatedesc") -> List[dict]:
        """Get thread list of a board (thread.php)."""
        data = self._get_json("/thread.php", {"fid": fid, "page": page, "order_by": order_by})
        return data.get("data", {}).get("__T", [])

    def get_thread(self, tid: int) -> dict:
        """Get one thread including main post and replies (read.php)."""
        return self._get_json("/read.php", {"tid": tid})

    # ------------------------------------------------------------------
    # Historical CSV (backtest-safe)
    # ------------------------------------------------------------------
    def _load_csv(self) -> Optional[pd.DataFrame]:
        """Load historical NGA data from CSV."""
        if self._csv_data is not None:
            return self._csv_data
        if not os.path.exists(self.csv_path):
            logger.warning(f"NGA historical data CSV not found: {self.csv_path}")
            return None
        try:
            df = pd.read_csv(self.csv_path)
            df["publish_time"] = pd.to_datetime(df["publish_time"], errors="coerce")
            self._csv_data = df
            logger.debug(f"Loaded {len(df)} NGA posts from CSV: {self.csv_path}")
            return df
        except Exception as e:
            logger.error(f"Failed to load NGA data from CSV {self.csv_path}: {e}")
            return None

    def get_posts_from_csv(self, start_timestamp: Optional[float] = None,
                           end_timestamp: Optional[float] = None,
                           keywords: Optional[List[str]] = None,
                           min_score: int = 0, min_comments: int = 0,
                           limit: int = 25) -> List[MediaNews]:
        """Filter historical posts by time window, keywords and engagement."""
        df = self._load_csv()
        if df is None or df.empty:
            return []

        if start_timestamp and end_timestamp:
            start_dt = datetime.fromtimestamp(start_timestamp)
            end_dt = datetime.fromtimestamp(end_timestamp)
            df = df[(df["publish_time"] >= start_dt) & (df["publish_time"] <= end_dt)]

        if keywords:
            kw_lower = [k.lower() for k in keywords]
            mask = pd.Series(False, index=df.index)
            for col in ["title", "summary"]:
                if col in df.columns:
                    mask |= df[col].fillna("").str.lower().apply(
                        lambda text: any(k in text for k in kw_lower))
            df = df[mask]

        if "score" in df.columns:
            df = df[df["score"].fillna(0) >= min_score]
        if "num_comments" in df.columns:
            df = df[df["num_comments"].fillna(0) >= min_comments]

        df = df.sort_values("publish_time", ascending=False).head(limit)

        news_list = []
        for _, row in df.iterrows():
            news_list.append(MediaNews(
                title=row.get("title", ""),
                publish_time=row["publish_time"].strftime("%Y-%m-%d %H:%M:%S"),
                publisher=row.get("publisher", ""),
                link=row.get("link", ""),
                summary=row.get("summary", ""),
                score=int(row.get("score", 0)) if pd.notna(row.get("score", 0)) else None,
                num_comments=int(row.get("num_comments", 0)) if pd.notna(row.get("num_comments", 0)) else None,
            ))
        return news_list

    # ------------------------------------------------------------------
    # Ticker relevance
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_keywords(ticker: str) -> List[str]:
        """Extract match keywords from an item ticker: English parts + CN aliases."""
        keywords = []
        # English parts: split by | and () and spaces
        for sep in ["|", "(", ")", ",", "/"]:
            ticker = ticker.replace(sep, " ")
        for part in ticker.split():
            if part.strip():
                keywords.append(part.strip())

        # CN aliases for each English token
        for en, aliases in CN_ALIASES.items():
            if en.lower() in ticker.lower():
                keywords.extend(aliases)

        # deduplicate (case-insensitive), keep order
        seen = set()
        result = []
        for kw in keywords:
            k = kw.lower()
            if k not in seen:
                seen.add(k)
                result.append(kw)
        return result

    def get_ticker_relevant_posts(self, ticker: str, forums: Optional[List[int]] = None,
                                  limit: int = 15, min_score: int = 0,
                                  min_comments: int = 1,
                                  trading_date: Optional[datetime] = None,
                                  window_days: int = 7) -> List[MediaNews]:
        """Get NGA posts relevant to a CS2 ticker within [trading_date-window, trading_date].

        Only reads from the historical CSV (no live calls) so backtests don't
        leak future data. If no CSV data exists, returns [].
        """
        if trading_date:
            if isinstance(trading_date, str):
                trading_date = datetime.fromisoformat(trading_date.replace("Z", "+00:00"))
            elif hasattr(trading_date, "date"):
                trading_date = datetime.combine(trading_date, datetime.min.time())
            end_dt = trading_date.replace(hour=23, minute=59, second=59)
            start_dt = end_dt - timedelta(days=window_days)
            start_ts = start_dt.timestamp()
            end_ts = end_dt.timestamp()
        else:
            logger.warning("trading_date is required to fetch NGA posts from CSV")
            return []

        keywords = self._extract_keywords(ticker)
        logger.debug(f"NGA keywords for {ticker}: {keywords[:10]}... (total: {len(keywords)})")

        posts = self.get_posts_from_csv(
            start_timestamp=start_ts,
            end_timestamp=end_ts,
            keywords=keywords,
            min_score=min_score,
            min_comments=min_comments,
            limit=limit,
        )
        if posts:
            logger.debug(f"Using {len(posts)} NGA posts for {ticker} on {trading_date.date()}")
            return posts
        logger.warning(f"No NGA posts found for {ticker} on {trading_date.date()}")
        return []


def _thread_to_media_news(thread: dict, summary: str = "") -> Optional[MediaNews]:
    """Convert a NGA thread dict to MediaNews (for the fetch script)."""
    tid = thread.get("tid")
    subject = thread.get("subject") or ""
    if not tid or not subject:
        return None
    postdate = thread.get("postdate") or 0
    publish_time = datetime.fromtimestamp(postdate).strftime("%Y-%m-%d %H:%M:%S") if postdate else ""
    return MediaNews(
        title=subject,
        publish_time=publish_time,
        publisher=thread.get("author") or "",
        link=f"https://bbs.nga.cn/read.php?tid={tid}",
        summary=summary or subject,
        score=int(thread.get("recommend") or 0),
        num_comments=int(thread.get("replies") or 0),
    )
