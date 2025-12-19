# 支付宝账单分析系统 API 文档

## API 概述

本文档详细说明了支付宝账单分析系统的所有 API 接口。所有接口均采用 RESTful 风格设计，返回 JSON 格式数据。

## 1. 文件管理 API

### 1.1 上传文件
~~~http
POST /api/upload
Content-Type: multipart/form-data

file: 账单文件 (支持 .csv 或 .xlsx; 支付宝仅支持 .csv，微信支持 .xlsx/.csv)
~~~

**响应示例：**
~~~json
{
    "success": true,
    "filename": "alipay_record_2024.csv",
    "message": "上传成功"
}
~~~

### 1.2 获取文件列表
~~~http
GET /api/files
~~~

**响应示例：**
~~~json
{
    "files": [
        {
            "name": "alipay_record_2024.csv",
            "size": 1024567
        }
    ]
}
~~~

### 1.3 删除文件
~~~http
DELETE /api/files/{filename}
~~~

**响应示例：**
~~~json
{
    "success": true
}
~~~

## 2. 数据分析 API

### 2.1 年度分析
~~~http
GET /api/yearly_analysis
Query Parameters:
  - year: 年份（可选，默认当前年）
  - filter: 筛选类型（all/large/small）
~~~

**响应示例：**
~~~json
{
    "total_expense": 170595.24,
    "total_income": 44619.38,
    "transaction_count": 1398,
    "monthly_trend": [...],
    "category_distribution": [...]
}
~~~

### 2.2 月度分析
~~~http
GET /api/monthly_analysis
Query Parameters:
  - year: 年份
  - month: 月份
  - filter: 筛选类型
~~~

**响应示例：**
~~~json
{
    "total": 15234.56,
    "count": 156,
    "daily_avg": 507.82,
    "mom_rate": -5.2,
    "categories": [...]
}
~~~

### 2.3 分类分析
~~~http
GET /api/category_analysis
Query Parameters:
  - category: 分类名称
  - range: 时间范围
  - filter: 筛选类型
~~~

**响应示例：**
~~~json
{
    "categories": ["餐饮美食", "日用百货"],
    "category_groups": {
        "alipay": ["餐饮美食", "交通出行"],
        "wechat": ["转账", "红包"]
    },
    "stats": {
        "totals": [1000.0, 500.0],
        "counts": [10, 5],
        "averages": [100.0, 100.0]
    }
}
~~~

### 2.4 时间分析
~~~http
GET /api/time_analysis
Query Parameters:
  - year: 年份
  - month: 月份（可选）
  - filter: 筛选类型
~~~

### 2.5 交易记录
~~~http
GET /api/transactions
Query Parameters:
  - page: 页码
  - size: 每页条数
  - category: 分类
  - type: 收支类型
  - min_amount: 最小金额
  - max_amount: 最大金额
  - keyword: 搜索关键词
~~~

### 2.6 分类详情
~~~http
GET /api/category_detail/{month}/{category}
Query Parameters:
  - min_amount: 最小金额（可选）
  - max_amount: 最大金额（可选）
  - weekend_only: 是否仅周末（可选，boolean）
~~~

**响应示例：**
~~~json
[
    {
        "time": "2024-03-15 12:30:45",
        "description": "午餐",
        "counterparty": "某餐厅",
        "amount": 35.50,
        "status": "交易成功"
    }
]
~~~

## 3. 会话管理 API

### 3.1 获取会话状态
~~~http
GET /api/session/status
~~~

**响应示例：**
~~~json
{
    "active": true,
    "remaining": 1500,
    "timeout": 1800
}
~~~

## 4. 错误处理

所有 API 在发生错误时返回统一格式：

~~~json
{
    "success": false,
    "error": "错误信息描述"
}
~~~

### 常见错误代码：

- 400: 请求参数错误
- 401: 未授权访问
- 404: 资源不存在
- 413: 文件大小超限
- 415: 不支持的文件类型
- 500: 服务器内部错误

## 5. 数据格式规范

### 5.1 时间格式
- 日期时间：ISO 8601 格式（YYYY-MM-DD HH:mm:ss）
- 日期：YYYY-MM-DD
- 月份：YYYY-MM

### 5.2 金额格式
- 数值类型：float
- 精度：小数点后2位
- 货币单位：人民币（元）

### 5.3 分页参数
- page: 从1开始的页码
- size: 每页记录数（默认20，最大100）

## 6. 安全说明

- 所有 API 请求需要在有效会话内进行
- 会话超时时间为 30 分钟
- 文件大小限制为 16MB
- 仅支持 CSV (支付宝/微信) 和 XLSX (微信) 格式文件上传
~~~ 