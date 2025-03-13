import MetaTrader5 as mt5

# --- Your account details ---
account=2100542414

password="Fikree24@"
server="IUXMarkets-Demo"

# --- Initialize MT5 connection ---
if not mt5.initialize(login=account, password=password, server=server):
    print("initialize() failed, error code =", mt5.last_error())
    quit()

print("MT5 Initialized and Logged in Successfully!")

# --- Example: Get account info to confirm connection ---
account_info = mt5.account_info()
if account_info:
    print(account_info)
else:
    print("Failed to get account info")

# --- Shutdown MT5 connection when done ---
mt5.shutdown()