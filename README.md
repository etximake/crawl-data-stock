# crawl-data-stock

Công cụ dòng lệnh giúp tải dữ liệu tỷ giá (Yahoo Finance) và lạm phát (FRED)
để so sánh sức mua thực tế giữa các cặp tiền tệ từ năm 2015 đến nay.

## Chuẩn bị

1. Cài đặt các thư viện Python cần thiết:
   ```bash
   pip install pandas yfinance fredapi
   ```
2. Tạo FRED API key tại [https://fred.stlouisfed.org/](https://fred.stlouisfed.org/)
   và lưu vào biến môi trường `FRED_API_KEY` (hoặc cung cấp trực tiếp khi chạy script).

## Sử dụng

Chạy lệnh sau và truyền vào các cặp tiền cần so sánh theo định dạng `CUR1-CUR2`:

```bash
python main.py GBP-JPY EUR-USD
```

Một vài tham số hữu ích:

- `--start`: ngày bắt đầu thu thập dữ liệu (mặc định `2015-01-01`).
- `--amount`: số tiền ban đầu tính theo đồng tiền thứ nhất trong mỗi cặp (mặc định `1000`).
- `--fred-key`: API key nếu không đặt biến môi trường.
- `--output`: tên file Excel đầu ra (mặc định `currency_inflation_comparison.xlsx`).
- `--cpi-series`: (tùy chọn) ghi đè mã CPI cho từng đồng tiền khi việc tìm kiếm tự động không phù hợp, ví dụ `GBP=GBRCPIALLMINMEI`.

Nếu không truyền đối số, chương trình sẽ hỏi thông tin trực tiếp trong quá trình chạy.

## Kết quả

Script tạo file Excel với cấu trúc:

| Name | Image | 2015-01 | 2015-02 | ... |
|------|-------|---------|---------|-----|
| GBP  |       | ...     | ...     | ... |
| JPY  |       | ...     | ...     | ... |

Trong đó mỗi dòng thể hiện sức mua tính theo USD (đã điều chỉnh lạm phát)
cho số tiền ban đầu ở từng đồng tiền thuộc các cặp mà bạn cung cấp.
