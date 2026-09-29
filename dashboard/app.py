"""
PM TERMINAL — Polymarket market-making & Fed monitor
====================================================
Run:  python app.py
Open: http://127.0.0.1:8050

  F1 BOOK   order book, depth, price, time & sales, liquidity rewards
  F2 FED    FOMC path: fed funds futures vs Kalshi vs Polymarket
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dash
from dash import ALL, Input, Output, State, ctx, dcc, html
from dash.exceptions import PreventUpdate

import api
import feed
import mm
import net
from pages import book, fed

HERE = os.path.dirname(os.path.abspath(__file__))

app = dash.Dash(
    __name__,
    title="PM TERMINAL",
    assets_folder=os.path.join(HERE, "assets"),
    suppress_callback_exceptions=True,
    update_title=None,
)

PAGES = {"/": ("F1", "BOOK", book), "/fed": ("F2", "FED", fed)}
SOURCES = ["GAMMA", "CLOB", "DATA", "WS", "KALSHI", "FRED", "CME"]
TAPE_SIZE = 25


def fkey(path, code, label):
    return dcc.Link(id=f"fkey-{label.lower()}", href=path, className="fkey",
                    children=[html.Span(code, className="code"), label])


app.layout = html.Div(className="term", children=[
    dcc.Location(id="url"),
    dcc.Store(id="sel-market", storage_type="session"),
    dcc.Store(id="tape-data"),
    dcc.Interval(id="clock-tick", interval=1000),
    dcc.Interval(id="tape-tick", interval=20_000),

    html.Div(id="tape", className="tape", children=html.Div("LOADING TAPE …", className="tape-empty")),
    html.Div(className="fbar", children=[
        html.Div("PM▪TERMINAL", className="brand"),
        *[fkey(path, code, label) for path, (code, label, _) in PAGES.items()],
        html.Div(className="fbar-spacer"),
        html.Div(id="clock", className="clock"),
    ]),
    html.Div(id="page", className="page"),
    html.Div(id="statusbar", className="statusbar"),
])


@app.callback(
    Output("page", "children"),
    *[Output(f"fkey-{label.lower()}", "className") for _, label, _ in PAGES.values()],
    Input("url", "pathname"),
)
def route(path):
    path = path if path in PAGES else "/"
    classes = ["fkey active" if p == path else "fkey" for p in PAGES]
    return (PAGES[path][2].layout(), *classes)


@app.callback(
    Output("tape", "children"),
    Output("tape-data", "data"),
    Input("tape-tick", "n_intervals"),
)
def tape(_n):
    markets = api.top_markets(TAPE_SIZE)
    if not markets:
        status = net.health().get("GAMMA", {})
        msg = f'TAPE UNAVAILABLE — GAMMA {status["msg"]}' if status and not status["ok"] else "LOADING MARKETS …"
        return html.Div(msg, className="tape-empty"), []
    items = []
    for i, m in enumerate(markets):
        chg = m["day_change"]
        arrow, color = ("▲", "var(--up)") if chg and chg > 0 else ("▼", "var(--down)") if chg and chg < 0 else ("■", "var(--muted)")
        items.append(html.Span(id={"type": "tape", "index": i}, n_clicks=0, className="tape-item", children=[
            html.Span(m["question"][:48].upper(), className="tape-name"),
            html.Span(mm.fmt_cents(api.mid_price(m)), className="tape-px"),
            html.Span(f"{arrow}{abs(chg or 0) * 100:.1f}", style={"color": color}),
        ]))
    return html.Div(items, className="tape-track"), markets


@app.callback(
    Output("sel-market", "data", allow_duplicate=True),
    Output("url", "pathname"),
    Input({"type": "tape", "index": ALL}, "n_clicks"),
    State("tape-data", "data"),
    prevent_initial_call=True,
)
def tape_pick(clicks, markets):
    trig = ctx.triggered_id
    if not trig or not markets or not any(clicks or []):
        raise PreventUpdate
    idx = trig["index"]
    if idx >= len(markets) or not clicks[idx]:
        raise PreventUpdate
    return markets[idx], "/"


@app.callback(
    Output("clock", "children"),
    Output("statusbar", "children"),
    Input("clock-tick", "n_intervals"),
    State("sel-market", "data"),
)
def status(_n, market):
    now = datetime.now(timezone.utc)
    clock = f'{now.strftime("%d-%b-%y").upper()}  {now.strftime("%H:%M:%S")} UTC  ·  {datetime.now().strftime("%H:%M")} LOCAL'

    health = net.health()
    pills = []
    for src in SOURCES:
        h = health.get(src)
        if h is None:
            pills.append(html.Span([html.B(src), "IDLE"], className="pill idle"))
        elif h["ok"]:
            pills.append(html.Span([html.B(src), "OK"], className="pill ok"))
        else:
            pills.append(html.Span([html.B(src), h["msg"]], className="pill err", title=h["msg"]))

    cache = api.cache_status()
    info = [f'{cache["count"]:,} MKTS' + (" ↻" if cache["warming"] else "")]
    info.append(f"{len(feed.active_feeds())} FEEDS")
    if market:
        f = feed.get_feed(market)
        info.append(f"{f.status} · {f.msg_count:,} MSGS")
    return clock, pills + [html.Span("  ·  ".join(info), className="status-msg")]


book.register(app)
fed.register(app)


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=int(os.environ.get("PORT", 8050)))
