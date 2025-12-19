import pandas as pd
import os
from collections import Counter

def analyze_merchant_names():
    # 获取当前目录下所有支付宝账单文件
    csv_files = [f for f in os.listdir('.') if f.startswith('alipay_record_') and f.endswith('.csv')]
    
    all_merchants = []
    
    for file in csv_files:
        try:
            # 先读取文件找到表头行
            with open(file, encoding='gbk') as f:
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
                # 读取CSV文件
                df = pd.read_csv(file, encoding='gbk', skiprows=header_row)
                
                # 只分析支出数据
                expense_df = df[df['收/支'] == '支出']
                
                # 收集所有交易对方
                merchants = expense_df['交易对方'].tolist()
                all_merchants.extend(merchants)
                
                print(f"成功处理文件 {file}，包含 {len(merchants)} 个交易对方")
            
        except Exception as e:
            print(f"处理文件 {file} 时出错: {str(e)}")
    
    # 统计每个商家出现的次数
    merchant_counts = Counter(all_merchants)
    
    # 按出现次数排序
    sorted_merchants = sorted(merchant_counts.items(), key=lambda x: x[1], reverse=True)
    
    # 将结果写入文本文件
    with open('merchant_analysis.txt', 'w', encoding='utf-8') as f:
        f.write("交易对方分析结果：\n")
        f.write("格式：商家名称 (出现次数)\n\n")
        
        for merchant, count in sorted_merchants:
            f.write(f"{merchant} ({count})\n")
    
    print(f"\n分析完成，共发现 {len(merchant_counts)} 个不同的交易对方")
    print("结果已保存到 merchant_analysis.txt")

if __name__ == '__main__':
    analyze_merchant_names() 