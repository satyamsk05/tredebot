import logging

def check_signal(closes):
    """
    Returns "YES/NO" for streaks >= 3. (Standard Martingale: 3-6-13...)
    """
    if len(closes) < 3:
        return None

    last_3 = closes[-3:]
    
    # Standard Mode: Check 3rd streak or higher
    if all(p > 0.5 for p in last_3):
        return "NO"
    if all(p < 0.5 for p in last_3):
        return "YES"

    return None
