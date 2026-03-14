import os
import sys
import re
from datetime import datetime

# ANSI Colors for terminal clarity
R = "\033[1;31m"  # Red
G = "\033[1;32m"  # Green
Y = "\033[1;33m"  # Yellow
B = "\033[1;34m"  # Blue
C = "\033[1;36m"  # Cyan
W = "\033[0m"     # White (Reset)

def vlen(text):
    """Calculates the visual length of a string by stripping ANSI escape codes."""
    if not text: return 0
    # Strip ANSI color codes and other escape sequences
    clean = re.sub(r'\033\[[0-9;]*[A-HJKSTfmpqrsu]', '', str(text))
    # Double check for basic color codes just in case
    clean = re.sub(r'\033\[[0-9;]*m', '', clean)
    return len(clean)

class SimpleLogger:
    def __init__(self):
        self.status_data = {
            "balance": "0.00",
            "active_market": "None",
            "martingale_step": 0,
            "bet_amount": 0,
            "next_sync": "00:00",
            "yes_price": "0.00",
            "no_price": "0.00",
            "matic_balance": "0.0000",
            "last_result": None,
            "last_dir": None,
            "pid": os.getpid()
        }
        self.logs = []
        self.max_logs = 8 
        self.width = 80
        self.clear_screen()

    def clear_screen(self):
        """Full terminal clear and cursor home."""
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()

    def get_frame(self):
        frame = []
        
        # 1. SPLASH HEADER
        splash_rows = [
            f"{C}██████╗  ██████╗ ██╗  ██╗   ██╗   ██╗ █████╗ ██████╗ ██╗  ██╗███████╗████████╗",
            f"{C}██╔══██╗██╔═══██╗██║  ╚██╗ ██╔╝  ██╔╝██╔══██╗██╔══██╗██║ ██╔╝██╔════╝╚══██╔══╝",
            f"{C}██████╔╝██║   ██║██║   ╚████╔╝  ██╔╝ ███████║██████╔╝█████╔╝ █████╗     ██║   ",
            f"{C}██╔═══╝ ██║   ██║██║    ╚██╔╝  ██╔╝  ██╔══██║██╔══██╗██╔═██╗ ██╔══╝     ██║   ",
            f"{C}██║     ╚██████╔╝███████╗██║  ██╔╝   ██║  ██║██║  ██║██║  ██╗███████╗   ██║   ",
            f"{C}╚═╝      ╚═════╝ ╚══════╝╚═╝  ╚═╝    ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝   ╚═╝   "
        ]
        for row in splash_rows:
            frame.append(row)
        
        # 2. WARNING + DASHBOARD TITLE (compact)
        frame.append(f"{W}  " + "─"*(self.width-4))
        frame.append(f"{W}    {Y}PREVIEW — USE AT OWN RISK | MULTI-ASSET UP/DOWN STRATEGY{W}")
        
        timestamp = datetime.now().strftime('%H:%M:%S')
        title = f" {W}TRADING TERMINAL v4.0 - {timestamp} "
        left_p = (self.width - vlen(title)) // 2
        frame.append(f"{C}" + "─"*left_p + title + "─"*(self.width - left_p - vlen(title)) + f"{W}")
        
        # Row 1: Status Details
        bal = f"{W}USDC: {G}${self.status_data['balance']} {W}| {C}VIRTUAL: {G}${self.status_data.get('virtual_balance', '500.00')}"
        sync = f"{W}NEXT CANDLE: {Y}{self.status_data['next_sync']}"
        l1 = f"  {bal}"
        # We need a fallback length check since padding depends on visual length
        l1_pad = self.width - vlen(l1) - vlen(sync) - 2
        l1 += " " * max(1, l1_pad)
        l1 += f"{sync}  "
        frame.append(l1)
        
        # Row 2: Market & Martingale
        mkt = self.status_data['active_market']
        if vlen(mkt) > 45: mkt = mkt[:42] + "..."
        m_str = f"{W}MARKET: {W}{mkt}"
        mg = f"{W}STEP: {C}L{int(self.status_data['martingale_step'])+1} {W}| BET: {C}${self.status_data['bet_amount']}"
        
        l2 = f"  {m_str}"
        l2 += " " * (self.width - vlen(l2) - vlen(mg) - 2)
        l2 += f"{mg}  "
        frame.append(l2)
        
        # Row 3: Live Prices & Gas
        pr = f"{W}YES PROB: {G}{self.status_data['yes_price']} {W}| NO PROB: {R}{self.status_data['no_price']}"
        gas = f"{W}GAS: {Y}{self.status_data.get('matic_balance', '0.0')} MATIC"
        l3 = f"  {pr}"
        l3 += " " * (self.width - vlen(l3) - vlen(gas) - 2)
        l3 += f"{gas}  "
        frame.append(l3)
        
        frame.append(f"{C}" + "─"*self.width + f"{W}")
        
        # 3. RESULT BANNER (Pinned Row)
        res = self.status_data.get('last_result')
        if res:
            res_color = G if res == "WIN" else R
            market_dir = self.status_data.get('last_dir', '---')
            banner = f"{res_color}LAST RESULT: {res} ({market_dir}){W}"
            banner_pad = (self.width - vlen(banner)) // 2
            frame.append(" " * banner_pad + banner)
        else:
            frame.append("")
        
        # 4. FIXED LOG AREA
        frame.append(f"{W}  [ SYSTEM LOGS ]")
        log_slice = self.logs[-self.max_logs:]
        for log in log_slice:
            frame.append(f"  {log}")
            
        # Clear/Fill the rest of the log area to prevent jumping
        for _ in range(self.max_logs - len(log_slice)):
            frame.append("")
        
        # Build final output:
        # \033[?25l = hide cursor (prevents flicker)
        # \033[H    = move cursor to top-left
        # \033[K    = clear to end of each line
        # \033[J    = clear from cursor to bottom (wipe leftover lines)
        # \033[?25h = show cursor again
        lines = "\n".join([line + "\033[K" for line in frame])
        return f"\033[?25l\033[H{lines}\033[J\033[?25h"

    def update(self):
        """Single-shot frame write to stop flickering."""
        try:
            sys.stdout.write(self.get_frame())
            sys.stdout.flush()
        except Exception:
            pass

    def print_log(self, prefix, msg, color=W):
        ts = datetime.now().strftime("%H:%M:%S")
        clean_msg = str(msg).replace("[bold green]", "").replace("[/bold green]", "")
        log_line = f"[{ts}] {color}{prefix}:{W} {clean_msg}"
        self.logs.append(log_line)
        if len(self.logs) > 100: self.logs.pop(0)
        self.update()

ui = SimpleLogger()

def log_info(msg):
    ui.print_log("INFO", msg, B)

def log_success(msg):
    ui.print_log("SUCCESS", msg, G)

def log_warning(msg):
    ui.print_log("WARNING", msg, Y)

def log_error(msg):
    ui.print_log("ERROR", msg, R)
    import logging
    logging.error(f"UI_ERROR: {msg}")

def log_trade(msg):
    ui.print_log("TRADE", msg, C)

def log_telegram(msg):
    ui.print_log("TG", msg, B)

def log_network_error(action, error):
    err_str = str(error)
    if "ConnectionResetError" in err_str or "10054" in err_str:
        msg = "Connection Reset"
    elif "ConnectTimeoutError" in err_str or "timeout" in err_str.lower():
        msg = "Timeout"
    else:
        msg = err_str.split('\n')[0][:60]
    log_warning(f"Network issue while {action}: {msg}")

def log_countdown(seconds):
    mins, secs = divmod(seconds, 60)
    ui.status_data["next_sync"] = f"{mins:02d}:{secs:02d}"

def log_status(running, coin_list):
    log_info(f"System Status: {'RUNNING' if running else 'STOPPED'}")

def print_result_banner(res, market_dir):
    ui.status_data['last_result'] = res
    ui.status_data['last_dir'] = market_dir
    ui.update()

def print_summary():
    ui.update()
