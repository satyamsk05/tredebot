import logging

def check_signal(closes):
    """
    Checks the last 3 closes (probabilities 0-1 of the YES token).
    Returns "NO" if 3 closes > 0.5 (UP streak).
    Returns "YES" if 3 closes < 0.5 (DOWN streak).
    """
    if len(closes) < 3:
        return None

    last_3 = closes[-3:]
    
    # Check if all 3 are above 0.5
    if all(price > 0.5 for price in last_3):
        logging.info(f"Signal: 3 closes > 0.5 {last_3}. Betting NO.")
        return "NO"

    # Check if all 3 are below 0.5
    if all(price < 0.5 for price in last_3):
        logging.info(f"Signal: 3 closes < 0.5 {last_3}. Betting YES.")
        return "YES"

    return None
