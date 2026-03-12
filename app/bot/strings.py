import json
import os

STRINGS = {
    "en": {
        "welcome": "📈 *{nickname} TRADING HUB*\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n⚡️ *BTC High Frequency Alpha*\n---------------------------\n💵 Base Bet: *${bet}*\n⏱️ State: *{mode}*\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\nDashboard ready... 👇",
        "status_header": "🖥️ *{nickname} DASHBOARD*\n━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "balance_header": "💰 *FINANCIAL OVERVIEW*\n━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "history_header": "📊 *BTC {tf}M HISTORY LOG*\n━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "matrix_header": "🏆 *BTC {tf}M MATRIX*\n━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "odds_header": "📉 *{tf}M REAL-TIME ODDS*\n━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "settings_header": "🛠️ *{nickname} SETTINGS*\n━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "appearance_header": "🎨 *UI PERSONALIZATION*\n━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "btn_start": "▶️ START BOT",
        "btn_stop": "🛑 STOP BOT",
        "btn_status": "📈 Status",
        "btn_balance": "💰 Balance",
        "btn_history": "📊 History",
        "btn_live": "📉 Live Price",
        "btn_manual": "🎯 Manual Trade",
        "btn_settings": "🛠️ Settings",
        "btn_back": "🔙 Back",
        "btn_perf": "🏆 Performance",
        "btn_reset": "🔄 Reset L1",
        "btn_report": "📊 Daily Report",
        "btn_help": "🆘 Help",
        "btn_appearance": "🎨 Appearance",
        "btn_lang": "🌐 Language",
        "btn_theme": "🎭 Theme",
        "btn_nick": "✍️ Nickname",
        "btn_custom": "Custom",
        "btn_tf": "TF",
        "btn_switch_to": "Switch to",
        "btn_odds": "Odds",
        "msg_lang_changed": "✅ Language changed to *English*",
        "msg_theme_changed": "🎭 Theme changed to *{theme}*",
        "msg_nick_changed": "✍️ Nickname updated to *{nickname}*",
        "msg_enter_nick": "✍️ *Set Bot Nickname*\n\nReply with the new name for your bot:"
    },
    "hi": {
        "welcome": "📈 *{nickname} ट्रेडिंग हब*\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n⚡️ *BTC हाई फ्रीक्वेंसी अल्फा*\n---------------------------\n💵 शुरुआती दांव: *${bet}*\n⏱️ स्थिति: *{mode}*\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\nडैशबोर्ड तैयार है... 👇",
        "status_header": "🖥️ *{nickname} डैशबोर्ड*\n━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "balance_header": "💰 *वित्तीय विवरण*\n━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "history_header": "📊 *BTC {tf}M इतिहास*\n━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "matrix_header": "🏆 *BTC {tf}M मैट्रिक्स*\n━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "odds_header": "📉 *{tf}M रीयल-टाइम ऑड्स*\n━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "settings_header": "🛠️ *{nickname} सेटिंग्स*\n━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "appearance_header": "🎨 *यूआई निजीकरण*\n━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "btn_start": "▶️ बॉट शुरू करें",
        "btn_stop": "🛑 बॉट रोकें",
        "btn_status": "📈 स्थिति",
        "btn_balance": "💰 बैलेंस",
        "btn_history": "📊 इतिहास",
        "btn_live": "📉 लाइव भाव",
        "btn_manual": "🎯 मैनुअल ट्रेड",
        "btn_settings": "🛠️ सेटिंग्स",
        "btn_back": "🔙 वापस",
        "btn_perf": "🏆 प्रदर्शन",
        "btn_reset": "🔄 L1 रीसेट करें",
        "btn_report": "📊 दैनिक रिपोर्ट",
        "btn_help": "🆘 मदद",
        "btn_appearance": "🎨 दिखावट",
        "btn_lang": "🌐 भाषा",
        "btn_theme": "🎭 थीम",
        "btn_nick": "✍️ उपनाम",
        "btn_custom": "कस्टम",
        "btn_tf": "समय",
        "btn_switch_to": "बदलें",
        "btn_odds": "ऑड्स",
        "msg_lang_changed": "✅ भाषा बदलकर *हिंदी* कर दी गई है",
        "msg_theme_changed": "🎭 थीम बदलकर *{theme}* कर दी गई है",
        "msg_nick_changed": "✍️ उपनाम बदलकर *{nickname}* कर दिया गया है",
        "msg_enter_nick": "✍️ *बॉट उपनाम सेट करें*\n\nअपने बॉट के लिए नया नाम लिखकर भेजें:"
    }
}

THEMES = {
    "classic": {"up": "🟢", "down": "🔴", "win": "✅", "loss": "❌", "bullet": "•"},
    "neon": {"up": "⚡️", "down": "🔥", "win": "💎", "loss": "💀", "bullet": "🔸"}
}

def get_config():
    config = {"nickname": "ogbot", "theme": "classic", "language": "en"}
    path = "data/ui_config.json"
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                config = json.load(f)
        except: pass
    return config

def t(key, **kwargs):
    config = get_config()
    lang = config.get("language", "en")
    text = STRINGS.get(lang, STRINGS["en"]).get(key, key)
    
    # Inject nickname if not provided but needed
    if "nickname" not in kwargs:
        kwargs["nickname"] = config.get("nickname", "ogbot").upper()
        
    return text.format(**kwargs)

def get_theme():
    config = get_config()
    return THEMES.get(config.get("theme", "classic"), THEMES["classic"])
