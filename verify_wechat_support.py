import pandas as pd
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_load_data(data_dir):
    all_data = []
    print(f"Scanning directory: {data_dir}")
    
    for filename in os.listdir(data_dir):
        filepath = os.path.join(data_dir, filename)
        
        # Alipay (CSV)
        if filename.endswith('.csv'):
            print(f"Found CSV: {filename}")
            try:
                with open(filepath, encoding='gbk') as f:
                    lines = f.readlines()
                    header_row = None
                    status_row = None
                    for i, line in enumerate(lines):
                        if '交易状态' in line:
                            status_row = i
                        if '交易时间' in line:
                            header_row = i
                            break
                
                if header_row is not None:
                    df = pd.read_csv(filepath, encoding='gbk', skiprows=header_row)
                    # Status column
                    status_df = pd.read_csv(filepath, encoding='gbk', skiprows=status_row, nrows=1)
                    status_column = status_df.columns[0]
                    # Preprocess
                    df['交易时间'] = pd.to_datetime(df['交易时间'])
                    df['月份'] = df['交易时间'].dt.strftime('%Y-%m')
                    df['日期'] = df['交易时间'].dt.strftime('%Y-%m-%d')
                    # Refund
                    df['是否退款'] = df[status_column].isin(['退款成功', '交易关闭'])
                    df.loc[df['是否退款'], '金额'] = -df.loc[df['是否退款'], '金额']
                    
                    df['Source'] = 'Alipay'
                    all_data.append(df)
                    print(f"  Loaded {len(df)} rows from Alipay")
            except Exception as e:
                print(f"  Error loading CSV: {e}")

        # WeChat (XLSX)
        elif filename.endswith('.xlsx'):
            print(f"Found XLSX: {filename}")
            try:
                df = pd.read_excel(filepath, header=16, engine='openpyxl')
                if '交易时间' in df.columns and '金额(元)' in df.columns:
                    # Map columns
                    df = df.rename(columns={
                        '交易类型': '交易分类', 
                        '商品': '商品说明',
                        '金额(元)': '金额',
                        '当前状态': '交易状态',
                        '支付方式': '收/付款方式'
                    })
                    # Clean Amount
                    df['金额'] = df['金额'].astype(str).str.replace('¥', '').str.replace(',', '').astype(float)
                    # Time
                    df['交易时间'] = pd.to_datetime(df['交易时间'])
                    df['月份'] = df['交易时间'].dt.strftime('%Y-%m')
                    df['日期'] = df['交易时间'].dt.strftime('%Y-%m-%d')
                    # Refund
                    df['是否退款'] = df['交易状态'].astype(str).str.contains('退款|关闭|撤销', case=False, na=False)
                    df.loc[df['是否退款'], '金额'] = -df.loc[df['是否退款'], '金额'].abs()
                    
                    # Ensure columns
                    if '交易对方' not in df.columns: df['交易对方'] = '未知'
                    if '收/支' not in df.columns: df['收/支'] = '/'
                    
                    df['Source'] = 'WeChat'
                    all_data.append(df)
                    print(f"  Loaded {len(df)} rows from WeChat")
                else:
                    print("  Invalid WeChat structure")
            except Exception as e:
                print(f"  Error loading XLSX: {e}")

    if not all_data:
        print("No data loaded")
        return None

    combined_df = pd.concat(all_data, ignore_index=True)
    combined_df = combined_df.sort_values('交易时间')
    return combined_df

if __name__ == "__main__":
    # Use the Record_File directory directly
    record_dir = "/Users/tian/Codes/Pay_record_analysis/Record_File"
    df = test_load_data(record_dir)
    
    if df is not None:
        print("\n=== Summary ===")
        print(f"Total Rows: {len(df)}")
        print(df.groupby('Source').size())
        print("\nLast 5 transactions:")
        print(df[['交易时间', 'Source', '交易分类', '金额', '收/支', '收/付款方式']].tail())
        
        # Check type of Amount
        print(f"\nAmount Dtype: {df['金额'].dtype}")
