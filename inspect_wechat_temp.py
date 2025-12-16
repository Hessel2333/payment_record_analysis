import pandas as pd
import sys

file_path = "/Users/tian/Codes/Pay_record_analysis/Record_File/微信支付账单流水文件(20210101-20210331)_20251216085809.xlsx"
try:
    df = pd.read_excel(file_path, header=16, engine='openpyxl')
    print("Unique Statuses:")
    print(df['当前状态'].unique())
    print("Unique Types:")
    print(df['收/支'].unique())
except Exception as e:
    print(f"Error: {e}")
