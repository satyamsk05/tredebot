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
from py_clob_client.clob_types import OrderArgs, OrderType, ApiCreds, MarketOrderArgs
from py_clob_client.constants import POLYGON
from py_clob_client.exceptions import PolyApiException

# Setup clients lazily to reuse connections (Free speed)
_client = None
_sync_http = httpx.Client(timeout=10)
_async_http = httpx.AsyncClient(timeout=10)

def get_clob_client():
    global _client
    if _client is None:
        creds = ApiCreds(
            api_key=POLY_API_KEY, 
            api_secret=POLY_API_SECRET, 
            api_passphrase=POLY_PASSPHRASE
        )
        pk = POLY_PRIVATE_KEY[2:] if POLY_PRIVATE_KEY and POLY_PRIVATE_KEY.startswith("0x") else POLY_PRIVATE_KEY
        sig_type = 2 if FUNDER_ADDRESS else 1
        _client = ClobClient(
            "https://clob.polymarket.com", 
            chain_id=POLYGON, 
            creds=creds, 
            signature_type=sig_type, 
            funder=FUNDER_ADDRESS,
            key=pk
        )
    return _client

def get_active_market(coin="BTC", offset_minutes=0, interval=5):
    """Synchronous version for main.py"""
    now = int(time.time()) + (offset_minutes * 60)
    block_sec = interval * 60
    ts_sec = (now // block_sec) * block_sec
    slug = f"{coin.lower()}-updown-{interval}m-{ts_sec}"
    url = f"https://gamma-api.polymarket.com/markets/slug/{slug}"
    
    try:
        res = _sync_http.get(url)
        if res.status_code == 200:
            data = res.json()
            tokens = data.get("clobTokenIds", [])
            if isinstance(tokens, str):
                try: import orjson as json
                except ImportError: import json
                try: tokens = json.loads(tokens)
                except: tokens = []
            
            return {
                "market_id": data.get("conditionId"),
                "question": data.get("question"),
                "yes_token": tokens[0] if len(tokens) > 0 else None,
                "no_token": tokens[1] if len(tokens) > 1 else None,
                "timestamp": ts_sec,
                "interval": interval,
                "coin": coin
            }
    except Exception as e:
        logging.error(f"Error fetching sync market for {coin}: {e}")
    return None

async def async_get_active_market(coin="BTC", offset_minutes=0, interval=5):
    """Asynchronous version for telegram_bot.py"""
    now = int(time.time()) + (offset_minutes * 60)
    block_sec = interval * 60
    ts_sec = (now // block_sec) * block_sec
    slug = f"{coin.lower()}-updown-{interval}m-{ts_sec}"
    url = f"https://gamma-api.polymarket.com/markets/slug/{slug}"
    
    try:
        res = await _async_http.get(url)
        if res.status_code == 200:
            data = res.json()
            tokens = data.get("clobTokenIds", [])
            if isinstance(tokens, str):
                try: import orjson as json
                except ImportError: import json
                try: tokens = json.loads(tokens)
                except: tokens = []
            
            return {
                "market_id": data.get("conditionId"),
                "question": data.get("question"),
                "yes_token": tokens[0] if len(tokens) > 0 else None,
                "no_token": tokens[1] if len(tokens) > 1 else None,
                "timestamp": ts_sec,
                "interval": interval,
                "coin": coin
            }
    except Exception as e:
        logging.error(f"Error fetching async market for {coin}: {e}")
    return None

def get_last_trade_price(token_id):
    """Synchronous version"""
    url = f"https://clob.polymarket.com/last-trade-price?token_id={token_id}"
    try:
        res = _sync_http.get(url)
        return float(res.json().get('price', 0)) if res.status_code == 200 else None
    except: return None

async def async_get_last_trade_price(token_id):
    """Asynchronous version"""
    url = f"https://clob.polymarket.com/last-trade-price?token_id={token_id}"
    try:
        res = await _async_http.get(url)
        return float(res.json().get('price', 0)) if res.status_code == 200 else None
    except: return None

def place_bet(token_id, amount, coin="BTC", price=0.99, order_type="GTC", sizing_price=None):
    """Synchronous order placement"""
    if DRY_RUN: return True
    try:
        client = get_clob_client()
        
        # Determine if it's a "market" order (FOK with high price) or a true "limit" order
        is_limit = price < 0.90
        
        # Calculate size based on pricing
        calc_price = sizing_price if sizing_price else price
        size = round(amount / calc_price, 2)
        
        # Safety: Polymarket has min order size usually around $1
        if size < 0.1:
            logging.warning(f"[{coin}] Calculated size {size} is too small. Skipping.")
            return False

        order_args = OrderArgs(
            token_id=token_id, 
            price=price,
            size=size,
            side="BUY"
        )
        signed_order = client.create_order(order_args)

        if not is_limit:
            logging.info(f"[{coin}] Placing Market-Fill order: ${amount} (Size: {size}) at limit {price}")
            actual_order_type = OrderType.FOK if order_type == "FOK" else OrderType.GTC
            resp = client.post_order(signed_order, actual_order_type, post_only=False)
        else:
            logging.info(f"[{coin}] Placing Limit Order (Post-Only): ${amount} (Size: {size}) at ${price}")
            resp = client.post_order(signed_order, OrderType.GTC, post_only=True) # Maker Rebate active!
            
        return resp and resp.get("success")
    except Exception as e:
        import traceback
        logging.error(f"[{coin}] Order error: {e}")
        logging.error(traceback.format_exc())
        return False

async def async_place_bet(token_id, amount, coin="BTC", price=0.99, order_type="GTC", sizing_price=None):
    """Offloads the synchronous SDK call to a thread to keep bot alive"""
    return await asyncio.to_thread(place_bet, token_id, amount, coin, price, order_type, sizing_price)

def fetch_redeemable_positions(wallet_address):
    """
    Synchronous version of fetch_redeemable_positions_from_api.
    """
    if not wallet_address:
        return []
        
    url = f"https://data-api.polymarket.com/positions?user={wallet_address}"
    try:
        with httpx.Client(timeout=15) as client:
            res = client.get(url)
            if res.status_code == 200:
                positions = res.json()
                redeemables = []
                for pos in positions:
                    is_redeemable = pos.get('redeemable', False)
                    idx = pos.get('outcomeIndex')
                    bitmask = 1 << int(idx) if idx is not None else 0
                    
                    if is_redeemable and bitmask > 0:
                        val = float(pos.get("currentValue", 0))
                        if val > 0:
                            logging.info(f"Sync Found redeemable: {pos.get('title')} - Value: ${val}")
                            logging.info(f"Sync Position Data: {pos}")
                            redeemables.append({
                                "condition_id": pos.get("conditionId"),
                                "outcome_index": bitmask,
                                "payout": val
                            })
                return redeemables
    except Exception as e:
        logging.error(f"Error fetching sync redeemable positions: {e}")
    return []

async def fetch_redeemable_positions_from_api(wallet_address):
    """
    Fetches all redeemable winning positions for a user from Polymarket Data API.
    Returns: List of dicts with {'market_id': condition_id, 'outcome_index': index_set_bitmask}
    """
    if not wallet_address:
        return []
        
    url = f"https://data-api.polymarket.com/positions?user={wallet_address}"
    try:
        res = await _async_http.get(url, timeout=15)
        if res.status_code == 200:
            positions = res.json()
            logging.info(f"Retrieved {len(positions)} positions for {wallet_address}")
            redeemables = []
            for pos in positions:
                # Check if it's redeemable and has value
                is_redeemable = pos.get('redeemable', False)
                idx = pos.get('outcomeIndex')
                bitmask = 1 << int(idx) if idx is not None else 0
                
                if is_redeemable and bitmask > 0:
                    val = float(pos.get("currentValue", 0))
                    if val > 0:
                        logging.info(f"Found redeemable: {pos.get('title')} - Value: ${val}")
                        logging.info(f"Position Data: {pos}")
                        redeemables.append({
                            "condition_id": pos.get("conditionId"),
                            "outcome_index": bitmask,
                            "payout": val
                        })
            logging.info(f"Total redeemables found: {len(redeemables)}")
            return redeemables
        else:
            logging.error(f"Data API Error {res.status_code} for {wallet_address}: {res.text}")
            return []
    except Exception as e:
        logging.error(f"Error fetching redeemable positions: {e}")
    return []

def send_heartbeat(heartbeat_id="og-bot-v5.2"):
    """
    Sends a heartbeat to Polymarket to activate the 'Cancel on Disconnect' safety switch.
    Requires SDK v0.34.0+
    """
    if DRY_RUN: return True
    try:
        client = get_clob_client()
        resp = client.post_heartbeat(heartbeat_id)
        if resp.get("ok"):
            # logging.debug(f"[HEARTBEAT] Signal sent: {heartbeat_id}")
            return True
        else:
            logging.error(f"[HEARTBEAT] Failed: {resp}")
            return False
    except Exception as e:
        logging.error(f"[HEARTBEAT] Error: {e}")
        return False

async def async_send_heartbeat(heartbeat_id="og-bot-v5.2"):
    """Offloads to thread"""
    return await asyncio.to_thread(send_heartbeat, heartbeat_id)
