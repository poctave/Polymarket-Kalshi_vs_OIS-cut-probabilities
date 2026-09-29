# Polymarket-Kalshi_vs_OIS-cut-probabilities
Visualizes differences between how Fed-Fund-Futures, Overnight Index Swaps and prediction markets price Fed rate moves.

The project is now **PM Terminal**: a read-only dashboard with a 2010s trading-terminal look and two pages.
It places no orders and holds no keys.

| Key | Page | What it shows |
|-----|------|---------------|
| **F2** | FED | Expected FOMC path implied by CBOT fed funds futures (CME FedWatch-style) vs Kalshi vs Polymarket, per-meeting cut / hold / hike odds, and the biggest pricing gap |
| **F1** | BOOK | Polymarket market search, live YES/NO order books, depth, price history, time & sales, liquidity-reward band |

<img width="1879" height="630" alt="Screenshot 2026-09-29 at 23 03 45" src="https://github.com/user-attachments/assets/a265a011-0e34-4483-b0f8-bc1460cbcd20" />

<img width="1061" height="735" alt="Screenshot 2026-03-08 at 23 10 06" src="https://github.com/user-attachments/assets/b4f449cc-a1dc-4f93-b2fe-44fab27525b5" />

## Run

```bash
cd dashboard
python3 -m pip install -r requirements.txt
python3 app.py            # http://127.0.0.1:8050
python3 -m pytest tests   # offline test suite
```

Shortcuts: `F1`/`F2` switch pages, `/` or `Ctrl+K` focuses the search line, and clicking a name on the ticker tape loads that market.
The status bar at the bottom shows the health of each data source.

## How the FED page works

- **Rate moves are signed:** negative is a cut, positive is a hike. Earlier versions clipped hikes to zero.
- **Fed funds futures:** each ZQ contract settles on the month-average EFFR. Starting from today's EFFR and walking the meetings in order:
  - `post = (N·R_m − D·pre) / (N − D)`
  - or the next month's contract, when the meeting falls in the last week of the month and the next month has no meeting
  - The expected move is split across the two nearest 25bp outcomes.
- **Kalshi:** one call gets every `KXFEDDECISION` meeting. Meeting dates come from the events' `strike_date`. Outcome prices are the mids of `yes_bid_dollars`/`yes_ask_dollars` (Kalshi dropped the old cent fields), normalized to 100%.
- **Polymarket:** "Fed … after <month> meeting" markets are found in the Gamma market list, with no hard-coded slugs. Prices are bid/ask mids, not last trade.
- **Gap:** futures-implied probability minus the venue price, for the most mispriced outcome the model gives probability to. Flags cover only the next 2 meetings, because further out chained-futures error and term premium dominate. Treat gaps as leads, not arbitrage.
- **OIS:** not wired in yet. Fed funds futures are the rates-market reference.

## Data sources

| Source | Used for |
|--------|----------|
| fred.stlouisfed.org | EFFR |
| Yahoo Finance (`ZQ*.CBT`) | 30-day fed funds futures |
| api.elections.kalshi.com | FOMC calendar, Fed decision odds |
| gamma-api / clob / data-api.polymarket.com (REST + websocket) | markets, order books, price history, trades |

None of them need authentication.

**Network note:** some French ISPs DNS-block Polymarket (the response is an `anj.fr` certificate). The status bar then shows `BLOCKED BY ISP DNS (ANJ)`.
The FED page still works from Kalshi, FRED and Yahoo.

## Layout

```
dashboard/
  app.py          shell: ticker tape, F-key bar, routing, status bar
  pages/fed.py    F2 FED page         pages/book.py   F1 BOOK page
  fed/model.py    implied path, outcome distributions, gaps
  fed/sources.py  FRED, Yahoo ZQ, Kalshi, Polymarket Fed markets
  fed/monitor.py  joins sources, background refresh
  api.py          Polymarket REST       feed.py   per-market websocket feeds
  mm.py           reward-band maths     net.py    HTTP + per-source health
  theme.py        palette (matches assets/terminal.css)
  tests/          pytest suite (offline)
generate_report.py   builds Polymarket_Trading_Bot_Research.pdf (needs fpdf2)
```
