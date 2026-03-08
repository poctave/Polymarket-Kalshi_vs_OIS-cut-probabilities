"""
FFF / OIS vs Polymarket — WIRP Dashboard
==========================================
Run:  python arb_app.py
Open: http://localhost:8051

Bloomberg WIRP-style chart: cumulative expected 25bps cuts implied by
Fed Funds Futures (ZQ proxy contracts) vs Polymarket per-meeting markets.
"""

import dash
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output
import plotly.graph_objects as go
from datetime import date

import fff_data

# ── App ───────────────────────────────────────────────────────────────────────

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY],
    title="WIRP Arb",
    assets_folder="assets",
)
app.config.suppress_callback_exceptions = True

# ── Palette ───────────────────────────────────────────────────────────────────

C_BG     = "#0d1117"
C_CARD   = "#161b22"
C_BORDER = "#30363d"
C_TEXT   = "#e6edf3"
C_MUTED  = "#8b949e"
C_GREEN  = "#3fb950"
C_RED    = "#f85149"
C_AMBER  = "#d29922"
C_INDIGO = "#6366f1"
C_GRAY   = "#6e7681"

PLOT_BASE = dict(
    paper_bgcolor=C_CARD,
    plot_bgcolor=C_CARD,
    font_color=C_MUTED,
    font_family="'SF Mono', 'Fira Code', monospace",
    legend=dict(bgcolor="rgba(0,0,0,0)", font_color=C_MUTED),
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _edge_color(edge_pp):
    if edge_pp is None:    return "transparent"
    if abs(edge_pp) < 3:  return "transparent"
    if abs(edge_pp) < 8:  return "rgba(210,153,34,0.18)"
    if edge_pp >= 8:      return "rgba(63,185,80,0.18)"
    return "rgba(248,81,73,0.18)"


def _edge_text_color(edge_pp):
    if edge_pp is None:   return C_MUTED
    if abs(edge_pp) < 3:  return C_MUTED
    if abs(edge_pp) < 8:  return C_AMBER
    if edge_pp >= 8:      return C_GREEN
    return C_RED


def _fmt_pct(v):
    if v is None: return "—"
    return f"{v * 100:.1f}%"


def _fmt_edge(v):
    if v is None: return "—"
    return f"{v:+.1f} pp"


def _fmt_cuts(v):
    if v is None: return "—"
    return f"{v:.2f}x"


def _fmt_zq(v):
    if v is None: return "—"
    return f"{v:.4f}"


# ── WIRP Chart ────────────────────────────────────────────────────────────────

def _build_wirp_chart(rows):
    """
    Bloomberg WIRP-style line chart.

    X-axis: FOMC meeting dates
    Y-axis: Cumulative expected 25bps cuts from current EFFR
    - Indigo line: FFF-implied (proxy contract formula)
    - Amber line:  Polymarket-implied (accumulated per-meeting expectations)
    - Shaded fill between the two lines (green if FFF>PM, red if FFF<PM)
    - Today anchor at y=0
    """
    today = date.today()
    today_str = today.isoformat()

    C_PM = "#e879f9"   # fuchsia for Polymarket

    # Separate by source
    x_fff = [today_str] + [r["date"].isoformat() for r in rows if r["fff_cuts"] is not None]
    y_fff = [0.0]       + [r["fff_cuts"] for r in rows if r["fff_cuts"] is not None]

    x_kalshi = [today_str] + [r["date"].isoformat() for r in rows if r["kalshi_cuts"] is not None]
    y_kalshi  = [0.0]      + [r["kalshi_cuts"] for r in rows if r["kalshi_cuts"] is not None]

    x_poly = [today_str] + [r["date"].isoformat() for r in rows if r["polymarket_cuts"] is not None]
    y_poly  = [0.0]      + [r["polymarket_cuts"] for r in rows if r["polymarket_cuts"] is not None]

    # Hovertext
    hover_fff = ["Today — anchor"] + [
        f"<b>{r['label']}</b><br>FFF Cuts: {_fmt_cuts(r['fff_cuts'])}<br>"
        f"FFF P(↓): {_fmt_pct(r['fff_p_cut'])}<br>ZQ: {_fmt_zq(r['zq_price'])}"
        for r in rows if r["fff_cuts"] is not None
    ]
    hover_kalshi = ["Today — anchor"] + [
        f"<b>{r['label']}</b><br>Kalshi Cuts: {_fmt_cuts(r['kalshi_cuts'])}<br>"
        f"Kalshi P(↓): {_fmt_pct(r['kalshi_p_cut'])}"
        for r in rows if r["kalshi_cuts"] is not None
    ]
    hover_poly = ["Today — anchor"] + [
        f"<b>{r['label']}</b><br>Polymarket Cuts: {_fmt_cuts(r['polymarket_cuts'])}<br>"
        f"PM P(↓): {_fmt_pct(r['polymarket_p_cut'])}"
        for r in rows if r["polymarket_cuts"] is not None
    ]

    fig = go.Figure()

    # ── Shaded fill: FFF vs Kalshi ─────────────────────────────────────────────
    x_both = [r["date"].isoformat() for r in rows if r["fff_cuts"] is not None and r["kalshi_cuts"] is not None]
    fff_over    = [r["fff_cuts"]    for r in rows if r["fff_cuts"] is not None and r["kalshi_cuts"] is not None]
    kalshi_over = [r["kalshi_cuts"] for r in rows if r["fff_cuts"] is not None and r["kalshi_cuts"] is not None]

    if x_both:
        avg_gap = sum(f - k for f, k in zip(fff_over, kalshi_over)) / len(fff_over)
        fill_color = "rgba(63,185,80,0.10)" if avg_gap >= 0 else "rgba(248,81,73,0.10)"
        fig.add_trace(go.Scatter(
            x=[today_str] + x_both, y=[0.0] + kalshi_over,
            mode="lines", line=dict(color="rgba(0,0,0,0)", width=0),
            showlegend=False, hoverinfo="skip",
        ))
        fig.add_trace(go.Scatter(
            x=[today_str] + x_both, y=[0.0] + fff_over,
            mode="lines", line=dict(color="rgba(0,0,0,0)", width=0),
            fill="tonexty", fillcolor=fill_color,
            showlegend=False, hoverinfo="skip",
        ))

    # ── Polymarket WIRP line (fuchsia, partial — only where markets exist) ─────
    if len(x_poly) > 1:
        fig.add_trace(go.Scatter(
            name="Polymarket WIRP",
            x=x_poly, y=y_poly,
            mode="lines+markers",
            line=dict(color=C_PM, width=2, dash="dash"),
            marker=dict(size=7, color=C_PM, symbol="diamond"),
            hovertext=hover_poly,
            hovertemplate="%{hovertext}<extra></extra>",
        ))

    # ── Kalshi WIRP line (amber) ───────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        name="Kalshi WIRP",
        x=x_kalshi, y=y_kalshi,
        mode="lines+markers",
        line=dict(color=C_AMBER, width=2.5, dash="solid"),
        marker=dict(size=8, color=C_AMBER, symbol="circle"),
        hovertext=hover_kalshi,
        hovertemplate="%{hovertext}<extra></extra>",
    ))

    # ── FFF WIRP line (indigo) ─────────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        name="FFF Implied WIRP",
        x=x_fff, y=y_fff,
        mode="lines+markers",
        line=dict(color=C_INDIGO, width=2.5, dash="solid"),
        marker=dict(size=8, color=C_INDIGO, symbol="circle"),
        hovertext=hover_fff,
        hovertemplate="%{hovertext}<extra></extra>",
    ))

    # ── Gap line (FFF − Kalshi) on secondary axis ─────────────────────────────
    gap_x = [today_str] + [r["date"].isoformat() for r in rows if r["gap"] is not None]
    gap_y = [0.0]       + [r["gap"] for r in rows if r["gap"] is not None]
    if len(gap_x) > 1:
        fig.add_trace(go.Scatter(
            name="FFF−Kalshi Gap",
            x=gap_x, y=gap_y,
            mode="lines+markers",
            line=dict(color=C_GREEN, width=1.5, dash="dot"),
            marker=dict(size=5, color=C_GREEN),
            yaxis="y2",
            hovertemplate="<b>%{x}</b><br>Gap: %{y:.2f}x<extra></extra>",
        ))

    # ── Today vertical reference line ─────────────────────────────────────────
    fig.add_shape(
        type="line",
        x0=today_str, x1=today_str,
        y0=0, y1=1,
        yref="paper",
        line=dict(color=C_GRAY, width=1, dash="dash"),
    )
    fig.add_annotation(
        x=today_str, y=1.01,
        yref="paper",
        text="Today",
        showarrow=False,
        font=dict(color=C_GRAY, size=10),
        xanchor="left",
    )

    # ── Zero reference line ───────────────────────────────────────────────────
    fig.add_hline(
        y=0,
        line=dict(color=C_BORDER, width=1),
    )

    all_y = [v for v in y_fff + y_kalshi + y_poly if v is not None]
    y_max = max(all_y) * 1.35 if all_y else 4.0

    layout = dict(PLOT_BASE)
    layout["legend"] = dict(
        bgcolor="rgba(0,0,0,0)",
        font_color=C_MUTED,
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="right",
        x=1,
    )
    fig.update_layout(
        **layout,
        height=380,
        margin=dict(l=55, r=75, t=20, b=50),
        xaxis=dict(
            type="date",
            gridcolor=C_BORDER,
            tickfont=dict(color=C_MUTED),
            linecolor=C_BORDER,
            tickformat="%b %Y",
        ),
        yaxis=dict(
            title=dict(text="Cumulative Cuts (×25bps)", font=dict(color=C_MUTED)),
            gridcolor=C_BORDER,
            tickfont=dict(color=C_MUTED),
            range=[-0.1, y_max],
            zeroline=False,
        ),
        yaxis2=dict(
            title=dict(text="Gap (FFF−PM)", font=dict(color=C_GREEN)),
            overlaying="y",
            side="right",
            tickfont=dict(color=C_GREEN),
            gridcolor="rgba(0,0,0,0)",
            showgrid=False,
            zeroline=True,
            zerolinecolor=C_BORDER,
        ),
        hovermode="x unified",
    )
    return fig


# ── Arb Table ─────────────────────────────────────────────────────────────────

def _build_table(rows):
    hdr = {
        "padding": "8px 14px",
        "color": C_MUTED,
        "fontSize": "11px",
        "fontWeight": "600",
        "letterSpacing": "0.08em",
        "textTransform": "uppercase",
        "borderBottom": f"1px solid {C_BORDER}",
        "textAlign": "right",
    }
    hdr_l = {**hdr, "textAlign": "left"}

    C_PM = "#e879f9"
    hdr_k = {**hdr, "color": C_AMBER}
    hdr_p = {**hdr, "color": C_PM}

    header = html.Tr([
        html.Th("Meeting",         style=hdr_l),
        html.Th("ZQ Price",        style=hdr),
        html.Th("FFF Cuts",        style=hdr),
        html.Th("Kalshi Cuts",     style=hdr_k),
        html.Th("PM Cuts",         style=hdr_p),
        html.Th("FFF−Kalshi Gap",  style=hdr),
        html.Th("FFF P(↓)",        style=hdr),
        html.Th("Kalshi P(↓)",     style=hdr_k),
        html.Th("PM P(↓)",         style=hdr_p),
        html.Th("Signal",          style=hdr),
    ])

    body_rows = []
    for row in rows:
        edge   = row["edge_pp"]
        bg     = _edge_color(edge)
        signal = row["signal"]

        if signal == "BUY":
            sig_color, sig_text = C_GREEN, "▲ BUY"
        elif signal == "SELL":
            sig_color, sig_text = C_RED,   "▼ SELL"
        elif signal == "WATCH":
            sig_color, sig_text = C_AMBER, "● WATCH"
        else:
            sig_color, sig_text = C_GRAY,  "—"

        cell   = {"padding": "9px 12px", "textAlign": "right", "fontSize": "12px",
                  "color": C_TEXT, "background": bg}
        cell_l = {**cell, "textAlign": "left"}

        gap_val = row["gap"]
        if gap_val is None:
            gap_tc, gap_txt = C_MUTED, "—"
        elif gap_val > 0.05:
            gap_tc, gap_txt = C_GREEN, f"+{gap_val:.2f}x"
        elif gap_val < -0.05:
            gap_tc, gap_txt = C_RED,   f"{gap_val:.2f}x"
        else:
            gap_tc, gap_txt = C_MUTED, f"{gap_val:+.2f}x"

        body_rows.append(html.Tr([
            html.Td(row["label"],                              style=cell_l),
            html.Td(_fmt_zq(row["zq_price"]),                  style=cell),
            html.Td(_fmt_cuts(row["fff_cuts"]),                 style=cell),
            html.Td(_fmt_cuts(row["kalshi_cuts"]),              style={**cell, "color": C_AMBER}),
            html.Td(_fmt_cuts(row["polymarket_cuts"]),          style={**cell, "color": C_PM}),
            html.Td(gap_txt,                                   style={**cell, "color": gap_tc, "fontWeight": "600"}),
            html.Td(_fmt_pct(row["fff_p_cut"]),                 style=cell),
            html.Td(_fmt_pct(row["kalshi_p_cut"]),              style={**cell, "color": C_AMBER}),
            html.Td(_fmt_pct(row["polymarket_p_cut"]),          style={**cell, "color": C_PM}),
            html.Td(sig_text,                                  style={**cell, "color": sig_color, "fontWeight": "600"}),
        ]))

    return html.Table(
        [html.Thead(header), html.Tbody(body_rows)],
        style={
            "width": "100%",
            "borderCollapse": "collapse",
            "fontFamily": "'SF Mono','Fira Code',monospace",
        },
    )


# ── Layout ────────────────────────────────────────────────────────────────────

def _layout():
    return html.Div(
        style={"backgroundColor": C_BG, "minHeight": "100vh", "padding": "0"},
        children=[
            # Accent bar
            html.Div(style={"height": "4px", "background": f"linear-gradient(90deg, {C_INDIGO}, #a855f7)"}),

            # Header
            html.Div(
                style={
                    "display": "flex", "alignItems": "center", "justifyContent": "space-between",
                    "padding": "16px 24px 8px",
                    "borderBottom": f"1px solid {C_BORDER}",
                },
                children=[
                    html.Div([
                        html.Span("Polymarket · ", style={"color": C_MUTED, "fontSize": "14px"}),
                        html.Span("WIRP Arb",      style={"color": C_TEXT,  "fontSize": "16px", "fontWeight": "700"}),
                    ]),
                    html.Div(
                        id="header-stats",
                        style={"display": "flex", "gap": "24px", "alignItems": "center"},
                    ),
                ],
            ),

            # Main content
            html.Div(
                style={"padding": "20px 24px", "maxWidth": "1200px", "margin": "0 auto"},
                children=[

                    # WIRP chart card (primary)
                    html.Div(
                        style={
                            "backgroundColor": C_CARD,
                            "border": f"1px solid {C_BORDER}",
                            "borderRadius": "8px",
                            "marginBottom": "20px",
                        },
                        children=[
                            html.Div(
                                "WIRP Curve — Cumulative Expected 25bps Cuts per FOMC Meeting",
                                style={
                                    "padding": "12px 16px",
                                    "borderBottom": f"1px solid {C_BORDER}",
                                    "color": C_TEXT,
                                    "fontSize": "12px",
                                    "fontWeight": "600",
                                    "letterSpacing": "0.08em",
                                    "textTransform": "uppercase",
                                }
                            ),
                            dcc.Graph(
                                id="wirp-chart",
                                config={"displayModeBar": False},
                                style={"height": "400px"},
                            ),
                        ],
                    ),

                    # Per-meeting table card
                    html.Div(
                        style={
                            "backgroundColor": C_CARD,
                            "border": f"1px solid {C_BORDER}",
                            "borderRadius": "8px",
                            "marginBottom": "20px",
                            "overflow": "hidden",
                        },
                        children=[
                            html.Div(
                                "Per-Meeting Breakdown",
                                style={
                                    "padding": "12px 16px",
                                    "borderBottom": f"1px solid {C_BORDER}",
                                    "color": C_TEXT,
                                    "fontSize": "12px",
                                    "fontWeight": "600",
                                    "letterSpacing": "0.08em",
                                    "textTransform": "uppercase",
                                }
                            ),
                            html.Div(id="arb-table", style={"overflowX": "auto"}),
                        ],
                    ),

                    # Methodology note
                    html.Div(
                        [
                            html.Span("WIRP FFF: ", style={"color": C_MUTED, "fontWeight": "600"}),
                            html.Span(
                                "(EFFR − proxy_rate) / 0.25  where proxy = first no-meeting ZQ month after M  |  "
                                "WIRP PM: accumulated E[cuts] = P(−25bps)×1 + P(−50bps+)×2 per meeting",
                                style={"color": C_GRAY},
                            ),
                        ],
                        style={
                            "fontSize": "11px",
                            "fontFamily": "'SF Mono','Fira Code',monospace",
                            "color": C_GRAY,
                        },
                    ),
                ],
            ),

            dcc.Interval(id="interval", interval=60_000, n_intervals=0),
        ],
    )


app.layout = _layout


# ── Callbacks ─────────────────────────────────────────────────────────────────

@app.callback(
    Output("wirp-chart",   "figure"),
    Output("arb-table",    "children"),
    Output("header-stats", "children"),
    Input("interval",      "n_intervals"),
)
def refresh(n):
    rows = fff_data.get_wirp_curve()
    effr = fff_data.get_current_effr()

    chart = _build_wirp_chart(rows)
    table = _build_table(rows)

    # Count actionable signals
    signals = [r["signal"] for r in rows if r["signal"] not in ("—", "N/A")]
    n_signals = len(signals)

    stats = [
        html.Div([
            html.Span("● ", style={"color": C_GREEN, "fontSize": "10px"}),
            html.Span("Live", style={"color": C_MUTED, "fontSize": "12px"}),
        ]),
        html.Div([
            html.Span("EFFR  ", style={"color": C_MUTED, "fontSize": "11px", "fontWeight": "600",
                                       "letterSpacing": "0.05em", "textTransform": "uppercase"}),
            html.Span(f"{effr:.2f}%", style={"color": C_TEXT, "fontSize": "13px", "fontWeight": "700"}),
        ]),
        html.Div([
            html.Span("Signals  ", style={"color": C_MUTED, "fontSize": "11px", "fontWeight": "600",
                                          "letterSpacing": "0.05em", "textTransform": "uppercase"}),
            html.Span(str(n_signals),
                      style={"color": C_GREEN if n_signals > 0 else C_MUTED,
                             "fontSize": "13px", "fontWeight": "700"}),
        ]),
        html.A(
            "← Main Dashboard",
            href="http://127.0.0.1:8050",  # main dashboard
            style={"color": C_INDIGO, "fontSize": "12px", "textDecoration": "none"},
        ),
    ]

    return chart, table, stats


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=8052)
