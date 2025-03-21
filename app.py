import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import google.generativeai as genai
import threading
import time
from datetime import datetime

# ตั้งค่า Gemini API
GOOGLE_API_KEY = "AIzaSyD-k1gCMg6sDKrEc4nnRDhJ3tPGtH2tyTY"
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash-thinking-exp-01-21')

# เริ่มต้น MT5
print("พยายามเชื่อมต่อ MT5...")
if not mt5.initialize(login=2100542414, password="Fikree24@", server="IUXMarkets-Demo"):
    print("การเชื่อมต่อ MT5 ล้มเหลว", mt5.last_error())
    quit()
print("เชื่อมต่อ MT5 สำเร็จ")

# ฟังก์ชันคำนวณตัวชี้วัด (เพิ่ม Stochastic และ ADX)
def calculate_indicators(data):
    data['MA20'] = data['Close'].rolling(window=20).mean()
    data['RSI'] = compute_rsi(data['Close'], 14)
    data['ATR'] = compute_atr(data, 14)
    data['BB_Middle'] = data['Close'].rolling(window=20).mean()
    data['BB_Std'] = data['Close'].rolling(window=20).std()
    data['BB_Upper'] = data['BB_Middle'] + 2 * data['BB_Std']
    data['BB_Lower'] = data['BB_Middle'] - 2 * data['BB_Std']
    data['EMA12'] = data['Close'].ewm(span=12, adjust=False).mean()
    data['EMA26'] = data['Close'].ewm(span=26, adjust=False).mean()
    data['MACD'] = data['EMA12'] - data['EMA26']
    data['Signal'] = data['MACD'].ewm(span=9, adjust=False).mean()
    
    # Stochastic (14,3,3)
    low14 = data['Low'].rolling(window=14).min()
    high14 = data['High'].rolling(window=14).max()
    data['%K'] = 100 * (data['Close'] - low14) / (high14 - low14)
    data['Stochastic'] = data['%K'].rolling(window=3).mean()
    
    # ADX (14)
    data['+DM'] = np.where((data['High'].diff() > data['Low'].diff()) & (data['High'].diff() > 0), data['High'].diff(), 0)
    data['-DM'] = np.where((data['Low'].diff() < data['High'].diff()) & (data['Low'].diff() > 0), data['Low'].diff(), 0)
    tr = compute_atr(data, 14)
    data['+DI'] = 100 * data['+DM'].rolling(window=14).mean() / tr
    data['-DI'] = 100 * data['-DM'].rolling(window=14).mean() / tr
    dx = 100 * np.abs(data['+DI'] - data['-DI']) / (data['+DI'] + data['-DI'])
    data['ADX'] = dx.rolling(window=14).mean()
    
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

# ดึงข้อมูลเรียลไทม์ (ปรับ bars เป็น 30 สำหรับ 5 วัน)
def get_realtime_data(symbol, timeframe=mt5.TIMEFRAME_H4, bars=30):
    if not mt5.symbol_select(symbol, True):
        print(f"Failed to select symbol: {symbol}")
        return pd.DataFrame()
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
    if rates is None or len(rates) == 0:
        print(f"No data retrieved for symbol {symbol}.")
        return pd.DataFrame()
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

# Prompt 1: วิเคราะห์ข้อมูลตลาดสำหรับการเปิดออเดอร์ใหม่ (ปรับเพิ่ม Stochastic และ ADX)
def analyze_market(data, open_orders):
    latest_data = data.iloc[-1]
    previous_data = data.iloc[-2] if len(data) > 1 else latest_data
    trend = "Uptrend" if latest_data['Close'] > latest_data['MA20'] else "Downtrend"
    orders_info = "\n".join([f"Order {o['ticket']}: {o['type']} at {o['price_open']}, SL: {o['sl']}, TP: {o['tp']}, Profit: {o['profit']}" for o in open_orders])
    prompt_analysis = (
        f"Analyze the following H4 market data for XAUUSD (5-day short-term focus, Monday to Friday):\n"
        f"Latest Data: Close: {latest_data['Close']}, MA20: {latest_data['MA20']}, RSI: {latest_data['RSI']}, ATR: {latest_data['ATR']}, "
        f"Stochastic: {latest_data['Stochastic']}, ADX: {latest_data['ADX']}\n"
        f"Previous Close: {previous_data['Close']}\n"
        f"Bollinger Bands: Upper: {latest_data['BB_Upper']}, Middle: {latest_data['BB_Middle']}, Lower: {latest_data['BB_Lower']}\n"
        f"MACD: {latest_data['MACD']}, Signal: {latest_data['Signal']}\n"
        f"Open Orders:\n{orders_info if open_orders else 'No open orders'}\n"
        f"Determine:\n"
        f"1. Trend: Uptrend/Downtrend based on Close vs MA20 and MACD direction.\n"
        f"2. Volatility: High (>1.5*average ATR) or Low.\n"
        f"3. Momentum: Strong (MACD diverging from Signal, Stochastic > 50) or Weak (MACD converging, Stochastic < 50).\n"
        f"4. Trend Strength: Strong (ADX > 25) or Weak (ADX < 25).\n"
        f"5. Potential reversal: Price near BB_Upper/BB_Lower with RSI > 70 or < 30, or Stochastic > 80 or < 20."
    )
    response = model.generate_content(prompt_analysis)
    return response.text

# Prompt 2: ตัดสินใจเปิดออเดอร์ใหม่ (ปรับเงื่อนไขให้เข้มงวดขึ้น)
def llm_decision_new_order(analysis, data, open_orders):
    latest_data = data.iloc[-1]
    prompt_decision = (
        f"Based on this H4 market analysis for XAUUSD (5-day aggressive strategy, Monday to Friday):\n{analysis}\n"
        f"Current Price: {latest_data['Close']}, ATR: {latest_data['ATR']}\n"
        f"Short-term Trading Strategy for Opening New Orders:\n"
        f"- Open Buy: If Uptrend (Price > MA20, MACD > Signal), Strong Trend (ADX > 25), Momentum Strong (Stochastic > 50), RSI < 70, price near BB_Lower or Middle, no conflicting sell orders.\n"
        f"- Open Sell: If Downtrend (Price < MA20, MACD < Signal), Strong Trend (ADX > 25), Momentum Weak (Stochastic < 50), RSI > 30, price near BB_Upper or Middle, no conflicting buy orders.\n"
        f"- Hold: If no clear entry signal, weak trend (ADX < 25), or conflicting orders exist.\n"
        f"Provide a decision: 'open_buy', 'open_sell', or 'hold', and briefly explain why."
    )
    response = model.generate_content(prompt_decision)
    return response.text

# Prompt 3: วิเคราะห์และตัดสินใจสำหรับออเดอร์ที่เปิดอยู่ (ปรับเงื่อนไขให้เหมาะสม)
def analyze_open_orders(data, open_orders):
    if not open_orders:
        return "No open orders to analyze."
    
    latest_data = data.iloc[-1]
    orders_info = "\n".join([f"Order {o['ticket']}: {o['type']} at {o['price_open']}, SL: {o['sl']}, TP: {o['tp']}, Profit: {o['profit']}" for o in open_orders])
    prompt_open_orders = (
        f"Analyze the following H4 market data and open orders for XAUUSD (5-day focus):\n"
        f"Latest Data: Close: {latest_data['Close']}, MA20: {latest_data['MA20']}, RSI: {latest_data['RSI']}, ATR: {latest_data['ATR']}, "
        f"Stochastic: {latest_data['Stochastic']}, ADX: {latest_data['ADX']}\n"
        f"Bollinger Bands: Upper: {latest_data['BB_Upper']}, Middle: {latest_data['BB_Middle']}, Lower: {latest_data['BB_Lower']}\n"
        f"MACD: {latest_data['MACD']}, Signal: {latest_data['Signal']}\n"
        f"Open Orders:\n{orders_info}\n"
        f"Strategy for Managing Open Orders:\n"
        f"- Close Order: If profit > 2*ATR, loss > 1.5*ATR, or trend reverses (e.g., Buy order but Price < MA20 and MACD < Signal and ADX < 25; Sell order but Price > MA20 and MACD > Signal and ADX < 25).\n"
        f"- Hold: If profit < 2*ATR, loss < 1.5*ATR, and trend remains strong (ADX > 25) with no reversal signal.\n"
        f"Provide a decision for each order: 'close_order' or 'hold', and briefly explain why."
    )
    response = model.generate_content(prompt_open_orders)
    return response.text

# ส่งคำสั่งเทรดหรือปิดออเดอร์ (ปรับ SL/TP ตาม ADX)
def execute_trade(symbol, action, data, open_orders, volume=0.1):
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print(f"Failed to get tick data for {symbol}")
        return
    
    if 'open' in action:
        price = tick.ask if 'buy' in action else tick.bid
        atr = data.iloc[-1]['ATR']
        adx = data.iloc[-1]['ADX']
        if adx > 25:  # แนวโน้มแข็งแกร่ง
            sl = price - atr * 1.5 if 'buy' in action else price + atr * 1.5
            tp = price + atr * 3 if 'buy' in action else price - atr * 3
        else:  # แนวโน้มอ่อน
            sl = price - atr * 1 if 'buy' in action else price + atr * 1
            tp = price + atr * 2 if 'buy' in action else price - atr * 2

        order_type = mt5.ORDER_TYPE_BUY if 'buy' in action else mt5.ORDER_TYPE_SELL
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": 10,
            "magic": 123456,
            "comment": "Automated Trade",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            print(f"Trade executed successfully: {action} - Ticket: {result.order}, Price: {price}, SL: {sl}, TP: {tp}, Volume: {volume}")
            time.sleep(1)
            positions = mt5.positions_get(symbol=symbol)
            print(f"Current positions after trade: {positions}")
        else:
            print(f"Failed to execute trade: {action} - Error: {result.retcode}, Comment: {result.comment}")

    elif action == 'close_order':
        for order in open_orders:
            ticket = order['ticket']
            order_type = mt5.ORDER_TYPE_BUY if order['type'] == 'Sell' else mt5.ORDER_TYPE_SELL
            price = tick.bid if order['type'] == 'Buy' else tick.ask
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": order_type,
                "position": ticket,
                "price": price,
                "deviation": 10,
                "magic": 123456,
                "comment": "Close Automated Trade",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(request)
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                print(f"Order closed successfully: Ticket {ticket}, Price: {price}")
            else:
                print(f"Failed to close order: Ticket {ticket} - Error: {result.retcode}, Comment: {result.comment}")

# ฟังก์ชันตรวจสอบวันเทรด (จันทร์ถึงศุกร์)
def is_trading_day():
    current_day = datetime.now().weekday()  # 0 = Monday, 6 = Sunday
    return 0 <= current_day <= 4  # Monday to Friday

# รันบอททุก 5 นาที (ปรับให้เทรดเฉพาะจันทร์-ศุกร์)
running = True

def run_trading_bot():
    symbol = "XAUUSD.iux"
    print(f"Account Info: {mt5.account_info()}")  # ตรวจสอบบัญชี
    while running:
        if not is_trading_day():
            print(f"Non-trading day at {time.ctime()}, sleeping for 24 hours.")
            time.sleep(86400)  # Sleep for 24 hours if weekend
            continue

        data = get_realtime_data(symbol, bars=30)
        if data.empty:
            print(f"No data for {symbol} at {time.ctime()}. Retrying later.")
            time.sleep(300)
            continue

        data = calculate_indicators(data)
        open_orders = get_open_orders(symbol)
        
        # วิเคราะห์ตลาดสำหรับการเปิดออเดอร์ใหม่
        market_analysis = analyze_market(data, open_orders)
        new_order_decision_text = llm_decision_new_order(market_analysis, data, open_orders)
        new_order_decision = 'hold'
        if 'open_buy' in new_order_decision_text.lower():
            new_order_decision = 'open_buy'
        elif 'open_sell' in new_order_decision_text.lower():
            new_order_decision = 'open_sell'

        # วิเคราะห์ออเดอร์ที่เปิดอยู่
        open_orders_analysis = analyze_open_orders(data, open_orders)
        open_orders_decisions = {}
        if open_orders:
            for order in open_orders:
                ticket = order['ticket']
                if f"close_order" in open_orders_analysis.lower() and str(ticket) in open_orders_analysis:
                    open_orders_decisions[ticket] = 'close_order'
                else:
                    open_orders_decisions[ticket] = 'hold'

        # รายงานผล พร้อมเพิ่มเวลาในส่วนสุดท้าย
        current_time = time.ctime()
        print(f"\n=== Trading Report at {current_time} ===")
        print(f"Market Analysis (New Orders):\n{market_analysis}")
        print(f"New Order Decision:\n{new_order_decision_text}")
        print(f"Final Decision (New Order) at {current_time}: {new_order_decision}")
        print(f"Open Orders Analysis at {current_time}:\n{open_orders_analysis}")
        if open_orders:
            print(f"Decisions for Open Orders at {current_time}:")
            for ticket, decision in open_orders_decisions.items():
                print(f"Order {ticket}: {decision}")

        # ดำเนินการตามคำสั่ง
        if new_order_decision in ['open_buy', 'open_sell']:
            execute_trade(symbol, new_order_decision, data, open_orders)
        for ticket, decision in open_orders_decisions.items():
            if decision == 'close_order':
                execute_trade(symbol, 'close_order', data, [o for o in open_orders if o['ticket'] == ticket])

        time.sleep(300)

bot_thread = threading.Thread(target=run_trading_bot)
bot_thread.start()