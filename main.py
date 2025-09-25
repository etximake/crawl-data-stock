# --- START OF FILE main_v3.py ---

"""Script so sánh sức mua giữa các cặp tiền tệ."""

import argparse
from datetime import datetime
import sys
from typing import Dict, List, Tuple

import pandas as pd
import yfinance as yf
from fredapi import Fred

# --- CẤU HÌNH SCRIPT ---

# 1. Danh sách cặp tiền mặc định nếu không truyền tham số dòng lệnh
DEFAULT_CURRENCY_PAIRS: List[str] = [
    "GBP-JPY",
]

# 2. Các tham số khác
DEFAULT_START_AMOUNT = 1000.0
DEFAULT_START_DATE = "2015-01-01"
DEFAULT_END_DATE = datetime.now().strftime("%Y-%m-%d")
DEFAULT_FRED_API_KEY = "d734a47c4d9113d7238034d16aa61bf0"
DEFAULT_OUTPUT_FILENAME = "currency_pair_comparison_for_charts.csv"

# 3. Cơ sở dữ liệu tiền tệ
DEFAULT_CURRENCY_DATABASE: Dict[str, Dict[str, str]] = {
    "USD": {
        "name": "Đô la Mỹ",
        "fx_ticker": None,  # Là tiền tệ cơ sở
        "cpi_series": "CPIAUCNS",  # CPI for United States
        "region": "Bắc Mỹ",
        "fx_type": "base",
    },
    "GBP": {
        "name": "Bảng Anh",
        "fx_ticker": "GBPUSD=X",
        "cpi_series": "GBRCPIALLMINMEI",
        "region": "Châu Âu",
        "fx_type": "direct",
    },
    "JPY": {
        "name": "Yên Nhật",
        "fx_ticker": "USDJPY=X",
        "cpi_series": "JPNCPIALLMINMEI",
        "region": "Châu Á",
        "fx_type": "inverse",
    },
}

# 4. Fallback cho mã CPI khi thiếu cấu hình chi tiết trong cơ sở dữ liệu.
#    Điều này hữu ích khi người dùng thêm tiền tệ mới nhưng quên khai báo
#    mã CPI hoặc vô tình xóa khỏi cấu hình mặc định.
KNOWN_CPI_SERIES: Dict[str, str] = {
    code: details["cpi_series"]
    for code, details in DEFAULT_CURRENCY_DATABASE.items()
    if details.get("cpi_series")
}
# --- KẾT THÚC CẤU HÌNH ---


def parse_cpi_overrides(raw_value: str | None) -> Dict[str, str]:
    """Phân tích tham số --cpi-series ở định dạng CODE=SERIES."""

    overrides: Dict[str, str] = {}
    if not raw_value:
        return overrides

    parts = [item.strip() for item in raw_value.split(",") if item.strip()]
    for part in parts:
        if "=" not in part:
            raise ValueError(
                "Định dạng --cpi-series không hợp lệ. Hãy sử dụng ví dụ như GBP=GBRCPIALLMINMEI"
            )
        code, series = [token.strip().upper() for token in part.split("=", 1)]
        if not code or not series:
            raise ValueError(
                "Định dạng --cpi-series không hợp lệ. Hãy sử dụng ví dụ như GBP=GBRCPIALLMINMEI"
            )
        overrides[code] = series
    return overrides


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="So sánh sức mua giữa các cặp tiền tệ với dữ liệu CPI"
    )
    parser.add_argument(
        "--pairs",
        type=str,
        help=(
            "Danh sách cặp tiền dạng CUR1-CUR2, phân tách bởi dấu phẩy "
            "(ví dụ: GBP-USD,EUR-USD)"
        ),
    )
    parser.add_argument(
        "--start-date",
        dest="start_date",
        type=str,
        default=DEFAULT_START_DATE,
        help="Ngày bắt đầu (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        dest="end_date",
        type=str,
        default=DEFAULT_END_DATE,
        help="Ngày kết thúc (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--start-amount",
        dest="start_amount",
        type=float,
        default=DEFAULT_START_AMOUNT,
        help="Số tiền ban đầu bằng đồng tiền cơ sở của cặp (mặc định: 1000)",
    )
    parser.add_argument(
        "--output",
        dest="output_file",
        type=str,
        default=DEFAULT_OUTPUT_FILENAME,
        help="Tên file CSV đầu ra",
    )
    parser.add_argument(
        "--fred-api-key",
        dest="fred_api_key",
        type=str,
        default=DEFAULT_FRED_API_KEY,
        help="FRED API key. Có thể bỏ trống để sử dụng giá trị mặc định trong file",
    )
    parser.add_argument(
        "--cpi-series",
        dest="cpi_overrides",
        type=str,
        help="Ghi đè mã CPI cho từng đồng tiền, ví dụ: GBP=GBRCPIALLMINMEI,JPY=JPNCPIALLMINMEI",
    )
    return parser


def normalize_pairs(raw_pairs: str | None, fallback: List[str]) -> List[str]:
    if not raw_pairs:
        return fallback
    pairs: List[str] = []
    for item in raw_pairs.split(","):
        value = item.strip().upper()
        if value:
            pairs.append(value)
    return pairs or fallback


def build_and_validate_job_list(pairs: List[str], db: Dict[str, Dict[str, str]]) -> Tuple:
    """
    Phân tích các cặp tiền, xác thực và tập hợp tất cả các yêu cầu dữ liệu.
    """

    print("0. Đang phân tích và xác thực các cặp tiền tệ...")
    unique_currencies = set()
    invalid_codes = []

    for pair in pairs:
        codes = pair.split("-")
        if len(codes) != 2:
            print(f"\nLỖI: Cặp '{pair}' không hợp lệ. Phải có định dạng 'CUR1-CUR2'.")
            return None, None, None

        for code in codes:
            if code not in db:
                invalid_codes.append(code)
            unique_currencies.add(code)

    if invalid_codes:
        print(
            f"\nLỖI: Không tìm thấy các mã tiền tệ sau: {', '.join(sorted(set(invalid_codes)))}"
        )
        print("Các mã được hỗ trợ bao gồm:", ", ".join(db.keys()))
        return None, None, None

    fx_tickers_needed = [db[c]["fx_ticker"] for c in unique_currencies if db[c]["fx_ticker"]]

    # Bổ sung mã CPI bị thiếu bằng cơ sở tri thức mặc định nếu có.
    missing_cpi = []
    for code in unique_currencies:
        if db[code].get("cpi_series"):
            continue
        if code in KNOWN_CPI_SERIES:
            db[code]["cpi_series"] = KNOWN_CPI_SERIES[code]
            print(
                "   -> Tự động áp dụng mã CPI mặc định "
                f"'{KNOWN_CPI_SERIES[code]}' cho {code}."
            )
        else:
            missing_cpi.append(code)

    cpi_series_needed = {code: db[code]["cpi_series"] for code in unique_currencies}
    still_missing = [code for code, series in cpi_series_needed.items() if not series]
    if still_missing:
        missing_list = ", ".join(sorted(still_missing))
        raise ValueError(
            "Không thể tự động xác định mã CPI cho các đồng tiền: "
            f"{missing_list}. Sử dụng tham số --cpi-series để chỉ định thủ công (ví dụ: GBP=GBRCPIALLMINMEI)."
        )

    print("-> Xác thực thành công.")
    print(f"-> Sẽ phân tích {len(pairs)} cặp tiền.")
    print(f"-> Cần tải dữ liệu cho các đồng tiền: {', '.join(sorted(unique_currencies))}\n")
    return list(unique_currencies), fx_tickers_needed, cpi_series_needed


def get_data(
    fx_tickers: List[str], cpi_map: Dict[str, str], api_key: str, start: str, end: str
) -> pd.DataFrame:
    """Tải tất cả dữ liệu FX và CPI cần thiết."""

    print("1. Đang tải tất cả dữ liệu cần thiết...")
    try:
        # Tải FX
        fx_data = yf.download(
            fx_tickers, start=start, end=end, auto_adjust=True, progress=False
        )["Close"]
        if len(fx_tickers) == 1:
            fx_data = fx_data.to_frame(name=fx_tickers[0])
        fx_data.ffill(inplace=True)

        # Tải CPI
        fred = Fred(api_key=api_key)
        cpi_df = pd.DataFrame()
        for name, code in cpi_map.items():
            series = fred.get_series(code, observation_start=start)
            cpi_df[name] = series
        cpi_df.index = pd.to_datetime(cpi_df.index)
        cpi_daily = cpi_df.resample("D").ffill()

        # Kết hợp
        combined_df = fx_data.join(cpi_daily, how="inner").dropna()
        print("-> Tải và kết hợp dữ liệu thành công.\n")
        return combined_df
    except Exception as e:  # pylint: disable=broad-except
        print(f"Lỗi khi tải dữ liệu: {e}")
        return pd.DataFrame()


def get_usd_rate(df: pd.DataFrame, code: str, db: Dict[str, Dict[str, str]]):
    """Lấy tỷ giá hối đoái của một đồng tiền so với USD, xử lý fx_type."""

    if code == "USD":
        return 1.0

    props = db[code]
    ticker = props["fx_ticker"]
    fx_type = props["fx_type"]

    if fx_type == "direct":  # CUR/USD
        return df[ticker]
    if fx_type == "inverse":  # USD/CUR
        return 1 / df[ticker]
    raise ValueError(f"fx_type '{fx_type}' không được hỗ trợ cho {code}.")


def main() -> None:
    print("--- SCRIPT SO SÁNH SỨC MUA GIỮA CÁC CẶP TIỀN TỆ ---")

    parser = build_arg_parser()
    args = parser.parse_args()

    currency_pairs = normalize_pairs(args.pairs, DEFAULT_CURRENCY_PAIRS)

    try:
        cpi_overrides = parse_cpi_overrides(args.cpi_overrides)
    except ValueError as exc:
        print(f"\nLỗi: {exc}")
        sys.exit(1)

    currency_database = {code: details.copy() for code, details in DEFAULT_CURRENCY_DATABASE.items()}
    for code, series in cpi_overrides.items():
        if code not in currency_database:
            print(
                f"\nCảnh báo: Không tìm thấy thông tin tiền tệ cho {code}. "
                "Hãy thêm cấu hình vào DEFAULT_CURRENCY_DATABASE."
            )
            continue
        currency_database[code]["cpi_series"] = series

    # Bước 0: Xây dựng danh sách công việc từ đầu vào
    try:
        currencies, fx_tickers, cpi_series = build_and_validate_job_list(
            currency_pairs, currency_database
        )
    except ValueError as exc:
        print(f"\nLỗi: {exc}")
        sys.exit(1)
    if not currencies:
        sys.exit(1)

    fred_api_key = args.fred_api_key or DEFAULT_FRED_API_KEY
    if "YOUR_FRED_API_KEY" in fred_api_key or not fred_api_key:
        print("\nLỗi: Vui lòng thay thế 'YOUR_FRED_API_KEY' bằng API key thật của bạn từ FRED.")
        return

    start_amount = args.start_amount
    start_date = args.start_date
    end_date = args.end_date
    output_file = args.output_file

    # Bước 1 & 2: Tải tất cả dữ liệu một lần
    df = get_data(fx_tickers, cpi_series, fred_api_key, start_date, end_date)
    if df.empty:
        print("Không thể tải dữ liệu cần thiết. Kết thúc chương trình.")
        return

    # Bước 3: Thực hiện tính toán cho từng cặp
    print("3. Đang thực hiện tính toán cho từng cặp...")
    results_df = pd.DataFrame(index=df.index)

    for pair in currency_pairs:
        code_a, code_b = pair.split("-")
        print(f"-> Đang xử lý cặp: {code_a}-{code_b}")

        # Lấy tỷ giá A/USD và B/USD tại ngày bắt đầu
        start_rate_a_usd = get_usd_rate(df.iloc[0], code_a, currency_database)
        start_rate_b_usd = get_usd_rate(df.iloc[0], code_b, currency_database)

        # Tính tỷ giá chéo A/B tại ngày bắt đầu
        start_rate_a_b = start_rate_a_usd / start_rate_b_usd

        # Tính lượng tiền B ban đầu
        initial_amount_b = start_amount * start_rate_a_b

        # Lấy CPI cơ sở
        base_cpi_a = df[code_a].iloc[0]
        base_cpi_b = df[code_b].iloc[0]

        # Tính sức mua thực tế theo đồng nội tệ
        real_value_a = start_amount / (df[code_a] / base_cpi_a)
        real_value_b = initial_amount_b / (df[code_b] / base_cpi_b)

        # Chuẩn hóa về USD để so sánh
        daily_rate_a_usd = get_usd_rate(df, code_a, currency_database)
        daily_rate_b_usd = get_usd_rate(df, code_b, currency_database)

        # Lưu kết quả vào DataFrame chung
        results_df[f"{pair}_{code_a}"] = real_value_a * daily_rate_a_usd
        results_df[f"{pair}_{code_b}"] = real_value_b * daily_rate_b_usd

    print("-> Tính toán hoàn tất.\n")

    # Bước 4: Định dạng kết quả cho Living Charts
    print("4. Đang định dạng dữ liệu đầu ra...")
    monthly_data = results_df.resample("M").last()
    pivoted_data = monthly_data.transpose()
    pivoted_data.columns = pivoted_data.columns.strftime("%Y-%m")

    # Tạo các cột metadata
    names = []
    groups = []
    regions = []
    for col_name in pivoted_data.index:
        pair, code = col_name.split("_")
        base_code = pair.split("-")[0]
        if code == base_code:
            names.append(f"Sức mua của {start_amount:,.0f} {code}")
        else:
            names.append("Sức mua của lượng {code} tương đương".format(code=code))
        groups.append(pair)
        regions.append(currency_database[code]["region"])

    pivoted_data["Name"] = names
    pivoted_data["Group"] = groups
    pivoted_data["Region"] = regions

    date_columns = [col for col in pivoted_data.columns if col not in ["Name", "Group", "Region"]]
    final_df = pivoted_data[["Name", "Group", "Region"] + date_columns]

    try:
        final_df.to_csv(output_file, index=False)
        print(f"-> Hoàn tất! Dữ liệu đã được lưu vào file '{output_file}'\n")
    except Exception as e:  # pylint: disable=broad-except
        print(f"Lỗi khi lưu file CSV: {e}")

    print("--- QUÁ TRÌNH HOÀN TẤT ---")


if __name__ == "__main__":
    main()
# --- END OF FILE main_v3.py ---
