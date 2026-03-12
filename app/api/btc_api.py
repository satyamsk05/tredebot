import httpx
import time
import os
import logging
import asyncio
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

def get_active_btc_market(offset_minutes=0, interval=5):
    """Synchronous version for main.py"""
    now = int(time.time()) + (offset_minutes * 60)
    block_sec = interval * 60
    ts_sec = (now // block_sec) * block_sec
    slug = f"btc-updown-{interval}m-{ts_sec}"
    url = f"https://gamma-api.polymarket.com/markets/slug/{slug}"
    
    try:
        with httpx.Client(timeout=10) as client:
            res = client.get(url)
            if res.status_code == 200:
                data = res.json()
                tokens = data.get("clobTokenIds", [])
                if isinstance(tokens, str):
                    import json
                    try: tokens = json.loads(tokens)
                    except: tokens = []
                
                return {
                    "market_id": data.get("conditionId"),
                    "question": data.get("question"),
                    "yes_token": tokens[0] if len(tokens) > 0 else None,
                    "no_token": tokens[1] if len(tokens) > 1 else None,
                    "timestamp": ts_sec,
                    "interval": interval
                }
    except Exception as e:
        logging.error(f"Error fetching sync market: {e}")
    return None

async def async_get_active_btc_market(offset_minutes=0, interval=5):
    """Asynchronous version for telegram_bot.py"""
    now = int(time.time()) + (offset_minutes * 60)
    block_sec = interval * 60
    ts_sec = (now // block_sec) * block_sec
    slug = f"btc-updown-{interval}m-{ts_sec}"
    url = f"https://gamma-api.polymarket.com/markets/slug/{slug}"
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(url)
            if res.status_code == 200:
                data = res.json()
                tokens = data.get("clobTokenIds", [])
                if isinstance(tokens, str):
                    import json
                    try: tokens = json.loads(tokens)
                    except: tokens = []
                
                return {
                    "market_id": data.get("conditionId"),
                    "question": data.get("question"),
                    "yes_token": tokens[0] if len(tokens) > 0 else None,
                    "no_token": tokens[1] if len(tokens) > 1 else None,
                    "timestamp": ts_sec,
                    "interval": interval
                }
    except Exception as e:
        logging.error(f"Error fetching async market: {e}")
    return None

def get_last_trade_price(token_id):
    """Synchronous version"""
    url = f"https://clob.polymarket.com/last-trade-price?token_id={token_id}"
    try:
        with httpx.Client(timeout=10) as client:
            res = client.get(url)
            return float(res.json().get('price', 0)) if res.status_code == 200 else None
    except: return None

async def async_get_last_trade_price(token_id):
    """Asynchronous version"""
    url = f"https://clob.polymarket.com/last-trade-price?token_id={token_id}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(url)
            return float(res.json().get('price', 0)) if res.status_code == 200 else None
    except: return None

def place_btc_bet(token_id, amount, price=0.99, order_type="FOK"):
    """Synchronous weightlifter"""
    if DRY_RUN: return True
    try:
        client = get_clob_client()
        order_args = OrderArgs(price=price, size=amount, side="BUY", token_id=token_id)
        signed_order = client.create_order(order_args)
        poly_order_type = OrderType.FOK if order_type == "FOK" else OrderType.GTC
        resp = client.post_order(signed_order, poly_order_type)
        return resp and resp.get("success")
    except Exception as e:
        logging.error(f"Order error: {e}")
        return False

async def async_place_btc_bet(token_id, amount, price=0.99, order_type="FOK"):
    """Offloads the synchronous SDK call to a thread to keep bot alive"""
    return await asyncio.to_thread(place_btc_bet, token_id, amount, price, order_type)

