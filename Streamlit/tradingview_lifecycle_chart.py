"""TradingView Lightweight Charts renderer for lifecycle review.

This module is deliberately independent from ``chart_plot.py``.  The existing
Plotly module can continue serving unrelated pages while lifecycle review uses
this responsive price, volume, and RSI chart. The scanner remains the source of
truth for every lifecycle value shown on the chart.
"""

from __future__ import annotations

import html
import json
from typing import Any, Mapping

import pandas as pd


LIGHTWEIGHT_CHARTS_URL = (
    "https://unpkg.com/lightweight-charts@5.0.9/"
    "dist/lightweight-charts.standalone.production.js"
)


def _number(value: Any) -> float | None:
    """Return a finite float for a saved lifecycle value, otherwise None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if pd.notna(number) and number not in (float("inf"), float("-inf")) else None


def _date(value: Any) -> pd.Timestamp | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    if getattr(parsed, "tzinfo", None) is not None:
        parsed = parsed.tz_localize(None)
    return pd.Timestamp(parsed).normalize()


def prepare_lifecycle_chart_data(
    daily_df: pd.DataFrame,
    timeframe: str = "Daily",
    context_start: Any = None,
) -> pd.DataFrame:
    """Normalize OHLC data and optionally aggregate it into completed weeks."""
    if daily_df is None or daily_df.empty:
        raise ValueError("No price data is available for this chart.")

    frame = daily_df.copy()
    if "Date" in frame.columns:
        frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
        frame = frame.set_index("Date")
    elif not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.to_datetime(frame.index, errors="coerce")

    frame = frame[~frame.index.isna()].sort_index()
    if frame.index.tz is not None:
        frame.index = frame.index.tz_localize(None)
    required = ["Open", "High", "Low", "Close"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"Price data is missing: {', '.join(missing)}")

    frame[required] = frame[required].apply(pd.to_numeric, errors="coerce")
    if "Volume" in frame.columns:
        frame["Volume"] = pd.to_numeric(frame["Volume"], errors="coerce").fillna(0)
    frame = frame.dropna(subset=required)
    start = _date(context_start)
    if start is not None:
        # A little pre-base context makes the left high easier to interpret.
        frame = frame.loc[frame.index >= start - pd.Timedelta(days=35)]

    if str(timeframe).lower().startswith("week"):
        aggregations = {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
        if "Volume" in frame.columns:
            aggregations["Volume"] = "sum"
        frame = frame.resample("W-FRI").agg(aggregations).dropna(subset=required)
        frame = frame.tail(160)
    else:
        frame = frame.tail(650)

    if frame.empty:
        raise ValueError("No valid OHLC candles remain for the selected timeframe.")
    return frame


def calculate_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Calculate Wilder-style RSI for the displayed candle series."""
    close = pd.to_numeric(close, errors="coerce")
    delta = close.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    average_gain = gains.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    average_loss = losses.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    relative_strength = average_gain / average_loss
    rsi = 100 - (100 / (1 + relative_strength))
    rsi = rsi.mask((average_loss == 0) & (average_gain > 0), 100.0)
    rsi = rsi.mask((average_gain == 0) & (average_loss > 0), 0.0)
    rsi = rsi.mask((average_gain == 0) & (average_loss == 0), 50.0)
    return rsi.clip(lower=0, upper=100)


def _nearest_chart_date(value: Any, available_dates: pd.DatetimeIndex) -> str | None:
    target = _date(value)
    if target is None or len(available_dates) == 0:
        return None
    positions = available_dates.get_indexer([target], method="nearest")
    if positions[0] < 0:
        return None
    return available_dates[positions[0]].strftime("%Y-%m-%d")


def build_lifecycle_price_lines(result_row: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Build uncluttered structural, active-pivot, and breakout-range lines."""
    active = _number(result_row.get("selected_pivot", result_row.get("pivot_price")))
    left_high = _number(result_row.get("left_high", result_row.get("peak_price")))
    candidate = _number(result_row.get("daily_handle_candidate_pivot"))
    handle_low = _number(result_row.get("daily_handle_low"))
    range_low = _number(result_row.get("breakout_range_low"))
    range_high = _number(result_row.get("breakout_range_high"))
    range_pct = _number(result_row.get("breakout_range_pct"))
    range_pct = 0.10 if range_pct is None else range_pct
    range_label = f"{range_pct * 100:g}%"

    lines: list[dict[str, Any]] = []

    def add(price, title, color, style=0, width=1):
        if price is None:
            return
        lines.append(
            {
                "price": price,
                "title": title,
                "color": color,
                "lineStyle": style,
                "lineWidth": width,
            }
        )

    source = str(result_row.get("pivot_source", "LEFT_HIGH")).replace("_", " ").title()
    add(active, f"Active pivot - {source}", "#22c55e", 0, 2)
    if left_high is not None and (active is None or abs(left_high - active) > max(0.01, active * 0.0001)):
        add(left_high, "Left high", "#94a3b8", 2, 1)
    if candidate is not None and (active is None or abs(candidate - active) > max(0.01, active * 0.0001)):
        add(candidate, "Handle candidate", "#f59e0b", 2, 1)
    add(handle_low, "Handle low", "#f87171", 1, 1)
    add(range_high, f"Breakout range +{range_label}", "#60a5fa", 1, 1)
    add(range_low, f"Breakout range -{range_label}", "#60a5fa", 1, 1)
    return lines


def build_lifecycle_markers(
    result_row: Mapping[str, Any], available_dates: pd.DatetimeIndex
) -> list[dict[str, Any]]:
    """Map lifecycle dates to exact candles accepted by Lightweight Charts."""
    definitions = [
        ("left_high_index", "aboveBar", "#94a3b8", "arrowDown", "Left high"),
        ("base_low_index", "belowBar", "#22c55e", "arrowUp", "Base low"),
        ("daily_handle_candidate_date", "aboveBar", "#f59e0b", "circle", "Handle candidate"),
        ("daily_handle_confirmation_date", "belowBar", "#14b8a6", "circle", "Handle ready"),
        ("breakout_date", "belowBar", "#3b82f6", "arrowUp", "Breakout"),
        ("breakout_success_date", "belowBar", "#22c55e", "arrowUp", "Success"),
    ]
    markers = []
    for field, position, color, shape, label in definitions:
        value = result_row.get(field)
        if field == "left_high_index" and value is None:
            value = result_row.get("peak_idx")
        if field == "base_low_index" and value is None:
            value = result_row.get("bottom_idx")
        marker_date = _nearest_chart_date(value, available_dates)
        if marker_date:
            markers.append(
                {
                    "time": marker_date,
                    "position": position,
                    "color": color,
                    "shape": shape,
                    "text": label,
                }
            )
    return sorted(markers, key=lambda marker: marker["time"])


def build_lifecycle_chart_html(
    daily_df: pd.DataFrame,
    result_row: Mapping[str, Any],
    symbol: str,
    timeframe: str = "Daily",
) -> str:
    """Return a self-contained responsive chart document for Streamlit's iframe."""
    frame = prepare_lifecycle_chart_data(
        daily_df,
        timeframe=timeframe,
        context_start=result_row.get("left_high_index", result_row.get("peak_idx")),
    )
    candles = [
        {
            "time": index.strftime("%Y-%m-%d"),
            "open": float(row.Open),
            "high": float(row.High),
            "low": float(row.Low),
            "close": float(row.Close),
        }
        for index, row in frame.iterrows()
    ]
    volumes = [
        {
            "time": index.strftime("%Y-%m-%d"),
            "value": float(row.Volume),
            "color": (
                "rgba(34,197,94,0.55)"
                if row.Close >= row.Open
                else "rgba(239,68,68,0.55)"
            ),
        }
        for index, row in frame.iterrows()
        if "Volume" in frame.columns and pd.notna(row.Volume)
    ]
    rsi_values = calculate_rsi(frame["Close"], period=14)
    rsi = [
        {"time": index.strftime("%Y-%m-%d"), "value": round(float(value), 4)}
        for index, value in rsi_values.items()
        if pd.notna(value)
    ]
    lines = build_lifecycle_price_lines(result_row)
    markers = build_lifecycle_markers(result_row, frame.index.normalize())
    payload = json.dumps(
        {
            "candles": candles,
            "volumes": volumes,
            "rsi": rsi,
            "lines": lines,
            "markers": markers,
        },
        separators=(",", ":"),
        allow_nan=False,
    ).replace("</", "<\\/")
    safe_symbol = html.escape(str(symbol))
    safe_timeframe = html.escape(str(timeframe))

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
html,body,#root{{width:100%;height:100%;margin:0;overflow:hidden;font-family:Inter,system-ui,sans-serif}}
#root{{display:flex;flex-direction:column;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:8px}}
#toolbar{{height:38px;display:flex;align-items:center;gap:8px;padding:0 10px;border-bottom:1px solid #334155;font-size:12px}}
#title{{font-weight:650;margin-right:auto}} button{{background:#1e293b;color:#e2e8f0;border:1px solid #475569;border-radius:5px;padding:4px 9px;cursor:pointer}}
#chart{{flex:1;min-height:0}} #error{{display:none;padding:18px;color:#fecaca}}
#credit{{color:#94a3b8;text-decoration:none;font-size:10px}} #root:fullscreen{{height:100vh;border:0;border-radius:0}}
@media (prefers-color-scheme:light){{#root{{background:#fff;color:#0f172a;border-color:#cbd5e1}}#toolbar{{border-color:#e2e8f0}}button{{background:#f8fafc;color:#0f172a;border-color:#cbd5e1}}}}
</style></head><body>
<div id="root"><div id="toolbar"><span id="title">{safe_symbol} · {safe_timeframe} · Volume · RSI(14)</span><button id="fit">Fit</button><button id="full">Fullscreen</button><a id="credit" href="https://www.tradingview.com/" target="_blank" rel="noopener">Charts by TradingView</a></div><div id="chart"></div><div id="error">The chart library could not load. Reload the page or check browser access to unpkg.com.</div></div>
<script src="{LIGHTWEIGHT_CHARTS_URL}"></script>
<script>
(() => {{
  const payload={payload}; const root=document.getElementById('root'); const area=document.getElementById('chart');
  if (!window.LightweightCharts) {{ document.getElementById('error').style.display='block'; area.style.display='none'; return; }}
  const dark=window.matchMedia('(prefers-color-scheme: dark)').matches;
  const chart=LightweightCharts.createChart(area,{{width:area.clientWidth,height:area.clientHeight,
    layout:{{background:{{type:'solid',color:dark?'#0f172a':'#ffffff'}},textColor:dark?'#cbd5e1':'#334155',attributionLogo:false,
      panes:{{separatorColor:dark?'#334155':'#cbd5e1',separatorHoverColor:'#3b82f6',enableResize:true}}}},
    grid:{{vertLines:{{color:dark?'#1e293b':'#f1f5f9'}},horzLines:{{color:dark?'#1e293b':'#f1f5f9'}}}},
    rightPriceScale:{{borderColor:dark?'#334155':'#cbd5e1'}},timeScale:{{borderColor:dark?'#334155':'#cbd5e1',timeVisible:true,rightOffset:5}},
    crosshair:{{mode:LightweightCharts.CrosshairMode.Normal}},handleScroll:true,handleScale:true
  }});
  const series=chart.addSeries(LightweightCharts.CandlestickSeries,{{upColor:'#22c55e',downColor:'#ef4444',borderVisible:false,wickUpColor:'#22c55e',wickDownColor:'#ef4444'}});
  series.setData(payload.candles);
  payload.lines.forEach(line => series.createPriceLine({{...line,axisLabelVisible:true}}));
  if (payload.markers.length) LightweightCharts.createSeriesMarkers(series,payload.markers);
  const volumeSeries=chart.addSeries(LightweightCharts.HistogramSeries,{{
    title:'Volume',priceFormat:{{type:'volume'}},priceLineVisible:false,lastValueVisible:true
  }},1);
  volumeSeries.setData(payload.volumes);
  const rsiSeries=chart.addSeries(LightweightCharts.LineSeries,{{
    title:'RSI 14',color:'#a855f7',lineWidth:2,priceLineVisible:false,lastValueVisible:true,
    priceFormat:{{type:'price',precision:1,minMove:0.1}}
  }},2);
  rsiSeries.setData(payload.rsi);
  rsiSeries.createPriceLine({{price:70,color:'#f59e0b',lineWidth:1,lineStyle:2,axisLabelVisible:true,title:'Overbought 70'}});
  rsiSeries.createPriceLine({{price:30,color:'#60a5fa',lineWidth:1,lineStyle:2,axisLabelVisible:true,title:'Oversold 30'}});
  const panes=chart.panes();
  if (panes.length >= 3) {{ panes[0].setStretchFactor(6); panes[1].setStretchFactor(2); panes[2].setStretchFactor(2); }}
  chart.timeScale().fitContent();
  new ResizeObserver(() => chart.resize(area.clientWidth,area.clientHeight)).observe(area);
  document.getElementById('fit').onclick=() => chart.timeScale().fitContent();
  document.getElementById('full').onclick=() => document.fullscreenElement?document.exitFullscreen():root.requestFullscreen();
  document.addEventListener('fullscreenchange',() => {{document.getElementById('full').textContent=document.fullscreenElement?'Exit fullscreen':'Fullscreen'; setTimeout(() => chart.resize(area.clientWidth,area.clientHeight),50);}});
}})();
</script></body></html>"""


def render_tradingview_lifecycle_chart(
    daily_df: pd.DataFrame,
    result_row: Mapping[str, Any],
    symbol: str,
    timeframe: str = "Daily",
    height: int = 760,
) -> None:
    """Render the lifecycle chart without adding a Python package dependency."""
    import streamlit.components.v1 as components

    components.html(
        build_lifecycle_chart_html(daily_df, result_row, symbol, timeframe),
        height=height,
        scrolling=False,
    )
