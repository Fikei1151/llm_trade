import MetaTrader5 as mt5

if not mt5.initialize():
    print("การเชื่อมต่อล้มเหลว")
    quit()
print("MT5 เวอร์ชัน:", mt5.version())
mt5.shutdown()