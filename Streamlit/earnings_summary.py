import streamlit as st
import pandas as pd
from pathlib import Path
import plotly.express as px

ROOT_DIR = Path(__file__).resolve().parents[1]

GROWTH_FIELDS = {
    "Revenue": {
        "normal_yoy": "normal_revenue_yoy_growth_pct",
        "weighted_yoy": "weighted_revenue_yoy_growth_pct",
        "normal_qoq": "normal_revenue_qoq_growth_pct",
        "weighted_qoq": "weighted_revenue_qoq_growth_pct",
    },
    "Operating Profit": {
        "normal_yoy": "normal_operating_profit_yoy_growth_pct",
        "weighted_yoy": "weighted_operating_profit_yoy_growth_pct",
        "normal_qoq": "normal_operating_profit_qoq_growth_pct",
        "weighted_qoq": "weighted_operating_profit_qoq_growth_pct",
    },
    "Net Profit": {
        "normal_yoy": "normal_profit_yoy_growth_pct",
        "weighted_yoy": "weighted_profit_yoy_growth_pct",
        "normal_qoq": "normal_profit_qoq_growth_pct",
        "weighted_qoq": "weighted_profit_qoq_growth_pct",
    },
}

INDEX_COLORS = {
    "NIFTY 50": "#2563eb",
    "NIFTY MIDCAP 100": "#0f766e",
    "NIFTY SMALLCAP 100": "#f97316",
}


def first_existing_path(*candidates):
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return path
    return None


def parse_quarter_label(label):
    if not isinstance(label, str):
        return None

    import re
    match = re.search(r"Q\s*([1-4])\s*FY\s*(\d{2,4})", label, re.IGNORECASE)
    if not match:
        return None

    quarter = int(match.group(1))
    year = int(match.group(2))
    if year < 100:
        year += 2000
    return quarter, year


def quarter_sort_key(label):
    parsed = parse_quarter_label(label)
    if parsed is None:
        return 0
    quarter, year = parsed
    return year * 10 + quarter


def format_pct(value, signed=True):
    if pd.isna(value):
        return "N/A"
    sign = "+" if signed else ""
    return f"{value:{sign}.2f}%"


def format_number(value):
    if pd.isna(value):
        return "N/A"
    return f"{value:,.0f}"


def growth_color(value):
    if pd.isna(value):
        return "#6b7280"
    return "#15803d" if value >= 0 else "#dc2626"


def selected_growth_column(metric, basis, period):
    return GROWTH_FIELDS[metric][f"{basis.lower()}_{period.lower()}"]


def build_growth_chart_df(df, basis, period):
    rows = []
    for _, row in df.iterrows():
        for metric in GROWTH_FIELDS:
            value = row.get(selected_growth_column(metric, basis, period))
            rows.append({
                "Index": row.get("index_name"),
                "Metric": metric,
                "Growth": pd.to_numeric(value, errors="coerce"),
            })
    return pd.DataFrame(rows)


def render_metric_card(index_name, row, period, basis):
    revenue_col = selected_growth_column("Revenue", basis, period)
    op_col = selected_growth_column("Operating Profit", basis, period)
    profit_col = selected_growth_column("Net Profit", basis, period)

    st.markdown(
        f"""
        <div class="earnings-card">
            <div class="earnings-card-title">{index_name}</div>
            <div class="earnings-card-subtitle">
                {format_number(row.get("declared_count"))} companies declared | {format_pct(row.get("declared_weight_pct"), signed=False)} weight
            </div>
            <div class="earnings-metric-grid">
                <div>
                    <div class="earnings-label">Revenue</div>
                    <div class="earnings-value" style="color:{growth_color(row.get(revenue_col))}">{format_pct(row.get(revenue_col))}</div>
                </div>
                <div>
                    <div class="earnings-label">Operating Profit</div>
                    <div class="earnings-value" style="color:{growth_color(row.get(op_col))}">{format_pct(row.get(op_col))}</div>
                </div>
                <div>
                    <div class="earnings-label">Net Profit</div>
                    <div class="earnings-value" style="color:{growth_color(row.get(profit_col))}">{format_pct(row.get(profit_col))}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_page_styles():
    st.markdown(
        """
        <style>
        .earnings-card-section {
            margin-bottom: 1.35rem;
        }
        .earnings-card {
            border: 1px solid rgba(148, 163, 184, 0.35);
            border-radius: 8px;
            padding: 16px 18px 15px;
            background: rgba(255, 255, 255, 0.72);
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
            min-height: 210px;
            margin-bottom: 12px;
        }
        .earnings-card-title {
            font-size: 0.98rem;
            font-weight: 700;
            color: #111827;
            line-height: 1.25;
        }
        .earnings-card-subtitle {
            margin-top: 4px;
            color: #64748b;
            font-size: 0.78rem;
            line-height: 1.45;
        }
        .earnings-metric-grid {
            display: grid;
            grid-template-columns: 1fr;
            gap: 9px;
            margin-top: 16px;
        }
        .earnings-metric-grid > div {
            display: flex;
            align-items: baseline;
            justify-content: space-between;
            gap: 14px;
            border-top: 1px solid rgba(148, 163, 184, 0.22);
            padding-top: 8px;
        }
        .earnings-label {
            color: #64748b;
            font-size: 0.76rem;
            line-height: 1.2;
            max-width: 48%;
        }
        .earnings-value {
            font-size: clamp(1rem, 1.2vw, 1.18rem);
            font-weight: 700;
            line-height: 1.1;
            text-align: right;
            white-space: nowrap;
        }
        @media (max-width: 780px) {
            .earnings-card {
                min-height: auto;
            }
            .earnings-value {
                font-size: 1.05rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_growth_bar_chart(chart_df, selected_quarter, period, basis):
    fig = px.bar(
        chart_df,
        x="Metric",
        y="Growth",
        color="Index",
        barmode="group",
        text=chart_df["Growth"].map(lambda value: "" if pd.isna(value) else f"{value:.1f}%"),
        color_discrete_map=INDEX_COLORS,
        title=f"{selected_quarter} {basis} {period} Growth by Index",
    )
    fig.add_hline(y=0, line_width=1, line_color="#94a3b8")
    fig.update_traces(textposition="outside", cliponaxis=False)
    fig.update_layout(
        height=430,
        margin=dict(l=10, r=10, t=58, b=20),
        legend_title_text="",
        yaxis_title="Growth %",
        xaxis_title="",
        bargap=0.28,
        plot_bgcolor="white",
    )
    st.plotly_chart(fig, use_container_width=True)


def render_index_cards(df, growth_period, growth_basis):
    cards_per_row = min(3, len(df))
    for start in range(0, len(df), cards_per_row):
        row_df = df.iloc[start:start + cards_per_row]
        card_cols = st.columns(cards_per_row)
        for idx, (_, row) in enumerate(row_df.iterrows()):
            with card_cols[idx]:
                render_metric_card(row["index_name"], row, growth_period, growth_basis)


def render_growth_trend(df, selected_indices, basis, period):
    trend_rows = []
    for _, row in df[df["index_name"].isin(selected_indices)].iterrows():
        for metric in GROWTH_FIELDS:
            trend_rows.append({
                "Quarter": row.get("quarter_label"),
                "quarter_sort_key": row.get("quarter_sort_key"),
                "Index": row.get("index_name"),
                "Metric": metric,
                "Growth": pd.to_numeric(row.get(selected_growth_column(metric, basis, period)), errors="coerce"),
            })
    trend_df = pd.DataFrame(trend_rows).dropna(subset=["Growth"])
    if trend_df["Quarter"].nunique() < 2:
        return

    trend_df = trend_df.sort_values("quarter_sort_key")
    fig = px.line(
        trend_df,
        x="Quarter",
        y="Growth",
        color="Index",
        facet_col="Metric",
        markers=True,
        color_discrete_map=INDEX_COLORS,
        title=f"{basis} {period} Growth Trend",
    )
    fig.add_hline(y=0, line_width=1, line_color="#94a3b8")
    fig.update_layout(
        height=360,
        margin=dict(l=10, r=10, t=58, b=20),
        legend_title_text="",
        plot_bgcolor="white",
    )
    fig.update_yaxes(matches=None, title="Growth %")
    fig.for_each_annotation(lambda annotation: annotation.update(text=annotation.text.split("=")[-1]))
    st.plotly_chart(fig, use_container_width=True)


@st.cache_data(show_spinner=True)
def load_earnings_summary_data(summary_path, summary_mtime):
    if not summary_path.exists():
        return pd.DataFrame()

    summary_df = pd.read_csv(summary_path)
    summary_df.columns = summary_df.columns.str.strip()
    if "quarter_label" in summary_df.columns:
        summary_df["quarter_label"] = summary_df["quarter_label"].astype(str).str.strip()
    if "index_name" in summary_df.columns:
        summary_df["index_name"] = summary_df["index_name"].astype(str).str.strip()
    return summary_df


def render_earnings_summary_page():
    render_page_styles()
    st.title("India Inc Earnings Summary")
    st.caption("Index-wise earnings growth dashboard across revenue, operating profit, and net profit.")

    summary_path = ROOT_DIR / "data" / "quarterly" / "india_inc_earnings_summary.csv"
    summary_mtime = summary_path.stat().st_mtime if summary_path.exists() else None
    earnings_df = load_earnings_summary_data(summary_path, summary_mtime)
    if earnings_df.empty:
        st.warning("India Inc earnings summary file was not found.")
        return

    earnings_df["quarter_sort_key"] = earnings_df["quarter_label"].apply(quarter_sort_key)
    earnings_df = earnings_df.sort_values(["quarter_sort_key", "index_name"], ascending=[False, True])

    quarters = earnings_df["quarter_label"].dropna().unique().tolist()
    indices = ["All"] + sorted(earnings_df["index_name"].dropna().unique().tolist())

    control_cols = st.columns([1.2, 1, 1, 1.2])
    selected_quarter = control_cols[0].selectbox("Quarter", quarters, index=0)
    growth_period = control_cols[1].radio("Growth", ["YoY", "QoQ"], horizontal=True)
    growth_basis = control_cols[2].radio("Basis", ["Weighted", "Normal"], horizontal=True)
    selected_index = control_cols[3].selectbox("Index filter", indices)

    filtered_df = earnings_df[earnings_df["quarter_label"] == selected_quarter]
    if selected_index != "All":
        filtered_df = filtered_df[filtered_df["index_name"] == selected_index]

    if filtered_df.empty:
        st.warning("No earnings summary rows match the selected filters.")
        return

    st.markdown(f"### {selected_quarter} Growth Snapshot")
    st.markdown('<div class="earnings-card-section">', unsafe_allow_html=True)
    render_index_cards(filtered_df.reset_index(drop=True), growth_period, growth_basis)
    st.markdown("</div>", unsafe_allow_html=True)

    chart_df = build_growth_chart_df(filtered_df, growth_basis, growth_period)
    render_growth_bar_chart(chart_df, selected_quarter, growth_period, growth_basis)

    selected_indices = filtered_df["index_name"].dropna().unique().tolist()
    render_growth_trend(earnings_df, selected_indices, growth_basis, growth_period)
    
    with st.expander("Full summary data"):
        display_df = filtered_df.drop(columns=["quarter_sort_key"], errors="ignore")
        st.dataframe(display_df, use_container_width=True, hide_index=True)
