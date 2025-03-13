import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import google.generativeai as genai
from flask import Flask, jsonify
import time
import threading

# ตั้งค่า Gemini API
GOOGLE_API_KEY = "your_google_api_key"
genai.configure(api_key=GOOGLE_API_KEY)

# เริ่มต้น MT5
print("พยายามเชื่อมต่อ MT5...")
if not mt5.initialize(login=2100538058, password="Fikree24@", server="IUXMarkets-Demo"):
    print("การเชื่อมต่อ MT5 ล้มเหลว")
    print(f"รหัสข้อผิดพลาด: {mt5.last_error()}")
    quit()
print("เชื่อมต่อ MT5 สำเร็จ")

# ฟังก์ชันคำนวณตัวชี้วัด (เหมือนเดิม)...
def calculate_indicators(data):
    data['MA200'] = data['Close'].rolling(window=200).mean()
    data['RSI'] = compute_rsi(data['Close'], 14)
    data['ATR'] = compute_atr(data, 14)
    return data

def compute_rsi(data, window):
    diff = data.diff(1)
    gain = (diff.where(diff > 0, 0)).rolling(window=window).mean()
    loss = (-diff.where(diff < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def compute_atr(data, window):
    high_low = data['High'] - data['Low']
    high_close = np.abs(data['High'] - data['Close'].shift())
    low_close = np.abs(data['Low'] - data['Close'].shift())
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.rolling(window=window).mean()

# ดึงข้อมูลเรียลไทม์
def get_realtime_data(symbol, timeframe=mt5.TIMEFRAME_H4, days=7):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, 24 * days)
    data = pd.DataFrame(rates)
    data['time'] = pd.to_datetime(data['time'], unit='s')
    data = data.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close'})
    return data

# ดึงข้อมูลออเดอร์
def get_open_orders(symbol):
    positions = mt5.positions_get(symbol=symbol)
    if positions:
        return [{"ticket": pos.ticket, "type": "Buy" if pos.type == mt5.ORDER_TYPE_BUY else "Sell",
                 "price_open": pos.price_open, "sl": pos.sl, "tp": pos.tp, "profit": pos.profit} for pos in positions]
    return []

# LLM ตัดสินใจด้วย Gemini
model = genai.GenerativeModel('gemini-1.5-flash')

def llm_decision(data, open_orders, economic_news="No significant news"):
    latest_data = data.iloc[-1]
    orders_info = "\n".join([f"Order {o['ticket']}: {o['type']} at {o['price_open']}, SL: {o['sl']}, TP: {o['tp']}, Profit: {o['profit']}" for o in open_orders])
    prompt = (
        f"Analyze the market and open orders to decide the next action:\n"
        f"Market Data: Close: {latest_data['Close']}, MA200: {latest_data['MA200']}, RSI: {latest_data['RSI']}, ATR: {latest_data['ATR']}\n"
        f"Open Orders:\n{orders_info if open_orders else 'No open orders'}\n"
        f"Economic News: {economic_news}\n"
        f"Strategy: Open a new buy order if price > MA200 and RSI < 70 and no conflicting orders. "
        f"Open a new sell order if price < MA200 and RSI > 30 and no conflicting orders. "
        f"Close an order if it’s near SL/TP or trend reverses. Otherwise, hold."
    )
    response = model.generate_content(prompt)
    decision = response.text.strip().lower()
    if 'open buy' in decision:
        return 'open_buy'
    elif 'open sell' in decision:
        return 'open_sell'
    elif 'close order' in decision:
        return 'close_order'
    else:
        return 'hold'

# ส่งคำสั่งเทรด
def execute_trade(symbol, action, volume=0.1):
    if action in ['open_buy', 'open_sell']:
        price = mt5.symbol_info_tick(symbol).ask if action == "open_buy" else mt5.symbol_info_tick(symbol).bid
        order_type = mt5.ORDER_TYPE_BUY if action == "open_buy" else mt5.ORDER_TYPE_SELL
        request = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": volume, "type": order_type,
            "price": price, "sl": price * 0.98 if action == "open_buy" else price * 1.02,
            "tp": price * 1.04 if action == "open_buy" else price * 0.96, "magic": 123456,
            "comment": "Trade by Bot", "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC
        }
        result = mt5.order_send(request)
        print(f"{action}: {result.comment}")
    elif action == 'close_order':
        positions = mt5.positions_get(symbol=symbol)
        for pos in positions:
            close_request = {
                "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": pos.volume,
                "type": mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY,
                "position": pos.ticket,
                "price": mt5.symbol_info_tick(symbol).bid if pos.type == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(symbol).ask,
                "magic": 123456, "comment": "Close by Bot", "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC
            }
            result = mt5.order_send(close_request)
            print(f"Closed order {pos.ticket}: {result.comment}")

# Flask app
app = Flask(__name__)

@app.route('/trade_decision', methods=['GET'])
def trade_decision():
    symbol = "EURUSD"
    data = get_realtime_data(symbol, days=7)
    data = calculate_indicators(data)
    open_orders = get_open_orders(symbol)
    decision = llm_decision(data, open_orders)
    return jsonify({"symbol": symbol, "decision": decision, "open_orders": open_orders})

# รันบอททุก 30 นาที
def run_trading_bot():
    symbol = "EURUSD"
    while True:
        data = get_realtime_data(symbol, days=7)
        data = calculate_indicators(data)
        open_orders = get_open_orders(symbol)
        decision = llm_decision(data, open_orders)
        if decision in ['open_buy', 'open_sell', 'close_order']:
            execute_trade(symbol, decision)
        print(f"Decision: {decision} at {time.ctime()}")
        time.sleep(1800)  # 30 นาที

bot_thread = threading.Thread(target=run_trading_bot)
bot_thread.start()

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=8000)
