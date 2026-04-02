"""
A股AI专家团队 - 云端后端服务
使用Tushare Pro HTTP API获取数据
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
from datetime import datetime, timedelta
import os

app = Flask(__name__)
CORS(app)

# Tushare Pro Token
TUSHARE_TOKEN = os.environ.get('TUSHARE_TOKEN', 'cbc94cae8e5b8e540c9ec3b1656d033cb9e8939b030338f5bbfbfb39')
TUSHARE_API_URL = 'http://api.tushare.pro'

# 热门股票池
WATCHED_STOCKS = [
    '000875', '002567', '600517', '300750', '601012',
    '002230', '000725', '600036', '002594', '300059',
    '600519', '000858', '300274', '002466', '600900',
    '300033', '002475', '300124', '688981', '300223'
]

def tushare_api(api_name, params=None, fields=None):
    """调用Tushare API"""
    payload = {
        'api_name': api_name,
        'token': TUSHARE_TOKEN,
        'params': params or {},
        'fields': fields or ''
    }
    try:
        resp = requests.post(TUSHARE_API_URL, json=payload, timeout=30)
        result = resp.json()
        if result.get('code') == 0:
            return result.get('data', {})
        return None
    except Exception as e:
        print(f"API调用错误: {e}")
        return None

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok', 'message': '服务运行中', 'time': datetime.now().isoformat()})

@app.route('/api/stocks/realtime', methods=['GET'])
def get_realtime_stocks():
    """获取实时行情"""
    try:
        today = datetime.now().strftime('%Y%m%d')
        
        # 获取日线数据 - 用tushare Python库
        import tushare as ts
        pro = ts.pro_api(TUSHARE_TOKEN)
        
        all_stocks = []
        # 批量获取数据
        for i in range(0, len(WATCHED_STOCKS), 50):
            batch = WATCHED_STOCKS[i:i+50]
            ts_codes = ','.join([f'{code}.SZ' if code.startswith(('0', '3')) else f'{code}.SH' for code in batch])
            
            df = pro.daily(ts_code=ts_codes, trade_date=today)
            if df is None or df.empty:
                df = pro.daily(ts_code=ts_codes)
            
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    ts_code = row['ts_code']
                    code = ts_code.split('.')[0]
                    close = float(row['close'])
                    pct_chg = float(row['pct_chg']) if row['pct_chg'] else 0
                    turnover = float(row.get('turnover_rate', 0)) if row.get('turnover_rate') else 0
                    
                    stock = {
                        'code': code,
                        'name': row.get('name', code),
                        'price': round(close, 2),
                        'change': round(pct_chg, 2),
                        'change_value': round(pct_chg * close / 100, 2),
                        'open': round(float(row['open']), 2),
                        'high': round(float(row['high']), 2),
                        'low': round(float(row['low']), 2),
                        'volume': int(row['vol']) if row['vol'] else 0,
                        'amount': round(float(row['amount']) / 100000000, 2) if row['amount'] else 0,
                        'turnover': round(turnover, 2),
                        'trade_date': str(row['trade_date']),
                        'volumeRatio': round(turnover / 3, 2),
                        'hasLimitUp': pct_chg >= 9.9,
                        'kLineBullish': pct_chg > 0 and (row['vol'] or 0) > 1000000
                    }
                    stock['signal'] = '买入' if pct_chg >= 3 and turnover >= 3 else '持有'
                    stock['confidence'] = min(95, max(30, int(50 + pct_chg * 2 + turnover)))
                    stock['buyCondition'] = f"{stock['name']}回踩5日线企稳放量时可买入"
                    stock['sellCondition'] = f"{stock['name']}冲高回落超过3%果断卖出"
                    all_stocks.append(stock)
        
        # 按涨幅排序
        all_stocks.sort(key=lambda x: x['change'], reverse=True)
        for i, s in enumerate(all_stocks):
            s['rank'] = i + 1
        
        if not all_stocks:
            return jsonify({'success': False, 'error': '暂无数据'})
        
        return jsonify({'success': True, 'data': all_stocks, 'update_time': datetime.now().isoformat()})
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/stocks/detail/<code>', methods=['GET'])
def get_stock_detail(code):
    """获取单只股票详情"""
    try:
        today = datetime.now().strftime('%Y%m%d')
        start_date = (datetime.now() - timedelta(days=30)).strftime('%Y%m%d')
        
        import tushare as ts
        pro = ts.pro_api(TUSHARE_TOKEN)
        
        if code.startswith(('0', '3')):
            ts_code = f'{code}.SZ'
        else:
            ts_code = f'{code}.SH'
        
        df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=today)
        
        if df is None or df.empty:
            return jsonify({'success': False, 'error': '暂无数据'})
        
        info = pro.stock_basic(ts_code=ts_code, fields='ts_code,symbol,name,industry')
        
        closes = df['close'].tolist()
        ma5 = sum(closes[:5]) / min(5, len(closes)) if len(closes) >= 1 else 0
        ma10 = sum(closes[:10]) / min(10, len(closes)) if len(closes) >= 1 else 0
        ma20 = sum(closes[:20]) / min(20, len(closes)) if len(closes) >= 1 else 0
        
        latest = df.iloc[0]
        limit_up_count = len(df[df['pct_chg'] >= 9.9])
        
        return jsonify({
            'success': True,
            'data': {
                'code': code,
                'name': info['name'].values[0] if not info.empty else code,
                'industry': info['industry'].values[0] if not info.empty else '',
                'price': round(float(latest['close']), 2),
                'change': round(float(latest['pct_chg']), 2) if latest['pct_chg'] else 0,
                'open': round(float(latest['open']), 2),
                'high': round(float(latest['high']), 2),
                'low': round(float(latest['low']), 2),
                'volume': int(latest['vol']),
                'amount': round(float(latest['amount']) / 100000000, 2) if latest['amount'] else 0,
                'ma5': round(ma5, 2),
                'ma10': round(ma10, 2),
                'ma20': round(ma20, 2),
                'kLineBullish': ma5 > ma10 > ma20,
                'trade_date': str(latest['trade_date']),
                'limit_up_count_30d': limit_up_count,
                'limit_up_reasons': []
            }
        })
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/market/index', methods=['GET'])
def get_market_index():
    """获取大盘指数"""
    try:
        indices = [
            ('上证指数', '000001.SH'),
            ('深证成指', '399001.SZ'),
            ('创业板指', '399006.SZ'),
            ('沪深300', '000300.SH')
        ]
        
        import tushare as ts
        pro = ts.pro_api(TUSHARE_TOKEN)
        
        result = {}
        for name, code in indices:
            df = pro.index_daily(ts_code=code, trade_date=datetime.now().strftime('%Y%m%d'))
            if df is None or df.empty:
                df = pro.index_daily(ts_code=code)
            
            if df is not None and not df.empty:
                latest = df.iloc[0]
                result[name] = {
                    'code': code,
                    'price': round(float(latest['close']), 2),
                    'change': round(float(latest['pct_chg']), 2) if latest['pct_chg'] else 0,
                    'volume': int(latest['vol']) if 'vol' in latest and latest['vol'] else 0
                }
        
        return jsonify({'success': True, 'data': result})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
import os
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
