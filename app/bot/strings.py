import json
import os

STRINGS = {
    "en": {
        "welcome": "📈 *OGBOT TRADING HUB*\n——————————————————\n\n⚡️ *Multi-Asset High Frequency Alpha*\n——————————————————\n💵 Base Bet: *${bet}*\n⏱️ State: *{mode}*\n——————————————————\nDashboard ready... 👇",
        "status_header": "🖥️ *OGBOT DASHBOARD*\n————————————————",
        "balance_header": "💰 *FINANCIAL OVERVIEW*\n————————————————",
        "history_header": "📊 *{tf}M HISTORY LOG*\n————————————————",
        "matrix_header": "🏆 *OGBOT MATRIX*\n————————————————",
        "odds_header": "📉 *{tf}M REAL-TIME ODDS*\n————————————————",
        "settings_header": "🛠️ *OGBOT SETTINGS*\n————————————————",
        "appearance_header": "🎨 UI PERSONALIZATION",
        "btn_start": "▶️ START BOT",
        "btn_stop": "🛑 STOP BOT",
        "btn_status": "📈 Status",
        "btn_balance": "💰 Balance",
        "btn_history": "📊 History",
        "btn_live": "📉 Live Price",
        "btn_manual": "🎯 Manual Trade",
        "btn_settings": "🛠️ Settings",
        "btn_back_settings": "🔙 Settings",
        "btn_back": "🔙 Back",
        "btn_reset": "🔄 Reset L1",
        "btn_report": "📊 Daily Report",
        "btn_trends": "🕯️ Trends",
        "btn_help": "🆘 Help",
        "btn_claim": "🎁 Claim Winnings",
        "pending_claims": "🎁 Pending Claims: *${amount}*",
        "msg_claiming": "⏳ *Processing Claims...*\nBurning winning tokens and redeeming USDC.e...",
        "msg_claim_done": "✅ *Redemption Successful!*\nTotal Claimed: *${amount} USDC.e*",
        "msg_no_claims": "❌ No unclaimed winnings found.",
        "btn_custom": "Custom",
        "btn_refresh": "🔄 Refresh",
        "msg_manual_amount": "💰 *Manual Trade: Step 1*\n\nEnter the amount in USDC you want to bet:",
        "msg_manual_limit": "🎯 *Manual Trade: Step 2*\n\nEnter the **Limit Price** (e.g. 0.45).\n_Min: 0.01 | Max: 0.99_",
        "msg_manual_confirm": "📝 *Confirm Manual Trade*\n——————————————————\nSide   »  *{side}*\nAmt    »  *${amount}*\nLimit  »  *{price}*\n——————————————————\nConfirm with buttons below:",
        "btn_confirm_trade": "✅ Confirm & Place",
        "btn_cancel_trade": "❌ Cancel",
        "msg_invalid_price": "⚠️ *Invalid Price!*\nPrice must be between 0.01 and 0.99. Try again:"
    }
}

THEMES = {
    "classic": {"up": "🟢", "down": "🔴", "win": "✅", "loss": "❌", "bullet": "•"},
    "neon": {"up": "⚡️", "down": "🔥", "win": "💎", "loss": "💀", "bullet": "🔸"}
}

def get_config():
    config = {"nickname": "OG BOTS", "theme": "classic"}
    path = "data/ui_config.json"
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                config = json.load(f)
        except: pass
    if "nickname" not in config or config["nickname"] == "OGBOT":
        config["nickname"] = "OG BOTS"
    return config

def t(key, **kwargs):
    config = get_config()
    text = STRINGS["en"].get(key, key)
    
    # Inject nickname if not provided but needed
    if "nickname" not in kwargs:
        kwargs["nickname"] = config.get("nickname", "OG BOTS").upper()
        
    return text.format(**kwargs)

def get_theme():
    config = get_config()
    return THEMES.get(config.get("theme", "classic"), THEMES["classic"])
