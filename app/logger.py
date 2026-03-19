import os
import sys
import re
import time
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
    clean = re.sub(r'\033\[[0-9;]*[A-HJKSTfmpqrsu]', '', str(text))
    clean = re.sub(r'\033\[[0-9;]*m', '', clean)
    return len(clean)

class SimpleLogger:
    def __init__(self):
        self.status_data = {
            "balance": "0.00",
            "virtual_balance": "0.00",
            "active_market": "None",
            "martingale_step": 0,
            "bet_amount": 0,
            "next_sync": "00:00",
            "sync_percent": 0,
            "matic_balance": "0.0000",
            "last_result": None,
            "last_dir": None,
            "startup_status": "Ready",
            "markets": {} # Store per-coin stats: { 'BTC': {'yes': 0.5, 'no': 0.5, 'trend': '...', 'status': '...'} }
        }
        self.logs = []
        self.max_logs = 6 
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
            f"{C}  ██████╗  ██████╗ ██████╗  ██████╗ ████████╗",
            f"{C} ██╔═══██╗██╔════╝ ██╔══██╗██╔═══██╗╚══██╔══╝",
            f"{C} ██║   ██║██║  ███╗██████╔╝██║   ██║   ██║   ",
            f"{C} ██║   ██║██║   ██║██╔══██╗██║   ██║   ██║   ",
            f"{C} ╚██████╔╝╚██████╔╝██████╔╝╚██████╔╝   ██║   ",
            f"{C}  ╚═════╝  ╚═════╝ ╚═════╝  ╚═════╝    ╚═╝   "
        ]
        for row in splash_rows:
            frame.append(row)
        
        frame.append(f"{W}  " + "─"*(self.width-4))
        frame.append(f"{W}    {Y}PREVIEW — USE AT OWN RISK | MULTI-ASSET ALPHA STRATEGY{W}")
        
        timestamp = datetime.now().strftime('%H:%M:%S')
        title = f" {W}TRADING TERMINAL v4.1 PRO - {timestamp} "
        left_p = (self.width - vlen(title)) // 2
        frame.append(f"{C}" + "─"*left_p + title + "─"*(self.width - left_p - vlen(title)) + f"{W}")
        
        # Row 1: Status Details
        bal = f"{W}USDC: {G}${self.status_data['balance']} {W}| {C}VIRT: {G}${self.status_data.get('virtual_balance', '0.0')} {W}| {W}GAS: {Y}{self.status_data.get('matic_balance', '0.0')} MATIC"
        startup = self.status_data.get("startup_status", "Ready")
        st_color = Y if "/3" in startup else G
        st_str = f"{W}UPTIME: {st_color}{startup}{W}"
        
        l1 = f"  {bal}"
        l1 += " " * max(1, self.width - vlen(l1) - vlen(st_str) - 2)
        l1 += f"{st_str}  "
        frame.append(l1)

        # Row 2: Progress Bar
        p_val = self.status_data.get("sync_percent", 0)
        p_bar_size = 40
        filled = int(p_bar_size * (p_val / 100 or 0))
        p_bar = f"{G}{'█'*filled}{W}{'░'*(p_bar_size-filled)}"
        sync_str = f"{W}NEXT CANDLE: {Y}{self.status_data['next_sync']} {W}[{p_bar}{W}]"
        l_sync = f"  {sync_str}"
        frame.append(l_sync)
        
        frame.append(f"{W}  " + "─"*(self.width-4))

        # 2. MULTI-COIN TABLE
        table_header = f"  {W}ASSET   |  YES    |  NO     |  SIGNAL / STATUS{W}"
        frame.append(table_header)
        frame.append(f"  {W}--------|---------|---------|----------------------------------{W}")
        
        coins = ["BTC", "ETH", "SOL", "XRP"]
        m_data = self.status_data.get("markets", {})
        for c in coins:
            data = m_data.get(c, {"yes": "0.00", "no": "0.00", "status": "Scanning"})
            y_p = f"{G}${data.get('yes', '0.00')}{W}"
            n_p = f"{R}${data.get('no', '0.00')}{W}"
            status = data.get('status', 'Scanning')
            st_color = Y if "Signal" in status else (G if "WON" in status else (R if "LOST" in status else W))
            
            row = f"  {W}{c:<7} | {y_p:<15} | {n_p:<15} | {st_color}{status}{W}"
            frame.append(row)

        frame.append(f"{C}" + "─"*self.width + f"{W}")
        
        # 3. RESULT BANNER (Pinned Row)
        res = self.status_data.get('last_result')
        if res:
            res_color = G if res == "WIN" else R
            banner = f"{res_color}LAST EVENT: {res} ({self.status_data.get('last_dir', '---')}){W}"
            banner_pad = (self.width - vlen(banner)) // 2
            frame.append(" " * banner_pad + banner)
        else:
            frame.append("")
        
        # 4. FIXED LOG AREA
        frame.append(f"{W}  [ SYSTEM LOGS ]")
        log_slice = self.logs[-self.max_logs:]
        for log in log_slice:
            frame.append(f"  {log}")
            
        for _ in range(self.max_logs - len(log_slice)):
            frame.append("")
        
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

def log_info(msg): ui.print_log("INFO", msg, B)
def log_success(msg): ui.print_log("SUCCESS", msg, G)
def log_warning(msg): ui.print_log("WARNING", msg, Y)
def log_error(msg):
    ui.print_log("ERROR", msg, R)
    import logging
    logging.error(f"UI_ERROR: {msg}")

def log_trade(msg): ui.print_log("TRADE", msg, C)
def log_telegram(msg): ui.print_log("TG", msg, B)

def log_network_error(action, error):
    err_str = str(error)
    if "ConnectionResetError" in err_str or "10054" in err_str: msg = "Connection Reset"
    elif "ConnectTimeoutError" in err_str or "timeout" in err_str.lower(): msg = "Timeout"
    else: msg = err_str.split('\n')[0][:60]
    log_warning(f"Network issue while {action}: {msg}")

def log_countdown(seconds):
    # Calculate progress % (assuming 15m default)
    total = 900 
    remaining = max(0, seconds)
    percent = int(100 * (total - remaining) / total)
    mins, secs = divmod(remaining, 60)
    ui.status_data["next_sync"] = f"{mins:02d}:{secs:02d}"
    ui.status_data["sync_percent"] = percent
    ui.update()

def log_status(running, coin_list):
    log_info(f"System Status: {'RUNNING' if running else 'STOPPED'}")

def print_result_banner(res, market_dir):
    ui.status_data['last_result'] = res
    ui.status_data['last_dir'] = market_dir
    ui.update()

def print_summary():
    ui.update()
