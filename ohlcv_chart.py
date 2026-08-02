import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def plot_ohlcv(
    df,
    title="OHLCV Chart",
    date_col=None,
    open_col="Open",
    high_col="High",
    low_col="Low",
    close_col="Close",
    volume_col="Volume",
    moving_averages=(20, 50),
    height=750,
    show_range_slider=False,
):
    """
    Build a simple OHLCV candlestick chart with volume.

    Returns a Plotly figure. Use `fig.show()` in scripts/notebooks or
    `st.plotly_chart(fig, use_container_width=True)` in Streamlit.
    """
    chart_df = df.copy()

    if date_col:
        chart_df[date_col] = pd.to_datetime(chart_df[date_col])
        chart_df = chart_df.set_index(date_col)

    if not isinstance(chart_df.index, pd.DatetimeIndex):
        chart_df.index = pd.to_datetime(chart_df.index)

    chart_df = chart_df.sort_index()

    required_cols = [open_col, high_col, low_col, close_col, volume_col]
    missing_cols = [col for col in required_cols if col not in chart_df.columns]
    if missing_cols:
        raise ValueError(f"Missing required OHLCV columns: {missing_cols}")

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.72, 0.28],
    )

    fig.add_trace(
        go.Candlestick(
            x=chart_df.index,
            open=chart_df[open_col],
            high=chart_df[high_col],
            low=chart_df[low_col],
            close=chart_df[close_col],
            name="Price",
        ),
        row=1,
        col=1,
    )

    for window in moving_averages or ():
        ma_col = chart_df[close_col].rolling(window).mean()
        fig.add_trace(
            go.Scatter(
                x=chart_df.index,
                y=ma_col,
                mode="lines",
                name=f"{window} MA",
                line=dict(width=1.5),
            ),
            row=1,
            col=1,
        )

    volume_colors = [
        "#16a34a" if close >= open_ else "#dc2626"
        for open_, close in zip(chart_df[open_col], chart_df[close_col])
    ]

    fig.add_trace(
        go.Bar(
            x=chart_df.index,
            y=chart_df[volume_col],
            name="Volume",
            marker_color=volume_colors,
            opacity=0.55,
        ),
        row=2,
        col=1,
    )

    fig.update_layout(
        title=title,
        height=height,
        xaxis_rangeslider_visible=show_range_slider,
        hovermode="x unified",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
        margin=dict(l=40, r=30, t=70, b=40),
    )
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=2, col=1)

    return fig
