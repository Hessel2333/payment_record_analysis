import pandas as pd
import sys

print("Loading...", file=sys.stderr)
try:
    filepath = 'Record_File/支付宝账单/alipay_record_2024.csv'
    # Manually finding header
    header = 0
    with open(filepath, encoding='gbk') as f:
        for i, line in enumerate(f):
            if '交易时间' in line:
                header = i
                break
    
    print(f"Header at {header}", file=sys.stderr)
    df = pd.read_csv(filepath, encoding='gbk', skiprows=header)
    print(f"Loaded {len(df)} rows")
    print(df['交易分类'].value_counts().head().to_dict())
except Exception as e:
    print(f"Error: {e}")
