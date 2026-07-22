"""Derived lifecycle dashboard fields built from persisted tracking history."""

import pandas as pd


TODAY_STATUS_ORDER = ["NEW BASE", "NEW TO STAGE", "CONTINUED"]


def lifecycle_base_key_series(df):
    """Return a stable key for both current all-window and older lifecycle rows."""
    if df is None or df.empty:
        return pd.Series(dtype="object")

    symbol = df.get("Symbol", pd.Series("", index=df.index)).fillna("").astype(str).str.strip()
    window_source = df.get(
        "base_window_weeks",
        df.get("scan_window_weeks", pd.Series(float("nan"), index=df.index)),
    )
    window = pd.to_numeric(window_source, errors="coerce").fillna(-1).astype(int).astype(str)
    left_high = pd.to_datetime(
        df.get("left_high_index", pd.Series(pd.NaT, index=df.index)),
        errors="coerce",
    ).dt.strftime("%Y%m%d").fillna("na")
    base_low = pd.to_datetime(
        df.get("base_low_index", pd.Series(pd.NaT, index=df.index)),
        errors="coerce",
    ).dt.strftime("%Y%m%d").fillna("na")
    fallback = symbol + "|" + window + "W|" + left_high + "|" + base_low

    if "base_id" not in df.columns:
        return fallback
    return df["base_id"].where(df["base_id"].notna(), fallback).astype(str)


def latest_tracking_date(history_df):
    if history_df is None or history_df.empty or "tracking_date" not in history_df.columns:
        return pd.NaT
    dates = pd.to_datetime(history_df["tracking_date"], errors="coerce").dropna()
    return dates.max().normalize() if not dates.empty else pd.NaT


def build_lifecycle_activity_events(history_df):
    """Build one reusable per-base, per-date transition lookup."""
    required = {"tracking_date", "journey_stage"}
    if history_df is None or history_df.empty or not required.issubset(history_df.columns):
        return pd.DataFrame()

    events = history_df.copy()
    events["_activity_base_key"] = lifecycle_base_key_series(events)
    events["_activity_date"] = pd.to_datetime(
        events["tracking_date"], errors="coerce"
    ).dt.normalize()
    events = events.dropna(subset=["_activity_date"]).sort_values(
        ["_activity_base_key", "_activity_date"], kind="stable"
    )
    events["previous_journey_stage"] = events.groupby(
        "_activity_base_key", sort=False
    )["journey_stage"].shift(1)
    events["today_status"] = "CONTINUED"

    first_detected = pd.to_datetime(
        events.get("first_detected_date", pd.Series(pd.NaT, index=events.index)),
        errors="coerce",
    ).dt.normalize()
    new_base = first_detected.eq(events["_activity_date"])
    changed_stage = (
        events["previous_journey_stage"].notna()
        & events["journey_stage"].notna()
        & events["journey_stage"].ne(events["previous_journey_stage"])
    )
    events.loc[changed_stage, "today_status"] = "NEW TO STAGE"
    events.loc[new_base, "today_status"] = "NEW BASE"

    return events[
        [
            "_activity_base_key",
            "_activity_date",
            "today_status",
            "previous_journey_stage",
        ]
    ].drop_duplicates(["_activity_base_key", "_activity_date"], keep="last")


def derive_lifecycle_today_status(
    df,
    history_df,
    reference_date=None,
    row_date_column=None,
    activity_events=None,
):
    """Classify rows as NEW BASE, NEW TO STAGE, or CONTINUED.

    ``reference_date`` represents the selected scan/replay date. For a history
    table, ``row_date_column='tracking_date'`` derives the status on each row's
    own historical date instead.
    """
    if df is None or df.empty:
        return df

    result = df.copy()
    result["_activity_base_key"] = lifecycle_base_key_series(result)

    if row_date_column and row_date_column in result.columns:
        result["_activity_date"] = pd.to_datetime(
            result[row_date_column], errors="coerce"
        ).dt.normalize()
    else:
        resolved_date = pd.to_datetime(reference_date, errors="coerce")
        if pd.isna(resolved_date):
            resolved_date = latest_tracking_date(history_df)
        result["_activity_date"] = (
            resolved_date.normalize() if pd.notna(resolved_date) else pd.NaT
        )

    result["today_status"] = "CONTINUED"
    result["previous_journey_stage"] = pd.NA

    event_lookup = (
        activity_events
        if activity_events is not None
        else build_lifecycle_activity_events(history_df)
    )
    if event_lookup is not None and not event_lookup.empty:
        result = result.drop(
            columns=["today_status", "previous_journey_stage"]
        ).merge(
            event_lookup,
            on=["_activity_base_key", "_activity_date"],
            how="left",
        )

    first_detected = pd.to_datetime(
        result.get("first_detected_date", pd.Series(pd.NaT, index=result.index)),
        errors="coerce",
    ).dt.normalize()
    result["today_status"] = result["today_status"].fillna("CONTINUED")
    result.loc[first_detected.eq(result["_activity_date"]), "today_status"] = "NEW BASE"

    return result.drop(columns=["_activity_base_key", "_activity_date"])
