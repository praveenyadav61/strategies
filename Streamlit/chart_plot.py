import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from base_formation import calculate_cup_metrics, get_tight_close_groups


default_params = {
    "MIN_WEEKS": 8,
    "MAX_WEEKS": 52,
    "MIN_WEEKLY_BARS_REQUIRED": 10,
    "MIN_DEPTH": 15 / 100.0,
    "MAX_DEPTH": 60 / 100.0,
    "RECOVERY_MIN": 60 / 100.0,
    "ATR_WINDOW": 14,
    "COMPRESSION_LOOKBACK": 10,
}


def prepare_weekly_chart_data(df_weekly, params, symbol):
    """
    Reuse the existing base-formation calculations and add chart-only columns here.

    Keep this function as the single place for chart prep so future indicators can
    be added once and used by any layer method.
    """
    df = calculate_cup_metrics(df_weekly.copy(), params, symbol)

    # RSI is only needed for plotting, so it lives in the chart-prep layer.
    delta = df["Close"].diff()
    gain = delta.where(delta > 0, 0).ewm(com=13, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(com=13, adjust=False).mean()
    rs = gain / loss
    df["rsi_14"] = 100 - (100 / (1 + rs))

    return df


def get_cup_reference_points(df, params):
    """
    Extract the same peak / low reference points used by the existing cup logic.

    Returning plain values keeps the plotting methods simple and makes the
    annotation layer optional.
    """
    min_weeks = params["MIN_WEEKS"]
    max_weeks = params.get("MAX_WEEKS")

    if len(df) < min_weeks + 2:
        return None

    window = df.tail(max_weeks).copy() if max_weeks else df.copy()
    peak_search_window = window.iloc[:-min_weeks]
    if peak_search_window.empty:
        return None

    peak_idx = peak_search_window["High"].idxmax()
    peak_price = window.loc[peak_idx, "High"]
    after_peak = window.loc[peak_idx:]
    if len(after_peak) <= 1:
        return None

    bottom_idx = after_peak["Low"].idxmin()
    bottom_price = after_peak.loc[bottom_idx, "Low"]

    return {
        "peak_idx": peak_idx,
        "peak_price": peak_price,
        "bottom_idx": bottom_idx,
        "bottom_price": bottom_price,
        "window_end": df.index[-1],
        "after_peak": after_peak,
    }


class LayeredPriceChart:
    """
    Generic layered price chart builder.

    Use this for any multi-row price chart that combines candles, moving averages,
    volume, and optional indicator layers.
    """

    def __init__(
        self,
        df,
        symbol,
        rows=3,
        row_heights=None,
        vertical_spacing=0.05,
    ):
        self.symbol = symbol
        self.df = df.copy()
        self.rows = rows

        if row_heights is None:
            if rows == 2:
                row_heights = [0.75, 0.25]
            elif rows == 3:
                row_heights = [0.6, 0.2, 0.2]
            elif rows == 4:
                row_heights = [0.5, 0.2, 0.15, 0.15]
            else:
                row_heights = [1.0 / rows] * rows

        self.fig = make_subplots(
            rows=rows,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=vertical_spacing,
            row_heights=row_heights,
        )

    def add_candles(self, row=1, col=1, name="Price"):
        self.fig.add_trace(
            go.Candlestick(
                x=self.df.index,
                open=self.df["Open"],
                high=self.df["High"],
                low=self.df["Low"],
                close=self.df["Close"],
                name=name,
            ),
            row=row,
            col=col,
        )
        return self

    def add_price_moving_averages(
        self,
        row=1,
        col=1,
        ma_columns=None,
    ):
        ma_columns = ma_columns or [
            ("ma_10", "10W MA", "orange"),
            ("ma_40", "40W MA", "blue"),
        ]

        for column, label, color in ma_columns:
            if column in self.df.columns:
                self.fig.add_trace(
                    go.Scatter(
                        x=self.df.index,
                        y=self.df[column],
                        name=label,
                        line=dict(color=color),
                    ),
                    row=row,
                    col=col,
                )
        return self

    def add_ema_lines(
        self,
        row=1,
        col=1,
        ma_columns=None,
    ):
        ma_columns = ma_columns or [
            ("ema10", "EMA 10", "#f59e0b"),
            ("ema20", "EMA 20", "#2563eb"),
        ]

        for column, label, color in ma_columns:
            if column in self.df.columns:
                self.fig.add_trace(
                    go.Scatter(
                        x=self.df.index,
                        y=self.df[column],
                        name=label,
                        line=dict(color=color, width=2),
                    ),
                    row=row,
                    col=col,
                )
        return self

    def add_ema_trend_start_markers(self, result_row, row=1, col=1):
        if result_row is None:
            return self

        for ema_col, duration_key, label, color in [
            ("ema10", "duration_ema10", "EMA10 Trend Start", "#f59e0b"),
            ("ema20", "duration_ema21", "EMA21 Trend Start", "#2563eb"),
        ]:
            duration = result_row.get(duration_key)
            if pd.isna(duration) or duration <= 0:
                continue

            bars = int(duration)
            if bars > len(self.df):
                continue

            start_idx = self.df.index[-bars]
            start_close = self.df.iloc[-bars]["Close"]

            self.fig.add_trace(
                go.Scatter(
                    x=[start_idx],
                    y=[start_close],
                    mode="markers+text",
                    name=label,
                    text=[label],
                    textposition="bottom center",
                    marker=dict(color=color, size=10, symbol="diamond"),
                ),
                row=row,
                col=col,
            )

        return self

    def add_volume_bars(self, row=2, col=1, color="lightgrey"):
        if "Volume" not in self.df.columns:
            return self

        self.fig.add_trace(
            go.Bar(
                x=self.df.index,
                y=self.df["Volume"],
                name="Volume",
                marker_color=color,
            ),
            row=row,
            col=col,
        )
        return self

    def add_volume_moving_averages(
        self,
        row=2,
        col=1,
        ma_columns=None,
    ):
        ma_columns = ma_columns or [
            ("volume_ma_10", "10W Vol MA", "purple"),
            ("volume_ma_20", "20W Vol MA", "green"),
        ]

        for column, label, color in ma_columns:
            if column in self.df.columns:
                self.fig.add_trace(
                    go.Scatter(
                        x=self.df.index,
                        y=self.df[column],
                        name=label,
                        line=dict(color=color, width=1),
                    ),
                    row=row,
                    col=col,
                )
        return self

    def add_rsi(self, row=3, col=1):
        if "rsi_14" not in self.df.columns:
            return self

        self.fig.add_trace(
            go.Scatter(
                x=self.df.index,
                y=self.df["rsi_14"],
                name="RSI (14)",
            ),
            row=row,
            col=col,
        )
        self.fig.add_hline(y=70, line_dash="dash", line_color="red", row=row, col=col)
        self.fig.add_hline(y=30, line_dash="dash", line_color="red", row=row, col=col)
        return self

    def update_layout(
        self,
        title=None,
        height=800,
        show_range_slider=False,
    ):
        self.fig.update_layout(
            title=title or f"{self.symbol} - Price Analysis",
            xaxis_rangeslider_visible=show_range_slider,
            height=height,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1,
            ),
        )
        return self

    def update_axis_titles(
        self,
        price_title="Price",
        volume_title="Volume",
        indicator_title="RSI",
        eps_title="log EPS",
    ):
        self.fig.update_yaxes(title_text=price_title, row=1, col=1)
        if self.rows >= 2:
            self.fig.update_yaxes(title_text=volume_title, row=2, col=1)
        if self.rows >= 3:
            self.fig.update_yaxes(title_text=indicator_title, row=3, col=1)
        if self.rows >= 4:
            self.fig.update_yaxes(title_text=eps_title, row=4, col=1)
        return self

    def finalize(self):
        return self.fig


class LayeredCupChart(LayeredPriceChart):
    """Cup-specific chart builder that keeps the cup annotation helpers together."""

    def __init__(
        self,
        df_weekly,
        symbol,
        params=None,
        row_heights=None,
        vertical_spacing=0.05,
    ):
        self.params = params or default_params
        df = prepare_weekly_chart_data(df_weekly, self.params, symbol)
        super().__init__(df, symbol, rows=4, row_heights=row_heights, vertical_spacing=vertical_spacing)

    def add_peak_low_markers(self, row=1, col=1):
        points = get_cup_reference_points(self.df, self.params)
        if not points:
            return self

        self.fig.add_shape(
            type="line",
            x0=points["peak_idx"],
            y0=points["peak_price"],
            x1=points["window_end"],
            y1=points["peak_price"],
            line=dict(color="red", width=2, dash="dash"),
            row=row,
            col=col,
        )
        self.fig.add_annotation(
            x=points["peak_idx"],
            y=points["peak_price"],
            text="Peak",
            showarrow=True,
            arrowhead=1,
            row=row,
            col=col,
        )
        self.fig.add_annotation(
            x=points["bottom_idx"],
            y=points["bottom_price"],
            text="Low",
            showarrow=True,
            arrowhead=1,
            yshift=-10,
            row=row,
            col=col,
        )
        return self

    def add_tight_close_blocks(
        self,
        row=1,
        col=1,
        fillcolor="rgba(34, 139, 34, 0.12)",
        line_color="darkgreen",
    ):
        points = get_cup_reference_points(self.df, self.params)
        if not points:
            return self

        tight_group_info = get_tight_close_groups(points["after_peak"], window=3, tolerance=0.01)
        block_ranges = tight_group_info["block_ranges"]
        if not block_ranges:
            return self

        first_block = True
        for block in block_ranges:
            block_slice = points["after_peak"].loc[block["start_idx"]:block["end_idx"]]
            if block_slice.empty:
                continue

            self.fig.add_shape(
                type="rect",
                x0=block["start_idx"],
                x1=block["end_idx"],
                y0=block_slice["Low"].min(),
                y1=block_slice["High"].max(),
                fillcolor=fillcolor,
                line=dict(color=line_color, width=2),
                layer="above",
                row=row,
                col=col,
            )

            if first_block:
                self.fig.add_trace(
                    go.Scatter(
                        x=[block["start_idx"]],
                        y=[block_slice["High"].max()],
                        mode="markers",
                        name="Tight Close Block",
                        marker=dict(size=10, color=line_color, symbol="square"),
                        opacity=0,
                        hoverinfo="skip",
                        showlegend=True,
                    ),
                    row=row,
                    col=col,
                )
                first_block = False

        return self

    def add_pivot_marker(self, result_row, row=1, col=1):
        if result_row is None or 'pivot_index' not in result_row:
            return self
    
        pivot_date = result_row['pivot_index']
        pivot_price = result_row['pivot_price']
    
        # Check if pivot_date exists in the dataframe index
        if pivot_date not in self.df.index:
            return self
    
        self.fig.add_trace(
            go.Scatter(
                x=[pivot_date],
                y=[pivot_price],
                mode="markers+text",
                name="Pivot",
                text=["Pivot"],
                textposition="bottom center",
                marker=dict(color="orange", size=12, symbol="diamond"),
            ),
            row=row,
            col=col,
        )
        return self

    def add_eps(self, row=4, col=1):
        eps_df = pd.read_csv('data/quarterly/eps_processed.csv')
        eps_df = eps_df[eps_df['symbol']+".NS" == self.symbol]
        if eps_df.empty:
            return self
        eps_df['date'] = pd.to_datetime(eps_df['date'])
        eps_df = eps_df.sort_values('date')
        self.fig.add_trace(
            go.Scatter(
                x=eps_df['date'],
                y=eps_df['log_eps'],
                mode='lines+markers',
                name='Log EPS',
                line=dict(color='purple'),
            ),
            row=row,
            col=col,
        )
        return self


def plot_cup_formation(df_weekly, symbol, params, result_row=None):
    chart = LayeredCupChart(df_weekly, symbol, params)
    return (
        chart
        .add_candles()
        .add_price_moving_averages()
        .add_peak_low_markers()
        .add_tight_close_blocks()
        .add_pivot_marker(result_row)  # This will now use the passed result_row
        .add_volume_bars()
        .add_volume_moving_averages()
        .add_rsi()
        .add_eps()
        .update_layout(title=f"{symbol} - Cup Formation Analysis (Weekly)")
        .update_axis_titles()
        .finalize()
    )

def _prepare_trend_follower_data(df_daily):
    """Prepare daily data for the Trend Follower chart."""
    df = df_daily.copy()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date")

    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    df = df.sort_index()
    df["ema10"] = df["Close"].ewm(span=10, adjust=False).mean()
    df["ema20"] = df["Close"].ewm(span=20, adjust=False).mean()
    return df


def _prepare_custom_ohlcv_data(df_daily):
    """Prepare normalized daily OHLCV data for the custom data center chart."""
    df = df_daily.copy()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date")

    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    df = df.sort_index()
    df["ema10"] = df["Close"].ewm(span=10, adjust=False).mean()
    df["ema20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["sma50"] = df["Close"].rolling(50).mean()
    df["sma200"] = df["Close"].rolling(200).mean()
    return df


def plot_custom_ohlcv_chart(
    df_daily,
    symbol,
    enabled_mas=None,
    lookback=None,
    comparison_df=None,
    comparison_label="NASDAQ Composite",
):
    df = _prepare_custom_ohlcv_data(df_daily)
    if lookback is not None:
        df = df.tail(lookback)

    if enabled_mas is None:
        enabled_mas = ["ema10", "ema20", "sma50", "sma200"]
    enabled_mas = set(enabled_mas)
    ma_columns = [
        ("ema10", "EMA 10", "#f59e0b"),
        ("ema20", "EMA 20", "#2563eb"),
        ("sma50", "SMA 50", "#16a34a"),
        ("sma200", "SMA 200", "#dc2626"),
    ]
    ma_columns = [ma for ma in ma_columns if ma[0] in enabled_mas]

    chart = LayeredPriceChart(df, symbol, rows=2, row_heights=[0.75, 0.25])
    chart = (
        chart
        .add_candles(name="Price")
        .add_ema_lines(ma_columns=ma_columns)
        .add_volume_bars()
        .update_layout(title=f"{symbol} - Custom Data Center", height=780, show_range_slider=False)
        .update_axis_titles(price_title="Price", volume_title="Volume")
    )

    if comparison_df is not None and not comparison_df.empty:
        comparison = _prepare_custom_ohlcv_data(comparison_df)
        comparison = comparison.loc[comparison.index.intersection(df.index)]
        if not comparison.empty and comparison["Close"].iloc[0] != 0:
            rebased_close = comparison["Close"] / comparison["Close"].iloc[0] * df["Close"].iloc[0]
            chart.fig.add_trace(
                go.Scatter(
                    x=comparison.index,
                    y=rebased_close,
                    mode="lines",
                    name=f"{comparison_label} (rebased)",
                    line=dict(color="#7c3aed", width=2, dash="dot"),
                ),
                row=1,
                col=1,
            )

    return chart.finalize()


def plot_trend_follower_chart(df_daily, symbol, result_row=None, lookback=120):
    df = _prepare_trend_follower_data(df_daily).tail(lookback)

    chart = LayeredPriceChart(df, symbol, rows=2, row_heights=[0.75, 0.25])
    return (
        chart
        .add_candles(name="Price")
        .add_ema_lines()
        .add_ema_trend_start_markers(result_row)
        .add_volume_bars()
        .update_layout(title=f"{symbol} - Trend Follower", height=780, show_range_slider=False)
        .update_axis_titles(price_title="Price", volume_title="Volume")
        .finalize()
    )
