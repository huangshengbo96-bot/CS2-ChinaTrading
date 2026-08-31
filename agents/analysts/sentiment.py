from graph.constants import AgentKey, Signal
from llm.prompt import (
    SENTIMENT_PROMPT,
    NGA_SENTIMENT_INSUFFICIENT_DATA_PROMPT,
    NGA_SENTIMENT_FETCH_ERROR_PROMPT,
)
from graph.schema import FundState, AnalystSignal
from llm.inference import agent_call
from apis.router import Router, APISource
from util.cs2_db_helper import get_cs2_db
from util.logger import logger

# Sentiment analysis thresholds (NGA-adapted)
thresholds = {
    "nga_post_count": 5,  # Min ticker-relevant posts; NGA single-item threads are rarer than Reddit
    "nga_fid": 482,       # CS:GO board on NGA
    "nga_window_days": 7,
    # NGA quality filtering thresholds
    "nga_min_score": 0,      # NGA threads have no upvote score like Reddit; keep 0
    "nga_min_comments": 1,   # Minimum number of replies
    "nga_relevant_limit": 15  # Limit for ticker-relevant posts
}


def sentiment_agent(state: FundState):
    """
    Sentiment analysis specialist analyzing NGA community sentiment for CS2 market items.
    This agent focuses on Chinese community discussions, sentiment, and market sentiment trends.
    """
    agent_name = AgentKey.SENTIMENT
    ticker = state["ticker"]
    trading_date = state["trading_date"]
    llm_config = state["llm_config"]
    portfolio_id = state["portfolio"].id
    exp_name = state["exp_name"]
    
    db = get_cs2_db()
    
    logger.log_agent_status(agent_name, ticker, "Fetching NGA market sentiment")
    
    # Get the NGA posts
    router = Router(APISource.NGA)
    
    try:
        # Use ticker-relevant search on the CS:GO board
        # Pass trading_date to filter posts (only posts from trading_date - 7 days to trading_date)
        nga_posts = router.get_ticker_relevant_nga_posts(
            ticker=ticker,
            forums=[thresholds["nga_fid"]],
            limit=thresholds["nga_relevant_limit"],
            min_score=thresholds["nga_min_score"],
            min_comments=thresholds["nga_min_comments"],
            trading_date=trading_date
        )
        
        # If no posts or too few posts, use insufficient-data prompt
        min_posts = thresholds["nga_post_count"]
        if not nga_posts or len(nga_posts) < min_posts:
            post_count = len(nga_posts) if nga_posts else 0
            logger.warning(f"Insufficient NGA posts for {ticker}: {post_count} < {min_posts}. Using insufficient-data prompt.")

            prompt = NGA_SENTIMENT_INSUFFICIENT_DATA_PROMPT.format(
                ticker=ticker,
                post_count=post_count,
                min_posts=min_posts
            )
            
            signal = agent_call(
                prompt=prompt,
                llm_config=llm_config,
                pydantic_model=AnalystSignal,
            )
            
            logger.log_signal(agent_name, ticker, signal)
            db.save_signal(portfolio_id, agent_name, ticker, prompt, signal)
            
            return {"analyst_signals": [signal]}
        
        logger.info(f"Found {len(nga_posts)} ticker-relevant NGA posts for {ticker}. Proceeding with LLM analysis.")
                
    except Exception as e:
        logger.error(f"Failed to fetch NGA sentiment for {ticker}: {e}")

        prompt = NGA_SENTIMENT_FETCH_ERROR_PROMPT.format(ticker=ticker)
        
        signal = agent_call(
            prompt=prompt,
            llm_config=llm_config,
            pydantic_model=AnalystSignal,
        )

        logger.log_signal(agent_name, ticker, signal)
        db.save_signal(portfolio_id, agent_name, ticker, prompt, signal)

        return {"analyst_signals": [signal]}
    
    # Process NGA posts
    nga_posts_dict = [m.model_dump_json() for m in nga_posts]
    
    prompt = SENTIMENT_PROMPT.format(
        ticker=ticker,
        nga_posts=nga_posts_dict,
        post_count=len(nga_posts)
    )
    
    logger.info(f"Using {len(nga_posts)} ticker-relevant NGA posts for {ticker} sentiment analysis")
    
    # Get LLM signal
    signal = agent_call(
        prompt=prompt,
        llm_config=llm_config,
        pydantic_model=AnalystSignal,
    )

    # save signal
    logger.log_signal(agent_name, ticker, signal)
    db.save_signal(portfolio_id, agent_name, ticker, prompt, signal)

    return {"analyst_signals": [signal]}
