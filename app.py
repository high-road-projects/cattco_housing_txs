"""
Cattaraugus County Sales Explorer (Streamlit)
==============================================
A Streamlit port of the R Shiny "Cattaraugus County Sales Explorer" app, with the same
filtering and the same interactive controls. Profiles arms-length real property sales by
municipality and year, restricted to:
  (1) transactions on or after January 1, 2013 (sale_date_std), and
  (2) property class 210 ("One Family Year-Round Residence") or 215 at time of sale
      (prop_class_at_sale).

Run locally:
    streamlit run app.py

Deploy on Streamlit Community Cloud (https://share.streamlit.io):
    1. Push this file, requirements.txt, and the data CSV to a public GitHub repo.
    2. On share.streamlit.io, click "New app" and point it at the repo/branch/app.py.
    3. Deploy. (See the accompanying README.md for the full walkthrough.)
"""

import os

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import streamlit as st

# -----------------------------------------------------------------------------
# Page setup
# -----------------------------------------------------------------------------

st.set_page_config(page_title="Cattaraugus County Sales Explorer", layout="wide")

DATA_PATH = os.environ.get("CATTCO_DATA_PATH", "cattco_sales_arms_length_Y_with_2026usd.csv")
ALL_LABEL = "All Municipalities (County-wide)"


# -----------------------------------------------------------------------------
# 1-2. Load data and restrict the sample:
#      (a) sale_date_std on/after 2013-01-01
#      (b) prop_class_at_sale in {"210", "215"}
# -----------------------------------------------------------------------------

@st.cache_data
def load_sales(path: str) -> pd.DataFrame:
    raw = pd.read_csv(
        path,
        dtype={"prop_class_at_sale": "string", "sale_date_std": "string", "muni_name": "string"},
        low_memory=False,
    )
    # pandas already infers outlier_flag as True/False/NaN from the text TRUE/FALSE/blank
    # in the CSV; make it an explicit nullable boolean.
    raw["outlier_flag"] = raw["outlier_flag"].astype("boolean")
    raw["sale_date_std"] = pd.to_datetime(raw["sale_date_std"], format="%m/%d/%Y", errors="coerce")

    sales = raw[
        raw["sale_date_std"].notna()
        & (raw["sale_date_std"] >= pd.Timestamp("2013-01-01"))
        & raw["prop_class_at_sale"].isin(["210", "215"])
        & raw["muni_name"].notna()
        & raw["sale_year"].notna()
    ].copy()
    sales["sale_year"] = sales["sale_year"].astype(int)
    return sales


if not os.path.exists(DATA_PATH):
    st.error(
        f"Could not find the data file at '{DATA_PATH}'. Place the CSV next to this "
        "app (and commit it to the repo for deployment), or set the CATTCO_DATA_PATH "
        "environment variable to its full path."
    )
    st.stop()

sales = load_sales(DATA_PATH)

# Municipality list is drawn from the full (pre-outlier-filter, pre-2026-filter) sample so
# the dropdown options stay stable regardless of those toggles below.
muni_choices = [ALL_LABEL] + sorted(sales["muni_name"].unique())


# -----------------------------------------------------------------------------
# 3. Helpers: apply the outlier/2026 toggles, and build year-by-municipality profiles
# -----------------------------------------------------------------------------

def get_filtered_sales(df: pd.DataFrame, outliers: str, year2026: str) -> pd.DataFrame:
    """Applies the outlier and 2026-partial-year toggles on top of the date/property-class
    filters already baked into `sales`."""
    out = df
    if outliers != "include":
        out = out[out["outlier_flag"] == False]
    if year2026 != "include":
        out = out[out["sale_year"] != 2026]
    return out


@st.cache_data
def build_year_stats(df: pd.DataFrame) -> dict:
    # A small number of records have a missing sale_price_2026usd; they are still counted
    # as transactions but excluded from the price distribution.
    df_price = df[df["sale_price_2026usd"].notna()]

    def _agg_price(g):
        return pd.Series({
            "mean_price":   g["sale_price_2026usd"].mean(),
            "median_price": g["sale_price_2026usd"].median(),
            "p25_price":    g["sale_price_2026usd"].quantile(0.25),
            "p75_price":    g["sale_price_2026usd"].quantile(0.75),
        })

    count_stats = (
        df.groupby(["muni_name", "sale_year"], as_index=False)
          .size().rename(columns={"size": "n_tx"})
    )
    price_stats = (
        df_price.groupby(["muni_name", "sale_year"])
                .apply(_agg_price, include_groups=False)
                .reset_index()
    )

    county_count = df.groupby("sale_year", as_index=False).size().rename(columns={"size": "n_tx"})
    county_count.insert(0, "muni_name", ALL_LABEL)

    county_price = df_price.groupby("sale_year").apply(_agg_price, include_groups=False).reset_index()
    county_price.insert(0, "muni_name", ALL_LABEL)

    count_all = pd.concat([count_stats, county_count], ignore_index=True)
    price_all = pd.concat([price_stats, county_price], ignore_index=True)

    year_stats = (
        count_all.merge(price_all, on=["muni_name", "sale_year"], how="outer")
                 .sort_values(["muni_name", "sale_year"])
                 .reset_index(drop=True)
    )

    # Year-over-year % change, computed relative to the previous year that has at least
    # one recorded sale for that municipality (gap years, if any, are skipped rather than
    # treated as zero).
    yoy_stats = year_stats.sort_values(["muni_name", "sale_year"]).copy()
    grp = yoy_stats.groupby("muni_name")
    for col, newcol in [
        ("n_tx", "n_tx_yoy"), ("mean_price", "mean_yoy"),
        ("median_price", "median_yoy"), ("p25_price", "p25_yoy"), ("p75_price", "p75_yoy"),
    ]:
        prev = grp[col].shift(1)
        yoy_stats[newcol] = (yoy_stats[col] / prev - 1) * 100

    return {"year_stats": year_stats, "yoy_stats": yoy_stats}


def pct_change(a, b):
    """% change from a to b, or NaN if either is missing/zero. Used for the Total row of
    the YoY tables."""
    if pd.isna(a) or pd.isna(b) or a == 0:
        return np.nan
    return (b / a - 1) * 100


def fmt_dollar(v):
    return f"${v:,.0f}" if pd.notna(v) else None


def fmt_pct(v):
    return f"{v:.1f}%" if pd.notna(v) else None


# -----------------------------------------------------------------------------
# 4. Plotting functions
# -----------------------------------------------------------------------------

def plot_level_price(tx: pd.DataFrame, stats_muni: pd.DataFrame, muni: str):
    """Box plot of individual sale prices by year (median, 25th/75th percentile, whiskers),
    with the yearly mean overlaid as a connected red line -- the app's default view."""
    fig, ax = plt.subplots(figsize=(9, 5))
    stats_muni = stats_muni[stats_muni["mean_price"].notna()]
    years = sorted(tx["sale_year"].unique())
    if years:
        data_by_year = [tx.loc[tx["sale_year"] == y, "sale_price_2026usd"].values for y in years]
        bp = ax.boxplot(data_by_year, positions=range(1, len(years) + 1), widths=0.6,
                         patch_artist=True, showfliers=True)
        for box in bp["boxes"]:
            box.set(facecolor="#4C72B0", alpha=0.35)
        mean_by_year = stats_muni.set_index("sale_year")["mean_price"].reindex(years)
        ax.plot(range(1, len(years) + 1), mean_by_year.values,
                color="#C44E52", marker="o", linewidth=2)
        ax.set_xticks(range(1, len(years) + 1))
        ax.set_xticklabels(years)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax.set_title(f"Sale price distribution by year — {muni}\n"
                 "Box = median & 25th–75th percentile; red = mean", fontsize=11)
    ax.set_xlabel("Sale year")
    ax.set_ylabel("Sale price (2026 USD)")
    fig.tight_layout()
    return fig


def plot_level_count(stats_muni: pd.DataFrame, muni: str):
    """Bar chart of transaction counts by year."""
    fig, ax = plt.subplots(figsize=(9, 5))
    x = stats_muni["sale_year"].astype(str)
    ax.bar(x, stats_muni["n_tx"], color="#4C72B0", alpha=0.8)
    for xi, v in zip(x, stats_muni["n_tx"]):
        ax.text(xi, v, str(int(v)), ha="center", va="bottom", fontsize=8)
    ax.set_title(f"Number of transactions by year — {muni}")
    ax.set_xlabel("Sale year")
    ax.set_ylabel("Number of transactions")
    fig.tight_layout()
    return fig


def plot_yoy_price(yoy_muni: pd.DataFrame, muni: str):
    """YoY % change in mean and median sale price."""
    fig, ax = plt.subplots(figsize=(9, 5))
    d = yoy_muni.dropna(subset=["mean_yoy"])
    ax.axhline(0, color="gray")
    if len(d):
        ax.plot(d["sale_year"].astype(str), d["mean_yoy"], marker="o", label="Mean")
        ax.plot(d["sale_year"].astype(str), d["median_yoy"], marker="o", label="Median")
        ax.legend(title="Statistic")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.1f}%"))
    ax.set_title(f"YoY % change in sale price — {muni}")
    ax.set_xlabel("Sale year")
    ax.set_ylabel("YoY % change")
    fig.tight_layout()
    return fig


def plot_yoy_count(yoy_muni: pd.DataFrame, muni: str):
    """YoY % change in transaction count, colored by sign."""
    fig, ax = plt.subplots(figsize=(9, 5))
    d = yoy_muni.dropna(subset=["n_tx_yoy"])
    ax.axhline(0, color="gray")
    if len(d):
        colors = ["#4C72B0" if v >= 0 else "#C44E52" for v in d["n_tx_yoy"]]
        ax.bar(d["sale_year"].astype(str), d["n_tx_yoy"], color=colors)
        for xi, v in zip(d["sale_year"].astype(str), d["n_tx_yoy"]):
            ax.text(xi, v, f"{v:.1f}%", ha="center", va="bottom" if v >= 0 else "top", fontsize=8)
    ax.set_title(f"YoY % change in number of transactions — {muni}")
    ax.set_xlabel("Sale year")
    ax.set_ylabel("YoY % change in # transactions")
    fig.tight_layout()
    return fig


# -----------------------------------------------------------------------------
# 5. Table functions
# -----------------------------------------------------------------------------

def build_level_table(stats_muni: pd.DataFrame, tx_muni: pd.DataFrame, total_n: int) -> pd.DataFrame:
    """Year-by-year level stats, plus a Total row covering the full period (overall stats
    across every transaction, not an average of the yearly rows)."""
    body = pd.DataFrame({
        "Sale year":       stats_muni["sale_year"].astype(str),
        "# Transactions":  stats_muni["n_tx"],
        "Mean price":      stats_muni["mean_price"].map(fmt_dollar),
        "Median price":    stats_muni["median_price"].map(fmt_dollar),
        "25th pctile":     stats_muni["p25_price"].map(fmt_dollar),
        "75th pctile":     stats_muni["p75_price"].map(fmt_dollar),
    })
    prices = tx_muni["sale_price_2026usd"]
    total = pd.DataFrame([{
        "Sale year":      "Total",
        "# Transactions": total_n,
        "Mean price":     fmt_dollar(prices.mean()) if len(prices) else None,
        "Median price":   fmt_dollar(prices.median()) if len(prices) else None,
        "25th pctile":    fmt_dollar(prices.quantile(0.25)) if len(prices) else None,
        "75th pctile":    fmt_dollar(prices.quantile(0.75)) if len(prices) else None,
    }])
    return pd.concat([body, total], ignore_index=True)


def build_yoy_table(yoy_muni: pd.DataFrame, year_muni: pd.DataFrame) -> pd.DataFrame:
    """Year-by-year YoY % change, plus a Total row: cumulative % change from the earliest
    to the latest year of data in the period."""
    body = pd.DataFrame({
        "Sale year":           yoy_muni["sale_year"].astype(str),
        "# Tx YoY %":          yoy_muni["n_tx_yoy"].map(fmt_pct),
        "Mean price YoY %":    yoy_muni["mean_yoy"].map(fmt_pct),
        "Median price YoY %":  yoy_muni["median_yoy"].map(fmt_pct),
        "25th pctile YoY %":   yoy_muni["p25_yoy"].map(fmt_pct),
        "75th pctile YoY %":   yoy_muni["p75_yoy"].map(fmt_pct),
    })
    yr = year_muni.sort_values("sale_year")
    if len(yr) > 0:
        first, last = yr.iloc[0], yr.iloc[-1]
        total = pd.DataFrame([{
            "Sale year":          "Total",
            "# Tx YoY %":         fmt_pct(pct_change(first["n_tx"], last["n_tx"])),
            "Mean price YoY %":   fmt_pct(pct_change(first["mean_price"], last["mean_price"])),
            "Median price YoY %": fmt_pct(pct_change(first["median_price"], last["median_price"])),
            "25th pctile YoY %":  fmt_pct(pct_change(first["p25_price"], last["p25_price"])),
            "75th pctile YoY %":  fmt_pct(pct_change(first["p75_price"], last["p75_price"])),
        }])
        return pd.concat([body, total], ignore_index=True)
    return body


# -----------------------------------------------------------------------------
# 6. Sidebar controls (mirrors the Shiny sidebar)
# -----------------------------------------------------------------------------

st.sidebar.header("Controls")

muni = st.sidebar.selectbox("Municipality", muni_choices, index=0)

measure_label = st.sidebar.radio(
    "Measure", ["Sale price (2026 USD)", "Number of transactions"], index=0,
)
measure = "price" if measure_label.startswith("Sale") else "count"

show_yoy = st.sidebar.checkbox("Show year-over-year % change instead of levels", value=False)

outliers_label = st.sidebar.radio(
    "Outliers", ["Exclude outliers (default)", "Include outliers"], index=0,
)
outliers = "exclude" if outliers_label.startswith("Exclude") else "include"

year2026_label = st.sidebar.radio(
    "2026 sales", ["Exclude 2026 (default)", "Include 2026"], index=0,
)
year2026 = "exclude" if year2026_label.startswith("Exclude") else "include"

st.sidebar.caption(
    "2026 data run only through July 30, 2026 and are not yet available for the full "
    "calendar year; included here only if you opt in above."
)
st.sidebar.markdown("---")
st.sidebar.caption(
    "Sample: Includes all single-family arms-length sales from Jan 1, 2013 onward. "
    "Prices are inflation-adjusted to 2026 dollars (CPI). By default, records flagged "
    "as statistical outliers are excluded. Box plots show the median (center line), "
    "25th–75th percentile range (box), and whiskers; the red line/points show the mean. "
    "Years with no recorded sales for a municipality are omitted, and YoY change is "
    "measured against the most recent prior year with data. Each table's \"Total\" row "
    "covers the full period (overall stats for the level table; first-to-last cumulative "
    "change for the YoY table)."
)


# -----------------------------------------------------------------------------
# 7. Compute + render
# -----------------------------------------------------------------------------

st.title("Cattaraugus County Single-Family Arm's Length Sales")

fs = get_filtered_sales(sales, outliers, year2026)
fs_price = fs[fs["sale_price_2026usd"].notna()]
profiles = build_year_stats(fs)
year_stats, yoy_stats = profiles["year_stats"], profiles["yoy_stats"]

tx = fs_price if muni == ALL_LABEL else fs_price[fs_price["muni_name"] == muni]
stats_muni = year_stats[year_stats["muni_name"] == muni].sort_values("sale_year")
yoy_muni = yoy_stats[yoy_stats["muni_name"] == muni].sort_values("sale_year")
total_n = len(fs) if muni == ALL_LABEL else len(fs[fs["muni_name"] == muni])

if not show_yoy:
    fig = plot_level_price(tx, stats_muni, muni) if measure == "price" else plot_level_count(stats_muni, muni)
else:
    fig = plot_yoy_price(yoy_muni, muni) if measure == "price" else plot_yoy_count(yoy_muni, muni)

st.pyplot(fig)
plt.close(fig)

st.subheader("Underlying year-by-year data")
tbl = build_level_table(stats_muni, tx, total_n) if not show_yoy else build_yoy_table(yoy_muni, stats_muni)
st.dataframe(tbl, hide_index=True, use_container_width=True)
