# --- START OF FILE main_v3.py ---

import yfinance as yf
import pandas as pd
from fredapi import Fred
from datetime import datetime
import sys

# --- CẤU HÌNH SCRIPT ---

# 1. ĐẦU VÀO SIÊU ĐƠN GIẢN: Nhập các cặp tiền tệ bạn muốn so sánh.
CURRENCY_PAIRS_TO_ANALYZE = [
    "GBP-JPY",
]

# 2. CÁC THAM SỐ KHÁC
START_AMOUNT_BASE_CURRENCY = 1000.0
START_DATE = "2015-01-01"
END_DATE = datetime.now().strftime('%Y-%m-%d')

# THAY THẾ 'YOUR_FRED_API_KEY' BẰNG KEY CỦA BẠN
FRED_API_KEY = 'd734a47c4d9113d7238034d16aa61bf0'

OUTPUT_FILENAME = "currency_pair_comparison_for_charts.csv"

# --- CƠ SỞ DỮ LIỆU TIỀN TỆ (Đã thêm USD) ---
CURRENCY_DATABASE = {
    "USD": {
        "name": "Đô la Mỹ",
        "fx_ticker": None, # Là tiền tệ cơ sở
        "cpi_series": "CPIAUCNS", # CPI for United States
        "region": "Bắc Mỹ",
        "fx_type": "base"
    },
    "GBP": {
        "name": "Bảng Anh",
        "fx_ticker": "GBPUSD=X",
        "cpi_series": "GBRCPIALLMINMEI",
        "region": "Châu Âu",
        "fx_type": "direct"
    },
}
# --- KẾT THÚC CẤU HÌNH ---


def build_and_validate_job_list(pairs: list, db: dict) -> tuple:
    """
    Phân tích các cặp tiền, xác thực và tập hợp tất cả các yêu cầu dữ liệu.
    """
    print("0. Đang phân tích và xác thực các cặp tiền tệ...")
    unique_currencies = set()
    invalid_codes = []

    for pair in pairs:
        codes = pair.split('-')
        if len(codes) != 2:
            print(f"\nLỖI: Cặp '{pair}' không hợp lệ. Phải có định dạng 'CUR1-CUR2'.")
            return None, None, None
        
        for code in codes:
            if code not in db:
                invalid_codes.append(code)
            unique_currencies.add(code)

    if invalid_codes:
        print(f"\nLỖI: Không tìm thấy các mã tiền tệ sau: {', '.join(sorted(set(invalid_codes)))}")
        print("Các mã được hỗ trợ bao gồm:", ", ".join(db.keys()))
        return None, None, None

    fx_tickers_needed = [db[c]['fx_ticker'] for c in unique_currencies if db[c]['fx_ticker']]
    cpi_series_needed = {code: db[code]['cpi_series'] for code in unique_currencies}
    
    print("-> Xác thực thành công.")
    print(f"-> Sẽ phân tích {len(pairs)} cặp tiền.")
    print(f"-> Cần tải dữ liệu cho các đồng tiền: {', '.join(sorted(unique_currencies))}\n")
    return list(unique_currencies), fx_tickers_needed, cpi_series_needed

def get_data(fx_tickers: list, cpi_map: dict, api_key: str, start: str, end: str) -> pd.DataFrame:
    """Tải tất cả dữ liệu FX và CPI cần thiết."""
    print("1. Đang tải tất cả dữ liệu cần thiết...")
    try:
        # Tải FX
        fx_data = yf.download(fx_tickers, start=start, end=end, auto_adjust=True, progress=False)['Close']
        if len(fx_tickers) == 1:
            fx_data = fx_data.to_frame(name=fx_tickers[0])
        fx_data.ffill(inplace=True)

        # Tải CPI
        fred = Fred(api_key=api_key)
        cpi_df = pd.DataFrame()
        for name, code in cpi_map.items():
            series = fred.get_series(code, observation_start=start)
            cpi_df[name] = series
        cpi_daily = cpi_df.resample('D').ffill()

        # Kết hợp
        combined_df = fx_data.join(cpi_daily, how='inner').dropna()
        print("-> Tải và kết hợp dữ liệu thành công.\n")
        return combined_df
    except Exception as e:
        print(f"Lỗi khi tải dữ liệu: {e}")
        return pd.DataFrame()

def get_usd_rate(df: pd.DataFrame, code: str, db: dict):
    """Lấy tỷ giá hối đoái của một đồng tiền so với USD, xử lý fx_type."""
    if code == 'USD':
        return 1.0
    
    props = db[code]
    ticker = props['fx_ticker']
    fx_type = props['fx_type']

    if fx_type == 'direct': # CUR/USD
        return df[ticker]
    elif fx_type == 'inverse': # USD/CUR
        return 1 / df[ticker]

def main():
    print("--- SCRIPT SO SÁNH SỨC MUA GIỮA CÁC CẶP TIỀN TỆ ---")

    # Bước 0: Xây dựng danh sách công việc từ đầu vào
    currencies, fx_tickers, cpi_series = build_and_validate_job_list(CURRENCY_PAIRS_TO_ANALYZE, CURRENCY_DATABASE)
    if not currencies:
        sys.exit(1)
    
    if 'YOUR_FRED_API_KEY' in FRED_API_KEY or not FRED_API_KEY:
        print("\nLỗi: Vui lòng thay thế 'YOUR_FRED_API_KEY' bằng API key thật của bạn từ FRED.")
        return

    # Bước 1 & 2: Tải tất cả dữ liệu một lần
    df = get_data(fx_tickers, cpi_series, FRED_API_KEY, START_DATE, END_DATE)
    if df.empty:
        print("Không thể tải dữ liệu cần thiết. Kết thúc chương trình.")
        return

    # Bước 3: Thực hiện tính toán cho từng cặp
    print("3. Đang thực hiện tính toán cho từng cặp...")
    results_df = pd.DataFrame(index=df.index)

    for pair in CURRENCY_PAIRS_TO_ANALYZE:
        code_a, code_b = pair.split('-')
        print(f"-> Đang xử lý cặp: {code_a}-{code_b}")
        
        # Lấy tỷ giá A/USD và B/USD tại ngày bắt đầu
        start_rate_a_usd = get_usd_rate(df.iloc[0], code_a, CURRENCY_DATABASE)
        start_rate_b_usd = get_usd_rate(df.iloc[0], code_b, CURRENCY_DATABASE)
        
        # Tính tỷ giá chéo A/B tại ngày bắt đầu
        start_rate_a_b = start_rate_a_usd / start_rate_b_usd
        
        # Tính lượng tiền B ban đầu
        initial_amount_b = START_AMOUNT_BASE_CURRENCY * start_rate_a_b
        
        # Lấy CPI cơ sở
        base_cpi_a = df[code_a].iloc[0]
        base_cpi_b = df[code_b].iloc[0]

        # Tính sức mua thực tế theo đồng nội tệ
        real_value_a = START_AMOUNT_BASE_CURRENCY / (df[code_a] / base_cpi_a)
        real_value_b = initial_amount_b / (df[code_b] / base_cpi_b)
        
        # Chuẩn hóa về USD để so sánh
        daily_rate_a_usd = get_usd_rate(df, code_a, CURRENCY_DATABASE)
        daily_rate_b_usd = get_usd_rate(df, code_b, CURRENCY_DATABASE)
        
        # Lưu kết quả vào DataFrame chung
        results_df[f'{pair}_{code_a}'] = real_value_a * daily_rate_a_usd
        results_df[f'{pair}_{code_b}'] = real_value_b * daily_rate_b_usd
    
    print("-> Tính toán hoàn tất.\n")

    # Bước 4: Định dạng kết quả cho Living Charts
    print("4. Đang định dạng dữ liệu đầu ra...")
    monthly_data = results_df.resample('M').last()
    pivoted_data = monthly_data.transpose()
    pivoted_data.columns = pivoted_data.columns.strftime('%Y-%m')

    # Tạo các cột metadata
    names = []
    groups = []
    regions = []
    for col_name in pivoted_data.index:
        pair, code = col_name.split('_')
        base_code = pair.split('-')[0]
        if code == base_code:
            names.append(f"Sức mua của {START_AMOUNT_BASE_CURRENCY:,.0f} {code}")
        else:
            names.append(f"Sức mua của lượng {code} tương đương")
        groups.append(pair)
        regions.append(CURRENCY_DATABASE[code]['region'])
        
    pivoted_data['Name'] = names
    pivoted_data['Group'] = groups
    pivoted_data['Region'] = regions
    
    date_columns = [col for col in pivoted_data.columns if col not in ['Name', 'Group', 'Region']]
    final_df = pivoted_data[['Name', 'Group', 'Region'] + date_columns]

    try:
        final_df.to_csv(OUTPUT_FILENAME, index=False)
        print(f"-> Hoàn tất! Dữ liệu đã được lưu vào file '{OUTPUT_FILENAME}'\n")
    except Exception as e:
        print(f"Lỗi khi lưu file CSV: {e}")

    print("--- QUÁ TRÌNH HOÀN TẤT ---")

if __name__ == "__main__":
    main()
# --- END OF FILE main_v3.py ---