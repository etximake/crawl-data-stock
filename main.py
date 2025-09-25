"""Currency inflation comparison tool.

This script downloads FX rates from Yahoo Finance and CPI data from the
Federal Reserve (FRED) to analyse the inflation-adjusted value of
currency pairs.  The logic is optimised for the workflow described in the
project README: the user only needs to provide the currency pairs and the
script takes care of the rest.

Example
-------
$ python main.py GBP-JPY
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

import pandas as pd
import yfinance as yf
from fredapi import Fred

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_START_DATE = "2015-01-01"
START_AMOUNT_BASE_CURRENCY = 1_000.0


OUTPUT_FILENAME = "currency_inflation_comparison.xlsx"

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def parse_currency_pairs(pairs: Sequence[str]) -> List[str]:
    """Normalise and validate the list of currency pairs provided by the user."""

    formatted_pairs: List[str] = []
    for raw_pair in pairs:
        cleaned = raw_pair.strip().upper()
        if not cleaned:
            continue
        if "-" not in cleaned:
            raise ValueError(
                f"Cặp tiền '{raw_pair}' không hợp lệ. Vui lòng sử dụng định dạng 'CUR1-CUR2'."
            )
        code_a, code_b = cleaned.split("-", maxsplit=1)
        if len(code_a) != 3 or len(code_b) != 3:
            raise ValueError(
                f"Cặp tiền '{raw_pair}' không hợp lệ. Mỗi mã tiền phải gồm 3 ký tự."
            )
        formatted_pairs.append(f"{code_a}-{code_b}")

    if not formatted_pairs:
        raise ValueError("Bạn phải cung cấp ít nhất một cặp tiền tệ.")

    return formatted_pairs


def collect_currency_codes(pairs: Iterable[str]) -> List[str]:
    """Return the unique currency codes that appear in the requested pairs."""

    currencies: List[str] = []
    for pair in pairs:
        for code in pair.split("-"):
            if code not in currencies:
                currencies.append(code)
    return currencies


def parse_cpi_overrides(raw_overrides: Sequence[str]) -> Dict[str, str]:
    """Convert CLI overrides of the form CODE=SERIES_ID into a dictionary."""

    overrides: Dict[str, str] = {}
    for item in raw_overrides:
        if "=" not in item:
            raise ValueError(
                f"Giá trị override '{item}' không hợp lệ. Định dạng đúng: CODE=SERIES_ID."
            )
        code, series_id = item.split("=", maxsplit=1)
        code = code.strip().upper()
        series_id = series_id.strip()
        if len(code) != 3 or not series_id:
            raise ValueError(
                f"Giá trị override '{item}' không hợp lệ. Ví dụ hợp lệ: GBP=GBRCPIALLMINMEI."
            )
        overrides[code] = series_id
    return overrides


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Tự động tải dữ liệu và so sánh sức mua giữa các cặp tiền tệ.",
    )
    parser.add_argument(
        "pairs",
        nargs="*",
        help="Danh sách các cặp tiền ở định dạng CUR1-CUR2 (vd: GBP-JPY EUR-USD).",
    )
    parser.add_argument(
        "--start",
        default=DEFAULT_START_DATE,
        help="Ngày bắt đầu thu thập dữ liệu (YYYY-MM-DD). Mặc định: %(default)s",
    )
    parser.add_argument(
        "--amount",
        type=float,
        default=START_AMOUNT_BASE_CURRENCY,
        help="Số tiền ban đầu tính theo đồng tiền thứ nhất trong mỗi cặp. Mặc định: %(default).0f",
    )
    parser.add_argument(
        "--fred-key",
        default=os.getenv("FRED_API_KEY", ""),
        help="API key của FRED. Mặc định sẽ đọc từ biến môi trường FRED_API_KEY nếu có.",
    )
    parser.add_argument(
        "--output",
        default=OUTPUT_FILENAME,
        help="Tên file Excel đầu ra. Mặc định: %(default)s",
    )
    parser.add_argument(
        "--cpi-series",
        nargs="*",
        default=[],
        metavar="CODE=SERIES_ID",
        help=(
            "Ghi đè mã CPI cho từng đồng tiền nếu cần (ví dụ: GBP=GBRCPIALLMINMEI). "
            "Hữu ích khi việc tìm kiếm tự động không cho kết quả mong muốn."
        ),
    )
    return parser


def request_missing_arguments(args: argparse.Namespace) -> None:
    """Prompt the user for missing mandatory arguments when running interactively."""

    if not args.pairs:
        user_input = input(
            "Nhập các cặp tiền tệ (ví dụ: GBP-JPY,EUR-USD): "
        ).strip()
        args.pairs = [part for part in user_input.replace(",", " ").split() if part]

    if not args.fred_key:
        args.fred_key = input("Nhập FRED API key của bạn: ").strip()


def load_usd_fx_rate(code: str, start_date: str, end_date: str) -> Tuple[pd.Series, str | None]:
    """Download the USD exchange rate for a single currency."""

    if code == "USD":
        index = pd.date_range(start=start_date, end=end_date, freq="D")
        return pd.Series(1.0, index=index, name=code), None

    candidates: Tuple[Tuple[str, bool], ...] = (
        (f"{code}USD=X", False),
        (f"USD{code}=X", True),
    )

    for ticker, invert in candidates:
        data = yf.download(ticker, start=start_date, end=end_date, auto_adjust=True, progress=False)
        if not isinstance(data, pd.DataFrame) or "Close" not in data:
            continue
        series = data["Close"].dropna()
        if series.empty:
            continue
        series.index = pd.to_datetime(series.index)
        series = series.ffill().resample("D").ffill()
        if invert:
            series = 1 / series
        series.name = code
        return series, ticker

    raise ValueError(f"Không thể tải dữ liệu tỷ giá USD cho mã tiền {code} từ Yahoo Finance.")


def download_fx_data(currencies: Sequence[str], start_date: str, end_date: str) -> Tuple[pd.DataFrame, Dict[str, str]]:
    """Download USD exchange rates for all requested currencies."""

    series_list: List[pd.Series] = []
    sources: Dict[str, str] = {}

    for code in currencies:
        series, ticker = load_usd_fx_rate(code, start_date, end_date)
        series_list.append(series)
        if ticker:
            sources[code] = ticker

    fx_df = pd.concat(series_list, axis=1)
    fx_df = fx_df.dropna()
    if fx_df.empty:
        raise ValueError("Không có dữ liệu tỷ giá sau khi tải và làm sạch.")

    return fx_df, sources


def infer_cpi_series_id(fred: Fred, code: str, overrides: Mapping[str, str]) -> str:
    """Determine the CPI series id for a currency using overrides or FRED search."""

    manual_defaults = {
        # United States
        "USD": "CPIAUCNS",
        # United Kingdom
        "GBP": "GBRCPIALLMINMEI",
        # Japan
        "JPY": "JPNCPIALLMINMEI",
        # Euro Area (Eurostat harmonised index)
        "EUR": "CP0000EZ19M086NEST",
        # Australia
        "AUD": "AUSCPIALLMINMEI",
        # Canada
        "CAD": "CPALTT01CAM661N",
        # Switzerland
        "CHF": "CP0000CHM086NEST",
        # China
        "CNY": "CHNCPIALLMINMEI",
        # South Korea
        "KRW": "KORCPIALLMINMEI",
        # Singapore
        "SGD": "SGPCPIALLMINMEI",
    }

    if code in overrides:
        return overrides[code]
    if code in manual_defaults:
        return manual_defaults[code]

    search_terms = [
        f"{code} consumer price index all items",
        f"{code} consumer price index",
        f"{code} CPI",
        code,
    ]

    for term in search_terms:
        results = fred.search(term)
        if results is None or results.empty:
            continue

        candidates = results.copy()
        if "frequency" in candidates.columns:
            candidates = candidates[candidates["frequency"].str.contains("Monthly", case=False, na=False)]
        if "title" in candidates.columns:
            title_mask = candidates["title"].str.contains("Consumer Price Index", case=False, na=False)
            candidates = candidates[title_mask]
            all_items_mask = candidates["title"].str.contains("All Items", case=False, na=False)
            if all_items_mask.any():
                candidates = candidates[all_items_mask]

        if candidates.empty:
            continue

        sort_columns: List[Tuple[str, bool]] = []
        if "popularity" in candidates.columns:
            sort_columns.append(("popularity", False))
        if "search_rank" in candidates.columns:
            sort_columns.append(("search_rank", True))

        if sort_columns:
            columns, orders = zip(*sort_columns)
            candidates = candidates.sort_values(list(columns), ascending=list(orders))

        top_row = candidates.iloc[0]
        if "id" in top_row:
            return str(top_row["id"])
        if "series_id" in top_row:
            return str(top_row["series_id"])

    raise ValueError(
        f"Không thể tự động xác định mã CPI cho {code}. "
        "Sử dụng tham số --cpi-series để chỉ định thủ công (ví dụ: GBP=GBRCPIALLMINMEI)."
    )


def download_cpi_series(
    currencies: Sequence[str],
    fred: Fred,
    start_date: str,
    overrides: Mapping[str, str],
) -> Tuple[pd.DataFrame, Dict[str, str]]:
    """Download CPI series for all currencies and upsample to daily frequency."""

    frames: List[pd.Series] = []
    used_series: Dict[str, str] = {}

    for code in currencies:
        series_id = infer_cpi_series_id(fred, code, overrides)
        series = fred.get_series(series_id, observation_start=start_date)
        if series.empty:
            raise ValueError(
                f"Không tìm được dữ liệu CPI cho {code} với mã '{series_id}'."
            )
        series.index = pd.to_datetime(series.index)
        series = series.ffill().resample("D").ffill()
        series.name = code
        frames.append(series)
        used_series[code] = series_id

    cpi_df = pd.concat(frames, axis=1)
    cpi_df = cpi_df.dropna()
    if cpi_df.empty:
        raise ValueError("Không có dữ liệu CPI sau khi tải và làm sạch.")

    return cpi_df, used_series


def align_datasets(fx_df: pd.DataFrame, cpi_df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Return FX and CPI data aligned on a shared daily index."""

    common_index = fx_df.index.intersection(cpi_df.index)
    if common_index.empty:
        raise ValueError(
            "Không tìm thấy khoảng thời gian chung giữa dữ liệu tỷ giá và CPI. Kiểm tra ngày bắt đầu."
        )

    fx_aligned = fx_df.loc[common_index]
    cpi_aligned = cpi_df.loc[common_index]
    return fx_aligned, cpi_aligned


def resample_monthly(
    fx_df: pd.DataFrame, cpi_df: pd.DataFrame
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Convert the aligned daily data to month-end frequency."""

    if not fx_df.index.equals(cpi_df.index):
        raise ValueError("Chỉ số thời gian của dữ liệu tỷ giá và CPI không khớp.")

    fx_monthly = fx_df.resample("M").last()
    cpi_monthly = cpi_df.resample("M").last()
    return fx_monthly, cpi_monthly


def build_inflation_report(
    fx_monthly: pd.DataFrame,
    cpi_monthly: pd.DataFrame,
    pairs: Sequence[str],
    base_amount: float,
) -> pd.DataFrame:
    """Assemble a detailed month-by-month inflation comparison for every pair."""

    records: List[Dict[str, float | str | datetime]] = []

    for pair in pairs:
        code_a, code_b = pair.split("-")

        fx_a_usd = fx_monthly[code_a]
        fx_b_usd = fx_monthly[code_b]
        fx_a_to_b = fx_a_usd / fx_b_usd

        cpi_a = cpi_monthly[code_a]
        cpi_b = cpi_monthly[code_b]

        base_fx_ratio = fx_a_to_b.iloc[0]
        base_cpi_a = cpi_a.iloc[0]
        base_cpi_b = cpi_b.iloc[0]

        initial_amount_b = base_amount * base_fx_ratio

        inflation_index_a = cpi_a / base_cpi_a
        inflation_index_b = cpi_b / base_cpi_b

        inflation_pct_a = (inflation_index_a - 1.0) * 100.0
        inflation_pct_b = (inflation_index_b - 1.0) * 100.0
        inflation_diff = inflation_pct_a - inflation_pct_b

        yoy_a = cpi_a.pct_change(periods=12) * 100.0
        yoy_b = cpi_b.pct_change(periods=12) * 100.0

        real_value_a_usd = (base_amount / inflation_index_a) * fx_a_usd
        real_value_b_usd = (initial_amount_b / inflation_index_b) * fx_b_usd
        purchasing_power_ratio = real_value_a_usd / real_value_b_usd

        for timestamp in fx_monthly.index:
            records.append(
                {
                    "Pair": pair,
                    "Month": timestamp,
                    "Currency A": code_a,
                    "Currency B": code_b,
                    "Inflation Index A": inflation_index_a.loc[timestamp],
                    "Inflation Index B": inflation_index_b.loc[timestamp],
                    "Inflation Change A (%)": inflation_pct_a.loc[timestamp],
                    "Inflation Change B (%)": inflation_pct_b.loc[timestamp],
                    "Inflation Difference (pp)": inflation_diff.loc[timestamp],
                    "YoY Inflation A (%)": yoy_a.loc[timestamp],
                    "YoY Inflation B (%)": yoy_b.loc[timestamp],
                    "FX A/USD": fx_a_usd.loc[timestamp],
                    "FX B/USD": fx_b_usd.loc[timestamp],
                    "FX A/B": fx_a_to_b.loc[timestamp],
                    "Real Value A (USD)": real_value_a_usd.loc[timestamp],
                    "Real Value B (USD)": real_value_b_usd.loc[timestamp],
                    "Purchasing Power Ratio": purchasing_power_ratio.loc[timestamp],
                }
            )

    detail_df = pd.DataFrame.from_records(records)
    detail_df.sort_values(["Pair", "Month"], inplace=True)
    return detail_df


def create_summary(detail_df: pd.DataFrame) -> pd.DataFrame:
    """Extract the latest month of metrics for each currency pair."""

    if detail_df.empty:
        return detail_df.copy()

    latest_rows = (
        detail_df.sort_values(["Pair", "Month"])
        .groupby("Pair", as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )
    return latest_rows


def build_sources_table(
    currencies: Sequence[str],
    fx_sources: Mapping[str, str],
    cpi_series: Mapping[str, str],
) -> pd.DataFrame:
    """Create a table describing the FX and CPI data sources for Excel output."""

    rows: List[Dict[str, str]] = []
    for code in currencies:
        rows.append(
            {
                "Currency": code,
                "FX Source": fx_sources.get(code, "USD (1.0)"),
                "CPI Series": cpi_series[code],
            }
        )
    sources_df = pd.DataFrame(rows)
    return sources_df.sort_values("Currency").reset_index(drop=True)


def save_to_excel(
    summary_df: pd.DataFrame,
    detail_df: pd.DataFrame,
    sources_df: pd.DataFrame,
    filename: str,
) -> None:
    """Persist the comparison tables to an Excel workbook with multiple sheets."""

    summary_out = summary_df.copy()
    detail_out = detail_df.copy()

    for df in (summary_out, detail_out):
        if not df.empty:
            df["Month"] = pd.to_datetime(df["Month"]).dt.strftime("%Y-%m")
            numeric_cols = df.select_dtypes(include=["float", "int"]).columns
            df[numeric_cols] = df[numeric_cols].round(4)

    with pd.ExcelWriter(filename) as writer:
        summary_out.to_excel(writer, sheet_name="Summary", index=False)
        detail_out.to_excel(writer, sheet_name="Monthly Detail", index=False)
        sources_df.to_excel(writer, sheet_name="Sources", index=False)


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    request_missing_arguments(args)

    try:
        pairs = parse_currency_pairs(args.pairs)
    except ValueError as exc:
        parser.error(str(exc))
        return

    if not args.fred_key:
        parser.error("Bạn cần cung cấp FRED API key để chạy script.")
        return

    try:
        cpi_overrides = parse_cpi_overrides(args.cpi_series)
    except ValueError as exc:
        parser.error(str(exc))
        return

    currencies = collect_currency_codes(pairs)

    print("\n--- BẮT ĐẦU QUY TRÌNH THU THẬP DỮ LIỆU ---")
    print(f"Các cặp tiền được yêu cầu: {', '.join(pairs)}")
    print(f"Sử dụng dữ liệu từ {args.start} tới hiện tại.")
    print(f"Cần phân tích các đồng tiền: {', '.join(currencies)}\n")

    end_date = datetime.now().strftime("%Y-%m-%d")
    fred = Fred(api_key=args.fred_key)

    fx_df, fx_sources = download_fx_data(currencies, args.start, end_date)
    cpi_df, cpi_series = download_cpi_series(currencies, fred, args.start, cpi_overrides)
    fx_aligned, cpi_aligned = align_datasets(fx_df, cpi_df)
    fx_monthly, cpi_monthly = resample_monthly(fx_aligned, cpi_aligned)

    print("Nguồn tỷ giá USD đã chọn:")
    for code in currencies:
        ticker = fx_sources.get(code)
        if ticker:
            print(f"  - {code}: {ticker}")
        else:
            print(f"  - {code}: USD (1.0)")
    print("")

    print("Mã CPI sử dụng:")
    for code in currencies:
        print(f"  - {code}: {cpi_series[code]}")
    print("")

    print("Hoàn tất tải dữ liệu. Bắt đầu tính toán...\n")

    detail_table = build_inflation_report(fx_monthly, cpi_monthly, pairs, args.amount)
    summary_table = create_summary(detail_table)
    sources_table = build_sources_table(currencies, fx_sources, cpi_series)

    save_to_excel(summary_table, detail_table, sources_table, args.output)

    print(f"Đã lưu kết quả vào file '{args.output}'.")
    print("  - Sheet 'Summary': Chỉ số mới nhất cho từng cặp tiền.")
    print("  - Sheet 'Monthly Detail': Diễn biến theo từng tháng.")
    print("  - Sheet 'Sources': Nguồn dữ liệu đã sử dụng.\n")
    print("--- HOÀN THÀNH ---\n")


if __name__ == "__main__":
    main()
