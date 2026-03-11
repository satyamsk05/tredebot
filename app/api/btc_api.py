import requests
import time
import os
import logging
from app.config import (
    POLY_API_KEY, POLY_API_SECRET, POLY_PASSPHRASE, 
    POLY_PRIVATE_KEY, FUNDER_ADDRESS, DRY_RUN
)
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType, ApiCreds
from py_clob_client.constants import POLYGON
from py_clob_client.exceptions import PolyApiException

# Setup client lazily
_client = None

def get_clob_client():
    global _client
    if _client is None:
        creds = ApiCreds(
            api_key=POLY_API_KEY, 
            api_secret=POLY_API_SECRET, 
            api_passphrase=POLY_PASSPHRASE
        )
        _client = ClobClient(
            "https://clob.polymarket.com", 
            chain_id=POLYGON, 
            creds=creds, 
            signature_type=1, 
            funder=FUNDER_ADDRESS
        )
        _client.set_credentials(creds)
    return _client

def get_active_btc_market(offset_minutes=0):
    """
    Fetches the BTC 5m Up/Down market.
    offset_minutes: 0 for the currently running candle, -5 for the previous candle.
    """
    now = int(time.time()) + (offset_minutes * 60)
    # 300 seconds = 5 minutes
    ts_sec = (now // 300) * 300
    slug = f"btc-updown-5m-{ts_sec}"
    url = f"https://gamma-api.polymarket.com/markets/slug/{slug}"
    
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            tokens = data.get("clobTokenIds", [])
            if isinstance(tokens, str):
                import json
                try:
                    tokens = json.loads(tokens)
                except Exception:
                    tokens = []
            
            yes_token = tokens[0] if len(tokens) > 0 else None
            no_token = tokens[1] if len(tokens) > 1 else None
            
            return {
                "market_id": data.get("conditionId"),
                "question": data.get("question"),
                "yes_token": yes_token,
                "no_token": no_token,
                "timestamp": ts_sec
            }
        else:
            logging.error(f"Market not found for slug {slug}. Status: {res.status_code}")
            return None
    except Exception as e:
        logging.error(f"Error fetching active BTC market: {e}")
        return None

def get_last_trade_price(token_id):
    """Fetches the last trade price of the given token from CLOB API."""
    url = f"https://clob.polymarket.com/last-trade-price?token_id={token_id}"
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            return float(res.json().get('price', 0))
        return None
    except Exception as e:
        logging.error(f"Error fetching last trade price: {e}")
        return None

def place_btc_bet(token_id, amount, price=0.99, order_type="FOK"):
    """
    Places a BUY order for the given token ID.
    order_type: 'FOK' for market orders, 'GTC' for limit orders.
    Uses DRY_RUN env var to prevent actual betting if testing.
    """
    logging.info(f"Preparing to bet {amount} units on Token {token_id} @ price {price} ({order_type})")
    
    if DRY_RUN:
        logging.info("[DRY RUN] Order simulation successful.")
        return True

    try:
        client = get_clob_client()
        order_args = OrderArgs(
            price=price,
            size=amount,
            side="BUY",
            token_id=token_id
        )
        
        # Create and sign the order.
        signed_order = client.create_order(order_args)
        
        # Post the order to Polymarket CLOB.
        poly_order_type = OrderType.FOK if order_type == "FOK" else OrderType.GTC
        resp = client.post_order(signed_order, poly_order_type)
        
        if resp and resp.get("success"):
            logging.info(f"Order placed successfully. ID: {resp.get('orderID')} ({order_type})")
            return True
        else:
            logging.error(f"Order failed: {resp.get('errorMsg', resp)}")
            return False
            
    except PolyApiException as e:
        logging.error(f"Polymarket API Exception: {e}")
        return False
    except Exception as e:
        logging.error(f"Unexpected error during order placement: {e}")
        return False

