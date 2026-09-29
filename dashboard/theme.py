"""
2010s trading-terminal palette and Plotly styling.
Colours here must match the custom properties in assets/terminal.css.
"""

from __future__ import annotations

import plotly.graph_objects as go

BG      = "#000000"
PANEL   = "#0a0a0a"
GRID    = "#1f1f1f"
BORDER  = "#3a3a3a"
TEXT    = "#d9d9d9"
WHITE   = "#ffffff"
MUTED   = "#8a8a8a"
AMBER   = "#ffa028"
YELLOW  = "#ffd83d"
UP      = "#1fdc5a"
DOWN    = "#ff3b3b"
CYAN    = "#48c8ff"
MAGENTA = "#e45cff"

UP_FILL   = "rgba(31,220,90,0.14)"
DOWN_FILL = "rgba(255,59,59,0.14)"

FONT = "Consolas, 'Lucida Console', Menlo, 'DejaVu Sans Mono', monospace"


def axis(**kw) -> dict:
    base = dict(
        gridcolor=GRID, griddash="dot", zeroline=False, linecolor=BORDER,
        tickfont=dict(color=MUTED, size=10), title_font=dict(color=MUTED, size=10),
        showspikes=True, spikemode="across", spikesnap="cursor",
        spikecolor="#777", spikethickness=1, spikedash="dot",
    )
    base.update(kw)
    return base


def base_layout(**kw) -> dict:
    layout = dict(
        paper_bgcolor=BG, plot_bgcolor=BG,
        font=dict(family=FONT, color=MUTED, size=10),
        margin=dict(l=48, r=12, t=10, b=28),
        hoverlabel=dict(bgcolor="#111", bordercolor=AMBER, font=dict(family=FONT, color=WHITE, size=11)),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=MUTED, size=10), orientation="h",
                    x=0, y=1.02, yanchor="bottom"),
        hovermode="x",
        uirevision="keep",       # keep zoom/pan across live refreshes
    )
    layout.update(kw)
    return layout


def empty_fig(msg: str = "", color: str = MUTED) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(**base_layout(
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        annotations=[dict(text=msg, x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False,
                          font=dict(color=color, size=12, family=FONT))] if msg else [],
    ))
    return fig
