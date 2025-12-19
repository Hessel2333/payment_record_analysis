import pandas as pd
import numpy as np
import random
from datetime import datetime, timedelta
import os

# 配置
START_DATE = '2021-01-01'
END_DATE = '2024-12-31'
OUTPUT_FILE = 'static/sample_data.csv'

# 支付宝分类 (21类) & 权重
ALIPAY_CATEGORIES = {
    '餐饮美食': 0.35,  # 高频
    '日用百货': 0.12,
    '交通出行': 0.10,
    '数码电器': 0.015, # 低频 (之前是更高)
    '服饰装扮': 0.05,
    '住房物业': 0.05,
    '充值缴费': 0.03,
    '医疗健康': 0.02,
    '文化休闲': 0.03,
    '教育培训': 0.01,
    '爱车养车': 0.02,
    '酒店旅游': 0.02,
    '亲子': 0.02,
    '宠物': 0.01,
    '运动户外': 0.02,
    '家居家装': 0.01,
    '美容美发': 0.02,
    '转账红包': 0.05,
    '收入': 0.05,
    '其他': 0.05,
    '理财': 0.005
}

# 微信分类 (6类) & 权重
WECHAT_CATEGORIES = {
    '商户消费': 0.40,
    '扫二维码付款': 0.30, 
    '转账': 0.15,
    '微信红包': 0.10,
    '群收款': 0.03,
    '其他': 0.02
}

# 丰富的数据字典
METADATA = {
    '餐饮美食': {
        'merchants': ['肯德基', '麦当劳', '星巴克', '瑞幸咖啡', '沙县小吃', '兰州拉面', '必胜客', '海底捞', '喜茶', '蜜雪冰城', '美团外卖', '饿了么'],
        'descriptions': ['工作餐', '聚餐', '下午茶', '早餐', '夜宵', '外卖订单', '周末改善伙食']
    },
    '日用百货': {
        'merchants': ['7-11便利店', '全家FamilyMart', '罗森', '沃尔玛', '家乐福', '屈臣氏', '名创优品', '淘宝购物', '京东超市'],
        'descriptions': ['购买生活用品', '零食饮料', '洗漱用品', '纸巾湿巾', '超市购物']
    },
    '交通出行': {
        'merchants': ['滴滴出行', '铁路12306', '中国石化', '中国石油', 'T3出行', '哈啰单车', '美团单车', '地铁出行', '公交公司'],
        'descriptions': ['打车上班', '回家车票', '加油', '地铁充值', '共享单车', '停车费']
    },
    '数码电器': {
        'merchants': ['京东自营', '苏宁易购', 'Apple Store', '小米之家', '华为商城', '拼多多'],
        'descriptions': ['购买手机', '电脑配件', '耳机', '充电器', '智能手环', '家用电器']
    },
    '服饰装扮': {
        'merchants': ['优衣库', 'ZARA', 'H&M', '耐克Nike', '阿迪达斯', '淘宝服饰', '唯品会'],
        'descriptions': ['换季衣服', '鞋子', '运动装备', '配饰']
    },
    '住房物业': {
        'merchants': ['万科物业', '碧桂园服务', '国家电网', '自来水公司', '房东'],
        'descriptions': ['物业费', '电费', '水费', '房租', '宽带费']
    },
    '充值缴费': {
        'merchants': ['中国移动', '中国联通', '中国电信', '腾讯视频', '爱奇艺', '百度网盘'],
        'descriptions': ['话费充值', '宽带续费', '会员订阅', '流量包']
    },
    '医疗健康': {
        'merchants': ['大参林药店', '海王星辰', '第一人民医院', '社区卫生中心'],
        'descriptions': ['买药', '挂号费', '体检', '口罩消毒液']
    },
    '文化休闲': {
        'merchants': ['万达影城', '猫眼电影', '大麦网', '网鱼网咖', '新华书店'],
        'descriptions': ['看电影', '演唱会门票', '买书', '游戏充值']
    },
    '酒店旅游': {
        'merchants': ['携程旅行', '去哪儿网', '飞猪旅行', '华住会', '亚朵酒店'],
        'descriptions': ['订酒店', '机票', '景点门票', '度假']
    },
    '爱车养车': {
        'merchants': ['途虎养车', '4S店', '路边洗车店', '平安车险'],
        'descriptions': ['洗车', '保养', '维修', '保险']
    },
    '美容美发': {
        'merchants': ['震轩美容美发', '审美造型', '丝芙兰', '完美日记'],
        'descriptions': ['理发', '染发', '护肤品', '化妆品']
    },
    '转账红包': {
        'merchants': ['张三', '李四', '王五', '赵六', '家庭群', '同事群'],
        'descriptions': ['转账', '节日红包', 'AA收款', '借款还款']
    },
    '收入': {
        'merchants': ['XX科技有限公司', '银行利息', '闲鱼买家'],
        'descriptions': ['工资发放', '奖金', '二手出售', '理财收益']
    },
    # 微信特定
    '商户消费': {
        'merchants': ['早餐车', '水果摊', '便利店', '菜市场', '小卖部'],
        'descriptions': ['买早餐', '买水果', '买菜', '零钱支付']
    },
    '扫二维码付款': {
        'merchants': ['出租车', '路边摊', '打印店', '小吃店'],
        'descriptions': ['付款', '扫码支付']
    },
    '微信红包': {
        'merchants': ['微信好友', '家人', '同学'],
        'descriptions': ['恭喜发财', '大吉大利', '生日快乐']
    },
    '群收款': {
        'merchants': ['班级群', '聚餐群', '旅游群'],
        'descriptions': ['AA分摊', '活动费']
    },
    '转账': {
        'merchants': ['朋友', '房东', '借款人'],
        'descriptions': ['转账', '房租', '还款']
    }
}

# 金额范围配置 (类别 -> [(min, max, weight)])
AMOUNT_RANGES = {
    '数码电器': [(10, 100, 0.4), (100, 1000, 0.4), (1000, 8000, 0.2)], 
    '餐饮美食': [(5, 50, 0.7), (50, 200, 0.25), (200, 1000, 0.05)], 
    '日用百货': [(5, 100, 0.8), (100, 500, 0.2)],
    '服饰装扮': [(50, 300, 0.6), (300, 2000, 0.4)],
    '交通出行': [(2, 20, 0.8), (20, 100, 0.15), (100, 600, 0.05)],
    '酒店旅游': [(100, 500, 0.3), (500, 3000, 0.7)],
    '医疗健康': [(10, 100, 0.6), (100, 1000, 0.4)],
    '商户消费': [(1, 50, 0.7), (50, 200, 0.25), (200, 800, 0.05)],
    '扫二维码付款': [(2, 30, 0.8), (30, 200, 0.2)],
    '微信红包': [(0.01, 10, 0.5), (10, 200, 0.45), (200, 520, 0.05)],
    'DEFAULT': [(10, 200, 0.8), (200, 1000, 0.2)]
}

def get_metadata(category):
    # 优先查找精确匹配
    data = METADATA.get(category)
    if not data:
        # 找不到则使用默认
        if category in WECHAT_CATEGORIES:
            data = METADATA.get('商户消费')
        else:
            data = METADATA.get('日用百货') # 默认fallback
            
    merchant = random.choice(data['merchants'])
    description = random.choice(data['descriptions'])
    return merchant, description

def random_date(start_date, end_date):
    days = (end_date - start_date).days
    random_days = random.randint(0, days)
    # 时间分布: 8am-11pm (95%), 0am-7am (5%)
    if random.random() < 0.05:
        hour = random.randint(0, 7)
    else:
        r = random.random()
        if r < 0.3: # 午餐高峰
            hour = int(random.normalvariate(12, 1.5))
        elif r < 0.6: # 晚餐高峰
            hour = int(random.normalvariate(19, 1.5))
        else:
            hour = random.randint(8, 23)
    
    hour = max(0, min(23, hour))
    minute = random.randint(0, 59)
    second = random.randint(0, 59)
    
    return start_date + timedelta(days=random_days, hours=hour, minutes=minute, seconds=second)

def adjust_prob_dict(d):
    s = sum(d.values())
    return {k: v/s for k, v in d.items()}

def get_amount(category):
    ranges = AMOUNT_RANGES.get(category, AMOUNT_RANGES['DEFAULT'])
    rand = random.random()
    cumulative = 0
    selected_range = ranges[-1][:2]
    for r_min, r_max, weight in ranges:
        cumulative += weight
        if rand <= cumulative:
            selected_range = (r_min, r_max)
            break
    amt = random.uniform(selected_range[0], selected_range[1])
    return round(amt, 2)

def generate_data():
    start = datetime.strptime(START_DATE, '%Y-%m-%d')
    end = datetime.strptime(END_DATE, '%Y-%m-%d')
    records = []
    total_days = (end - start).days
    
    alipay_probs = adjust_prob_dict(ALIPAY_CATEGORIES)
    wechat_probs = adjust_prob_dict(WECHAT_CATEGORIES)
    
    alipay_cats = list(alipay_probs.keys())
    alipay_weights = list(alipay_probs.values())
    
    wechat_cats = list(wechat_probs.keys())
    wechat_weights = list(wechat_probs.values())

    # 每天平均 4-6 笔
    for _ in range(total_days * 5): 
        dt = random_date(start, end)
        source = '支付宝' if random.random() < 0.7 else '微信' # 7:3 比例
        
        if source == '支付宝':
            category = random.choices(alipay_cats, weights=alipay_weights, k=1)[0]
        else:
            category = random.choices(wechat_cats, weights=wechat_weights, k=1)[0]
            
        merchant, desc = get_metadata(category)
        amount = get_amount(category)
        
        # 确定收支
        if category in ['收入', '退款']:
            type_ = '收入'
        elif category in ['转账红包', '微信红包', '转账'] and random.random() < 0.4:
            type_ = '收入' # 红包/转账有可能是收入
        else:
            type_ = '支出'
        
        # 修正商品说明：如果是商户消费，可以带上商品名
        product = desc
        if '消费' in desc or '购物' in desc:
             # 可以再随机一点商品
             pass

        record = {
            '交易时间': dt,
            '交易分类': category,
            '交易对方': merchant,
            '商品说明': f"{merchant}-{product}", # 组合一下更真实
            '收/支': type_,
            '金额': amount,
            '收/付款方式': '余额宝' if source == '支付宝' else '零钱',
            '交易状态': '支付成功',
            '来源': source,
            '是否退款': False
        }
        records.append(record)
        
    # 固定大额支出 (房租)
    curr = start
    while curr <= end:
        records.append({
            '交易时间': curr.replace(day=1, hour=9, minute=0, second=0),
            '交易分类': '住房物业',
            '交易对方': '房东',
            '商品说明': '房租',
            '收/支': '支出',
            '金额': 4500.00,
            '收/付款方式': '银行卡',
            '交易状态': '支付成功',
            '来源': '支付宝',
            '是否退款': False
        })
        # 增加一些固定的大额理财或收入
        # 工资
        records.append({
            '交易时间': curr.replace(day=15, hour=14, minute=30, second=0),
            '交易分类': '收入',
            '交易对方': 'XX科技有限公司',
            '商品说明': '工资',
            '收/支': '收入',
            '金额': 15000.00,
            '收/付款方式': '银行卡',
            '交易状态': '支付成功',
            '来源': '支付宝',
            '是否退款': False
        })
        
        if curr.month == 12:
            curr = curr.replace(year=curr.year+1, month=1)
        else:
            curr = curr.replace(month=curr.month+1)
            
    df = pd.DataFrame(records)
    df = df.sort_values('交易时间', ascending=False)
    
    # 防止金额全为0
    df = df[df['金额'] > 0]
    
    df.to_csv(OUTPUT_FILE, index=False)
    print(f"Generated {len(df)} rich records into {OUTPUT_FILE}")

if __name__ == '__main__':
    generate_data()
