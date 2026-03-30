import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from base_formation import calculate_cup_metrics, get_tight_close_groups


default_params = {
    "MIN_WEEKS": 8,
    "MAX_WEEKS": 52,
    "MIN_DEPTH": 15 / 100.0,
    "MAX_DEPTH": 60 / 100.0,
    "RECOVERY_MIN": 60 / 100.0,
    "RECOVERY_MAX": 120 / 100.0,
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
    max_weeks = params["MAX_WEEKS"]
    min_weeks = params["MIN_WEEKS"]

    if len(df) < max_weeks:
        return None

    window = df.iloc[-max_weeks:].copy()
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


class LayeredCupChart:
    """
    Build a Plotly chart one layer at a time.

    Typical usage:
        chart = LayeredCupChart(weekly_df, symbol, params)
        fig = (
            chart
            .add_candles()
            .add_price_moving_averages()
            .add_peak_low_markers()
            .add_volume_bars()
            .add_volume_moving_averages()
            .finalize()
        )
    """

    def __init__(
        self,
        df_weekly,
        symbol,
        params=None,
        row_heights=None,
        vertical_spacing=0.05,
    ):
        self.params = params or default_params
        self.symbol = symbol
        self.df = prepare_weekly_chart_data(df_weekly, self.params, symbol)

        # Use 3 rows up front so we can keep adding layers without rebuilding the chart.
        # Row 1: price
        # Row 2: volume
        # Row 3: momentum / future indicators
        self.fig = make_subplots(
            rows=3,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=vertical_spacing,
            row_heights=row_heights or [0.6, 0.2, 0.2],
        )

    def add_candles(self, row=1, col=1, name="Weekly Price"):
        """Base price layer. Start with this before adding overlays."""
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
        """
        Add price moving averages on top of the candle chart.

        `ma_columns` lets you extend this later without touching the method body.
        """
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

    def add_peak_low_markers(self, row=1, col=1):
        """
        Add the cup reference levels.

        Keep this separate from the candle layer so the chart can be used with or
        without pattern annotations.
        """
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
        """
        Highlight each tight-close group as one rectangular region.

        The scanner treats contiguous overlapping 3-week tight windows as a
        single group, so the chart should show one merged block per group too.
        """
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

            # Add one legend-friendly trace for the first block so the layer name
            # appears in the chart legend without repeating for every block.
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

    def add_volume_bars(self, row=2, col=1, color="lightgrey"):
        """Add raw volume bars on the dedicated volume row."""
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
        """Add volume average overlays after the volume bars are in place."""
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
        """
        Add RSI on its own row.

        This stays modular so you can swap RSI for another momentum layer later.
        """
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
        """
        Central place for layout defaults.

        If you change chart styling later, do it here once instead of in each plot method.
        """
        self.fig.update_layout(
            title=title or f"{self.symbol} - Cup Formation Analysis (Weekly)",
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
    ):
        """Keep axis title updates in one small helper."""
        self.fig.update_yaxes(title_text=price_title, row=1, col=1)
        self.fig.update_yaxes(title_text=volume_title, row=2, col=1)
        self.fig.update_yaxes(title_text=indicator_title, row=3, col=1)
        return self

    def finalize(self):
        """Return the built figure once all desired layers are added."""
        return self.fig


def plot_cup_formation(df_weekly, symbol, params):
    """
    Backward-compatible wrapper for the existing Streamlit call site.

    This uses the new modular builder internally, so home.py can keep a simple
    one-line plot call while you gradually move to explicit layer-by-layer usage.
    """
    chart = LayeredCupChart(df_weekly, symbol, params)
    return (
        chart
        .add_candles()
        .add_price_moving_averages()
        .add_peak_low_markers()
        .add_tight_close_blocks()
        .add_volume_bars()
        .add_volume_moving_averages()
        .add_rsi()
        .update_layout()
        .update_axis_titles()
        .finalize()
    )
