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
        "appearance_header": "🎨 *UI PERSONALIZATION*\n————————————————",
        "multi_market_header": "🌐 *MULTI-MARKET CONFIGURATION*\n————————————————",
        "btn_start": "▶️ START BOT",
        "btn_stop": "🛑 STOP BOT",
        "btn_status": "📈 Status",
        "btn_balance": "💰 Balance",
        "btn_history": "📊 History",
        "btn_history_5m": "📊 5M History",
        "btn_history_15m": "📊 15M History",
        "btn_live": "📉 Live Price",
        "btn_manual": "🎯 Manual Trade",
        "btn_settings": "🛠️ Settings",
        "btn_multi_market": "🌐 Multi-Market",
        "btn_back_settings": "🔙 Settings",
        "btn_back": "🔙 Back",
        "btn_perf": "🏆 Performance",
        "btn_reset": "🔄 Reset L1",
        "btn_report": "📊 Daily Report",
        "btn_help": "🆘 Help",
        "btn_appearance": "🎨 Appearance",
        "btn_lang": "🌐 Language",
        "btn_theme": "🎭 Theme",
        "btn_nick": "✍️ Nickname",
        "btn_claim": "🎁 Claim Winnings",
        "pending_claims": "🎁 Pending Claims: *${amount}*",
        "msg_claiming": "⏳ *Processing Claims...*\nBurning winning tokens and redeeming USDC.e...",
        "msg_claim_done": "✅ *Redemption Successful!*\nTotal Claimed: *${amount} USDC.e*",
        "msg_no_claims": "❌ No unclaimed winnings found.",
        "btn_custom": "Custom",
        "btn_tf": "TF",
        "btn_switch_to": "Switch to",
        "btn_odds": "Odds",
        "btn_odds_5m": "📈 5M Odds",
        "btn_odds_15m": "📉 15M Odds",
        "btn_refresh": "🔄 Refresh",
        "msg_lang_changed": "✅ Language changed to *English*",
        "msg_theme_changed": "🎭 Theme changed to *{theme}*",
        "msg_nick_changed": "✍️ Nickname updated to *{nickname}*",
        "msg_enter_nick": "✍️ *Set Bot Nickname*\n\nReply with the new name for your bot:",
        "btn_martingale": "🎲 Martingale Mode",
        "msg_martingale_changed": "🎲 Martingale mode changed to *{mode}*",
        "mode_standard": "Standard (L5)",
        "mode_test": "Test Mode ($1)",
        "msg_manual_amount": "💰 *Manual Trade: Step 1*\n\nEnter the amount in USDC you want to bet:",
        "msg_manual_limit": "🎯 *Manual Trade: Step 2*\n\nEnter the **Limit Price** (e.g. 0.45).\n_Min: 0.01 | Max: 0.99_",
        "msg_manual_confirm": "📝 *Confirm Manual Trade*\n——————————————————\nSide   »  *{side}*\nAmt    »  *${amount}*\nLimit  »  *{price}*\n——————————————————\nConfirm with buttons below:",
        "btn_confirm_trade": "✅ Confirm & Place",
        "btn_cancel_trade": "❌ Cancel",
        "msg_invalid_price": "⚠️ *Invalid Price!*\nPrice must be between 0.01 and 0.99. Try again:"
    },
    "hi": {
        "welcome": "📈 *{nickname} ट्रेडिंग हब*\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n⚡️ *मल्टी-एसेट हाई फ्रीक्वेंसी अल्फा*\n---------------------------\n💵 शुरुआती दांव: *${bet}*\n⏱️ स्थिति: *{mode}*\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\nडैशबोर्ड तैयार है... 👇",
        "status_header": "🖥️ *OGBOT डैशबोर्ड*\n————————————————",
        "balance_header": "💰 *वित्तीय विवरण*\n————————————————",
        "history_header": "📊 *{tf}M इतिहास*\n————————————————",
        "matrix_header": "🏆 *OGBOT मैट्रिक्स*\n————————————————",
        "odds_header": "📉 *{tf}M रीयल-टाइम ऑड्स*\n————————————————",
        "settings_header": "🛠️ *OGBOT सेटिंग्स*\n————————————————",
        "appearance_header": "🎨 *यूआई निजीकरण*\n————————————————",
        "multi_market_header": "🌐 *मल्टी-मार्केट कॉन्फ़िगरेशन*\n————————————————",
        "btn_start": "▶️ बॉट शुरू करें",
        "btn_stop": "🛑 बॉट रोकें",
        "btn_status": "📈 स्थिति",
        "btn_balance": "💰 बैलेंस",
        "btn_history": "📊 इतिहास",
        "btn_history_5m": "📊 5M इतिहास",
        "btn_history_15m": "📊 15M इतिहास",
        "btn_live": "📉 लाइव भाव",
        "btn_manual": "🎯 मैनुअल ट्रेड",
        "btn_settings": "🛠️ सेटिंग्स",
        "btn_multi_market": "🌐 मल्टी-मार्केट",
        "btn_back_settings": "🔙 सेटिंग्स",
        "btn_back": "🔙 वापस",
        "btn_perf": "🏆 प्रदर्शन",
        "btn_reset": "🔄 L1 रीसेट करें",
        "btn_report": "📊 दैनिक रिपोर्ट",
        "btn_help": "🆘 मदद",
        "btn_appearance": "🎨 दिखावट",
        "btn_lang": "🌐 भाषा",
        "btn_theme": "🎭 थीम",
        "btn_nick": "✍️ उपनाम",
        "btn_claim": "🎁 जीत का दावा करें",
        "pending_claims": "🎁 बकाया दावा: *${amount}*",
        "msg_claiming": "⏳ *दावे की प्रक्रिया...*\nजीतने वाले टोकन जलाए जा रहे हैं और USDC.e प्राप्त किया जा रहा है...",
        "msg_claim_done": "✅ *दावा सफल रहा!*\nकुल दावा राशि: *${amount} USDC.e*",
        "msg_no_claims": "❌ कोई बकाया जीत नहीं मिली।",
        "btn_custom": "कस्टम",
        "btn_tf": "समय",
        "btn_switch_to": "बदलें",
        "btn_odds": "ऑड्स",
        "btn_odds_5m": "📈 5M ऑड्स",
        "btn_odds_15m": "📉 15M ऑड्स",
        "btn_refresh": "🔄 रिफ्रेश",
        "msg_lang_changed": "✅ भाषा बदलकर *हिंदी* कर दी गई है",
        "msg_theme_changed": "🎭 थीम बदलकर *{theme}* कर दी गई है",
        "msg_nick_changed": "✍️ उपनाम बदलकर *{nickname}* कर दिया गया है",
        "msg_enter_nick": "✍️ *बॉट उपनाम सेट करें*\n\nअपने बॉट के लिए नया नाम लिखकर भेजें:",
        "btn_martingale": "🎲 मार्टिंगेल मोड",
        "msg_martingale_changed": "🎲 मार्टिंगेल मोड बदलकर *{mode}* कर दिया गया है",
        "mode_standard": "स्टैंडर्ड (L5)",
        "mode_test": "टेस्ट मोड ($1)",
        "msg_manual_amount": "💰 *मैनुअल ट्रेड: स्टेप 1*\n\nजितनी राशि (USDC) आप लगाना चाहते हैं, वह लिखें:",
        "msg_manual_limit": "🎯 *मैनुअल ट्रेड: स्टेप 2*\n\n**लिमिट प्राइस** लिखें (जैसे 0.45)।\n_न्यूनतम: 0.01 | अधिकतम: 0.99_",
        "msg_manual_confirm": "📝 *मैनुअल ट्रेड की पुष्टि करें*\n——————————————————\nसाइड   »  *{side}*\nराशि   »  *${amount}*\nलिमिट  »  *{price}*\n——————————————————\nनीचे दिए गए बटन से पुष्टि करें:",
        "btn_confirm_trade": "✅ पुष्टि करें और ट्रेड लगाएं",
        "btn_cancel_trade": "❌ रद्द करें",
        "msg_invalid_price": "⚠️ *गलत प्राइस!*\nप्राइस 0.01 और 0.99 के बीच होना चाहिए। फिर से कोशिश करें:"
    }
}

THEMES = {
    "classic": {"up": "🟢", "down": "🔴", "win": "✅", "loss": "❌", "bullet": "•"},
    "neon": {"up": "⚡️", "down": "🔥", "win": "💎", "loss": "💀", "bullet": "🔸"}
}

def get_config():
    config = {"nickname": "OGBOT", "theme": "classic", "language": "en"}
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
