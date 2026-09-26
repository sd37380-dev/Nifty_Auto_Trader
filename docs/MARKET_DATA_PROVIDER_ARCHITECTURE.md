# Market Data Provider Architecture

## 1. Provider Abstraction Principle

To ensure NIFTY Autonomous Trader remains vendor-agnostic and resilient against vendor API deprecation, all numerical data ingestion flows through the abstract `MarketDataProvider` contract.

```python
class MarketDataProvider(ABC):
    @property
    def name(self) -> str:
        return self.__class__.__name__

    @abstractmethod
    async def get_latest_candle(self, symbol: str, timeframe: Timeframe) -> Optional[Candle]:
        ...

    @abstractmethod
    async def get_recent_candles(self, symbol: str, timeframe: Timeframe, count: int = 100) -> List[Candle]:
        ...

    @abstractmethod
    async def get_historical_candles(self, symbol: str, timeframe: Timeframe, start_time: datetime, end_time: Optional[datetime] = None) -> List[Candle]:
        ...

    @abstractmethod
    async def get_market_status(self) -> MarketSessionStatus:
        ...

    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        ...
```

---

## 2. Concrete Implementations

### A. YahooFinanceProvider
* **Endpoint:** Yahoo Finance v8 chart API (`https://query1.finance.yahoo.com/v8/finance/chart/^NSEI`).
* **Symbol Mapping:** `NIFTY` / `NIFTY50` $\to$ `^NSEI`.
* **Timeframe Mapping:** `Timeframe.H1` $\to$ `"1h"`, `Timeframe.M15` $\to$ `"15m"`.
* **Resilience:** Configured with `httpx` async client, exponential backoff retries (`tenacity`), and custom desktop user-agent headers.
* **Integrity:** Automatically converts UTC unix timestamps into validated `Candle` models with IST timezone mapping.

### B. MockMarketDataProvider
* **Purpose:** Deterministic offline testing, synthetic scenario simulation, and CI/CD validation.
* **Features:**
  - Realistic synthetic geometric random walks around institutional base prices (default: 23,140.50).
  - Explicit failure injection (`set_simulate_failure(True)`).
  - Custom candle series injection (`load_candles(...)`).
  - Session state override (`set_forced_market_status(...)`).

---

## 3. Local SQLite Cache & Incremental Delta Sync

To avoid repetitive network calls and rate-limiting from external data providers, all ingested candles are stored locally in SQLite (`data/market/market_cache.db`).

### Schema & Indexing
```sql
CREATE TABLE IF NOT EXISTS candles (
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL,
    is_closed INTEGER NOT NULL,
    source TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (symbol, timeframe, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_candles_lookup 
ON candles(symbol, timeframe, timestamp DESC);
```

### Upsert Behavior
Duplicate candles with matching `(symbol, timeframe, timestamp)` are handled via `ON CONFLICT DO UPDATE SET ...`, allowing live forming candles to be refreshed until closed.
