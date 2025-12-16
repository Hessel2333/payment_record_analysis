# 支付宝账单分析系统 API 设计

## 1. 系统架构

### 1.1 数据流
1. 用户上传账单文件 (CSV/XLSX)
2. 后端解析并缓存数据
3. 前端通过统一 API 获取分析数据
4. 会话结束后自动清理数据

### 1.2 数据安全
- 所有数据仅在会话期间保存
- 使用 uuid 隔离不同用户的数据
- 文件保存在临时目录，定期清理
- 数据分析在本地进行，不上传服务器

## 2. 核心 API

### 2.1 统一数据查询接口
~~~
GET /api/stats

参数：
- year: (int) 年份筛选
- month: (int) 月份筛选
- category: (string) 分类筛选
- type: (string) 收支类型 [expense/income/all]
- group_by: (string) 分组方式 [date/category/hour/payment]
- min_amount: (float) 最小金额
- max_amount: (float) 最大金额
- include_invalid: (bool) 是否包含无效交易，默认 false

返回：
{
    "metadata": {
        "total_records": 100,
        "date_range": {
            "start": "2024-01-01",
            "end": "2024-12-31"
        }
    },
    "summary": {
        "total_amount": 5000.00,
        "avg_amount": 50.00,
        "transaction_count": 100,
        "active_days": 30
    },
    "groups": {
        "group_key": {
            "total_amount": 1000.00,
            "transaction_count": 20,
            "avg_amount": 50.00,
            "active_days": 10
        }
    },
    "status": {
        "交易成功": {
            "count": 95,
            "amount": 4800.00
        },
        "退款成功": {
            "count": 5,
            "amount": -200.00
        }
    }
}
~~~

### 2.2 可用日期查询
~~~
GET /api/available_dates

返回：
{
    "years": [2023, 2024],
    "months": {
        "2023": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        "2024": [1, 2, 3]
    },
    "min_date": "2023-01-01",
    "max_date": "2024-03-31"
}
~~~

### 2.3 文件上传接口
~~~
POST /api/upload
Content-Type: multipart/form-data

参数：
- file: 账单文件 (CSV/XLSX)

返回：
{
    "success": true,
    "filename": "alipay_record_2024.csv",
    "message": "上传成功"
}
~~~

## 3. 数据处理规则

### 3.1 数据验证
~~~python
必需字段_支付宝 = [
    '交易时间', '收/支', '金额', '交易分类', 
    '商品说明', '交易状态'
]

必需字段_微信 = [
    '交易时间', '收/支', '金额(元)', '交易类型', 
    '商品', '当前状态'
]
~~~

### 3.2 交易状态处理
- 交易成功：正常计入统计
- 退款成功：金额取负值，抵消原交易
- 交易关闭：视为退款处理
- 其他状态：标记为无效交易

### 3.3 支付方式标准化
~~~python
支付方式映射 = {
    '余额宝': ['余额宝', '红包'],
    '花呗': ['花呗'],
    '信用卡': ['信用卡'],
    '储蓄卡': ['储蓄卡']
}
~~~

### 3.4 特殊交易过滤
- 余额宝转入转出
- 信用卡还款
- 转账交易
- 红包交易

## 4. 使用示例

### 4.1 年度分析
~~~javascript
// 获取2024年支出统计
fetch('/api/stats?year=2024&type=expense&group_by=date')

// 获取2024年收入分类统计
fetch('/api/stats?year=2024&type=income&group_by=category')
~~~

### 4.2 月度分析
~~~javascript
// 获取2024年1月每日支出
fetch('/api/stats?year=2024&month=1&type=expense&group_by=date')
~~~

### 4.3 分类分析
~~~javascript
// 获取餐饮类别的时间分布
fetch('/api/stats?category=餐饮美食&group_by=date')
~~~

### 4.4 支付方式分析
~~~javascript
// 获取支付方式统计
fetch('/api/stats?group_by=payment')
~~~

## 5. 错误处理

### 5.1 统一错误返回格式
~~~json
{
    "success": false,
    "error": "错误信息描述"
}
~~~

### 5.2 常见错误类型
- 文件格式错误
- 缺少必需字段
- 数据类型错误
- 会话过期
- 文件不存在

## 6. 性能优化

### 6.1 数据缓存
- 使用 lru_cache 缓存数据加载结果
- 文件上传后清除缓存
- 会话结束自动清理

### 6.2 查询优化
- 按需加载数据
- 合理使用索引
- 减少重复计算

## 7. 注意事项

1. 数据安全：
   - 不永久存储用户数据
   - 会话超时自动清理
   - 文件访问权限控制

2. 错误处理：
   - 所有API返回统一格式
   - 详细的错误信息
   - 适当的HTTP状态码

3. 性能考虑：
   - 大文件处理
   - 并发请求处理
   - 内存使用优化 