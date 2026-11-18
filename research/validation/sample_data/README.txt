optionsdata.shop - free NIFTY options sample (paid-pack format)
================================================================

Trading days : 2026-09-15 (weekly expiry day), 2026-09-16, 2026-09-17 (IST)
Instrument   : NIFTY index options (NSE, exchange_code NFO), 1-minute bars
Files        : one Parquet file per trading day per expiry, 9 files, 495,715 rows
               NIFTY_OPT_1min_<trade-date>_exp<expiry>.parquet
               Every listed strike, calls and puts, for each expiry live that day.
Bar times    : 09:15 to 15:30, IST wall-clock (timezone-naive timestamps)

Columns (identical to paid packs, same names and types):
  datetime       timestamp  bar start time, IST
  stock_code     string     NIFTY (SENSEX files use BSESEN)
  exchange_code  string     NFO (SENSEX files use BFO)
  product_type   string     Options
  expiry_date    string     DD-MON-YYYY, e.g. 15-SEP-2026
  strike_price   float      strike
  right          string     Call / Put
  open, high, low, close  float  traded premium within the bar
  volume         int        volume in the bar, as reported by the source
  open_interest  int        open interest at the bar

NOT included - in this sample or in any paid pack:
  implied volatility (IV), Greeks, bid/ask quotes, order-book depth, tick-by-tick trades.

Full schema : https://optionsdata.shop/free/schema
Pandas guide: https://optionsdata.shop/guides/load-nifty-options-parquet-pandas
Buy packs   : https://optionsdata.shop  (promocode SAVE10 = 10% off)
Support     : https://optionsdata.shop/contact

Derived from a broker historical API; not exchange-authorised; not affiliated with NSE/BSE.
Evaluation sample only - redistribution not permitted.
