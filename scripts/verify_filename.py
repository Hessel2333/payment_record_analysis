from werkzeug.utils import secure_filename

filenames = [
    "微信支付账单(20240101-20240131).csv",
    "微信支付账单(20240201-20240229).csv",
    "支付宝交易流水证明_2024.csv",
    "alipay_record_2024.csv",
    "中文文件名.csv"
]

print(f"{'Original':<40} | {'Secured':<40}")
print("-" * 85)
for f in filenames:
    s = secure_filename(f)
    print(f"{f:<40} | {s:<40}")
