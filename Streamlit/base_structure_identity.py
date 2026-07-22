"""Identity rules for deduplicating the same base across search windows."""

import pandas as pd


DEFAULT_EQUIVALENCE = {
    "EQUIVALENT_BASE_LEFT_HIGH_MAX_WEEKS": 2,
    "EQUIVALENT_BASE_LOW_MAX_WEEKS": 1,
    "EQUIVALENT_BASE_LEFT_HIGH_PRICE_TOLERANCE_PCT": 0.05,
    "EQUIVALENT_BASE_LOW_PRICE_TOLERANCE_PCT": 0.03,
}


def _relative_difference(first, second):
    first = pd.to_numeric(first, errors="coerce")
    second = pd.to_numeric(second, errors="coerce")
    if pd.isna(first) or pd.isna(second) or max(abs(first), abs(second)) == 0:
        return float("inf")
    return abs(float(first) - float(second)) / max(abs(float(first)), abs(float(second)))


def bases_are_equivalent(first, second, params=None):
    """Return True when two window results represent one economic base."""
    settings = {**DEFAULT_EQUIVALENCE, **(params or {})}
    if str(first.get("Symbol", "")).removesuffix(".NS") != str(
        second.get("Symbol", "")
    ).removesuffix(".NS"):
        return False

    first_left = pd.to_datetime(first.get("left_high_index"), errors="coerce")
    second_left = pd.to_datetime(second.get("left_high_index"), errors="coerce")
    first_low = pd.to_datetime(first.get("base_low_index"), errors="coerce")
    second_low = pd.to_datetime(second.get("base_low_index"), errors="coerce")
    if any(pd.isna(value) for value in [first_left, second_left, first_low, second_low]):
        return False

    left_weeks = abs((first_left - second_left).days) / 7
    low_weeks = abs((first_low - second_low).days) / 7
    if left_weeks > float(settings["EQUIVALENT_BASE_LEFT_HIGH_MAX_WEEKS"]):
        return False
    if low_weeks > float(settings["EQUIVALENT_BASE_LOW_MAX_WEEKS"]):
        return False

    first_left_price = first.get("left_high", first.get("left_high_pivot"))
    second_left_price = second.get("left_high", second.get("left_high_pivot"))
    first_low_price = first.get("base_low", first.get("base_low_pivot"))
    second_low_price = second.get("base_low", second.get("base_low_pivot"))
    return bool(
        _relative_difference(first_left_price, second_left_price)
        <= float(settings["EQUIVALENT_BASE_LEFT_HIGH_PRICE_TOLERANCE_PCT"])
        and _relative_difference(first_low_price, second_low_price)
        <= float(settings["EQUIVALENT_BASE_LOW_PRICE_TOLERANCE_PCT"])
    )


def base_window_value(row):
    value = row.get("base_window_weeks", row.get("scan_window_weeks"))
    numeric = pd.to_numeric(value, errors="coerce")
    return int(numeric) if pd.notna(numeric) else 0


def consolidate_equivalent_bases(rows, params=None):
    """Keep the largest representative while recording every matching window."""
    canonical = []
    ordered = sorted(
        [dict(row) for row in rows],
        key=base_window_value,
        reverse=True,
    )
    for row in ordered:
        match = next(
            (kept for kept in canonical if bases_are_equivalent(kept, row, params)),
            None,
        )
        if match is None:
            window = base_window_value(row)
            row["equivalent_base_windows"] = str(window) if window else ""
            row["equivalent_window_count"] = 1
            canonical.append(row)
            continue

        windows = {
            int(value)
            for value in str(match.get("equivalent_base_windows", "")).split(",")
            if value.strip().isdigit()
        }
        duplicate_window = base_window_value(row)
        if duplicate_window:
            windows.add(duplicate_window)
        match["equivalent_base_windows"] = ",".join(
            str(value) for value in sorted(windows, reverse=True)
        )
        match["equivalent_window_count"] = len(windows)
    return canonical
