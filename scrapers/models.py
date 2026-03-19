"""
Unified data models for normalized odds across all sportsbooks.
Every scraper converts its raw data into these standard models.
"""

from pydantic import BaseModel
from typing import Optional, List, Dict, Tuple
from datetime import datetime
from enum import Enum


class MarketType(str, Enum):
    MONEYLINE = "moneyline"
    SPREAD = "spread"
    TOTAL = "total"
    PLAYER_PROP = "player_prop"
    FUTURES = "futures"
    OTHER = "other"


class Outcome(BaseModel):
    """A single betting outcome (e.g., 'Kansas City Chiefs -150')"""
    name: str
    price_american: Optional[int] = None
    price_decimal: Optional[float] = None
    point: Optional[float] = None  # spread or total line
    description: Optional[str] = None


class Market(BaseModel):
    """A betting market (e.g., 'Moneyline', 'Point Spread', 'Total')"""
    market_type: MarketType
    name: str
    outcomes: List[Outcome] = []


class Event(BaseModel):
    """A single sporting event (game/match)"""
    event_id: str
    sport: str
    league: str
    home_team: str
    away_team: str
    description: str
    start_time: Optional[datetime] = None
    is_live: bool = False
    markets: List[Market] = []


class SportsbookSnapshot(BaseModel):
    """All odds from a single sportsbook at a point in time"""
    sportsbook: str
    sport: str
    league: str
    fetched_at: datetime
    events: List[Event] = []


class AggregatedEvent(BaseModel):
    """An event with odds from multiple sportsbooks side by side"""
    home_team: str
    away_team: str
    sport: str
    league: str
    start_time: Optional[datetime] = None
    is_live: bool = False
    sportsbook_odds: dict = {}  # sportsbook_name -> Event


class BestOdds(BaseModel):
    """Best available odds across all books for an aggregated event"""
    event: AggregatedEvent
    best_prices: dict = {}  # market_type -> {outcome_name -> (price, sportsbook)}

    class Config:
        arbitrary_types_allowed = True