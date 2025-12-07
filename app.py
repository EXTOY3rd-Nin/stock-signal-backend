from flask import Flask, jsonify, request
from flask_cors import CORS
import yfinance as yf
import requests
import os

app = Flask(__name__)
CORS(app)  # อนุญาตให้เว็บภายนอกเรียก API ได้

# ใช้ FMP API Key จาก environment variable
FMP_API_KEY = os.environ.get("FMP_API_KEY", "YOUR_KEY_HERE")

def get_fundamental_data(symbol):
    url = f"https://financialmodelingprep.com/api/v3/profile/{symbol}?apikey={FMP_API_KEY}"
    try:
        resp = requests.get(url, timeout=5)
        if resp.status_code != 200 or not resp.json():
            return None
        data = resp.json()[0]
        
        growth_url = f"https://financialmodelingprep.com/api/v3/financial-growth/{symbol}?apikey={FMP_API_KEY}"
        growth_resp = requests.get(growth_url, timeout=5)
        eps_growth = None
        if growth_resp.status_code == 200 and growth_resp.json():
            eps_growth = growth_resp.json()[0].get("epsgrowth", 0)

        return {
            "pe": data.get("peRatio"),
            "roe": data.get("roe") * 100 if data.get("roe") else None,
            "debt_to_equity": data.get("debtToEquity"),
            "eps_growth": eps_growth * 100 if eps_growth else None
        }
    except:
        return None

def is_fundamentally_strong(fund):
    if not fund: return False
    pe = fund.get("pe")
    roe = fund.get("roe")
    de = fund.get("debt_to_equity")
    eps = fund.get("eps_growth")
    score = sum([
        pe is not None and 0 < pe < 30,
        roe is not None and roe > 15,
        de is not None and de < 1.0,
        eps is not None and eps > 10
    ])
    return score >= 3

def get_technical_data(symbol):
    try:
        data = yf.download(symbol, period="1y", interval="1d")
        if len(data) < 200: return None
        close = data['Close']
        ema50 = close.ewm(span=50, adjust=False).mean()
        ema200 = close.ewm(span=200, adjust=False).mean()
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return {
            "price": float(close.iloc[-1]),
            "rsi": float(rsi.iloc[-1]),
            "ema50": float(ema50.iloc[-1]),
            "ema200": float(ema200.iloc[-1]),
            "golden_cross": (ema50.iloc[-2] <= ema200.iloc[-2]) and (ema50.iloc[-1] > ema200.iloc[-1])
        }
    except:
        return None

@app.route('/hybrid-signal')
def hybrid_signal():
    symbol = request.args.get('symbol', 'AAPL').upper()
    tech = get_technical_data(symbol)
    if not tech or not tech["golden_cross"] or not (40 <= tech["rsi"] <= 65):
        return jsonify({"symbol": symbol, "signal": "HOLD", "reason": "Technical not ready", "price": tech["price"] if tech else None})
    
    fund = get_fundamental_data(symbol)
    if not is_fundamentally_strong(fund):
        return jsonify({"symbol": symbol, "signal": "HOLD", "reason": "Weak fundamentals", "price": tech["price"]})

    return jsonify({
        "symbol": symbol,
        "signal": "BUY",
        "price": tech["price"],
        "technical": {"rsi": round(tech["rsi"], 2), "golden_cross": True},
        "fundamental": {
            "pe": fund.get("pe"),
            "roe": round(fund.get("roe"), 2) if fund.get("roe") else None,
            "debt_to_equity": fund.get("debt_to_equity"),
            "eps_growth": round(fund.get("eps_growth"), 2) if fund.get("eps_growth") else None
        }
    })

@app.route('/screener')
def screener():
    symbols = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "BRK.B", "JNJ", "V"]
    buy_stocks = []
    for sym in symbols:
        try:
            tech = get_technical_data(sym)
            if tech and tech["golden_cross"] and 40 <= tech["rsi"] <= 65:
                fund = get_fundamental_data(sym)
                if is_fundamentally_strong(fund):
                    buy_stocks.append({
                        "symbol": sym,
                        "price": tech["price"],
                        "rsi": round(tech["rsi"], 2),
                        "pe": fund.get("pe")
                    })
        except:
            continue
    return jsonify(buy_stocks)

@app.route('/candle-data')
def candle_data():
    symbol = request.args.get('symbol', 'AAPL').upper()
    try:
        data = yf.download(symbol, period="30d", interval="1d")
        if data.empty:
            return jsonify({"error": "No data"})
        dates = [d.strftime("%Y-%m-%d") for d in data.index]
        return jsonify({
            "dates": dates,
            "open": [float(x) for x in data['Open']],
            "high": [float(x) for x in data['High']],
            "low": [float(x) for x in data['Low']],
            "close": [float(x) for x in data['Close']]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
