from flask import Flask, render_template, jsonify, request, session, redirect, url_for
import pandas as pd
from datetime import datetime, timedelta
from functools import lru_cache, wraps
import logging
import calendar
import json
import os
from werkzeug.utils import secure_filename
import shutil
import uuid
import threading
from time import sleep
import atexit
import numpy as np
from secrets import token_hex
import itertools

app = Flask(__name__)

# 在 app 配置后添加
app.config.update(
    SESSION_COOKIE_SECURE=False,  # 本地开发环境设为 False
    SESSION_COOKIE_HTTPONLY=True,  # 防止 JavaScript 访问 cookie
    SESSION_COOKIE_SAMESITE='Lax',  # 防止 CSRF 攻击
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30)  # 设置会话过期时间
)

# 从环境变量获取密钥，如果没有则生成一个新的
app.secret_key = os.environ.get('FLASK_SECRET_KEY') or token_hex(32)

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),  # 添加文件处理器
        logging.StreamHandler()  # 保留控制台输出
    ]
)
logger = logging.getLogger(__name__)

# 添加文件上传配置
UPLOAD_FOLDER = '/tmp/flask_uploads'  # PythonAnywhere 推荐的临时目录
ALLOWED_EXTENSIONS = {'csv', 'xlsx'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_session_dir():
    """获取当前会话的临时目录"""
    if 'user_id' not in session:
        # 使用更安全的方式生成用户ID
        session['user_id'] = f"user_{token_hex(16)}"
        # 记录会话创建时间
        session['created_at'] = datetime.now().timestamp()
        
    # 检查会话是否过期
    if 'created_at' in session:
        session_age = datetime.now().timestamp() - session['created_at']
        if session_age > 1800:  # 30分钟过期
            # 清理旧文件
            old_session_dir = os.path.join(app.config['UPLOAD_FOLDER'], session['user_id'])
            if os.path.exists(old_session_dir):
                shutil.rmtree(old_session_dir)
            # 重新生成会话
            session.clear()
            return get_session_dir()
    
    session_dir = os.path.join(app.config['UPLOAD_FOLDER'], session['user_id'])
    
    if not os.path.exists(session_dir):
        os.makedirs(session_dir, mode=0o700)  # 确保目录权限正确
    
    return session_dir

def user_cache(f):
    """用户级别的缓存装饰器"""
    cache = {}
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 演示模式下不需要缓存
        if session.get('is_demo'):
            return f(*args, **kwargs)

        # 获取当前用户ID
        user_id = session.get('user_id')
        if not user_id:
            return f(*args, **kwargs)
        
        # 检查缓存是否过期
        if user_id in cache:
            cache_time, cached_data = cache[user_id]
            if datetime.now().timestamp() - cache_time < 300:  # 5 minutes cache
                return cached_data
        
        # 执行函数并缓存结果
        result = f(*args, **kwargs)
        cache[user_id] = (datetime.now().timestamp(), result)
        
        # 清理其他用户的缓存
        current_time = datetime.now().timestamp()
        expired_keys = [k for k, v in cache.items() 
                       if current_time - v[0] > 300]
        for k in expired_keys:
            del cache[k]
        
        return result
    
    def clear_cache(user_id):
        if user_id in cache:
            del cache[user_id]
            
    decorated_function.clear_cache = clear_cache
    
    return decorated_function

@user_cache
def load_alipay_data():
    try:
        # 演示模式逻辑
        if session.get('is_demo'):
            sample_file = os.path.join(app.static_folder, 'sample_data.csv')
            if not os.path.exists(sample_file):
                raise FileNotFoundError("示例数据文件不存在")
            
            df = pd.read_csv(sample_file)
            df['交易时间'] = pd.to_datetime(df['交易时间'])
            df['月份'] = df['交易时间'].dt.strftime('%Y-%m')
            df['日期'] = df['交易时间'].dt.strftime('%Y-%m-%d')
            # 确保演示数据也有这些列
            if '是否退款' not in df.columns:
                 df['是否退款'] = False
            if '来源' not in df.columns:
                 df['来源'] = '示例数据'
            return df

        session_dir = get_session_dir()
        all_data = []
        
        # 读取会话目录中的所有文件
        for filename in os.listdir(session_dir):
            filepath = os.path.join(session_dir, filename)
            
            # 处理 CSV 文件
            if filename.endswith('.csv'):
                try:
                    # 判断是否为微信账单 (CSV格式)
                    is_wechat_csv = (detect_file_source(filepath) == 'wechat')
                    
                    if is_wechat_csv:
                        # 微信 CSV 处理逻辑
                        with open(filepath, encoding='utf-8-sig') as f:
                            lines = f.readlines()
                            header_row = None
                            for i, line in enumerate(lines):
                                if '交易时间' in line and '交易类型' in line:
                                    header_row = i
                                    break
                                    
                        if header_row is not None:
                            df = pd.read_csv(filepath, encoding='utf-8-sig', skiprows=header_row)
                            
                            # 映射列名
                            df = df.rename(columns={
                                '交易类型': '交易分类',
                                '商品': '商品说明',
                                '金额(元)': '金额',
                                '当前状态': '交易状态',
                                '支付方式': '收/付款方式'
                            })
                            
                            # 清理金额列 (移除 '¥')
                            df['金额'] = df['金额'].astype(str).str.replace('¥', '').str.replace(',', '').astype(float)
                            
                            # 处理时间
                            df['交易时间'] = pd.to_datetime(df['交易时间'])
                            df['月份'] = df['交易时间'].dt.strftime('%Y-%m')
                            df['日期'] = df['交易时间'].dt.strftime('%Y-%m-%d')
                            
                            # 标记退款
                            df['是否退款'] = df['交易状态'].astype(str).str.contains('退款|关闭|撤销', case=False, na=False)
                            df.loc[df['是否退款'], '金额'] = -df.loc[df['是否退款'], '金额'].abs()
                            
                            # 确保必要列
                            if '交易对方' not in df.columns:
                                df['交易对方'] = '未知'
                            if '收/支' not in df.columns:
                                df['收/支'] = '/'
                                
                            df['来源'] = '微信'
                            all_data.append(df)
                            
                    else:
                        # 支付宝 CSV 处理逻辑 (默认 gbk)
                        try:
                            # 重新以 GBK 打开 (支付宝通常是 GBK)
                            with open(filepath, encoding='gbk') as f:
                                lines = f.readlines()
                        except UnicodeDecodeError:
                            # 如果 GBK 失败，尝试 UTF-8
                            with open(filepath, encoding='utf-8') as f:
                                lines = f.readlines()
                                
                        header_row = None
                        status_row = None
                        for i, line in enumerate(lines):
                            if '交易状态' in line and not status_row:
                                status_row = i
                            if '交易时间' in line:
                                header_row = i
                                break
                    
                        if header_row is not None:
                            # 读取数据 (使用与上面相同的编码尝试，这里简化，pandas read_csv 也可以 try-except)
                            try:
                                df = pd.read_csv(filepath, encoding='gbk', skiprows=header_row)
                                status_df = pd.read_csv(filepath, encoding='gbk', skiprows=status_row, nrows=1)
                            except UnicodeDecodeError:
                                df = pd.read_csv(filepath, encoding='utf-8', skiprows=header_row)
                                status_df = pd.read_csv(filepath, encoding='utf-8', skiprows=status_row, nrows=1)
                            
                            # ... (原有支付宝处理逻辑) ...
                            status_column = status_df.columns[0]
                            
                            # 数据预处理
                            df['交易时间'] = pd.to_datetime(df['交易时间'])
                            df['月份'] = df['交易时间'].dt.strftime('%Y-%m')
                            df['日期'] = df['交易时间'].dt.strftime('%Y-%m-%d')
                            
                            # 标记交易状态
                            df['是否退款'] = df[status_column].isin(['退款成功', '交易关闭'])
                            df.loc[df['是否退款'], '金额'] = -df.loc[df['是否退款'], '金额']
                            
                            # 添加来源标识
                            df['来源'] = '支付宝'
                            
                            all_data.append(df)
                        
                except Exception as e:
                    logger.error(f"Error processing CSV file {filename}: {str(e)}")
                    continue

            # 处理 XLSX 文件 (微信)
            elif filename.endswith('.xlsx'):
                try:
                    # 微信账单通常头部有16行说明，第17行是标题
                    # 也可以尝试自动寻找标题行，但这里先按固定格式
                    df = pd.read_excel(filepath, header=16, engine='openpyxl')
                    
                    # 检查是否是有效的微信账单（检查关键列）
                    if '交易时间' in df.columns and '金额(元)' in df.columns:
                        # 映射列名以匹配支付宝格式
                        df = df.rename(columns={
                            '交易类型': '交易分类',  # 微信的交易类型对应支付宝的交易分类
                            '商品': '商品说明',
                            '金额(元)': '金额',
                            '当前状态': '交易状态',
                            '支付方式': '收/付款方式'
                        })
                        
                        # 清理金额列 (移除 '¥' 和 ',')
                        df['金额'] = df['金额'].astype(str).str.replace('¥', '').str.replace(',', '').astype(float)
                        
                        # 处理时间
                        df['交易时间'] = pd.to_datetime(df['交易时间'])
                        df['月份'] = df['交易时间'].dt.strftime('%Y-%m')
                        df['日期'] = df['交易时间'].dt.strftime('%Y-%m-%d')
                        
                        # 标记退款
                        # 微信状态包含: '支付成功', '已全额退款', '已退款' 等
                        df['是否退款'] = df['交易状态'].astype(str).str.contains('退款|关闭|撤销', case=False, na=False)
                        
                        # 处理退款金额为负数 (保持与支付宝逻辑一致)
                        df.loc[df['是否退款'], '金额'] = -df.loc[df['是否退款'], '金额'].abs()
                        
                        # 确保所有必要列都存在
                        if '交易对方' not in df.columns:
                            df['交易对方'] = '未知'
                        if '收/支' not in df.columns: # 微信通常有'收/支'
                            df['收/支'] = '/' # 或推断
                            
                        # 添加来源标识
                        df['来源'] = '微信'
                            
                        all_data.append(df)
                    else:
                        logger.warning(f"File {filename} does not look like a standard WeChat bill.")

                except Exception as e:
                    logger.error(f"Error processing Excel file {filename}: {str(e)}")
                    continue
        
        if not all_data:
            # 修改错误信息，不再只说CSV
            raise FileNotFoundError("未找到任何支付宝(.csv)或微信(.xlsx)账单文件")
        
        # 合并所有数据
        combined_df = pd.concat(all_data, ignore_index=True)
        combined_df = combined_df.sort_values('交易时间')
        
        return combined_df
        
    except Exception as e:
        logger.error(f"Error loading data: {str(e)}")
        raise

def validate_dataframe(df):
    required_columns = ['交易时间', '收/支', '金额', '交易分类', '商品说明']
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise ValueError(f"数据缺少必需列: {', '.join(missing_columns)}")
    
    # 验证数据类型
    if not pd.api.types.is_numeric_dtype(df['金额']):
        raise ValueError("'金额'列必须是数值类型")

def check_data_exists(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 演示模式直接通过
        if session.get('is_demo'):
            return f(*args, **kwargs)

        # 如果是 settings 页面，不需要检查数据
        if request.endpoint == 'settings':
            return f(*args, **kwargs)
            
        if 'user_id' not in session:
            return redirect(url_for('settings'))
            
        session_dir = get_session_dir()
        has_data = False
        if os.path.exists(session_dir):
            for filename in os.listdir(session_dir):
                if filename.endswith('.csv') or filename.endswith('.xlsx'):
                    has_data = True
                    break
        
        if not has_data:
            return redirect(url_for('settings'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
@app.route('/index')
def index():
    return render_template('index.html', active_page='index')

@app.route('/yearly')
@check_data_exists
def yearly():
    return render_template('yearly.html', active_page='yearly')

@app.route('/monthly')
@check_data_exists
def monthly():
    return render_template('monthly.html', active_page='monthly')

@app.route('/category')
@check_data_exists
def category():
    return render_template('category.html', active_page='category')

@app.route('/time')
@check_data_exists
def time():
    return render_template('time.html', active_page='time')

@app.route('/transactions')
@check_data_exists
def transactions():
    return render_template('transactions.html', active_page='transactions')

@app.route('/insights')
@check_data_exists
def insights():
    return render_template('insights.html', active_page='insights')

@app.route('/analysis')
@check_data_exists
def analysis():
    return render_template('analysis.html', active_page='analysis')

@app.route('/api/analysis')
def get_analysis():
    try:
        df = load_alipay_data()
        
        # 获取年份参数
        year = request.args.get('year', type=int)
        if year:
            df = df[df['交易时间'].dt.year == year]
        
        # 添加金额筛选参数支持
        min_amount = request.args.get('min_amount', type=float)
        max_amount = request.args.get('max_amount', type=float)
        
        if min_amount:
            df = df[df['金额'] >= min_amount]
        if max_amount:
            df = df[df['金额'] < max_amount]
        
        # 商家分析
        merchant_analysis = analyze_merchants(df)
        
        # 消费场景分析 
        scenario_analysis = analyze_scenarios(df)
        
        # 消费习惯分析
        habit_analysis = analyze_habits(df)
        
        # 高级洞察
        latte_factor = analyze_latte_factor(df)
        nighttime_analysis = analyze_nighttime_spending(df)
        subscription_analysis = analyze_subscriptions(df)
        inflation_analysis = analyze_inflation(df)
        brand_loyalty = analyze_brand_loyalty(df)
        
        # Phase 2 洞察
        sankey_data = analyze_sankey(df)
        engel_coefficient = analyze_engel_coefficient(df)
        weekend_monday = analyze_weekend_vs_monday(df)
        story_data = generate_story_data(df)
        
        # 智能标签
        tags = generate_smart_tags(df)
        
        # 分析支付方式
        payment_analysis = analyze_payment_methods(df)
        
        # 高级可视化图表数据
        chord_data = generate_chord_data(df)
        funnel_data = generate_funnel_data(df)
        quadrant_data = generate_quadrant_data(df)
        radar_data = generate_radar_data(df)
        wordcloud_data = generate_wordcloud_data(df)
        themeriver_data = generate_themeriver_data(df)
        
        # 科研风格图表数据
        boxplot_data = generate_boxplot_data(df)
        heatmap_data = generate_heatmap_data(df)
        pareto_data = generate_pareto_data(df)
        
        return jsonify({
            'success': True,
            'data': {
                'merchant_analysis': merchant_analysis,
                'scenario_analysis': scenario_analysis,
                'habit_analysis': habit_analysis,
                'latte_factor': latte_factor,
                'nighttime_analysis': nighttime_analysis,
                'subscription_analysis': subscription_analysis,
                'inflation_analysis': inflation_analysis,
                'brand_loyalty': brand_loyalty,
                'sankey_data': sankey_data,
                'engel_coefficient': engel_coefficient,
                'weekend_monday': weekend_monday,
                'story_data': story_data,
                'tags': tags,
                'payment_analysis': payment_analysis,
                'chord_data': chord_data,
                'funnel_data': funnel_data,
                'quadrant_data': quadrant_data,
                'radar_data': radar_data,
                'wordcloud_data': wordcloud_data,
                'themeriver_data': themeriver_data,
                'boxplot_data': boxplot_data,
                'heatmap_data': heatmap_data,
                'pareto_data': pareto_data
            }
        })
        
    except Exception as e:
        logger.error(f"Analysis error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/monthly_analysis')
def monthly_analysis():
    try:
        df = load_alipay_data()
        year, month = request.args.get('year', type=int), request.args.get('month', type=int)
        min_amount = request.args.get('min_amount', type=float)
        max_amount = request.args.get('max_amount', type=float)
        
        # 获取当前月份数据
        current_month_df = df[
            (df['交易时间'].dt.year == year) & 
            (df['交易时间'].dt.month == month)
        ]
        
        # 获取上月数据
        last_month = month - 1 if month > 1 else 12
        last_year = year if month > 1 else year - 1
        last_month_df = df[
            (df['交易时间'].dt.year == last_year) & 
            (df['交易时间'].dt.month == last_month)
        ]
        
        # 应用金额筛选
        if min_amount:
            current_month_df = current_month_df[current_month_df['金额'] >= min_amount]
            last_month_df = last_month_df[last_month_df['金额'] >= min_amount]
        if max_amount:
            current_month_df = current_month_df[current_month_df['金额'] < max_amount]
            last_month_df = last_month_df[last_month_df['金额'] < max_amount]
        
        # 处理收入和支出数据
        current_expense_df = current_month_df[
            (current_month_df['收/支'] == '支出') & 
            (~current_month_df['是否退款'])
        ]
        current_income_df = current_month_df[
            (current_month_df['收/支'] == '收入') & 
            (~current_month_df['是否退款'])
        ]
        
        # 计算统计数据
        current_expense = current_expense_df['金额'].sum()
        current_income = current_income_df['金额'].sum()
        current_balance = current_income - current_expense
        
        # 计算上月数据
        last_expense = last_month_df[
            (last_month_df['收/支'] == '支出') & 
            (~last_month_df['是否退款'])
        ]['金额'].sum()
        last_income = last_month_df[
            (last_month_df['收/支'] == '收入') & 
            (~last_month_df['是否退款'])
        ]['金额'].sum()
        last_balance = last_income - last_expense
        
        # 按日期统计
        daily_expenses = current_expense_df.groupby(
            current_expense_df['交易时间'].dt.date
        )['金额'].sum()
        daily_incomes = current_income_df.groupby(
            current_income_df['交易时间'].dt.date
        )['金额'].sum()
        
        # 计算分类统计
        expense_categories = current_expense_df.groupby('交易分类')['金额'].sum()
        income_categories = current_income_df.groupby('交易分类')['金额'].sum()

        # 计算分来源的分类统计
        expense_source = current_expense_df.groupby(['来源', '交易分类'])['金额'].sum().reset_index().to_dict('records')
        income_source = current_income_df.groupby(['来源', '交易分类'])['金额'].sum().reset_index().to_dict('records')
        
        # 生成当月所有日期
        import calendar
        last_day = calendar.monthrange(year, month)[1]
        all_dates = [
            datetime(year, month, day).date() 
            for day in range(1, last_day + 1)
        ]
        
        # 补充所有日期，缺失的填充0
        daily_expenses = daily_expenses.reindex(all_dates, fill_value=0)
        daily_incomes = daily_incomes.reindex(all_dates, fill_value=0)
        
        return jsonify({
            'success': True,
            'data': {
                'stats': {
                    'balance': float(current_balance),
                    'total_expense': float(current_expense),
                    'total_income': float(current_income),
                    'expense_count': int(len(current_expense_df)),
                    'income_count': int(len(current_income_df)),
                    'comparisons': {
                        'balance': {
                            'change': float(current_balance - last_balance),
                            'rate': float((current_balance - last_balance) / abs(last_balance) * 100) if last_balance != 0 else None
                        },
                        'expense': {
                            'change': float(current_expense - last_expense),
                            'rate': float((current_expense - last_expense) / last_expense * 100) if last_expense != 0 else None
                        },
                        'income': {
                            'change': float(current_income - last_income),
                            'rate': float((current_income - last_income) / last_income * 100) if last_income != 0 else None
                        }
                    }
                },
                'daily_data': {
                    'expense': {
                        'dates': [d.strftime('%Y-%m-%d') for d in all_dates],
                        'amounts': daily_expenses.values.tolist()
                    },
                    'income': {
                        'dates': [d.strftime('%Y-%m-%d') for d in all_dates],
                        'amounts': daily_incomes.values.tolist()
                    }
                },
                'categories': {
                    'expense': {
                        'names': expense_categories.index.tolist(),
                        'amounts': expense_categories.values.tolist()
                    },
                    'income': {
                        'names': income_categories.index.tolist(),
                        'amounts': income_categories.values.tolist()
                    }
                },
                'categories_source': {
                    'expense': expense_source,
                    'income': income_source
                }
            }
        })
        
    except Exception as e:
        logger.error(f"Error in monthly analysis: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/category_expenses')
def category_expenses():
    df = load_alipay_data()
    
    # 计算分类支出
    category_stats = df[df['收/支'] == '支出'].groupby('交易分类').agg({
        '金额': 'sum'
    }).sort_values('金额', ascending=False)
    
    # 准备ECharts数据格式
    data = {
        'categories': category_stats.index.tolist(),
        'amounts': category_stats['金额'].tolist()
    }
    
    return jsonify(data)

@app.route('/api/transactions')
def get_transactions():
    try:
        df = load_alipay_data()
        
        # 获取分页参数
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)  # 默认每页20条
        
        # 获取筛选参数
        year = request.args.get('year', type=int)
        month = request.args.get('month', type=int)
        date = request.args.get('date')
        hour = request.args.get('hour', type=int)
        category = request.args.get('category')
        min_amount = request.args.get('min_amount', type=float)
        max_amount = request.args.get('max_amount', type=float)
        
        # 获取交易类型参数（收入/支出）
        type = request.args.get('type')
        
        # 获取搜索参数
        search_query = request.args.get('search')
        
        # 应用筛选条件
        if type:
            df = df[df['收/支'] == type]  # 根据收入/支出类型筛选
        
        if search_query:
            # 在商品说明、交易对方、交易分类中搜索
            mask = (
                df['商品说明'].astype(str).str.contains(search_query, case=False, na=False) |
                df['交易对方'].astype(str).str.contains(search_query, case=False, na=False) |
                df['交易分类'].astype(str).str.contains(search_query, case=False, na=False)
            )
            df = df[mask]
        
        if year:
            df = df[df['交易时间'].dt.year == year]
        if month:
            df = df[df['交易时间'].dt.month == month]
        if date:
            df = df[df['日期'] == date]
        if hour is not None:
            df = df[df['交易时间'].dt.hour == hour]
        if category:
            df = df[df['交易分类'] == category]
        if min_amount:
            df = df[df['金额'] >= min_amount]
        if max_amount:
            df = df[df['金额'] <= max_amount]
            
        # 排除"不计收支"的交易
        df = df[df['收/支'].isin(['收入', '支出'])]
        
        # 排除退款交易
        df = df[~df['是否退款']]
        
        # 按时间倒序排序
        df = df.sort_values('交易时间', ascending=False)
        
        # 计算总记录数和总页数
        total_records = len(df)
        total_pages = (total_records + per_page - 1) // per_page
        
        # 确保页码在有效范围内
        page = max(1, min(page, total_pages))
        
        # 计算当前页的数据范围
        start_idx = (page - 1) * per_page
        end_idx = min(start_idx + per_page, total_records)
        
        # 获取当前页的数据
        page_df = df.iloc[start_idx:end_idx]
        
        # 转换为列表，处理 NaN 值
        transactions = []
        for _, row in page_df.iterrows():
            transactions.append({
                'time': row['交易时间'].strftime('%Y-%m-%d %H:%M:%S'),
                'description': str(row['商品说明']),
                'category': str(row['交易分类']),
                'type': str(row['收/支']),
                'amount': float(row['金额']),
                'status': str(row['交易状态']),
                'counterparty': str(row.get('交易对方', '')) if pd.notna(row.get('交易对方')) else ''
            })
        
        # 返回数据，包含分页信息
        return jsonify({
            'success': True,
            'transactions': transactions,
            'pagination': {
                'current_page': page,
                'per_page': per_page,
                'total_pages': total_pages,
                'total_records': total_records
            }
        })
        
    except Exception as e:
        logger.error(f"获取交易记录时出错: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': f'获取交易记录失败: {str(e)}'
        }), 500

@app.route('/api/summary')
def summary():
    df = load_alipay_data()
    
    # 获取当前自然月
    current_date = datetime.now()
    current_month = current_date.strftime('%Y-%m')
    
    # 计算基础统计信息
    expense_df = df[df['收/支'] == '支出']
    total_expense = expense_df['金额'].sum()
    total_income = df[df['收/支'] == '收入']['金额'].sum()
    
    # 按月份分组计算支出
    monthly_expenses = expense_df.groupby('月份')['金额'].sum()
    
    # 获取最新月份的支出
    latest_month = monthly_expenses.index[-1]
    latest_month_expense = monthly_expenses[latest_month]
    
    # 获取当前自然月的支出（如果有数据的话）
    current_month_expense = monthly_expenses.get(current_month)
    
    # 确定要显示的月份和支出金额
    display_month = current_month if current_month_expense is not None else latest_month
    display_expense = current_month_expense if current_month_expense is not None else latest_month_expense
    
    # 计算环比变化（与上一个月相比）
    if len(monthly_expenses) > 1:
        prev_month_expense = monthly_expenses.iloc[-2]
    else:
        prev_month_expense = display_expense
    
    return jsonify({
        'total_expense': round(total_expense, 2),
        'total_income': round(total_income, 2),
        'balance': round(total_income - total_expense, 2),
        'monthly_avg': round(monthly_expenses.mean(), 2),
        'current_month_expense': round(display_expense, 2),
        'prev_monthly_avg': round(prev_month_expense, 2),
        'month_count': len(monthly_expenses),
        'transaction_count': len(expense_df),
        'current_month': display_month,
        'has_current_month_data': current_month_expense is not None
    })

@app.route('/api/daily_data')
def daily_data():
    """获取热力图数据，支持年份筛选"""
    try:
        df = load_alipay_data()
        
        # 获取查询参数
        year = request.args.get('year', type=int)
        filter_type = request.args.get('filter', 'all')
        
        # 根据筛选条件过滤数据
        if filter_type == 'large':
            df = df[df['金额'] > 1000]
        elif filter_type == 'small':
            df = df[df['金额'] <= 1000]
            
        # 如果指定了年份，过滤对应年份的数据
        if year:
            df = df[df['交易时间'].dt.year == year]
        
        # 排除"不计收支"的交易
        df = df[df['收/支'].isin(['收入', '支出'])]
        
        # 计算每日数据
        daily_data = df.groupby(['日期', '收/支']).agg({
            '金额': 'sum',
            '交易时间': 'count'
        }).reset_index()
        
        # 准备热力图数据
        expense_data = []
        income_data = []
        transaction_data = []
        
        for date, group in daily_data.groupby('日期'):
            date_str = date
            
            # 支出数据
            expense = group[group['收/支'] == '支出']
            if not expense.empty:
                expense_data.append([date_str, float(expense['金额'].iloc[0])])
                
            # 收入数据
            income = group[group['收/支'] == '收入']
            if not income.empty:
                income_data.append([date_str, float(income['金额'].iloc[0])])
                
            # 交易笔数 - 收入和支出的总和
            transaction_count = group['交易时间'].sum()
            transaction_data.append([date_str, int(transaction_count)])
        
        # 计算分位数
        expense_amounts = [x[1] for x in expense_data]
        income_amounts = [x[1] for x in income_data]
        
        expense_quantiles = []
        income_quantiles = []
        
        if expense_amounts:
            expense_quantiles = [
                round(float(x), 2) for x in np.quantile(expense_amounts, [0.2, 0.4, 0.6, 0.8])
            ]
            
        if income_amounts:
            income_quantiles = [
                round(float(x), 2) for x in np.quantile(income_amounts, [0.2, 0.4, 0.6, 0.8])
            ]
        
        return jsonify({
            'expense': expense_data,
            'income': income_data,
            'transaction': transaction_data,
            'expense_quantiles': expense_quantiles,
            'income_quantiles': income_quantiles
        })
        
    except Exception as e:
        logger.error(f"Error in daily data: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/category_detail/<month>/<category>')
def category_detail(month, category):
    df = load_alipay_data()
    
    # 获取指定月份和分类的支出明细，添加交易对方列
    details = df[
        (df['月份'] == month) & 
        (df['交易分类'] == category) & 
        (df['收/支'] == '支出')
    ].sort_values('金额', ascending=False)[
        ['交易时间', '商品说明', '交易对方', '金额', '交易状态']
    ].to_dict('records')
    
    # 格式化数据
    formatted_details = [{
        'time': detail['交易时间'].strftime('%Y-%m-%d %H:%M:%S'),
        'description': detail['商品说明'],
        'counterparty': detail['交易对方'],  # 添加交易对方
        'amount': round(float(detail['金额']), 2),
        'status': detail['交易状态']
    } for detail in details]
    
    return jsonify(formatted_details)

@app.route('/api/top_transactions')
def get_top_transactions():
    """获取大额交易记录"""
    try:
        # 获取查询参数
        limit = int(request.args.get('limit', 10))  # 默认返回前10条
        min_amount = float(request.args.get('min_amount', 1000))  # 默认1000元以上
        
        # 加载数据
        df = load_alipay_data()
        
        # 筛选支出交易
        expense_df = df[df['收/支'] == '支出'].copy()
        
        # 筛选大额交易
        large_transactions = expense_df[expense_df['金额'] >= min_amount]
        
        # 按金额排序并限制数量
        top_transactions = large_transactions.nlargest(limit, '金额')
        
        # 转换为列表
        transactions = []
        for _, row in top_transactions.iterrows():
            transactions.append({
                'time': row['交易时间'].strftime('%Y-%m-%d %H:%M:%S'),
                'date': row['交易时间'].strftime('%Y-%m-%d'),
                'category': row['交易分类'],
                'description': row['商品说明'],
                'amount': float(row['金额']),
                'status': row['交易状态'],
                'counterparty': row.get('交易对方', '')
            })
        
        return jsonify({
            'success': True,
            'transactions': transactions
        })
        
    except Exception as e:
        logger.error(f"获取大额交易记录时出错: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': f'获取大额交易记录失败: {str(e)}'
        }), 500

@app.route('/api/category_trend/<category>')
def category_trend(category):
    df = load_alipay_data()
    
    # 获取指定分类的月度数据
    category_df = df[
        (df['收/支'] == '支出') & 
        (df['交易分类'] == category)
    ]
    
    # 按月份分组计算各项指标
    monthly_stats = category_df.groupby('月份').agg({
        '金额': ['sum', 'count', 'mean'],  # 总金额、交易次数、平均金额
        '交易时间': lambda x: len(x.dt.date.unique())  # 有交易的天数
    }).round(2)
    
    # 重命名列
    monthly_stats.columns = ['total', 'transactions', 'avg_amount', 'active_days']
    
    # 计算日均支出（总金额/当月有交易的天数）
    monthly_stats['daily_avg'] = (monthly_stats['total'] / monthly_stats['active_days']).round(2)
    
    # 计算环比变化率
    monthly_stats['mom_rate'] = (monthly_stats['total'].pct_change() * 100).round(2)
    
    # 计算占比
    total_expense = df[
        (df['收/支'] == '支出')
    ].groupby('月份')['金额'].sum()
    monthly_stats['percentage'] = (monthly_stats['total'] / total_expense * 100).round(2)
    
    # 准备返回数据
    result = {
        'months': monthly_stats.index.tolist(),
        'total': monthly_stats['total'].tolist(),
        'transactions': monthly_stats['transactions'].tolist(),
        'avg_amount': monthly_stats['avg_amount'].tolist(),
        'daily_avg': monthly_stats['daily_avg'].tolist(),
        'mom_rate': monthly_stats['mom_rate'].fillna(0).tolist(),
        'percentage': monthly_stats['percentage'].tolist(),
        'summary': {
            'total_amount': category_df['金额'].sum().round(2),
            'total_transactions': len(category_df),
            'max_month': monthly_stats['total'].idxmax(),
            'max_amount': monthly_stats['total'].max().round(2),
            'min_month': monthly_stats['total'].idxmin(),
            'min_amount': monthly_stats['total'].min().round(2),
            'avg_monthly': monthly_stats['total'].mean().round(2)
        }
    }
    
    return jsonify(result)

@app.route('/api/time_analysis')
def time_analysis():
    """获取时间分析数据，支持年份筛选"""
    try:
        df = load_alipay_data()
        
        # 获取查询参数
        year = request.args.get('year', type=int)
        filter_type = request.args.get('filter', 'all')
        
        # 只分析支出数据，且排除退款
        expense_df = df[(df['收/支'] == '支出') & (~df['是否退款'])]
        # 再次确保金额大于0
        expense_df = expense_df[expense_df['金额'] > 0]
        
        # 如果指定了年份，过滤对应年份的数据
        if year:
            expense_df = expense_df[expense_df['交易时间'].dt.year == year]
            
        # 根据筛选条件过滤数据 - 移到这里，在计算统计数据之前过滤
        if filter_type == 'large':
            expense_df = expense_df[expense_df['金额'] > 1000]
        elif filter_type == 'small':
            expense_df = expense_df[expense_df['金额'] <= 1000]
        
        # 1. 计算日内时段分布
        expense_df['hour'] = expense_df['交易时间'].dt.hour
        hourly_stats = expense_df.groupby('hour').agg({
            '金额': 'sum',
            '交易时间': 'count'
        }).reset_index()
        
        # 确保所有小时都有数据，没有数据的填充0
        all_hours = pd.DataFrame({'hour': range(24)})
        hourly_stats = pd.merge(all_hours, hourly_stats, on='hour', how='left').fillna(0)
        
        hourly_data = {
            'amounts': hourly_stats['金额'].round(2).tolist(),
            'counts': hourly_stats['交易时间'].tolist()
        }
        
        # 2. 计算工作日/周末分布
        expense_df['is_weekend'] = expense_df['交易时间'].dt.dayofweek.isin([5, 6])
        category_weekday = {}
        
        for category in expense_df['交易分类'].unique():
            category_df = expense_df[expense_df['交易分类'] == category]
            
            if len(category_df) == 0:
                continue
                
            weekday_amount = category_df[~category_df['is_weekend']]['金额'].sum()
            weekend_amount = category_df[category_df['is_weekend']]['金额'].sum()
            total_amount = weekday_amount + weekend_amount
            
            if total_amount == 0:
                continue
                
            weekday_count = len(category_df[~category_df['is_weekend']])
            weekend_count = len(category_df[category_df['is_weekend']])
            
            category_weekday[category] = {
                'weekday': {
                    'amount': float(weekday_amount),
                    'count': int(weekday_count),
                    'percentage': round(weekday_amount / total_amount * 100, 1)
                },
                'weekend': {
                    'amount': float(weekend_amount),
                    'count': int(weekend_count),
                    'percentage': round(weekend_amount / total_amount * 100, 1)
                }
            }
        
        # 按总金额排序
        sorted_categories = sorted(
            category_weekday.items(),
            key=lambda x: x[1]['weekday']['amount'] + x[1]['weekend']['amount'],
            reverse=True
        )
        category_weekday = dict(sorted_categories)
        
        return jsonify({
            'hourly': hourly_data,
            'weekday_weekend': category_weekday
        })
        
    except Exception as e:
        logger.error(f"Error in time analysis: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/filtered_monthly_analysis')
def filtered_monthly_analysis():
    df = load_alipay_data()
    filter_type = request.args.get('filter', 'all')
    
    # 在原始交易数据层面进行过滤
    expense_df = df[(df['收/支'] == '支出') & (~df['是否退款'])]
    expense_df = expense_df[expense_df['金额'] > 0]
    if filter_type == 'large':
        expense_df = expense_df[expense_df['金额'] > 1000]
    elif filter_type == 'small':
        expense_df = expense_df[expense_df['金额'] <= 1000]
    
    # 使用过滤后的数据计算月度统计
    monthly_stats = expense_df.groupby('月份').agg({
        '金额': ['sum', 'count', 'mean'],  # 总金额、交易次数、平均金额
        '交易时间': lambda x: len(x.dt.date.unique())  # 有交易的天数
    }).round(2)
    
    monthly_stats.columns = ['total', 'count', 'avg_amount', 'active_days']
    
    # 计算日均支出
    monthly_stats['daily_avg'] = (monthly_stats['total'] / monthly_stats['active_days']).round(2)
    
    # 计算环比变化率
    monthly_stats['mom_rate'] = (monthly_stats['total'].pct_change() * 100).round(2)
    
    # 计算3个月移动平均
    monthly_stats['moving_avg'] = monthly_stats['total'].rolling(3, min_periods=1).mean().round(2)
    
    # 计算分类支出
    category_expenses = expense_df.pivot_table(
        index='月份',
        columns='交易分类',
        values='金额',
        aggfunc='sum',
        fill_value=0
    )
    
    return jsonify({
        'months': monthly_stats.index.tolist(),
        'total_expenses': monthly_stats['total'].tolist(),
        'transaction_counts': monthly_stats['count'].tolist(),
        'daily_averages': monthly_stats['daily_avg'].tolist(),
        'mom_rates': monthly_stats['mom_rate'].fillna(0).tolist(),
        'moving_averages': monthly_stats['moving_avg'].tolist(),
        'categories': category_expenses.columns.tolist(),
        'category_expenses': category_expenses.values.tolist()
    })

@app.route('/favicon.ico')
def favicon():
    return '', 204

@app.errorhandler(404)
def not_found_error(error):
    return "页面未找到 - 404", 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal Server Error: {str(error)}")
    return jsonify({
        'success': False,
        'error': '服务器内部错误，请稍后重试'
    }), 500

@app.route('/api/overview_data')
def get_overview_data():
    try:
        df = load_alipay_data()
        
        # 获取筛选类型
        filter_type = request.args.get('filter', 'all')
        year = request.args.get('year', None)
        
        if year is None:
            year = str(df['交易时间'].max().year)
        
        # 筛选指定年份的数据
        year_df = df[df['交易时间'].dt.year == int(year)]
        
        # 根据金额筛选数据
        if filter_type == 'large':
            year_df = year_df[year_df['金额'].abs() >= 1000]
        elif filter_type == 'small':
            year_df = year_df[year_df['金额'].abs() < 1000]
        
        # 获取所有可用的年份列表
        available_years = sorted(df['交易时间'].dt.year.unique().tolist(), reverse=True)
        
        # 计算年度统计数据
        expense_df = year_df[
            (year_df['收/支'] == '支出') & 
            (~year_df['是否退款'])
        ]
        income_df = year_df[
            (year_df['收/支'] == '收入') & 
            (~year_df['是否退款'])
        ]
        
        # 年度统计，所有金额保留2位小数
        yearly_stats = {
            'total_expense': round(expense_df['金额'].sum(), 2),
            'total_income': round(income_df['金额'].sum(), 2),
            'balance': round(income_df['金额'].sum() - expense_df['金额'].sum(), 2),
            'expense_count': len(expense_df),
            'income_count': len(income_df),
            'total_count': len(expense_df) + len(income_df),
            'active_days': len(year_df['日期'].unique()),
            'avg_transaction': round(expense_df['金额'].mean(), 2) if len(expense_df) > 0 else 0,
            'avg_daily_expense': round(expense_df['金额'].sum() / 365, 2),
            'avg_monthly_income': round(income_df['金额'].sum() / 12, 2),
            'expense_ratio': round(expense_df['金额'].sum() / income_df['金额'].sum() * 100, 2) if income_df['金额'].sum() > 0 else 0
        }
        
        # 确保包含所有月份（1-12月）
        all_months = [f'{year}-{str(month).zfill(2)}' for month in range(1, 13)]
        
        # 按月统计支出
        monthly_data = expense_df.groupby('月份')['金额'].sum().round(2)
        
        # 创建包含所有月份的完整数据框
        monthly_stats = pd.DataFrame(index=all_months)
        monthly_stats['total'] = monthly_data
        
        # 填充缺失值
        monthly_stats = monthly_stats.fillna(0)
        
        # 计算分类统计
        category_stats = expense_df.groupby('交易分类')['金额'].sum().round(2).sort_values(ascending=False)
        
        return jsonify({
            'available_years': available_years,
            'current_year': year,
            'yearly_stats': yearly_stats,
            'months': all_months,
            'amounts': monthly_stats['total'].tolist(),
            'categories': category_stats.index.tolist(),
            'amounts_by_category': category_stats.values.tolist()
        })
        
    except Exception as e:
        print(f"API错误: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/api/monthly_data')
def get_monthly_data():
    try:
        df = load_alipay_data()
        
        # 获取所有可用月份
        available_months = sorted(df['月份'].unique().tolist(), reverse=True)
        
        # 从请求参数获取年月，如果没有指定则使用最新的可用月份
        latest_month = available_months[0]
        default_year = int(latest_month.split('-')[0])
        default_month = int(latest_month.split('-')[1])
        
        current_year = request.args.get('year', default_year, type=int)
        current_month = request.args.get('month', default_month, type=int)
        
        logger.info(f"请求月度数据: {current_year}-{current_month}")
        
        # 获取当前月份数据
        current_month_str = f"{current_year}-{current_month:02d}"
        current_month_df = df[df['月份'] == current_month_str].copy()
        
        # 计算上个月的年份和月份
        if current_month == 1:
            last_month_year = current_year - 1
            last_month = 12
        else:
            last_month_year = current_year
            last_month = current_month - 1
            
        # 获取上个月数据
        last_month_str = f"{last_month_year}-{last_month:02d}"
        last_month_df = df[df['月份'] == last_month_str].copy()
        
        # 获取筛选参数
        filter_type = request.args.get('filter', 'all')
        
        # 根据筛选类型过滤数据
        if filter_type == 'large':
            current_month_df = current_month_df[current_month_df['金额'] >= 1000]  # 修改为1000元
            last_month_df = last_month_df[last_month_df['金额'] >= 1000] if not last_month_df.empty else last_month_df
        elif filter_type == 'small':
            current_month_df = current_month_df[current_month_df['金额'] < 1000]  # 修改为1000元
            last_month_df = last_month_df[last_month_df['金额'] < 1000] if not last_month_df.empty else last_month_df
        
        # 计算当前月统计
        current_stats = calculate_monthly_stats(current_month_df)
        monthly_stats = {
            **current_stats,  # 保持原有统计数据
        }
        
        # 只有当存在上月数据时才计算环比
        if not last_month_df.empty:
            last_stats = calculate_monthly_stats(last_month_df)
            
            # 计算各项指标的环比变化
            comparisons = {}
            for key in ['total_expense', 'total_income', 'balance']:
                current_val = current_stats[key]
                last_val = last_stats[key]
                diff = current_val - last_val
                rate = (diff / abs(last_val) * 100) if last_val != 0 else 0
                comparisons[key] = {
                    'diff': diff,
                    'rate': rate
                }
            monthly_stats['comparisons'] = comparisons
            
        return jsonify({
            'success': True,
            'data': monthly_stats
        })
        
    except Exception as e:
        logger.error(f"Error in monthly analysis: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/categories')
def get_categories():
    """获取所有交易分类"""
    try:
        df = load_alipay_data()
        # 获取所有不为空的分类
        categories = sorted(df['交易分类'].dropna().unique().tolist())
        return jsonify({
            'success': True,
            'categories': categories
        })
    except Exception as e:
        logger.error(f"Error getting categories: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

def calculate_monthly_stats(df):
    """计算月度统计数据"""
    if df.empty:
        return {
            'balance': 0,
            'total_expense': 0,
            'total_income': 0,
            'expense_count': 0,
            'income_count': 0,
            'total_count': 0,
            'active_days': 0,
            'avg_transaction': 0,
            'avg_daily_expense': 0,
            'expense_ratio': 0
        }
    
    # 过滤有效交易
    expense_df = df[
        (df['收/支'] == '支出') & 
        (~df['是否退款'])
    ]
    income_df = df[
        (df['收/支'] == '收入') & 
        (~df['是否退款'])
    ]
    
    total_expense = expense_df['金额'].sum() if not expense_df.empty else 0
    total_income = income_df['金额'].sum() if not income_df.empty else 0
    active_days = len(df['日期'].unique())
    
    return {
        'balance': total_income - total_expense,
        'total_expense': total_expense,
        'total_income': total_income,
        'expense_count': len(expense_df),
        'income_count': len(income_df),
        'total_count': len(expense_df) + len(income_df),
        'active_days': active_days,
        'avg_transaction': round(expense_df['金额'].mean(), 2) if len(expense_df) > 0 else 0,
        'avg_daily_expense': round(total_expense / max(1, active_days), 2),
        'expense_ratio': round(total_expense / total_income * 100, 2) if total_income > 0 else 0
    }

@app.route('/api/yearly_data')
def yearly_data():
    try:
        df = load_alipay_data()
        logger.info(f"数据加载完成，总行数: {len(df)}")
        
        # 获取所有可用年份并转换为普通 Python 列表
        available_years = sorted(df['交易时间'].dt.year.unique().tolist(), reverse=True)
        
        # 从请求参数获取年份，如果没有指定则使用最新的可用年份
        year = request.args.get('year', available_years[0], type=int)
        logger.info(f"请求年度数据: {year}")
        
        current_year_df = df[df['交易时间'].dt.year == year].copy()
        logger.info(f"当前年份数据行数: {len(current_year_df)}")
        
        last_year_df = df[df['交易时间'].dt.year == (year - 1)].copy()
        logger.info(f"上一年数据行数: {len(last_year_df)}")
        
        # 获取筛选参数
        filter_type = request.args.get('filter', 'all')
        
        # 根据筛选类型过滤数据
        if filter_type == 'large':
            current_year_df = current_year_df[current_year_df['金额'] >= 1000]  # 修改为1000元
            last_year_df = last_year_df[last_year_df['金额'] >= 1000] if not last_year_df.empty else last_year_df
        elif filter_type == 'small':
            current_year_df = current_year_df[current_year_df['金额'] < 1000]  # 修改为1000元
            last_year_df = last_year_df[last_year_df['金额'] < 1000] if not last_year_df.empty else last_year_df
        
        # 当前年度统计
        current_stats = calculate_yearly_stats(current_year_df)
        
        # 计算环比变化
        yearly_stats = {
            **current_stats,  # 保持原有统计数据
        }
        
        # 只有当存在上一年数据时才计算环比
        if len(last_year_df) > 0:
            print("发现上一年数据，计算环比...")
            last_year_stats = calculate_yearly_stats(last_year_df)
            
            # 计算环比变化率
            balance_change_rate = calculate_change_rate(current_stats['balance'], last_year_stats['balance'])
            expense_change_rate = calculate_change_rate(current_stats['total_expense'], last_year_stats['total_expense'])
            income_change_rate = calculate_change_rate(current_stats['total_income'], last_year_stats['total_income'])
            transaction_change_rate = calculate_change_rate(current_stats['total_count'], last_year_stats['total_count'])
            
            # 添加环比变化数据，确保转换为普通 Python 数值，处理 None 值
            yearly_stats.update({
                'balance_change': float(current_stats['balance'] - last_year_stats['balance']),
                'expense_change': float(current_stats['total_expense'] - last_year_stats['total_expense']),
                'income_change': float(current_stats['total_income'] - last_year_stats['total_income']),
                'transaction_change': int(current_stats['total_count'] - last_year_stats['total_count']),
                'balance_change_rate': float(balance_change_rate) if balance_change_rate is not None else None,
                'expense_change_rate': float(expense_change_rate) if expense_change_rate is not None else None,
                'income_change_rate': float(income_change_rate) if income_change_rate is not None else None,
                'transaction_change_rate': float(transaction_change_rate) if transaction_change_rate is not None else None
            })
            print("环比数据计算完成")
        else:
            print("未找到上一年数据")
            yearly_stats.update({
                'balance_change': None,
                'expense_change': None,
                'income_change': None,
                'transaction_change': None,
                'balance_change_rate': None,
                'expense_change_rate': None,
                'income_change_rate': None,
                'transaction_change_rate': None
            })
        
        # 处理月度数据
        months = sorted(current_year_df['月份'].unique().tolist())
        expenses = []
        incomes = []
        
        for month in months:
            month_data = current_year_df[current_year_df['月份'] == month]
            expenses.append(float(round(month_data[
                (month_data['收/支'] == '支出') & 
                (~month_data['是否退款'])
            ]['金额'].sum(), 2)))
            incomes.append(float(round(month_data[
                (month_data['收/支'] == '收入') & 
                (~month_data['是否退款'])
            ]['金额'].sum(), 2)))
        
        # 处理分类数据
        expense_df = current_year_df[
            (current_year_df['收/支'] == '支出') & 
            (~current_year_df['是否退款'])
        ]
        categories = expense_df.groupby('交易分类')['金额'].sum().sort_values(ascending=False)
        
        return jsonify({
            'yearly_stats': yearly_stats,
            'months': months,
            'expenses': expenses,
            'incomes': incomes,
            'categories': categories.index.tolist(),
            'amounts_by_category': [float(x) for x in categories.values.tolist()],
            'available_years': available_years,
            'current_year': int(year)
        })
        
    except Exception as e:
        logger.error(f"处理年度数据时出错: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

def calculate_change_rate(current, previous):
    """计算环比变化率，处理特殊情况"""
    try:
        if previous == 0:
            if current == 0:
                return 0
            return None  # 无法计算增长率（从0增长）
        if current == 0:
            return -100  # 降低100%
        return round((current - previous) / abs(previous) * 100, 2)
    except:
        return None

def calculate_yearly_stats(df):
    """计算年度统计数据"""
    if df.empty:
        return {
            'balance': 0,
            'total_expense': 0,
            'total_income': 0,
            'expense_count': 0,
            'income_count': 0,
            'total_count': 0,
            'active_days': 0,
            'avg_transaction': 0,
            'avg_daily_expense': 0,
            'avg_monthly_income': 0,
            'expense_ratio': 0
        }
    
    # 过滤有效交易
    expense_df = df[
        (df['收/支'] == '支出') & 
        (~df['是否退款'])
    ]
    income_df = df[
        (df['收/支'] == '收入') & 
        (~df['是否退款'])
    ]
    
    total_expense = expense_df['金额'].sum() if not expense_df.empty else 0
    total_income = income_df['金额'].sum() if not income_df.empty else 0
    
    return {
        'balance': total_income - total_expense,
        'total_expense': total_expense,
        'total_income': total_income,
        'expense_count': len(expense_df),
        'income_count': len(income_df),
        'total_count': len(expense_df) + len(income_df),
        'active_days': len(df['日期'].unique()),
        'avg_transaction': round(expense_df['金额'].mean(), 2) if len(expense_df) > 0 else 0,
        'avg_daily_expense': round(total_expense / max(1, len(df['日期'].unique())), 2),
        'avg_monthly_income': round(total_income / 12, 2),
        'expense_ratio': round(total_expense / total_income * 100, 2) if total_income > 0 else 0
    }

@app.route('/api/category_analysis')
def category_analysis():
    try:
        df = load_alipay_data()
        category = request.args.get('category')
        time_range = request.args.get('range', 'year')
        year = request.args.get('year')
        month = request.args.get('month')
        min_amount = request.args.get('min_amount')  # 添加金额范围参数
        max_amount = request.args.get('max_amount')  # 添加金额范围参数
        
        # 过滤支出数据
        expense_df = df[
            (df['收/支'] == '支出') & 
            (~df['是否退款'])
        ]
        
        # 根据时间范围过滤数据
        if time_range == 'year' and year:
            expense_df = expense_df[expense_df['交易时间'].dt.year == int(year)]
        elif time_range == 'month' and year and month:
            expense_df = expense_df[
                (expense_df['交易时间'].dt.year == int(year)) & 
                (expense_df['交易时间'].dt.month == int(month))
            ]
        
        # 按金额范围过滤
        try:
            if min_amount:
                min_val = float(min_amount)
                expense_df = expense_df[expense_df['金额'] >= min_val]
            if max_amount and max_amount.lower() != 'infinity':
                max_val = float(max_amount)
                expense_df = expense_df[expense_df['金额'] < max_val]
        except ValueError as e:
            logger.warning(f"金额转换错误: {str(e)}")
        
        if not category:
            # 返回所有可用分类及其基本统计信息
            categories_stats = expense_df.groupby('交易分类').agg({
                '金额': ['sum', 'count', 'mean']
            }).round(2)
            
            categories_stats.columns = ['total', 'count', 'avg']
            
            # 综合排序逻辑：结合金额及频次
            # 防止"次数极少但金额很大"的偶发性大额消费一直霸占首位
            # 算法：加权排名 (Rank Score)
            # 权重：金额排名 70% + 频次排名 30% (分数越低排名越靠前)
            categories_stats['amount_rank'] = categories_stats['total'].rank(ascending=False)
            categories_stats['count_rank'] = categories_stats['count'].rank(ascending=False)
            categories_stats['score'] = 0.7 * categories_stats['amount_rank'] + 0.3 * categories_stats['count_rank']
            
            categories_stats = categories_stats.sort_values('score', ascending=True)
            
            # 分组逻辑
            category_groups = None
            if '来源' in expense_df.columns:
                # 获取全局分类排序（按综合分数升序，分数越低排名越靠前）
                global_order = categories_stats['score'].sort_values(ascending=True).index.tolist()
                
                # 获取各渠道存在的分类
                alipay_existing = expense_df[expense_df['来源'] == '支付宝']['交易分类'].unique()
                wechat_existing = expense_df[expense_df['来源'] == '微信']['交易分类'].unique()
                
                # 按照全局顺序筛选出各渠道的分类
                alipay_cats = [cat for cat in global_order if cat in alipay_existing]
                wechat_cats = [cat for cat in global_order if cat in wechat_existing]
                
                # 去重：优先保留在支付宝分组（或按需调整）
                alipay_set = set(alipay_cats)
                wechat_cats = [c for c in wechat_cats if c not in alipay_set]
                
                category_groups = {
                    'alipay': alipay_cats,
                    'wechat': wechat_cats
                }
            
            return jsonify({
                'categories': categories_stats.index.tolist(),
                'category_groups': category_groups,
                'stats': {
                    'totals': categories_stats['total'].tolist(),
                    'counts': categories_stats['count'].tolist(),
                    'averages': categories_stats['avg'].tolist()
                }
            })
        
        # 过滤特定分类的数据
        category_df = expense_df[expense_df['交易分类'] == category]
        
        if category_df.empty:
            return jsonify({
                'error': f'未找到分类 "{category}" 的数据'
            }), 404
        
        # 计算日期范围
        if time_range == 'all':
            date_range = (category_df['交易时间'].max() - category_df['交易时间'].min()).days + 1
        elif time_range == 'year':
            date_range = 365
        else:
            date_range = calendar.monthrange(int(year), int(month))[1]
        
        # 基础统计
        total_expense = category_df['金额'].sum()
        transaction_count = len(category_df)
        avg_amount = round(category_df['金额'].mean(), 2) if transaction_count > 0 else 0
        
        # 计算该分类占总支出的比例
        if time_range == 'all':
            total_all_expense = expense_df['金额'].sum()
        elif time_range == 'year':
            total_all_expense = expense_df[expense_df['交易时间'].dt.year == int(year)]['金额'].sum()
        else:
            total_all_expense = expense_df[
                (expense_df['交易时间'].dt.year == int(year)) & 
                (expense_df['交易时间'].dt.month == int(month))
            ]['金额'].sum()
        
        expense_ratio = round((total_expense / total_all_expense * 100), 2) if total_all_expense > 0 else 0
        
        # 按时间分组统计
        if time_range == 'all':
            # 按年份分组
            grouped = category_df.groupby(category_df['交易时间'].dt.strftime('%Y'))
            total_grouped = expense_df.groupby(expense_df['交易时间'].dt.strftime('%Y'))
        elif time_range == 'year':
            # 按月份分组
            grouped = category_df.groupby(category_df['交易时间'].dt.strftime('%Y-%m'))
            total_grouped = expense_df.groupby(expense_df['交易时间'].dt.strftime('%Y-%m'))
        else:
            # 按日期分组
            grouped = category_df.groupby(category_df['交易时间'].dt.strftime('%Y-%m-%d'))
            total_grouped = expense_df.groupby(expense_df['交易时间'].dt.strftime('%Y-%m-%d'))
        
        time_series = grouped['金额'].sum().round(2)
        total_series = total_grouped['金额'].sum().round(2)
        transaction_counts = grouped.size()
        
        # 计算原始稀疏数据的占比 (保持原有逻辑)
        ratios = []
        for date in time_series.index:
            if date in total_series.index and total_series[date] > 0:
                ratio = (time_series[date] / total_series[date] * 100).round(1)
            else:
                ratio = 0
            ratios.append(ratio)

        # --- 新增：生成全量时间轴数据 (trend_full) ---
        full_time_series = time_series.copy()
        full_transaction_counts = transaction_counts.copy()
        full_ratios = []
        
        if time_range == 'year':
            # 生成所有月份: 2024-01 到 2024-12
            full_index = pd.period_range(start=f'{year}-01', end=f'{year}-12', freq='M').strftime('%Y-%m')
            full_time_series = time_series.reindex(full_index, fill_value=0)
            full_transaction_counts = transaction_counts.reindex(full_index, fill_value=0)
            # 全量数据的 total_series 也需要补全，以便计算占比
            full_total_series = total_series.reindex(full_index, fill_value=0)
            
            for date in full_time_series.index:
                if full_total_series[date] > 0:
                    ratio = (full_time_series[date] / full_total_series[date] * 100).round(1)
                else:
                    ratio = 0
                full_ratios.append(ratio)
                
        elif time_range == 'month':
            # 生成当月所有日期
            days_in_month = calendar.monthrange(int(year), int(month))[1]
            full_index = pd.period_range(start=f'{year}-{month}-01', periods=days_in_month, freq='D').strftime('%Y-%m-%d')
            full_time_series = time_series.reindex(full_index, fill_value=0)
            full_transaction_counts = transaction_counts.reindex(full_index, fill_value=0)
            full_total_series = total_series.reindex(full_index, fill_value=0)
            
            for date in full_time_series.index:
                if full_total_series[date] > 0:
                    ratio = (full_time_series[date] / full_total_series[date] * 100).round(1)
                else:
                    ratio = 0
                full_ratios.append(ratio)
        else:
            # 'all' 模式暂不强制补全所有年份，或者可以按需补充
            full_time_series = time_series
            full_transaction_counts = transaction_counts
            # 对于 'all'，直接复用原逻辑计算的 ratio
            full_ratios = ratios
            
        # 计算消费规律
        hour_pattern = category_df.groupby(category_df['交易时间'].dt.hour)['金额'].agg([
            ('count', 'count'),
            ('sum', 'sum')
        ]).round(2)
        
        # 计算金额分布
        amount_ranges = [0, 50, 100, 200, 500, 1000, float('inf')]
        amount_labels = ['0-50', '50-100', '100-200', '200-500', '500-1000', '1000+']
        amount_dist = pd.cut(category_df['金额'], bins=amount_ranges, labels=amount_labels)
        amount_distribution = amount_dist.value_counts().sort_index()

        # --- 新增：生成全量消费规律 (pattern_full) ---
        full_hours = pd.Index(range(24), name='交易时间')
        hour_pattern_full = hour_pattern.reindex(full_hours, fill_value=0)
        
        # --- 新增：生成全量金额分布 (distribution_full) ---
        # amount_distribution 已经是 Series, index 是 intervals/categories
        # amount_dist.value_counts() 会返回所有 observed=False 的 bin 吗？
        # pd.cut 默认 observed=True (for categorical), so we might miss bins with 0 counts if not careful.
        # But here amount_labels are explicit. Let's ensure we reindex against all labels.
        full_amount_labels = amount_labels
        amount_distribution_full = amount_distribution.reindex(full_amount_labels, fill_value=0)

        return jsonify({
            'category': category,
            'stats': {
                'total_expense': float(total_expense),
                'transaction_count': int(transaction_count),
                'avg_amount': float(avg_amount),
                'expense_ratio': float(expense_ratio),
                'date_range': int(date_range),
                'max_amount': float(category_df['金额'].max()) if not category_df.empty else 0,
                'min_amount': float(category_df['金额'].min()) if not category_df.empty else 0,
                'median_amount': float(category_df['金额'].median()) if not category_df.empty else 0
            },
            'trend': {
                'dates': full_time_series.index.tolist(),
                'amounts': full_time_series.fillna(0).values.tolist(),
                'counts': full_transaction_counts.fillna(0).values.tolist(),
                'ratios': [0 if np.isnan(x) else x for x in full_ratios]
            },
            'pattern': {
                'hours': hour_pattern_full.index.tolist(),
                'counts': hour_pattern_full['count'].tolist(),
                'amounts': hour_pattern_full['sum'].tolist(),
                'averages': (hour_pattern_full['sum'] / hour_pattern_full['count']).round(2).fillna(0).tolist()
            },
            'distribution': {
                'ranges': amount_distribution_full.index.tolist(),
                'counts': amount_distribution_full.values.tolist(),
                'percentages': (amount_distribution_full / amount_distribution_full.sum() * 100).round(1).fillna(0).tolist()
            }
        })
        
    except Exception as e:
        logger.error(f"处理分类分析数据时出错: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/available_dates')
def get_available_dates():
    try:
        df = load_alipay_data()
        dates = df['交易时间'].dt.strftime('%Y-%m').unique().tolist()
        dates.sort(reverse=True)
        
        return jsonify({
            'success': True,
            'months': dates,
            'years': sorted(df['交易时间'].dt.year.unique().tolist(), reverse=True)
        })
    except Exception as e:
        logger.error(f"Error getting available dates: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/category_available_dates')
def get_category_available_dates():
    try:
        df = load_alipay_data()
        
        # 按年份分组获取每年的可用月份
        dates = pd.DataFrame({
            'year': df['交易时间'].dt.year,
            'month': df['交易时间'].dt.month
        })
        
        available_months = {}
        # 修改这里：按年份倒序排列
        for year in sorted(dates['year'].unique(), reverse=True):  # 添加 reverse=True
            months = sorted(dates[dates['year'] == year]['month'].unique())
            available_months[int(year)] = [int(m) for m in months]
        
        return jsonify({
            'years': sorted(dates['year'].unique().tolist(), reverse=True),  # 添加 reverse=True
            'months': available_months
        })
    except Exception as e:
        logger.error(f"Error getting category available dates: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/demo/enter', methods=['POST'])
def enter_demo_mode():
    session['is_demo'] = True
    session['user_id'] = 'demo_user'  # 为了兼容 login_required 等检查
    return jsonify({'success': True})

@app.route('/api/demo/exit', methods=['POST'])
def exit_demo_mode():
    session.pop('is_demo', None)
    if session.get('user_id') == 'demo_user':
        session.pop('user_id', None)
    return jsonify({'success': True})

@app.route('/settings')
def settings():
    # 访问设置页面时确保会话已初始化
    # 这可以防止并发上传文件时产生多个不同的会话ID
    get_session_dir()
    return render_template('settings.html', active_page='settings')

@app.route('/api/upload', methods=['POST'])
def upload_file():
    try:
        logger.info("Starting file upload...")
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': '没有文件被上传'}), 400
            
        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': '未选择文件'}), 400
            
        if not allowed_file(file.filename):
            return jsonify({'success': False, 'error': '不支持的文件类型'}), 400
            
        # 确保目录存在
        session_dir = get_session_dir()
        if not os.path.exists(session_dir):
            os.makedirs(session_dir, mode=0o700)
            
        # 安全地保存文件
        original_filename = file.filename
        safe_filename = secure_filename(original_filename)
        
        # 优化文件名: 去除微信导出文件名中的时间戳后缀
        # 例如: 20210401-20210630_20251216085838.xlsx -> 20210401-20210630.xlsx
        import re
        match = re.match(r'^(\d{8}-\d{8})_\d+(?:\.xlsx|\.csv)$', safe_filename)
        if match:
             base = match.group(1)
             ext = os.path.splitext(safe_filename)[1]
             safe_filename = f"{base}{ext}"

        # 处理纯中文文件名被 secure_filename 变成空或仅后缀的情况
        if not safe_filename or safe_filename.startswith('.'):
            #如果不包含有效文件名，使用时间戳+随机字符
            ext = os.path.splitext(original_filename)[1]
            safe_filename = f"upload_{int(datetime.now().timestamp())}_{token_hex(4)}{ext}"
            
        # 防止同名文件覆盖，添加数字后缀
        base_name, ext = os.path.splitext(safe_filename)
        counter = 1
        filename = safe_filename
        while os.path.exists(os.path.join(session_dir, filename)):
            filename = f"{base_name}_{counter}{ext}"
            counter += 1
            
        filepath = os.path.join(session_dir, filename)
        file.save(filepath)
        
        # 更新会话时间戳
        now_ts = datetime.now().timestamp()
        session['created_at'] = now_ts
        session['session_start'] = datetime.fromtimestamp(now_ts).strftime('%Y-%m-%d %H:%M:%S')
        
        # 清除数据缓存，确保重新加载数据
        if 'user_id' in session:
            load_alipay_data.clear_cache(session['user_id'])
        
        return jsonify({
            'success': True,
            'filename': filename,
            'message': '文件上传成功'
        })
        
    except Exception as e:
        logger.exception("Upload failed with error:")  # 这会记录完整的堆栈跟踪
        return jsonify({'success': False, 'error': str(e)}), 500

def detect_file_source(filepath):
    """检测文件是支付宝还是微信账单"""
    filename = os.path.basename(filepath)
    if filename.endswith('.xlsx'):
        return 'wechat'
    elif filename.endswith('.csv'):
        try:
            # 读取文件前1024字节判断
            with open(filepath, encoding='utf-8-sig') as f:
                content = f.read(1024)
            if '微信支付账单' in content:
                return 'wechat'
        except:
            pass
        return 'alipay'
    return 'unknown'

@app.route('/api/files')
def list_files():
    """列出当前会话的文件"""
    session_dir = get_session_dir()
    files = []
    if os.path.exists(session_dir):
        for filename in os.listdir(session_dir):
            if filename.endswith('.csv') or filename.endswith('.xlsx'):
                filepath = os.path.join(session_dir, filename)
                files.append({
                    'name': filename,
                    'size': os.path.getsize(filepath),
                    'source': detect_file_source(filepath)
                })
    
    # 按文件名排序
    files.sort(key=lambda x: x['name'])
    return jsonify({'files': files})

@app.route('/api/files/<filename>', methods=['DELETE'])
def delete_file(filename):
    """删除会话中的文件"""
    if not filename.endswith(('.csv', '.xlsx')):
        return jsonify({'success': False, 'error': '无效的文件名'})
    
    try:
        session_dir = get_session_dir()
        filepath = os.path.join(session_dir, secure_filename(filename))
        
        if os.path.exists(filepath):
            os.remove(filepath)
            # 清除数据缓存
            if 'user_id' in session:
                load_alipay_data.clear_cache(session['user_id'])
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': '文件不存在'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/session/status')
def get_session_status():
    """获取会话状态"""
    if 'user_id' not in session:
        return jsonify({
            'active': False,
            'message': '会话未初始化'
        })
    
    # 不再检查超时，只返回会话状态
    return jsonify({
        'active': True,
        'message': '会话活跃'
    })

@app.route('/api/clear_data', methods=['POST'])
def clear_data():
    """手动清除用户数据"""
    try:
        session_dir = None
        if 'user_id' in session:
            session_dir = get_session_dir()
            
        # 清空会话目录
        if session_dir and os.path.exists(session_dir):
            shutil.rmtree(session_dir)
            
        # 清除缓存
        if 'user_id' in session:
            load_alipay_data.clear_cache(session['user_id'])
            
        # 清除会话本身
        session.clear()

        return jsonify({'success': True, 'message': '数据已清除'})
    except Exception as e:
        logger.error(f"清除数据时出错: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': f'清除数据失败: {str(e)}'
        }), 500

@app.route('/api/cleanup', methods=['POST'])
def cleanup():
    """只在会话过期时清理数据"""
    try:
        if 'session_start' in session:
            start_time = datetime.strptime(session['session_start'], '%Y-%m-%d %H:%M:%S')
            expire_time = start_time + timedelta(minutes=30)  # 改为30分钟
            
            if datetime.now() >= expire_time:
                if 'user_id' in session:
                    session_dir = get_session_dir()
                    if os.path.exists(session_dir):
                        shutil.rmtree(session_dir)
                    
                    # 清除缓存
                    if 'user_id' in session:
                        load_alipay_data.clear_cache(session['user_id'])
                        
                    session.clear()
                return jsonify({'success': True, 'message': '会话已过期,数据已清理'})
            
        return jsonify({'success': True, 'message': '会话未过期'})
        
    except Exception as e:
        logger.error(f"清理数据时出错: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

# 添加应用关闭时的清理
@atexit.register
def cleanup_all():
    """应用关闭时清理所有临时数据"""
    try:
        if os.path.exists(UPLOAD_FOLDER):
            shutil.rmtree(UPLOAD_FOLDER)
            os.makedirs(UPLOAD_FOLDER, mode=0o700)
    except Exception as e:
        logger.error(f"清理临时文件夹失败: {str(e)}")

# 确保临时文件根目录存在
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# 添加获取会话剩余时间的接口
@app.route('/api/session/time_remaining')
def get_session_time_remaining():
    if 'session_start' not in session:
        logger.info("No session_start found in session")
        return jsonify({'remaining': 0})
    
    start_time = datetime.strptime(session['session_start'], '%Y-%m-%d %H:%M:%S')
    expire_time = start_time + timedelta(minutes=30)
    now = datetime.now()
    
    if now >= expire_time:
        try:
            session_dir = get_session_dir()
            logger.info(f"Session expired. Checking directory: {session_dir}")
            
            if os.path.exists(session_dir):
                # 检查目录是否正在使用
                try:
                    # 尝试创建一个临时文件来测试目录是否可写
                    test_file = os.path.join(session_dir, '.test')
                    with open(test_file, 'w') as f:
                        f.write('test')
                    os.remove(test_file)
                    
                    # 如果可以写入，说明目录没有被锁定
                    files = os.listdir(session_dir)
                    logger.info(f"Found files: {files}")
                    
                    # 逐个检查并删除文件
                    for file in files:
                        filepath = os.path.join(session_dir, file)
                        try:
                            # 尝试打开文件，确保没有其他进程在使用
                            with open(filepath, 'r') as f:
                                pass
                            # 如果成功打开，则删除文件
                            os.remove(filepath)
                            logger.info(f"Deleted file: {file}")
                        except IOError as e:
                            logger.warning(f"Cannot delete file {file}: {str(e)}")
                            continue
                    
                    # 最后删除目录
                    os.rmdir(session_dir)
                    logger.info("Directory deleted successfully")
                    
                except IOError as e:
                    logger.warning(f"Directory is in use: {str(e)}")
                    # 如果目录被锁定，不进行删除
                    return jsonify({'remaining': 30, 'extended': True})
            
            # 清除缓存和会话
            load_alipay_data.cache_clear()
            session.clear()
            logger.info("Cache and session cleared")
            
            return jsonify({'remaining': 0, 'expired': True})
            
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}", exc_info=True)
            # 如果清理过程出错，给用户多一些时间
            return jsonify({'remaining': 30, 'error': str(e), 'extended': True})
    
    remaining_seconds = int((expire_time - now).total_seconds())
    logger.debug(f"Session remaining time: {remaining_seconds} seconds")
    return jsonify({'remaining': remaining_seconds, 'expired': False})

@app.route('/api/available_years')
def get_available_years():
    """获取数据中所有可用的年份"""
    try:
        df = load_alipay_data()
        # 从交易时间中提取所有不重复的年份
        years = sorted(df['交易时间'].dt.year.unique().tolist(), reverse=True)
        
        return jsonify({
            'success': True,
            'years': years
        })
        
    except Exception as e:
        logger.error(f"获取可用年份时出错: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'获取可用年份失败: {str(e)}'
        }), 500

def analyze_merchants(df):
    """商家消费分析"""
    # 只分析支出数据
    expense_df = df[df['收/支'] == '支出']
    
    # 按商家分组统计
    merchant_stats = expense_df.groupby('交易对方').agg({
        '金额': ['count', 'sum', 'mean'],
        '交易时间': lambda x: (x.max() - x.min()).days + 1  # 交易跨度
    }).round(2)
    
    merchant_stats.columns = ['交易次数', '总金额', '平均金额', '交易跨度']
    
    # 识别常客商家
    # 如果是筛选后的数据（比如大额交易），则降低频次要求
    min_count = 2
    if len(df) < 50:  # 如果数据量较少（说明经过了筛选），则显示所有商家
        min_count = 1
        
    frequent_merchants = []
    for merchant, group in expense_df.groupby('交易对方'):
        if len(group) >= min_count:
            frequent_merchants.append({
                'name': merchant,
                'amount': group['金额'].sum(),
                'count': len(group),
                'last_visit': group['交易时间'].max().strftime('%Y-%m-%d')
            })
    
    # 按消费金额排序
    frequent_merchants.sort(key=lambda x: x['amount'], reverse=True)
    
    return {
        'merchant_stats': merchant_stats.to_dict('index'),
        'frequent_merchants': frequent_merchants[:20]  # 返回前20个
    }

def analyze_scenarios(df):
    """消费场景分析"""
    # 创建副本避免 SettingWithCopyWarning
    expense_df = df[df['收/支'] == '支出'].copy()
    
    # 1. 线上/线下消费
    online_keywords = [
        '淘宝', '天猫', '京东', '拼多多', '美团', '饿了么', 'App Store', 'Steam', 
        'Apple Music', 'iCloud', '网易', '支付宝', '微信', '闲鱼', '得物'
    ]
    expense_df.loc[:, '消费场景'] = expense_df['交易对方'].apply(
        lambda x: '线上' if any(k in str(x) for k in online_keywords) else '线下'
    )
    
    # 2. 消费时段分析
    expense_df.loc[:, '消费时段'] = expense_df['交易时间'].dt.hour.map(
        lambda x: '清晨(6-9点)' if 6 <= x < 9
        else '上午(9-12点)' if 9 <= x < 12
        else '中午(12-14点)' if 12 <= x < 14
        else '下午(14-17点)' if 14 <= x < 17
        else '傍晚(17-20点)' if 17 <= x < 20
        else '晚上(20-23点)' if 20 <= x < 23
        else '深夜(23-6点)'
    )
    
    # 3. 消费金额层级
    expense_df.loc[:, '消费层级'] = expense_df['金额'].map(
        lambda x: '大额(1000+)' if x >= 1000
        else '中额(300-1000)' if x >= 300
        else '小额(100-300)' if x >= 100
        else '零花(0-100)'
    )
    
    # 汇总各维度的统计数据
    scenario_stats = []
    
    # 添加线上/线下统计
    online_stats = expense_df.groupby('消费场景')['金额'].sum()
    for scene, amount in online_stats.items():
        scenario_stats.append({
            'name': scene,
            'value': float(amount),
            'category': '渠道'
        })
    
    # 添加时段统计
    time_stats = expense_df.groupby('消费时段')['金额'].sum()
    for period, amount in time_stats.items():
        scenario_stats.append({
            'name': period,
            'value': float(amount),
            'category': '时段'
        })
    
    # 添加金额层级统计
    level_stats = expense_df.groupby('消费层级')['金额'].sum()
    for level, amount in level_stats.items():
        scenario_stats.append({
            'name': level,
            'value': float(amount),
            'category': '层级'
        })
    
    return scenario_stats

def analyze_habits(df):
    """消费习惯分析"""
    expense_df = df[df['收/支'] == '支出'].copy()
    
    # 1. 基础统计
    daily_expenses = expense_df.groupby(expense_df['交易时间'].dt.date)['金额'].sum()
    daily_avg = float(daily_expenses.mean())
    active_days = int(len(daily_expenses))
    
    # 2. 计算周末消费比例
    weekend_expenses = expense_df[expense_df['交易时间'].dt.dayofweek.isin([5, 6])]['金额'].sum()
    weekend_ratio = float((weekend_expenses / expense_df['金额'].sum() * 100))
    
    # 3. 计算固定支出比例 (每月都有消费的商家)
    # 按月份和商家分组统计
    monthly_merchant_counts = expense_df.groupby(['交易对方', expense_df['交易时间'].dt.to_period('M')]).size()
    # 计算每个商家出现的月份数
    merchant_months = monthly_merchant_counts.reset_index().groupby('交易对方').size()
    # 获取总月份数
    total_months = len(expense_df['交易时间'].dt.to_period('M').unique())
    
    # 如果商家出现的月份数占比超过 80%，则视为固定支出
    recurring_merchants = merchant_months[merchant_months >= max(2, total_months * 0.8)].index
    
    fixed_expenses = expense_df[expense_df['交易对方'].isin(recurring_merchants)]['金额'].sum()
    fixed_ratio = float((fixed_expenses / expense_df['金额'].sum() * 100)) if expense_df['金额'].sum() > 0 else 0
    
    # 4. 计算月初消费比例
    month_start = expense_df[expense_df['交易时间'].dt.day <= 5]['金额'].sum()
    month_start_ratio = float((month_start / expense_df['金额'].sum() * 100)) if expense_df['金额'].sum() > 0 else 0
    
    return {
        'daily_avg': round(daily_avg, 2),
        'active_days': active_days,
        'weekend_ratio': round(weekend_ratio, 1),
        'fixed_expenses': round(fixed_ratio, 1),
        'month_start_ratio': round(month_start_ratio, 1)
    }

    
    return {
        'daily_avg': round(daily_avg, 2),
        'active_days': active_days,
        'weekend_ratio': round(weekend_ratio, 1),
        'fixed_expenses': round(fixed_ratio, 1),
        'month_start_ratio': round(month_start_ratio, 1)
    }

def analyze_latte_factor(df):
    """拿铁因子分析：小额高频支出"""
    expense_df = df[df['收/支'] == '支出'].copy()
    
    # 定义小额：小于 30 元
    small_expenses = expense_df[expense_df['金额'] < 30]
    
    # 按商家分组统计频次
    merchant_counts = small_expenses.groupby('交易对方').size()
    
    # 筛选高频：月均超过 5 次 (简单起见，这里用总次数 > 5)
    # 更好的做法是计算月均，但为了演示效果，先用总次数
    frequent_merchants = merchant_counts[merchant_counts > 5].index
    
    latte_df = small_expenses[small_expenses['交易对方'].isin(frequent_merchants)]
    
    total_amount = latte_df['金额'].sum()
    item_count = len(latte_df)
    
    # 找出最典型的“拿铁”商家（次数最多）
    top_merchant = merchant_counts.idxmax() if not merchant_counts.empty else "未知"
    
    return {
        'total_amount': float(total_amount),
        'item_count': int(item_count),
        'top_merchant': top_merchant,
        'avg_price': float(total_amount / item_count) if item_count > 0 else 0
    }

def analyze_nighttime_spending(df):
    """深夜消费分析：22:00 - 04:00"""
    expense_df = df[df['收/支'] == '支出'].copy()
    
    # 筛选深夜时段
    # 22:00 - 23:59 OR 00:00 - 04:00
    night_mask = (expense_df['交易时间'].dt.hour >= 22) | (expense_df['交易时间'].dt.hour <= 4)
    night_df = expense_df[night_mask]
    
    total_night_spend = night_df['金额'].sum()
    total_spend = expense_df['金额'].sum()
    
    # 深夜最常光顾的商家
    top_merchant = "无"
    if not night_df.empty:
        top_merchant = night_df.groupby('交易对方')['金额'].sum().idxmax()
        
    return {
        'total_amount': float(total_night_spend),
        'ratio': float((total_night_spend / total_spend * 100)) if total_spend > 0 else 0,
        'count': len(night_df),
        'top_merchant': top_merchant
    }

def analyze_subscriptions(df):
    """隐形订阅分析：每月固定扣款"""
    expense_df = df[df['收/支'] == '支出'].copy()
    
    # 按商家和月份分组，计算每月金额
    monthly_spend = expense_df.groupby(['交易对方', expense_df['交易时间'].dt.to_period('M')])['金额'].sum().reset_index()
    
    # 计算每个商家的月均金额标准差，如果标准差很小，说明金额固定
    merchant_stats = monthly_spend.groupby('交易对方')['金额'].agg(['mean', 'std', 'count'])
    
    # 筛选：出现月份数 > 3 且 金额标准差 < 5 (金额基本固定)
    subs_merchants = merchant_stats[
        (merchant_stats['count'] >= 3) & 
        (merchant_stats['std'] < 5)
    ]
    
    subscriptions = []
    for merchant in subs_merchants.index:
        avg_amount = merchant_stats.loc[merchant, 'mean']
        subscriptions.append({
            'name': merchant,
            'monthly_amount': float(avg_amount),
            'annual_amount': float(avg_amount * 12)
        })
        
    # 按年化金额排序
    subscriptions.sort(key=lambda x: x['annual_amount'], reverse=True)
    
    return subscriptions

def analyze_inflation(df):
    """个人通胀率：客单价变化"""
    expense_df = df[df['收/支'] == '支出'].copy()
    
    # 按季度分组
    expense_df['quarter'] = expense_df['交易时间'].dt.to_period('Q')
    
    quarterly_avg = expense_df.groupby('quarter')['金额'].mean()
    
    if len(quarterly_avg) < 2:
        return {'trend': 'stable', 'rate': 0}
        
    first_q = quarterly_avg.iloc[0]
    last_q = quarterly_avg.iloc[-1]
    
    rate = ((last_q - first_q) / first_q * 100) if first_q > 0 else 0
    
    return {
        'trend': 'up' if rate > 5 else ('down' if rate < -5 else 'stable'),
        'rate': float(rate),
        'first_avg': float(first_q),
        'last_avg': float(last_q)
    }

def analyze_brand_loyalty(df):
    """品牌忠诚度分析"""
    expense_df = df[df['收/支'] == '支出'].copy()
    
    if expense_df.empty:
        return None
        
    # 消费金额最高的商家
    top_amount_merchant = expense_df.groupby('交易对方')['金额'].sum().idxmax()
    top_amount = expense_df.groupby('交易对方')['金额'].sum().max()
    
    # 消费次数最多的商家
    top_count_merchant = expense_df.groupby('交易对方').size().idxmax()
    top_count = expense_df.groupby('交易对方').size().max()
    
    return {
        'top_amount': {
            'name': top_amount_merchant,
            'value': float(top_amount)
        },
        'top_count': {
            'name': top_count_merchant,
            'value': int(top_count)
        }
    }

def analyze_sankey(df):
    """生成桑基图数据：总支出 -> 分类 -> Top商家"""
    expense_df = df[df['收/支'] == '支出'].copy()
    
    if expense_df.empty:
        return {'nodes': [], 'links': []}
        
    nodes = []
    links = []
    node_names = set()
    
    # 根节点
    root_name = "总支出"
    nodes.append({'name': root_name})
    node_names.add(root_name)
    
    # 第一层：分类
    # 取前 8 大分类，其他的归为"其他"
    cat_stats = expense_df.groupby('交易分类')['金额'].sum().sort_values(ascending=False)
    top_cats = cat_stats.head(8)
    other_cats_amount = cat_stats.iloc[8:].sum()
    
    for cat, amount in top_cats.items():
        if cat not in node_names:
            nodes.append({'name': cat})
            node_names.add(cat)
        links.append({
            'source': root_name,
            'target': cat,
            'value': float(amount)
        })
        
        # 第二层：该分类下的商家
        # 逻辑修改：不再固定显示 Top 3，而是显示金额占比超过总支出 0.5% 的商家
        cat_df = expense_df[expense_df['交易分类'] == cat]
        total_expense = expense_df['金额'].sum()
        threshold = total_expense * 0.005  # 0.5% 阈值
        
        merchant_stats = cat_df.groupby('交易对方')['金额'].sum().sort_values(ascending=False)
        
        # 筛选超过阈值的商家，且最多只显示 Top 3
        significant_merchants = merchant_stats[merchant_stats >= threshold].head(3)
        
        # 如果没有商家超过阈值，为了避免空连接，至少显示 Top 1 (如果存在)
        if significant_merchants.empty and not merchant_stats.empty:
            significant_merchants = merchant_stats.head(1)
            
        for merchant, m_amount in significant_merchants.items():
            # 商家名字可能重复（不同分类下），为了桑基图节点唯一，可以加后缀或处理
            # 这里简单处理：如果商家名已存在（比如作为分类名），加个空格
            m_node_name = merchant
            while m_node_name in node_names:
                m_node_name += " "
            
            nodes.append({'name': m_node_name})
            node_names.add(m_node_name)
            
            links.append({
                'source': cat,
                'target': m_node_name,
                'value': float(m_amount)
            })
            
    if other_cats_amount > 0:
        other_name = "其他分类"
        other_merchant_name = "其他商家"
        
        # 添加二级节点：其他分类
        nodes.append({'name': other_name})
        links.append({
            'source': root_name,
            'target': other_name,
            'value': float(other_cats_amount)
        })
        
        # 添加三级节点：其他商家
        nodes.append({'name': other_merchant_name})
        links.append({
            'source': other_name,
            'target': other_merchant_name,
            'value': float(other_cats_amount)
        })
        
    return {'nodes': nodes, 'links': links}

def analyze_engel_coefficient(df):
    """恩格尔系数分析 (食品支出占比)"""
    expense_df = df[df['收/支'] == '支出'].copy()
    total_expense = expense_df['金额'].sum()
    
    if total_expense == 0:
        return {'ratio': 0, 'amount': 0}
        
    # 定义食品相关关键词
    food_keywords = ['餐饮', '食品', '美食', '超市', '外卖', '菜市场']
    
    # 筛选食品类消费
    # 假设 '交易分类' 或 '商品说明' 中包含关键词
    # 这里主要基于 '交易分类'，如果分类不准，可以结合 '交易对方'
    food_mask = expense_df['交易分类'].str.contains('|'.join(food_keywords), na=False)
    food_expense = expense_df[food_mask]['金额'].sum()
    
    ratio = (food_expense / total_expense * 100)
    
    return {
        'ratio': float(ratio),
        'amount': float(food_expense)
    }

def analyze_weekend_vs_monday(df):
    """周末效应 vs 周一综合症"""
    expense_df = df[df['收/支'] == '支出'].copy()
    
    # 周末 (周六=5, 周日=6)
    weekend_df = expense_df[expense_df['交易时间'].dt.dayofweek.isin([5, 6])]
    # 周一 (0)
    monday_df = expense_df[expense_df['交易时间'].dt.dayofweek == 0]
    
    # 计算日均消费
    # 注意：要除以实际出现的天数，而不是简单的总天数
    weekend_days = len(weekend_df['交易时间'].dt.date.unique())
    monday_days = len(monday_df['交易时间'].dt.date.unique())
    
    weekend_avg = weekend_df['金额'].sum() / max(1, weekend_days)
    monday_avg = monday_df['金额'].sum() / max(1, monday_days)
    
    return {
        'weekend_avg': float(weekend_avg),
        'monday_avg': float(monday_avg),
        'ratio': float(weekend_avg / monday_avg) if monday_avg > 0 else 0
    }

def generate_story_data(df):
    """生成年度账单故事数据 (增强版)"""
    expense_df = df[df['收/支'] == '支出'].copy()
    
    if expense_df.empty:
        return None
        
    # 1. 最贵的一天
    daily_sum = expense_df.groupby(expense_df['交易时间'].dt.date)['金额'].sum()
    max_day = daily_sum.idxmax()
    max_day_amount = daily_sum.max()
    
    # 2. 消费最高的一个月
    monthly_sum = expense_df.groupby(expense_df['交易时间'].dt.to_period('M'))['金额'].sum()
    max_month = monthly_sum.idxmax()
    max_month_amount = monthly_sum.max()
    
    # 3. 最晚的一笔消费
    expense_df['time_only'] = expense_df['交易时间'].dt.time
    late_night_df = expense_df[(expense_df['交易时间'].dt.hour >= 0) & (expense_df['交易时间'].dt.hour <= 4)]
    if not late_night_df.empty:
        latest_tx = late_night_df.sort_values('time_only', ascending=False).iloc[0]
    else:
        latest_tx = expense_df.sort_values('time_only', ascending=False).iloc[0]
        
    # 4. 消费最多的分类
    top_cat = expense_df.groupby('交易分类')['金额'].sum().idxmax()
    top_cat_amount = expense_df.groupby('交易分类')['金额'].sum().max()
    
    # 5. 全年总览
    total_days = (expense_df['交易时间'].max() - expense_df['交易时间'].min()).days + 1
    total_tx_count = len(expense_df)
    
    # --- 新增：特色指数 ---
    
    # [咖啡指数]
    coffee_keywords = ['咖啡', 'luckin', 'starbucks', '瑞幸', '星巴克', 'manner', 'tim hortons', '皮爷']
    coffee_df = expense_df[expense_df['商品说明'].str.contains('|'.join(coffee_keywords), case=False, na=False) | 
                           expense_df['交易对方'].str.contains('|'.join(coffee_keywords), case=False, na=False)]
    coffee_count = len(coffee_df)
    coffee_total = coffee_df['金额'].sum()
    
    # [深夜哲学] (22:00 - 05:00)
    night_philosophy_df = expense_df[(expense_df['交易时间'].dt.hour >= 22) | (expense_df['交易时间'].dt.hour <= 4)]
    night_avg = night_philosophy_df['金额'].mean() if not night_philosophy_df.empty else 0
    night_total = night_philosophy_df['金额'].sum()
    
    # [周末人格]
    expense_df['weekday'] = expense_df['交易时间'].dt.weekday # 0=Mon, 6=Sun
    weekday_df = expense_df[expense_df['weekday'] < 5]
    weekend_df = expense_df[expense_df['weekday'] >= 5]
    
    weekday_avg = weekday_df['金额'].mean() if not weekday_df.empty else 0
    weekend_avg = weekend_df['金额'].mean() if not weekend_df.empty else 0
    
    # [通胀感知]
    # 找频率最高的商家
    top_merchant = expense_df['交易对方'].value_counts().idxmax()
    merchant_df = expense_df[expense_df['交易对方'] == top_merchant].sort_values('交易时间')
    
    inflation_data = {'merchant': top_merchant, 'start_price': 0, 'end_price': 0, 'trend': 'stable'}
    if len(merchant_df) > 5:
        # 取前3笔和后3笔的平均值比较
        start_price = merchant_df.head(3)['金额'].mean()
        end_price = merchant_df.tail(3)['金额'].mean()
        inflation_data['start_price'] = float(start_price)
        inflation_data['end_price'] = float(end_price)
        if end_price > start_price * 1.1:
            inflation_data['trend'] = 'up'
        elif end_price < start_price * 0.9:
            inflation_data['trend'] = 'down'

    # --- 新增 V2 (Rich Story) ---
    
    # 1. 年度首单
    first_tx = expense_df.sort_values('交易时间').iloc[0]
    
    # 2. 剁手黄金时间 (小时)
    peak_hour = expense_df['交易时间'].dt.hour.mode()[0]
    
    # 3. 外卖之王
    takeout_keywords = ['美团', '饿了么', '外卖', '肯德基', '麦当劳']
    takeout_df = expense_df[expense_df['商品说明'].str.contains('|'.join(takeout_keywords), case=False, na=False) | 
                            expense_df['交易对方'].str.contains('|'.join(takeout_keywords), case=False, na=False)]
    takeout_count = len(takeout_df)
    takeout_amount = takeout_df['金额'].sum()
    
    # 4. 消费季节
    # 12-2 冬, 3-5 春, 6-8 夏, 9-11 秋
    def get_season(month):
        if month in [12, 1, 2]: return 'Winter'
        elif month in [3, 4, 5]: return 'Spring'
        elif month in [6, 7, 8]: return 'Summer'
        else: return 'Autumn'
        
    expense_df['season'] = expense_df['交易时间'].dt.month.apply(get_season)
    season_result = expense_df.groupby('season')['金额'].sum()
    if not season_result.empty:
        top_season_en = season_result.idxmax()
        season_map = {'Winter': '冬', 'Spring': '春', 'Summer': '夏', 'Autumn': '秋'}
        top_season = season_map.get(top_season_en, '全年')
    else:
        top_season = '全年'
    
    return {
        'max_day': {
            'date': max_day.strftime('%Y年%m月%d日'),
            'amount': float(max_day_amount)
        },
        'max_month': {
            'month': str(max_month),
            'amount': float(max_month_amount)
        },
        'latest_tx': {
            'time': latest_tx['交易时间'].strftime('%H:%M'),
            'merchant': latest_tx['交易对方'],
            'amount': float(latest_tx['金额'])
        },
        'top_category': {
            'name': top_cat,
            'amount': float(top_cat_amount)
        },
        'summary': {
            'total_days': int(total_days),
            'tx_count': int(total_tx_count),
            'total_amount': float(expense_df['金额'].sum())
        },
        'features': {
            'coffee': {
                'count': int(coffee_count),
                'amount': float(coffee_total)
            },
            'night': {
                'avg': float(night_avg),
                'total': float(night_total),
                'count': len(night_philosophy_df)
            },
            'weekend': {
                'weekday_avg': float(weekday_avg),
                'weekend_avg': float(weekend_avg)
            },
            'inflation': inflation_data,
            'first_tx': {
                'date': first_tx['交易时间'].strftime('%Y-%m-%d %H:%M'),
                'merchant': first_tx['交易对方'],
                'amount': float(first_tx['金额']),
                'product': first_tx['商品说明']
            },
            'peak_hour': int(peak_hour),
            'takeout': {
                'count': int(takeout_count),
                'amount': float(takeout_amount)
            },
            'top_season': top_season
        }
    }

def generate_smart_tags(df):
    """智能标签生成"""
    expense_df = df[df['收/支'] == '支出']
    result = {
        'tags': [],
        'time_pattern': '',
        'spending_preference': '',
        'spending_pattern': '',
        'spending_power': ''
    }
    
    # 计算总体消费情况
    total_expense = expense_df['金额'].sum()
    avg_expense = expense_df['金额'].mean()
    daily_expense = expense_df.groupby(expense_df['交易时间'].dt.date)['金额'].sum().mean()
    
    # 时间模式分析
    hour_stats = expense_df.groupby(expense_df['交易时间'].dt.hour).size()
    peak_hours = hour_stats[hour_stats > hour_stats.mean()].index.tolist()
    
    if 22 in peak_hours or 23 in peak_hours:
        result['tags'].append('夜间消费达人')
        result['time_pattern'] = '您偏好在夜间消费，要注意作息哦'
    elif 6 in peak_hours or 7 in peak_hours:
        result['tags'].append('早起达人')
        result['time_pattern'] = '您是个早起消费的生活达人'
    else:
        result['time_pattern'] = '您的消费时间比较规律，集中在日间'
    
    # 消费偏好分析
    category_ratio = expense_df.groupby('交易分类')['金额'].sum() / total_expense
    top_categories = category_ratio[category_ratio > 0.15].index.tolist()
    
    preference_desc = []
    for category in top_categories:
        result['tags'].append(f'{category}控')
        preference_desc.append(f'{category}({(category_ratio[category]*100):.1f}%)')
    
    result['spending_preference'] = f"最常消费的品类是{', '.join(preference_desc)}"
    
    # 消费规律分析
    daily_expenses = expense_df.groupby(expense_df['交易时间'].dt.date)['金额'].sum()
    cv = daily_expenses.std() / daily_expenses.mean()
    
    if cv < 0.5:
        result['tags'].append('消费稳健派')
        result['spending_pattern'] = '您的消费非常有规律，是个理性消费者'
    elif cv < 0.8:
        result['tags'].append('平衡消费派')
        result['spending_pattern'] = '您的消费较为均衡，适度有波动'
    else:
        result['tags'].append('随性消费派')
        result['spending_pattern'] = '您的消费比较随性，可能需要更多预算管理'
    
    # 消费能力分析
    if daily_expense > 500:
        result['tags'].append('高消费人群')
        result['spending_power'] = f'日均消费{daily_expense:.0f}元，属于高消费人群'
    elif daily_expense > 200:
        result['tags'].append('中等消费人群')
        result['spending_power'] = f'日均消费{daily_expense:.0f}元，消费能力适中'
    else:
        result['tags'].append('理性消费人群')
        result['spending_power'] = f'日均消费{daily_expense:.0f}元，消费比较节制'
    
    return result

def analyze_payment_methods(df):
    """分析支付方式的使用情况"""
    expense_df = df[df['收/支'] == '支出'].copy()
    
    # 清理和标准化支付方式名称
    def standardize_payment_method(method):
        method = str(method).split('(')[0].strip()
        # 统一支付方式名称
        if '余额宝' in method or '红包' in method:
            return '余额宝'
        return method
    
    expense_df['支付方式'] = expense_df['收/付款方式'].apply(standardize_payment_method)
    
    # 基础统计
    payment_stats = expense_df.groupby('支付方式').agg({
        '金额': ['count', 'sum', 'mean'],
        '交易时间': lambda x: x.dt.date.nunique()  # 使用天数
    })
    
    # 重命名列
    payment_stats.columns = ['交易次数', '总金额', '平均金额', '使用天数']
    
    # 计算使用频率和金额占比
    total_amount = float(expense_df['金额'].sum())  # 转换为 float
    total_count = int(len(expense_df))  # 转换为 int
    
    # 转换为列表格式
    payment_list = []
    for method, stats in payment_stats.iterrows():
        payment_list.append({
            'name': method,
            'transaction_count': int(stats['交易次数']),  # 转换为 int
            'total_amount': float(stats['总金额']),  # 转换为 float
            'avg_amount': float(stats['平均金额']),  # 转换为 float
            'usage_days': int(stats['使用天数']),  # 转换为 int
            'amount_ratio': float(stats['总金额'] / total_amount * 100),  # 转换为 float
            'count_ratio': float(stats['交易次数'] / total_count * 100)  # 转换为 float
        })
    
    # 按总金额排序
    payment_list.sort(key=lambda x: x['total_amount'], reverse=True)
    
    return payment_list

@app.route('/api/yearly_analysis')
def yearly_analysis():
    try:
        df = load_alipay_data()
        year = request.args.get('year', type=int)
        min_amount = request.args.get('min_amount', type=float)
        max_amount = request.args.get('max_amount', type=float)
        
        # 获取当前年份数据
        current_year_df = df[df['交易时间'].dt.year == year] if year else df
        
        # 获取上一年数据
        last_year = year - 1 if year else df['交易时间'].dt.year.max() - 1
        last_year_df = df[df['交易时间'].dt.year == last_year]
        
        # 应用金额筛选
        if min_amount:
            current_year_df = current_year_df[current_year_df['金额'] >= min_amount]
            last_year_df = last_year_df[last_year_df['金额'] >= min_amount]
        if max_amount:
            current_year_df = current_year_df[current_year_df['金额'] < max_amount]
            last_year_df = last_year_df[last_year_df['金额'] < max_amount]
        
        # 过滤有效交易（排除不计收支和退款）
        current_expense_df = current_year_df[
            (current_year_df['收/支'] == '支出') & 
            (~current_year_df['是否退款'])
        ]
        current_income_df = current_year_df[
            (current_year_df['收/支'] == '收入') & 
            (~current_year_df['是否退款'])
        ]
        
        last_expense_df = last_year_df[
            (last_year_df['收/支'] == '支出') & 
            (~last_year_df['是否退款'])
        ]
        last_income_df = last_year_df[
            (last_year_df['收/支'] == '收入') & 
            (~last_year_df['是否退款'])
        ]
        
        # 计算当前年份数据
        current_expense = current_expense_df['金额'].sum()
        current_income = current_income_df['金额'].sum()
        current_balance = current_income - current_expense  # 这里的计算是对的
        
        # 计算上一年数据
        last_expense = last_expense_df['金额'].sum()
        last_income = last_income_df['金额'].sum()
        last_balance = last_income - last_expense
        
        # 生成完整的月份列表（1月到12月）
        all_months = [f"{year}-{str(month).zfill(2)}" for month in range(1, 13)]
        
        # 按月统计支出和收入
        monthly_expenses = current_expense_df.groupby(
            current_expense_df['交易时间'].dt.strftime('%Y-%m')
        )['金额'].sum()
        monthly_incomes = current_income_df.groupby(
            current_income_df['交易时间'].dt.strftime('%Y-%m')
        )['金额'].sum()
        
        # 使用生成的月份列表重新索引
        monthly_expenses = monthly_expenses.reindex(all_months, fill_value=0)
        monthly_incomes = monthly_incomes.reindex(all_months, fill_value=0)
        
        # 计算分类统计
        category_expenses = current_expense_df.groupby('交易分类')['金额'].sum()
        category_incomes = current_income_df.groupby('交易分类')['金额'].sum()
        
        # 计算分来源的分类统计
        expense_source = current_expense_df.groupby(['来源', '交易分类'])['金额'].sum().reset_index().to_dict('records')
        income_source = current_income_df.groupby(['来源', '交易分类'])['金额'].sum().reset_index().to_dict('records')
        
        # 计算年度统计数据
        yearly_stats = {
            'balance': float(current_balance),  # 这里传递的也是对的
            'total_expense': float(current_expense),
            'total_income': float(current_income),
            'expense_count': int(len(current_expense_df)),
            'income_count': int(len(current_income_df)),
            'total_count': int(len(current_expense_df) + len(current_income_df)),
            'active_days': int(len(current_year_df['交易时间'].dt.date.unique())),
            'avg_transaction': float(current_expense_df['金额'].mean()) if len(current_expense_df) > 0 else 0,
            'avg_daily_expense': float(current_expense / max(1, len(current_year_df['交易时间'].dt.date.unique()))),
            'avg_monthly_income': float(current_income / 12),
            'expense_ratio': float(current_expense / current_income * 100) if current_income > 0 else 0,
            'comparisons': {
                'balance': {
                    'change': float(current_balance - last_balance) if len(last_year_df) > 0 else None,
                    'rate': float((current_balance - last_balance) / abs(last_balance) * 100) if len(last_year_df) > 0 and last_balance != 0 else None
                },
                'expense': {
                    'change': float(current_expense - last_expense) if len(last_year_df) > 0 else None,
                    'rate': float((current_expense - last_expense) / last_expense * 100) if len(last_year_df) > 0 and last_expense != 0 else None
                },
                'income': {
                    'change': float(current_income - last_income) if len(last_year_df) > 0 else None,
                    'rate': float((current_income - last_income) / last_income * 100) if len(last_year_df) > 0 and last_income != 0 else None
                },
                'count': {
                    'change': int(len(current_expense_df) + len(current_income_df) - len(last_expense_df) - len(last_income_df)) if len(last_year_df) > 0 else None,
                    'rate': float((len(current_expense_df) + len(current_income_df) - len(last_expense_df) - len(last_income_df)) / (len(last_expense_df) + len(last_income_df)) * 100) if len(last_year_df) > 0 and (len(last_expense_df) + len(last_income_df)) != 0 else None
                }
            }
        }
        
        # 添加日志
        logger.info(f"Yearly stats: income={current_income}, expense={current_expense}, balance={current_balance}")
        
        return jsonify({
            'success': True,
            'data': {
                'trends': {
                    'months': monthly_expenses.index.tolist(),
                    'expenses': monthly_expenses.values.tolist(),
                    'incomes': monthly_incomes.values.tolist()
                },
                'categories': {
                    'expense': {
                        'names': category_expenses.index.tolist(),
                        'amounts': category_expenses.values.tolist()
                    },
                    'income': {
                        'names': category_incomes.index.tolist(),
                        'amounts': category_incomes.values.tolist()
                    }
                },
                'categories_source': {
                    'expense': expense_source,
                    'income': income_source
                },
                'yearly_stats': yearly_stats
            }
        })
        
    except Exception as e:
        logger.error(f"Error in yearly analysis: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

@app.before_request
def check_session_expiry():
    if 'created_at' in session:
        session_age = datetime.now().timestamp() - session['created_at']
        if session_age > 1800:  # 30分钟过期
            session.clear()
            return redirect(url_for('index'))

# 在应用启动时确保上传目录存在
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# 确保目录权限正确
def ensure_upload_dir():
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER, mode=0o700)
    else:
        os.chmod(UPLOAD_FOLDER, 0o700)

# 在应用启动时调用
ensure_upload_dir()

# ============ 高级可视化图表数据生成函数 ============

def generate_chord_data(df):
    """生成和弦图数据（星期 -> 消费分类流向）"""
    expense_df = df[df['收/支'] == '支出'].copy()
    
    if expense_df.empty:
        return {'nodes': [], 'links': []}
    
    # 星期映射
    weekday_map = {
        0: '周一', 1: '周二', 2: '周三', 3: '周四', 4: '周五', 5: '周六', 6: '周日'
    }
    expense_df['weekday'] = expense_df['交易时间'].dt.dayofweek.map(weekday_map)
    
    # 取 Top 10 分类
    top_categories = expense_df.groupby('交易分类')['金额'].sum().nlargest(10).index.tolist()
    
    # 统计 星期 -> 分类 的流量
    # 只统计 Top 分类
    flow_df = expense_df[expense_df['交易分类'].isin(top_categories)]
    flow_data = flow_df.groupby(['weekday', '交易分类'])['金额'].sum()
    
    nodes = []
    links = []
    
    # 添加星期节点
    weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    for day in weekdays:
        nodes.append({'name': day, 'category': 'weekday'})
        
    # 添加分类节点
    for cat in top_categories:
        nodes.append({'name': cat, 'category': 'category'})
        
    # 构建连线
    for (day, cat), amount in flow_data.items():
        if amount > 0:
            links.append({
                'source': day,
                'target': cat,
                'value': float(amount)
            })
            
    return {
        'nodes': nodes,
        'links': links
    }

def generate_funnel_data(df):
    """生成漏斗图数据（按金额区间）"""
    expense_df = df[df['收/支'] == '支出'].copy()
    
    if expense_df.empty:
        return []
    
    bins = [0, 50, 100, 500, 1000, 5000, float('inf')]
    labels = ['0-50元', '50-100元', '100-500元', '500-1000元', '1000-5000元', '>5000元']
    
    expense_df['amount_range'] = pd.cut(expense_df['金额'], bins=bins, labels=labels, right=False)
    
    # 统计各区间总金额
    funnel_data = expense_df.groupby('amount_range')['金额'].sum().reset_index()
    
    result = []
    for _, row in funnel_data.iterrows():
        result.append({
            'name': row['amount_range'],
            'value': float(row['金额'])
        })
        
    # 按金额排序
    result.sort(key=lambda x: x['value'], reverse=True)
    return result

def generate_quadrant_data(df):
    """生成消费象限数据（频次 vs 均价）"""
    expense_df = df[df['收/支'] == '支出'].copy()
    
    if expense_df.empty:
        return []
        
    # 按商家聚合
    merchant_stats = expense_df.groupby('交易对方').agg({
        '金额': ['count', 'mean', 'sum'],
        '交易分类': lambda x: x.mode().iloc[0] if not x.mode().empty else '其他'
    }).reset_index()
    
    # 重命名列
    merchant_stats.columns = ['name', 'count', 'avg_amount', 'total_amount', 'category']
    
    # 过滤掉极小额或极低频的数据，减少噪音
    # 例如：总金额 < 50 或 频次 < 2
    filtered_stats = merchant_stats[
        (merchant_stats['total_amount'] >= 50) & 
        (merchant_stats['count'] >= 2)
    ]
    
    data = []
    for _, row in filtered_stats.iterrows():
        data.append({
            'name': row['name'],
            'category': row['category'],
            'frequency': int(row['count']),
            'avg_amount': round(float(row['avg_amount']), 2),
            'total_amount': round(float(row['total_amount']), 2)
        })
        
    return data

def generate_radar_data(df):
    """生成雷达图数据（季度消费结构对比）"""
    expense_df = df[df['收/支'] == '支出'].copy()
    
    if expense_df.empty:
        return {'indicator': [], 'series': []}
    
    # 获取Top 8分类作为维度 (增加雷达图维度)
    top_categories = expense_df.groupby('交易分类')['金额'].sum().nlargest(8).index.tolist()
    
    if not top_categories:
        return {'indicator': [], 'series': []}
        
    # 按季度分组
    expense_df['quarter'] = expense_df['交易时间'].dt.quarter
    quarters = sorted(expense_df['quarter'].unique())
    
    series_data = []
    max_val = 0
    
    for q in quarters:
        q_df = expense_df[expense_df['quarter'] == q]
        values = []
        for cat in top_categories:
            val = float(q_df[q_df['交易分类'] == cat]['金额'].sum())
            values.append(val)
            max_val = max(max_val, val)
            
        series_data.append({
            'name': f'Q{q}',
            'value': values
        })
        
    indicator = [{'name': c, 'max': max_val * 1.1} for c in top_categories]
    
    return {'indicator': indicator, 'series': series_data}

def generate_wordcloud_data(df):
    """生成词云数据"""
    expense_df = df[df['收/支'] == '支出'].copy()
    
    if expense_df.empty:
        return []
        
    # 统计商家频次和金额
    merchant_stats = expense_df.groupby('交易对方').agg({
        '金额': 'sum',
        '交易对方': 'count'
    }).rename(columns={'交易对方': 'count'})
    
    # 归一化权重: 结合频次和金额
    # 简单起见，直接使用金额作为权重，或者两者结合
    data = []
    for merchant, row in merchant_stats.iterrows():
        # 过滤掉金额太小的
        if row['金额'] > 10:
            data.append({
                'name': merchant,
                'value': float(row['金额'])
            })
            
    # 按权重排序取Top 100
    data.sort(key=lambda x: x['value'], reverse=True)
    return data[:100]

def generate_themeriver_data(df):
    """生成河流图数据（按月统计各分类消费）"""
    expense_df = df[df['收/支'] == '支出'].copy()
    
    if expense_df.empty:
        return {'categories': [], 'data': []}
    
    # 取Top 10 分类 (增加河流图层数)
    top_categories = expense_df.groupby('交易分类')['金额'].sum()\
                               .nlargest(10).index.tolist()
    
    # 按月份和分类聚合
    expense_df['month'] = expense_df['交易时间'].dt.to_period('M').astype(str)
    
    # 获取所有月份
    all_months = sorted(expense_df['month'].unique())
    
    data = []
    for month in all_months:
        month_df = expense_df[expense_df['month'] == month]
        for category in top_categories:
            amount = month_df[month_df['交易分类'] == category]['金额'].sum()
            # 即使金额为0也添加，确保河流图连续
            data.append([month, category, float(amount)])
    
    return {
        'categories': top_categories,
        'data': data
    }

def generate_boxplot_data(df):
    """生成消费分布云图数据（原箱形图位置）"""
    expense_df = df[df['收/支'] == '支出'].copy()
    expense_df = expense_df[expense_df['金额'] > 0]
    
    if expense_df.empty:
        return {'categories': [], 'data': []}
    
    # 取 Top 8 分类
    top_categories = expense_df.groupby('交易分类')['金额'].sum().nlargest(8).index.tolist()
    
    points_data = []
    box_stats = []
    
    for i, cat in enumerate(top_categories):
        # 1. 获取该分类下的所有交易：用于散点图
        cat_df = expense_df[expense_df['交易分类'] == cat][['金额', '交易对方', '交易时间']]
        values = cat_df['金额'].tolist()
        
        for _, row in cat_df.iterrows():
            points_data.append({
                'c': i, # category index
                'v': float(row['金额']),
                'm': row['交易对方'],
                'd': row['交易时间'].strftime('%Y-%m-%d')
            })
            
        # 2. 计算统计量：用于箱形图
        if values:
            q1 = np.percentile(values, 25)
            q3 = np.percentile(values, 75)
            # ECharts boxplot: [min, Q1, median, Q3, max]
            box_stats.append([
                float(np.min(values)),
                float(q1),
                float(np.median(values)),
                float(q3),
                float(np.max(values))
            ])
        else:
            box_stats.append([])
            
    return {
        'categories': top_categories,
        'data': points_data,
        'box_data': box_stats
    }

def generate_heatmap_data(df):
    """生成热力图数据（周-小时消费节律）"""
    expense_df = df[df['收/支'] == '支出'].copy()
    
    if expense_df.empty:
        return []
        
    # 提取星期和小时
    expense_df['weekday'] = expense_df['交易时间'].dt.dayofweek  # 0-6
    expense_df['hour'] = expense_df['交易时间'].dt.hour        # 0-23
    
    # 统计每个时间格子的消费频次
    heatmap_data = expense_df.groupby(['weekday', 'hour']).size().reset_index(name='count')
    
    # 转换为 ECharts 格式: [weekday, hour, count]
    # 注意：ECharts heatmap通常 x轴是小时，y轴是星期
    # data item: [x, y, value] -> [hour, weekday, count]
    data = []
    for _, row in heatmap_data.iterrows():
        data.append([int(row['hour']), int(row['weekday']), int(row['count'])])
        
    return data

def generate_pareto_data(df):
    """生成帕累托图数据（二八定律分析）"""
    expense_df = df[df['收/支'] == '支出'].copy()
    
    if expense_df.empty:
        return {'categories': [], 'values': [], 'percentages': []}
        
    # 按分类汇总
    category_stats = expense_df.groupby('交易分类')['金额'].sum().sort_values(ascending=False)
    
    total_amount = category_stats.sum()
    if total_amount == 0:
        return {'categories': [], 'values': [], 'percentages': []}
        
    cumulative_sum = category_stats.cumsum()
    cumulative_percentages = (cumulative_sum / total_amount * 100).round(2)
    
    # 取前 15 个分类，避免图表太长
    top_n = 15
    categories = category_stats.index[:top_n].tolist()
    values = category_stats.values[:top_n].tolist()
    percentages = cumulative_percentages.values[:top_n].tolist()
    
    return {
        'categories': categories,
        'values': [float(v) for v in values],
        'percentages': [float(p) for p in percentages]
    }


if __name__ == '__main__':
    # 确保上传目录存在生产环境
    is_production = os.environ.get('PRODUCTION', False)
    
    if is_production:
        # 生产环境配置
        app.config['TEMPLATES_AUTO_RELOAD'] = False
        app.run(
            host='0.0.0.0',
            port=8080,
            debug=False,
            use_reloader=False
        )
    else:
        # 开发环境配置
        app.config['TEMPLATES_AUTO_RELOAD'] = True
        extra_files = ['app.py']
        app.run(
            host='0.0.0.0',
            port=8080,
            debug=True,
            use_reloader=True,
            extra_files=extra_files,
            reloader_interval=2
        )

def generate_sankey_data(df):
    """
    生成消费关联桑基图数据
    分析逻辑：查找时间相近（例如 2 小时内）的连续消费行为
    """
    try:
        sorted_df = df.sort_values('交易时间')
        expense_df = sorted_df[sorted_df['收/支'] == '支出'].copy()
        
        links = {}
        nodes = set()
        window_seconds = 7200
        
        prev_time = None
        prev_cat = None
        
        for idx, row in expense_df.iterrows():
            curr_time = row['交易时间']
            curr_cat = row['交易分类']
            
            if prev_time is not None:
                time_diff = (curr_time - prev_time).total_seconds()
                if 0 < time_diff <= window_seconds and prev_cat != curr_cat:
                    key = (prev_cat, curr_cat)
                    if key in links:
                        links[key] += 1
                    else:
                        links[key] = 1
                    nodes.add(prev_cat)
                    nodes.add(curr_cat)
            
            prev_time = curr_time
            prev_cat = curr_cat
            
        filtered_links = []
        for (source, target), weight in links.items():
            if weight >= 2:
                filtered_links.append({"source": source, "target": target, "value": weight})
        
        if len(filtered_links) < 5:
             filtered_links = [{"source": s, "target": t, "value": w} for (s, t), w in links.items()]

        filtered_links = sorted(filtered_links, key=lambda x: x['value'], reverse=True)[:30]
        
        active_nodes = set()
        for link in filtered_links:
            active_nodes.add(link['source'])
            active_nodes.add(link['target'])
            
        return {
            "nodes": [{"name": n} for n in active_nodes],
            "links": filtered_links
        }
    except Exception as e:
        print(f"Error generating sankey data: {e}")
        return {"nodes": [], "links": []}

def generate_burndown_data(df):
    """
    生成燃尽图数据 (每月视图)
    """
    try:
        expense_df = df[df['收/支'] == '支出'].copy()
        if expense_df.empty:
            return {}

        latest_date = expense_df['交易时间'].max()
        target_year = latest_date.year
        target_month = latest_date.month
        
        month_df = expense_df[
            (expense_df['交易时间'].dt.year == target_year) & 
            (expense_df['交易时间'].dt.month == target_month)
        ]
        
        total_expense = month_df['金额'].sum()
        days_in_month = pd.Period(f"{target_year}-{target_month}").days_in_month
        
        ideal_data = [] 
        actual_data = [] 
        
        daily_expense = month_df.groupby(month_df['交易时间'].dt.day)['金额'].sum().to_dict()
        
        current_remaining = total_expense 
        actual_data.append([0, total_expense]) 
        ideal_data.append([0, total_expense])
        
        for day in range(1, days_in_month + 1):
            ideal_remaining = total_expense * (1 - day / days_in_month)
            ideal_data.append([day, max(0, ideal_remaining)])
            
            if day <= latest_date.day: 
                spent = daily_expense.get(day, 0)
                current_remaining -= spent
                actual_data.append([day, max(0, current_remaining)])
                
        return {
            "month": f"{target_year}-{target_month}",
            "total": total_expense,
            "ideal": ideal_data,
            "actual": actual_data
        }
    except Exception as e:
        print(f"Error generating burndown data: {e}")
        return {}

def generate_rfm_data(df):
    """
    生成商家 RFM 模型数据
    """
    try:
        expense_df = df[df['收/支'] == '支出'].copy()
        exclude_keywords = ['转账', '红包', '提现', '亲请付']
        mask = expense_df['交易对方'].apply(lambda x: not any(k in str(x) for k in exclude_keywords))
        expense_df = expense_df[mask]
        
        now = pd.Timestamp.now()
        
        merchant_stats = expense_df.groupby('交易对方').agg({
            '交易时间': lambda x: (now - x.max()).days,
            '交易对方': 'count', 
            '金额': 'sum'
        })
        merchant_stats.columns = ['recency', 'frequency', 'monetary']
        
        top_merchants = merchant_stats[merchant_stats['frequency'] > 2].copy()
        
        def get_label(row):
            if row['frequency'] > 10 and row['monetary'] > 1000:
                return '灵魂伴侣' 
            elif row['frequency'] > 10:
                return '高频日常' 
            elif row['monetary'] > 1000:
                return '重金过客' 
            else:
                return '普通朋友'
                
        top_merchants['label'] = top_merchants.apply(get_label, axis=1)
        
        result = []
        for merchant, row in top_merchants.iterrows():
            if len(str(merchant)) > 8: 
                display_name = str(merchant)[:8] + '..'
            else:
                display_name = str(merchant)
                
            result.append({
                "name": display_name,
                "r": int(row['recency']),
                "f": int(row['frequency']),
                "m": float(row['monetary']),
                "label": row['label']
            })
            
        return sorted(result, key=lambda x: x['m'], reverse=True)[:50] 
    except Exception as e:
        print(f"Error generating RFM data: {e}")
        return []

def generate_spiral_data(df):
    """
    生成螺旋图数据 (消费周期分析)
    """
    try:
        expense_df = df[df['收/支'] == '支出'].copy()
        
        expense_df['weekday'] = expense_df['交易时间'].dt.weekday 
        expense_df['hour'] = expense_df['交易时间'].dt.hour 
        expense_df['time_slot'] = expense_df['weekday'] * 24 + expense_df['hour']
        
        stats = expense_df.groupby('time_slot')['金额'].agg(['sum', 'count']).reset_index()
        stats_dict = stats.set_index('time_slot')['sum'].to_dict()
        
        result = []
        for i in range(168):
            val = stats_dict.get(i, 0)
            result.append([i, val])
            
        return result
    except Exception as e:
        print(f"Error generating spiral data: {e}")
        return []
