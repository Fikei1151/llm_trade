import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import google.generativeai as genai
import threading
import time

# ตั้งค่า Gemini API
GOOGLE_API_KEY = "AIzaSyD-k1gCMg6sDKrEc4nnRDhJ3tPGtH2tyTY"
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash-thinking-exp-01-21')

# เริ่มต้น MT5
print("พยายามเชื่อมต่อ MT5...")
if not mt5.initialize(login=2100542874, password="Fikree24@", server="IUXMarkets-Demo"):
    print("การเชื่อมต่อ MT5 ล้มเหลว", mt5.last_error())
    quit()
print("เชื่อมต่อ MT5 สำเร็จ")

# ฟังก์ชันคำนวณตัวชี้วัด
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

# ดึงข้อมูลเรียลไทม์ (1 สัปดาห์ = 42 bars บน H4)
def get_realtime_data(symbol, timeframe=mt5.TIMEFRAME_H4, bars=42):
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

# Prompt 1: วิเคราะห์ข้อมูลตลาด (สายซิ่ง - รวดเร็วและเน้นโมเมนตัม)
def analyze_market(data, open_orders):
    latest_data = data.iloc[-1]
    previous_data = data.iloc[-2] if len(data) > 1 else latest_data
    trend = "Uptrend" if latest_data['Close'] > latest_data['MA20'] else "Downtrend"
    orders_info = "\n".join([f"Order {o['ticket']}: {o['type']} at {o['price_open']}, SL: {o['sl']}, TP: {o['tp']}, Profit: {o['profit']}" for o in open_orders])
    prompt_analysis = (
        f"Analyze the following H4 market data for XAUEUR.iux (aggressive short-term focus):\n"
        f"Latest Data: Close: {latest_data['Close']}, MA20: {latest_data['MA20']}, RSI: {latest_data['RSI']}, ATR: {latest_data['ATR']}\n"
        f"Previous Close: {previous_data['Close']}\n"
        f"Bollinger Bands: Upper: {latest_data['BB_Upper']}, Middle: {latest_data['BB_Middle']}, Lower: {latest_data['BB_Lower']}\n"
        f"MACD: {latest_data['MACD']}, Signal: {latest_data['Signal']}\n"
        f"Open Orders:\n{orders_info if open_orders else 'No open orders'}\n"
        f"Determine for aggressive trading:\n"
        f"1. Trend: Uptrend/Downtrend based on Close vs MA20 and MACD direction.\n"
        f"2. Volatility: High (>1.5*average ATR) or Low - prioritize high volatility for quick moves.\n"
        f"3. Momentum: Strong (MACD diverging from Signal rapidly) or Weak - focus on strong momentum.\n"
        f"4. Entry Opportunity: Price breaking BB_Upper (sell) or BB_Lower (buy) for breakout trades."
    )
    response = model.generate_content(prompt_analysis)
    return response.text

# Prompt 2: ตัดสินใจเปิดออเดอร์ใหม่ (สายซิ่ง - เน้น breakout และโมเมนตัมสูง)
def llm_decision_new_order(analysis, data, open_orders):
    latest_data = data.iloc[-1]
    prompt_decision = (
        f"Based on this H4 market analysis for XAUEUR.iux (aggressive breakout strategy):\n{analysis}\n"
        f"Current Price: {latest_data['Close']}, ATR: {latest_data['ATR']}\n"
        f"Aggressive Trading Strategy for High Risk and High Reward:\n"
        f"- Open Buy: If Uptrend (Price > MA20, MACD > Signal), Price breaks BB_Lower or strong momentum (MACD diverging), no conflicting sell orders.\n"
        f"- Open Sell: If Downtrend (Price < MA20, MACD < Signal), Price breaks BB_Upper or strong momentum (MACD diverging), no conflicting buy orders.\n"
        f"- Hold: If no breakout (Price within BB_Middle) or weak momentum (MACD near Signal).\n"
        f"Provide a decision: 'open_buy', 'open_sell', or 'hold', and briefly explain why."
    )
    response = model.generate_content(prompt_decision)
    return response.text

# Prompt 3: วิเคราะห์และตัดสินใจสำหรับออเดอร์ที่เปิดอยู่ (สายซิ่ง - ปิดเร็วเมื่อได้กำไรหรือแนวโน้มเปลี่ยน)
def analyze_open_orders(data, open_orders):
    if not open_orders:
        return "No open orders to analyze."
    
    latest_data = data.iloc[-1]
    orders_info = "\n".join([f"Order {o['ticket']}: {o['type']} at {o['price_open']}, SL: {o['sl']}, TP: {o['tp']}, Profit: {o['profit']}" for o in open_orders])
    prompt_open_orders = (
        f"Analyze the following H4 market data and open orders for XAUEUR.iux:\n"
        f"Latest Data: Close: {latest_data['Close']}, MA20: {latest_data['MA20']}, RSI: {latest_data['RSI']}, ATR: {latest_data['ATR']}\n"
        f"Bollinger Bands: Upper: {latest_data['BB_Upper']}, Middle: {latest_data['BB_Middle']}, Lower: {latest_data['BB_Lower']}\n"
        f"MACD: {latest_data['MACD']}, Signal: {latest_data['Signal']}\n"
        f"Open Orders:\n{orders_info}\n"
        f"Aggressive Strategy for Managing Open Orders:\n"
        f"- Close Order: If profit > 1*ATR (quick profit-taking) or trend reverses sharply (Buy but Price < MA20 and MACD < Signal; Sell but Price > MA20 and MACD > Signal).\n"
        f"- Hold: If profit < 1*ATR and trend still supports the order direction with strong momentum.\n"
        f"Provide a decision for each order: 'close_order' or 'hold', and briefly explain why."
    )
    response = model.generate_content(prompt_open_orders)
    return response.text

# ส่งคำสั่งเทรดหรือปิดออเดอร์ (สายซิ่ง: SL = 1.5*ATR, TP = 3*ATR)
def execute_trade(symbol, action, data, open_orders, volume=0.1):
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print(f"Failed to get tick data for {symbol}")
        return
    
    if 'open' in action:
        price = tick.ask if 'buy' in action else tick.bid
        atr = data.iloc[-1]['ATR']
        sl = price - atr * 1.5 if 'buy' in action else price + atr * 1.5  # SL = 1.5*ATR
        tp = price + atr * 3 if 'buy' in action else price - atr * 3      # TP = 3*ATR

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
            "comment": "Aggressive Trade",
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
                "comment": "Close Aggressive Trade",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(request)
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                print(f"Order closed successfully: Ticket {ticket}, Price: {price}")
            else:
                print(f"Failed to close order: Ticket {ticket} - Error: {result.retcode}, Comment: {result.comment}")

# รันบอททุก 3 นาที (สายซิ่ง)
running = True

def run_trading_bot():
    symbol = "XAUEUR.iux"
    print(f"Account Info: {mt5.account_info()}")  # ตรวจสอบบัญชี
    while running:
        data = get_realtime_data(symbol, bars=42)
        if data.empty:
            print(f"No data for {symbol} at {time.ctime()}. Retrying later.")
            time.sleep(180)  # รอ 3 นาที
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

        time.sleep(180)  # รันทุก 3 นาที

bot_thread = threading.Thread(target=run_trading_bot)
bot_thread.start()