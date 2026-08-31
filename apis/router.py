"""Router for APIs"""

from apis.steam.api import SteamAPI
from apis.cs2market.api import CS2MarketAPI
from apis.nga.api import NGAAPI

class APISource:
    CS2_MARKET = "cs2_market"
    NGA = "nga"
    STEAM = "steam"

class Router():
    """Router for APIs"""
    
    def __init__(self, source: APISource):
        if source == APISource.CS2_MARKET:
            self.api = CS2MarketAPI()
        elif source == APISource.NGA:
            self.api = NGAAPI()
        elif source == APISource.STEAM:
            self.api = SteamAPI()
        else:
            raise ValueError(f"Invalid API source: {source}")

    
    def get_cs2_stock_daily_candles_df(self, ticker, trading_date):
        """Get CS2 stock daily candles dataframe."""
        return self.api.get_cs2_stock_daily_candles_df(ticker=ticker, trading_date=trading_date)
    
    def get_cs2_stock_last_close_price(self, ticker, trading_date):
        """Get CS2 stock last close price."""
        return self.api.get_cs2_last_close_price(ticker=ticker, trading_date=trading_date)
    
    def get_nga_posts(self, fid, limit=25, trading_date=None, window_days=7):
        """Get posts from an NGA board (from historical CSV)."""
        return self.api.get_posts_from_csv(
            start_timestamp=None,
            end_timestamp=None,
            limit=limit,
        )
    
    def search_nga_posts(self, query, fid, limit=25, trading_date=None, window_days=7):
        """Search for posts matching a keyword in an NGA board."""
        return self.api.get_posts_from_csv(
            keywords=[query],
            limit=limit,
        )
    
    def get_ticker_relevant_nga_posts(self, ticker, forums, limit=15, min_score=0, min_comments=1, trading_date=None):
        """Get NGA posts relevant to a specific CS2 ticker/item."""
        return self.api.get_ticker_relevant_posts(
            ticker=ticker,
            forums=forums,
            limit=limit,
            min_score=min_score,
            min_comments=min_comments,
            trading_date=trading_date
        )

    # Steam API wrappers
    def get_steam_item_news(self, ticker, trading_date=None, limit=15):
        """Get Steam news relevant to a CS2 item."""
        return self.api.get_item_relevant_news(
            item_name=ticker,
            count=limit,
            trading_date=trading_date,
        )

    def get_steam_app_news(self, appid=SteamAPI.CS2_APP_ID, count=30, maxlength=300):
        """Get app-level Steam news (GetNewsForApp)."""
        return self.api.get_news_for_app(
            appid=appid,
            count=count,
            maxlength=maxlength,
        )

    def get_steam_historical_news(self, ticker, trading_date, window_days=7, limit=15, csv_path=None):
        """Load Steam news from historical CSV within a date window."""
        return self.api.get_historical_news_from_csv(
            ticker=ticker,
            trading_date=trading_date,
            window_days=window_days,
            limit=limit,
            csv_path=csv_path,
        )
