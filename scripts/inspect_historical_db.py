import sqlite3

conn = sqlite3.connect("data/hermes_research/market_data.db")
cur = conn.cursor()
cur.execute("SELECT symbol, timeframe, count(*), min(timestamp), max(timestamp) FROM normalized_bars GROUP BY symbol, timeframe")
rows = cur.fetchall()
print("market_data.db -> normalized_bars breakdown:")
for r in rows:
    print(f"  Symbol: {r[0]}, TF: {r[1]}, Count: {r[2]}, From: {r[3]}, To: {r[4]}")

cur.execute("SELECT * FROM normalized_bars ORDER BY timestamp DESC LIMIT 3")
print("\nSample 3 latest rows:")
for r in cur.fetchall():
    print(" ", r)

cur.execute("SELECT * FROM normalized_bars ORDER BY timestamp ASC LIMIT 3")
print("\nSample 3 earliest rows:")
for r in cur.fetchall():
    print(" ", r)

conn.close()
