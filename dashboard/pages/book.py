"""
F1 BOOK — single-market order book, depth, price history, time & sales and
liquidity-reward monitor.
"""

from __future__ import annotations

from datetime import datetime, timezone

import plotly.graph_objects as go
from dash import ALL, Input, Output, State, ctx, dcc, html, no_update
from dash.exceptions import PreventUpdate
from plotly.subplots import make_subplots

import api
import feed
import mm
import theme as T
from net import NetError

LADDER_DEPTH = 10
DEPTH_LEVELS = 40
TAS_ROWS = 30
BIG_PRINT_USD = 1000


# ── Layout ────────────────────────────────────────────────────────────────────

def panel(title, body, aux=None, body_class="panel-body", **kw):
    head = [html.Span(title, className="t")]
    if aux is not None:
        head.append(html.Span(aux, className="aux"))
    return html.Div(className="panel", children=[
        html.Div(head, className="panel-title"),
        html.Div(body, className=body_class),
    ], **kw)


def q_cell(label, cid, extra=""):
    return html.Div(className="q-cell", children=[
        html.Div(label, className="q-label"),
        html.Div("--", id=cid, className=f"q-val {extra}".strip()),
    ])


def layout():
    return html.Div([
        dcc.Interval(id="tick", interval=500),
        dcc.Interval(id="tick-slow", interval=3000),
        dcc.Store(id="search-results"),
        dcc.Store(id="book-state", data={}),

        html.Div(className="cmdline", children=[
            html.Div("MKT", className="cmd-label"),
            dcc.Input(id="cmd", className="cmd-input", type="text", autoComplete="off",
                      placeholder="KEYWORDS OR POLYMARKET URL, THEN <GO>   e.g. FED DECEMBER · BITCOIN 150K"),
            html.Button("GO", id="cmd-go", className="go-key", n_clicks=0),
            html.Div("/ OR CTRL+K TO FOCUS", className="cmd-hint"),
        ]),
        html.Div(id="results-panel"),

        html.Div(id="sec-header", className="sec-header"),
        html.Div(className="quote-strip", children=[
            q_cell("BID", "q-bid"), q_cell("ASK", "q-ask"), q_cell("MID ¢", "q-mid"),
            q_cell("SPRD ¢", "q-spread"), q_cell("LAST", "q-last"), q_cell("1D CHG ¢", "q-chg"),
            q_cell("24H VOL", "q-vol24", "small"), q_cell("TOT VOL", "q-vol", "small"),
            q_cell("LIQUIDITY", "q-liq", "small"), q_cell("EXPIRES", "q-exp", "small"),
            q_cell("FEED", "q-feed", "small"),
        ]),

        html.Div(className="grid grid-book", children=[
            panel(html.Span("YES BOOK", id="yes-title"), html.Div(id="yes-book", className="ladder"), aux="PX ¢ / SHARES"),
            panel(html.Span("NO BOOK", id="no-title"), html.Div(id="no-book", className="ladder"), aux="PX ¢ / SHARES"),
            panel("DEPTH", dcc.Graph(id="depth-chart", config={"displayModeBar": False},
                                     style={"height": "300px"}), aux="CUMULATIVE SHARES · YES",
                  body_class="panel-body flush"),
        ]),

        html.Div(className="grid grid-lower", children=[
            panel("PRICE · YES", dcc.Graph(id="price-chart", config={"displayModeBar": False},
                                           style={"height": "468px"}),
                  aux=dcc.RadioItems(id="hist-range", className="range-keys", value="1D",
                                     options=[{"label": k, "value": k} for k in api.HISTORY_RANGES]),
                  body_class="panel-body flush"),
            html.Div(className="stack", children=[
                panel("TIME & SALES", html.Div(id="tas", className="scroll", style={"maxHeight": "250px"}),
                      aux="UTC", body_class="panel-body flush"),
                panel("LIQUIDITY REWARDS", html.Div(id="rewards")),
            ]),
        ]),
    ])


# ── Renderers ─────────────────────────────────────────────────────────────────

def _search_table(markets: list, query: str):
    if not markets:
        return html.Div(className="panel", style={"marginBottom": "6px"}, children=[
            html.Div(className="panel-title", children=[html.Span("SEARCH", className="t")]),
            html.Div(f'NO MARKETS MATCH "{query.upper()}"', className="waiting"),
        ])
    head = html.Tr([html.Th("#"), html.Th("MARKET", className="l"), html.Th("YES ¢"), html.Th("24H VOL"),
                    html.Th("LIQ"), html.Th("RWD/DAY"), html.Th("EXPIRES")])
    rows = []
    for i, m in enumerate(markets):
        mid = api.mid_price(m)
        rows.append(html.Tr(id={"type": "pick", "index": i}, n_clicks=0, className="pick-row", children=[
            html.Td(f"{i + 1}", className="dim"),
            html.Td(m["question"], className="l q", title=m["question"]),
            html.Td(mm.fmt_cents(mid), className="num"),
            html.Td(mm.fmt_money(m["volume_24h"])),
            html.Td(mm.fmt_money(m["liquidity"]), className="dim"),
            html.Td(f'${m["rewards_daily"]:,.0f}' if m["rewards_daily"] else "-", className="dim"),
            html.Td(mm.fmt_expiry(m["end_date"]), className="dim"),
        ]))
    return html.Div(className="panel", style={"marginBottom": "6px"}, children=[
        html.Div(className="panel-title", children=[
            html.Span(f'SEARCH  "{query.upper()}"' if query else "TOP MARKETS BY 24H VOLUME", className="t"),
            html.Span(f"{len(markets)} RESULTS · CLICK TO LOAD", className="aux"),
        ]),
        html.Div(className="scroll", style={"maxHeight": "300px"},
                 children=html.Table([html.Thead(head), html.Tbody(rows)], className="tbl")),
    ])


def _ladder(book: feed.OrderBook, view, dec: int, err: str = ""):
    bids, asks = book.levels(LADDER_DEPTH)
    if not bids and not asks:
        return html.Div(err or "WAITING FOR BOOK …", className="waiting err" if err else "waiting")
    max_size = max([s for _, s in bids] + [s for _, s in asks], default=1) or 1

    def row(p, s, cum, side):
        return html.Div(className="lad-row", children=[
            html.Div(className=f"lad-bar {side}", style={"width": f"{min(s / max_size, 1) * 100:.1f}%"}),
            html.Span("◆" if mm.in_band(p, view) else "", className="band"),
            html.Span(mm.fmt_cents(p, dec), className=f"px {side}"),
            html.Span(f"{s:,.0f}", className="sz"),
            html.Span(f"{cum:,.0f}", className="cum"),
        ])

    ask_rows = [row(p, s, c, "ask") for p, s, c in reversed(mm.cumulative(asks))]
    bid_rows = [row(p, s, c, "bid") for p, s, c in mm.cumulative(bids)]
    spread = html.Div(className="lad-spread", children=[
        html.Span("SPREAD"),
        html.Span(f"{(asks[0][0] - bids[0][0]) * 100:.{dec}f}¢" if bids and asks else "ONE-SIDED"),
    ])
    head = html.Div(className="lad-head", children=[html.Span(""), html.Span("PX"), html.Span("SIZE"), html.Span("CUM")])
    return [head] + ask_rows + [spread] + bid_rows


def _depth_fig(book: feed.OrderBook, view) -> go.Figure:
    bids, asks = book.levels(DEPTH_LEVELS)
    if not bids and not asks:
        return T.empty_fig("NO DEPTH")
    fig = go.Figure()
    if bids:
        cb = mm.cumulative(bids)
        fig.add_trace(go.Scatter(x=[p * 100 for p, _, _ in cb], y=[c for _, _, c in cb], name="BID", mode="lines",
                                 line=dict(color=T.UP, width=1.5, shape="vh"), fill="tozeroy",
                                 fillcolor=T.UP_FILL, hovertemplate="%{x:.1f}¢  %{y:,.0f} sh<extra>BID</extra>"))
    if asks:
        ca = mm.cumulative(asks)
        fig.add_trace(go.Scatter(x=[p * 100 for p, _, _ in ca], y=[c for _, _, c in ca], name="ASK", mode="lines",
                                 line=dict(color=T.DOWN, width=1.5, shape="vh"), fill="tozeroy",
                                 fillcolor=T.DOWN_FILL, hovertemplate="%{x:.1f}¢  %{y:,.0f} sh<extra>ASK</extra>"))
    if view and view.get("lo") is not None:
        fig.add_vrect(x0=view["lo"] * 100, x1=view["hi"] * 100, fillcolor="rgba(255,216,61,0.07)",
                      line=dict(color="rgba(255,216,61,0.35)", width=1, dash="dot"))
    bid, ask = book.best()
    mid = mm.mid_of(bid, ask)
    if mid is not None:
        fig.add_vline(x=mid * 100, line=dict(color=T.YELLOW, width=1, dash="dash"))
    fig.update_layout(**T.base_layout(
        showlegend=False, margin=dict(l=52, r=10, t=8, b=30),
        xaxis=T.axis(title="PRICE ¢", ticksuffix=""),
        yaxis=T.axis(title="SHARES", rangemode="tozero"),
    ))
    return fig


def _price_fig(history: list, live: list, range_key: str, err: str = "") -> go.Figure:
    if not history and not live:
        return T.empty_fig(err or "NO PRICE HISTORY", T.DOWN if err else T.MUTED)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.76, 0.24], vertical_spacing=0.04)
    if history:
        xs = [datetime.fromtimestamp(t, tz=timezone.utc) for t, _ in history]
        fig.add_trace(go.Scatter(x=xs, y=[p * 100 for _, p in history], name="PRICE",
                                 line=dict(color=T.UP, width=1.6), fill="tozeroy", fillcolor=T.UP_FILL,
                                 hovertemplate="%{y:.1f}¢<extra>HIST</extra>"), row=1, col=1)
    if history and live:
        start = history[0][0]
        live = [pt for pt in live if pt["ts"] >= start]
    if live:
        xs = [datetime.fromtimestamp(pt["ts"], tz=timezone.utc) for pt in live]
        fig.add_trace(go.Scatter(x=xs, y=[pt["ask"] * 100 for pt in live], name="ASK",
                                 line=dict(color=T.DOWN, width=1, dash="dot"),
                                 hovertemplate="%{y:.1f}¢<extra>ASK</extra>"), row=1, col=1)
        fig.add_trace(go.Scatter(x=xs, y=[pt["bid"] * 100 for pt in live], name="BID",
                                 line=dict(color=T.UP, width=1, dash="dot"),
                                 hovertemplate="%{y:.1f}¢<extra>BID</extra>"), row=1, col=1)
        fig.add_trace(go.Scatter(x=xs, y=[pt["mid"] * 100 for pt in live], name="LIVE MID",
                                 line=dict(color=T.CYAN, width=2),
                                 hovertemplate="%{y:.2f}¢<extra>MID</extra>"), row=1, col=1)
        fig.add_trace(go.Scatter(x=xs, y=[pt["spread"] * 100 for pt in live], name="SPREAD ¢",
                                 line=dict(color=T.AMBER, width=1.2, shape="hv"), fill="tozeroy",
                                 fillcolor="rgba(255,160,40,0.15)",
                                 hovertemplate="%{y:.2f}¢<extra>SPREAD</extra>"), row=2, col=1)
    else:
        fig.add_annotation(text="LIVE SPREAD APPEARS WHEN THE FEED CONNECTS", x=0.5, y=0.1, xref="paper",
                           yref="paper", showarrow=False, font=dict(color=T.MUTED, size=10))
    ys = [p * 100 for _, p in history] + [v * 100 for pt in live for v in (pt["bid"], pt["ask"])]
    lo, hi = min(ys), max(ys)
    pad = max((hi - lo) * 0.12, 0.5)
    fig.update_layout(**T.base_layout(
        hovermode="x unified", margin=dict(l=48, r=12, t=22, b=26), uirevision=range_key,
        xaxis=T.axis(showticklabels=False), xaxis2=T.axis(),
        yaxis=T.axis(ticksuffix="¢", side="right", range=[max(0, lo - pad), min(100, hi + pad)]),
        yaxis2=T.axis(ticksuffix="¢", side="right", rangemode="tozero"),
    ))
    return fig


def _tas(trades: list, dec: int):
    if not trades:
        return html.Div("NO PRINTS YET", className="waiting")
    head = html.Tr([html.Th("TIME", className="l"), html.Th("SIDE", className="l"), html.Th("OUT", className="l"),
                    html.Th("PX ¢"), html.Th("SIZE"), html.Th("$")])
    rows = []
    for t in trades[:TAS_ROWS]:
        cls = "buy" if t["side"] == "BUY" else "sell"
        big = t["notional"] >= BIG_PRINT_USD
        rows.append(html.Tr([
            html.Td(datetime.fromtimestamp(t["ts"], tz=timezone.utc).strftime("%H:%M:%S") if t["ts"] else "--",
                    className="l dim"),
            html.Td(t["side"] or "--", className=f"l {cls}"),
            html.Td((t["outcome"] or "")[:6].upper(), className="l"),
            html.Td(mm.fmt_cents(t["price"], dec), className=cls),
            html.Td(f'{t["size"]:,.0f}'),
            html.Td(f'{t["notional"]:,.0f}', className="num" if big else "dim"),
        ]))
    return html.Table([html.Thead(head), html.Tbody(rows)], className="tbl")


def _rewards(view, dec: int):
    if view is None:
        return html.Div("NO LIQUIDITY REWARDS ON THIS MARKET", className="waiting")

    def kv(k, v, cls=""):
        return [html.Div(k, className="k"), html.Div(v, className=f"v {cls}".strip())]

    band = (f'{mm.fmt_cents(view["lo"], dec)} – {mm.fmt_cents(view["hi"], dec)}¢'
            if view.get("lo") is not None else "--")
    return html.Div([
        html.Div(className="kv", children=
            kv("DAILY POOL", f'${view["daily"]:,.2f}' if view["daily"] else "--", "up" if view["daily"] else "dim")
            + kv("MAX SPREAD", f'±{view["max_spread_c"]:g}¢ FROM MID')
            + kv("MIN SIZE", f'{view["min_size"]:,.0f} SH')
            + kv("SCORING BAND", band)
            + kv("BID DEPTH IN BAND", f'{view["bid_depth"]:,.0f} SH')
            + kv("ASK DEPTH IN BAND", f'{view["ask_depth"]:,.0f} SH')
            + kv("BOOK SPREAD", f'{view["book_spread_c"]:.{dec}f}¢' if view["book_spread_c"] is not None else "--")
            + kv("TWO-SIDED REQUIRED", "YES" if view["two_sided"] else "NO", "down" if view["two_sided"] else "dim")
        ),
        html.Div("◆ marks book levels inside the scoring band. Your quotes earn rewards only if they rest "
                 "inside the band and meet min size; the band follows the midpoint, so re-quote as it moves. "
                 "Depth counts aggregated levels ≥ min size (approximation).", className="note"),
    ])


def _sec_header(m: dict, f: feed.MarketFeed):
    sub = [html.B("CID "), m["condition_id"][:10] + "…", "  ·  ", html.B("ENDS "), (m["end_date"] or "--")[:10],
           "  ·  ", html.B("TICK "), f'{(f.tick_size or m["tick_size"]) * 100:g}¢']
    if m.get("neg_risk"):
        sub += ["  ·  ", html.B("NEG-RISK")]
    if m.get("event_title") and m["event_title"] != m["question"]:
        sub += ["  ·  ", html.B("EVENT "), m["event_title"]]
    return [html.Div(m["question"], className="sec-title"), html.Div(sub, className="sec-sub")]


WELCOME = html.Div(className="sec-empty", children=[
    html.Span("NO SECURITY LOADED", className="big"),
    "TYPE A KEYWORD IN THE MKT LINE AND PRESS <GO>, OR CLICK A NAME ON THE TICKER TAPE.",
])


# ── Callbacks ─────────────────────────────────────────────────────────────────

def register(app):

    @app.callback(
        Output("search-results", "data"),
        Output("results-panel", "children"),
        Input("cmd", "n_submit"),
        Input("cmd-go", "n_clicks"),
        State("cmd", "value"),
        prevent_initial_call=True,
    )
    def do_search(_submit, _clicks, query):
        query = (query or "").strip()
        try:
            markets = api.search_markets(query)
        except NetError as exc:
            return [], html.Div(className="panel", style={"marginBottom": "6px"}, children=[
                html.Div(className="panel-title", children=[html.Span("SEARCH", className="t")]),
                html.Div(f"SEARCH FAILED — {exc}", className="waiting err"),
            ])
        return markets, _search_table(markets, query)

    @app.callback(
        Output("sel-market", "data", allow_duplicate=True),
        Output("results-panel", "children", allow_duplicate=True),
        Input({"type": "pick", "index": ALL}, "n_clicks"),
        State("search-results", "data"),
        prevent_initial_call=True,
    )
    def pick(clicks, results):
        trig = ctx.triggered_id
        if not trig or not results or not any(clicks):
            raise PreventUpdate
        idx = trig["index"]
        if idx >= len(results) or not clicks[idx]:
            raise PreventUpdate
        return results[idx], []

    @app.callback(
        Output("sec-header", "children"),
        Output("yes-title", "children"), Output("no-title", "children"),
        Output("q-bid", "children"), Output("q-bid", "className"),
        Output("q-ask", "children"), Output("q-ask", "className"),
        Output("q-mid", "children"), Output("q-mid", "className"),
        Output("q-spread", "children"),
        Output("q-last", "children"), Output("q-last", "className"),
        Output("q-chg", "children"), Output("q-chg", "className"),
        Output("q-vol24", "children"), Output("q-vol", "children"),
        Output("q-liq", "children"), Output("q-exp", "children"),
        Output("q-feed", "children"), Output("q-feed", "className"),
        Output("yes-book", "children"), Output("no-book", "children"),
        Output("depth-chart", "figure"),
        Output("tas", "children"), Output("rewards", "children"),
        Output("book-state", "data"),
        Input("tick", "n_intervals"),
        Input("sel-market", "data"),
        State("book-state", "data"),
    )
    def refresh(n, market, state):
        state = state or {}
        if not market:
            if state.get("cid") == "":
                raise PreventUpdate
            ef = T.empty_fig("NO SECURITY LOADED")
            dash_ = "--"
            return ([WELCOME], "YES BOOK", "NO BOOK",
                    dash_, "q-val", dash_, "q-val", dash_, "q-val", dash_, dash_, "q-val", dash_, "q-val",
                    dash_, dash_, dash_, dash_, "IDLE", "q-val small",
                    html.Div("—", className="waiting"), html.Div("—", className="waiting"), ef,
                    html.Div("—", className="waiting"), html.Div("—", className="waiting"), {"cid": ""})

        f = feed.get_feed(market)
        if state.get("cid") == market["condition_id"] and state.get("version") == f.version:
            raise PreventUpdate

        dec = mm.price_decimals(f.tick_size)
        yes_bid, yes_ask = f.yes.best()
        no_bid, no_ask = f.no.best()
        mid = mm.mid_of(yes_bid, yes_ask)
        spreads, trades = f.history()

        last = None
        if trades:
            t0 = trades[0]
            last = t0["price"] if t0["outcome"] == market["outcomes"][0] else 1 - t0["price"]

        same = state.get("cid") == market["condition_id"]
        flip = 1 - state.get("flip", 0) if same else 0

        def flash(key, val, base="q-val"):
            prev = state.get(key) if same else None
            if val is None or prev is None or abs(val - prev) < 1e-9:
                return base
            return f"{base} {'flash-up' if val > prev else 'flash-down'}-{flip}"

        chg = market.get("day_change")
        chg_cls = "q-val" + (" up" if chg and chg > 0 else " down" if chg and chg < 0 else "")

        yes_bids, yes_asks = f.yes.levels(DEPTH_LEVELS)
        no_bids, no_asks = f.no.levels(DEPTH_LEVELS)
        yes_view = mm.reward_view(market, yes_bids, yes_asks, yes_bid, yes_ask)
        no_view = mm.reward_view(market, no_bids, no_asks, no_bid, no_ask)

        feed_cls = "q-val small " + ("up" if f.connected else "down")
        out_yes, out_no = (o.upper()[:18] for o in market["outcomes"])

        return (
            _sec_header(market, f),
            f"{out_yes} BOOK", f"{out_no} BOOK",
            mm.fmt_cents(yes_bid, dec), flash("bid", yes_bid),
            mm.fmt_cents(yes_ask, dec), flash("ask", yes_ask),
            mm.fmt_cents(mid, dec + 1), flash("mid", mid),
            f"{(yes_ask - yes_bid) * 100:.{dec}f}" if mid is not None else "--",
            mm.fmt_cents(last, dec), flash("last", last),
            f"{chg * 100:+.1f}" if chg is not None else "--", chg_cls,
            mm.fmt_money(market["volume_24h"]), mm.fmt_money(market["volume_total"]),
            mm.fmt_money(market["liquidity"]), mm.fmt_expiry(market["end_date"]),
            f.status, feed_cls,
            _ladder(f.yes, yes_view, dec, f.error), _ladder(f.no, no_view, dec, f.error),
            _depth_fig(f.yes, yes_view),
            _tas(trades, dec), _rewards(yes_view, dec),
            {"cid": market["condition_id"], "version": f.version,
             "bid": yes_bid, "ask": yes_ask, "mid": mid, "last": last, "flip": flip},
        )

    @app.callback(
        Output("price-chart", "figure"),
        Input("hist-range", "value"),
        Input("tick-slow", "n_intervals"),
        Input("sel-market", "data"),
    )
    def price_chart(range_key, _n, market):
        if not market:
            return T.empty_fig("NO SECURITY LOADED")
        err = ""
        try:
            history = api.get_price_history(market["yes_token"], range_key or "1D")
        except NetError as exc:
            history, err = [], f"HISTORY UNAVAILABLE — {exc}"
        live, _ = feed.get_feed(market).history()
        return _price_fig(history, live, range_key or "1D", err)
