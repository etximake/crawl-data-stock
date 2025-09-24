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
from collections import Counter
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
        "USD": "CPIAUCNS",
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


def calculate_real_values(
    fx_df: pd.DataFrame,
    cpi_df: pd.DataFrame,
    pairs: Sequence[str],
    base_amount: float,
) -> pd.DataFrame:
    """Compute the inflation-adjusted USD value for each currency in every pair."""

    if not fx_df.index.equals(cpi_df.index):
        raise ValueError("Chỉ số thời gian của dữ liệu tỷ giá và CPI không khớp.")

    results = pd.DataFrame(index=fx_df.index)
    for pair in pairs:
        code_a, code_b = pair.split("-")

        daily_rate_a_usd = fx_df[code_a]
        daily_rate_b_usd = fx_df[code_b]

        start_rate_a_usd = daily_rate_a_usd.iloc[0]
        start_rate_b_usd = daily_rate_b_usd.iloc[0]
        start_rate_a_b = start_rate_a_usd / start_rate_b_usd
        initial_amount_b = base_amount * start_rate_a_b

        base_cpi_a = cpi_df[code_a].iloc[0]
        base_cpi_b = cpi_df[code_b].iloc[0]

        real_value_a = base_amount / (cpi_df[code_a] / base_cpi_a)
        real_value_b = initial_amount_b / (cpi_df[code_b] / base_cpi_b)

        results[f"{pair}:{code_a}"] = real_value_a * daily_rate_a_usd
        results[f"{pair}:{code_b}"] = real_value_b * daily_rate_b_usd

    return results


def format_for_excel(results_df: pd.DataFrame, pairs: Sequence[str]) -> pd.DataFrame:
    """Pivot the results into the Excel-friendly format requested by the user."""

    monthly = results_df.resample("M").last()
    monthly.index = monthly.index.to_period("M").to_timestamp()

    pivoted = monthly.transpose()
    pivoted.columns = [col.strftime("%Y-%m") for col in pivoted.columns]

    currency_usage = Counter(code for pair in pairs for code in pair.split("-"))

    names: List[str] = []
    images: List[str] = []
    for raw_name in pivoted.index:
        pair, code = raw_name.split(":")
        if currency_usage[code] > 1:
            display_name = f"{code} ({pair})"
        else:
            display_name = code
        names.append(display_name)
        images.append("")

    pivoted.insert(0, "Image", images)
    pivoted.insert(0, "Name", names)

    return pivoted


def save_to_excel(df: pd.DataFrame, filename: str) -> None:
    """Persist the final dataframe to an Excel file."""

    df.to_excel(filename, index=False)


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

    results = calculate_real_values(fx_aligned, cpi_aligned, pairs, args.amount)
    formatted = format_for_excel(results, pairs)

    save_to_excel(formatted, args.output)

    print(f"Đã lưu kết quả vào file '{args.output}'.")
    print("--- HOÀN THÀNH ---\n")


if __name__ == "__main__":
    main()
