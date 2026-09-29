"""
F2 FED — FOMC path implied by fed funds futures vs Kalshi vs Polymarket.
"""

from __future__ import annotations

from datetime import datetime, timezone

import plotly.graph_objects as go
from dash import Input, Output, dcc, html

import theme as T
from fed import model
from fed.monitor import FLAG_MEETINGS, GAP_FLAG_PP, snapshot
from pages.book import panel


def layout():
    return html.Div([
        dcc.Interval(id="fed-tick", interval=5000),
        html.Div(id="fed-header", className="quote-strip"),
        html.Div(className="grid grid-fed", children=[
            panel("EXPECTED POLICY PATH · CUMULATIVE CHANGE FROM TODAY'S EFFR",
                  dcc.Graph(id="fed-chart", config={"displayModeBar": False}, style={"height": "360px"}),
                  aux="BP  ·  + HIKES / − CUTS", body_class="panel-body flush"),
            panel("PER-MEETING BREAKDOWN", html.Div(id="fed-table", className="scroll"),
                  aux=f"HIGHLIGHT: |GAP| ≥ {GAP_FLAG_PP:g}PP · NEXT {FLAG_MEETINGS} MEETINGS", body_class="panel-body flush"),
            panel("METHOD", html.Div(className="note", style={"marginTop": 0}, children=[
                html.Span("FFF ", className="venue-f"),
                "CBOT 30-day fed funds futures via Yahoo. Contract = month-average EFFR; walking meetings in order, "
                "post = (N·R_m − D·pre)/(N − D), or the next month's contract when the meeting falls in the last "
                "week and the next month has no meeting (CME FedWatch convention). Expected move is split across "
                "the two nearest 25bp outcomes.  ",
                html.Span("KALSHI ", className="venue-k"),
                "KXFEDDECISION outcome mids, normalised to 100%.  ",
                html.Span("POLY ", className="venue-p"),
                "Polymarket 'Fed … after <month> meeting' markets from the Gamma cache (needs Polymarket access).  ",
                html.Br(),
                "GAP = FFF probability − venue price for the most mispriced outcome among those the model gives "
                "probability to (the step-split has no view on tails). Flags only cover the next "
                f"{FLAG_MEETINGS} meetings. Positive → venue is cheap "
                "versus futures (buy YES there if you trust the futures). Futures carry a small risk premium and "
                "the step-split is a model assumption, so treat gaps as leads, not arbitrage.",
            ])),
        ]),
    ])


# ── Renderers ─────────────────────────────────────────────────────────────────

def _bp(v):
    if v is None:
        return html.Span("--", className="dim")
    return html.Span(f"{v:+.1f}", className="bp-pos" if v > 0.05 else "bp-neg" if v < -0.05 else "dim")


def _dist(probs: dict):
    if not probs:
        return html.Span("--", className="dim")
    d = model.direction_probs(probs)
    return html.Span(className="dist", children=[
        "↓", html.B(f"{d['cut'] * 100:.0f}"), "  =", html.B(f"{d['hold'] * 100:.0f}"),
        "  ↑", html.B(f"{d['hike'] * 100:.0f}"),
    ])


def _gap(g):
    if not g:
        return "--"
    tag = "CHEAP" if g["edge_pp"] > 0 else "RICH"
    return (f'{g["venue"]} {model.BUCKET_LABEL[g["bucket"]]} {g["price"] * 100:.0f}¢ vs '
            f'{g["model"] * 100:.0f}% · {g["edge_pp"]:+.0f}PP {tag}')


def _chart(rows: list) -> go.Figure:
    if not rows:
        return T.empty_fig("NO MEETINGS")
    fig = go.Figure()
    today = datetime.now(timezone.utc).date().isoformat()
    series = (("FFF", "fff_cum", T.CYAN, "solid", "circle"),
              ("KALSHI", "kalshi_cum", T.AMBER, "solid", "square"),
              ("POLY", "poly_cum", T.MAGENTA, "dash", "diamond"))
    for name, key, color, dash, symbol in series:
        pts = [(r["date"].isoformat(), r[key]) for r in rows if r[key] is not None]
        if not pts:
            continue
        xs = [today] + [x for x, _ in pts]
        ys = [0.0] + [y for _, y in pts]
        fig.add_trace(go.Scatter(x=xs, y=ys, name=name, mode="lines+markers",
                                 line=dict(color=color, width=2, dash=dash, shape="hv"),
                                 marker=dict(size=7, color=color, symbol=symbol, line=dict(color="#000", width=1)),
                                 hovertemplate="%{y:+.1f}bp<extra>" + name + "</extra>"))
    for r in rows:
        fig.add_vline(x=r["date"].isoformat(), line=dict(color="#262626", width=1))
    fig.add_hline(y=0, line=dict(color="#555", width=1))
    fig.update_layout(**T.base_layout(
        hovermode="x unified", margin=dict(l=52, r=16, t=28, b=30),
        xaxis=T.axis(type="date", tickformat="%d-%b-%y"),
        yaxis=T.axis(title="BP", ticksuffix="", zeroline=False),
    ))
    return fig


def _table(rows: list):
    head = html.Tr([
        html.Th("MEETING", className="l"), html.Th("DAYS"), html.Th("ZQ RATE %"),
        html.Th("FFF Δ BP", className="venue-f"), html.Th("KALSHI Δ", className="venue-k"),
        html.Th("POLY Δ", className="venue-p"),
        html.Th("FFF CUM", className="venue-f"), html.Th("KALSHI CUM", className="venue-k"),
        html.Th("FFF ↓ = ↑ %", className="l venue-f"), html.Th("KALSHI ↓ = ↑ %", className="l venue-k"),
        html.Th("POLY ↓ = ↑ %", className="l venue-p"), html.Th("BIGGEST GAP", className="l"),
    ])
    body = []
    for r in rows:
        body.append(html.Tr(className="fed-flag" if r["flag"] else "", children=[
            html.Td(r["date"].strftime("%d-%b-%y").upper(), className="l num"),
            html.Td(str(r["days"]), className="dim"),
            html.Td(f'{r["zq_rate"]:.3f}' if r["zq_rate"] is not None else "--",
                    title=f'post-rate method: {r["method"] or "n/a"}'),
            html.Td(_bp(r["fff_bp"])), html.Td(_bp(r["kalshi_bp"])), html.Td(_bp(r["poly_bp"])),
            html.Td(_bp(r["fff_cum"])), html.Td(_bp(r["kalshi_cum"])),
            html.Td(_dist(r["fff_dist"]), className="l"), html.Td(_dist(r["kalshi_probs"]), className="l"),
            html.Td(_dist(r["poly_probs"]), className="l"),
            html.Td(_gap(r["gap"]), className="l gap"),
        ]))
    return html.Table([html.Thead(head), html.Tbody(body)], className="tbl")


def _header(data: dict, loading: bool, error: str):
    def cell(label, value, cls="q-val small"):
        return html.Div(className="q-cell", children=[html.Div(label, className="q-label"),
                                                      html.Div(value, className=cls)])
    if not data:
        return [cell("STATUS", "LOADING FUTURES, KALSHI, FRED …" if loading else (error or "NO DATA"),
                     "q-val small down" if error else "q-val small")]
    rows = data["rows"]
    nxt = rows[0] if rows else None
    as_of = datetime.fromtimestamp(data["as_of"], tz=timezone.utc).strftime("%H:%M:%S UTC")
    flags = sum(r["flag"] for r in rows)
    return [
        cell("EFFR", f'{data["effr"]:.2f}%' if data["effr"] is not None else "N/A",
             "q-val" if data["effr"] is not None else "q-val down"),
        cell("EFFR DATE", data["effr_date"] or "--"),
        cell("NEXT FOMC", nxt["date"].strftime("%d-%b-%y").upper() if nxt else "--"),
        cell("DAYS", str(nxt["days"]) if nxt else "--"),
        cell("FFF NEXT Δ", f'{nxt["fff_bp"]:+.1f}BP' if nxt and nxt["fff_bp"] is not None else "--"),
        cell("KALSHI NEXT Δ", f'{nxt["kalshi_bp"]:+.1f}BP' if nxt and nxt["kalshi_bp"] is not None else "--"),
        cell("CALENDAR", data["calendar_source"]),
        cell("POLYMARKET", "OK" if data["poly_available"] else "UNAVAILABLE",
             "q-val small up" if data["poly_available"] else "q-val small down"),
        cell("FLAGS", str(flags), "q-val small up" if flags else "q-val small"),
        cell("AS OF", as_of + (" ↻" if loading else "")),
    ]


def register(app):
    @app.callback(
        Output("fed-header", "children"),
        Output("fed-chart", "figure"),
        Output("fed-table", "children"),
        Input("fed-tick", "n_intervals"),
    )
    def refresh(_n):
        snap = snapshot()
        data = snap["data"]
        if not data:
            msg = "LOADING …" if snap["loading"] else (snap["error"] or "NO DATA")
            return _header(None, snap["loading"], snap["error"]), T.empty_fig(msg), html.Div(msg, className="waiting")
        return _header(data, snap["loading"], snap["error"]), _chart(data["rows"]), _table(data["rows"])
