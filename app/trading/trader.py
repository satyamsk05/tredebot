import logging
import json
import os
import asyncio
from web3 import Web3
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType
from py_clob_client.constants import POLYGON
from app.config import (
    DRY_RUN, POLY_API_KEY, POLY_API_SECRET, POLY_PASSPHRASE, 
    POLY_PRIVATE_KEY, FUNDER_ADDRESS, WALLET_ADDRESS, RPC_URL,
    VIRTUAL_BALANCE_START
)
from app.logger import log_error, log_trade

VIRTUAL_BALANCE_FILE = "data/virtual_balance.json"
_client = None

def _get_client():
    global _client
    if _client is None:
        creds = ApiCreds(api_key=POLY_API_KEY, api_secret=POLY_API_SECRET, api_passphrase=POLY_PASSPHRASE)
        pk = POLY_PRIVATE_KEY[2:] if POLY_PRIVATE_KEY and POLY_PRIVATE_KEY.startswith("0x") else POLY_PRIVATE_KEY
        _client = ClobClient("https://clob.polymarket.com", chain_id=POLYGON, key=pk, creds=creds, signature_type=1, funder=FUNDER_ADDRESS)
    return _client

def get_balance():
    """Synchronous version for main.py"""
    try:
        w3 = Web3(Web3.HTTPProvider(RPC_URL))
        target_wallet = w3.to_checksum_address(FUNDER_ADDRESS if FUNDER_ADDRESS else WALLET_ADDRESS)
        usdc_address = w3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
        erc20_abi = [{"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"}]
        usdc_contract = w3.eth.contract(address=usdc_address, abi=erc20_abi)
        raw_balance = usdc_contract.functions.balanceOf(target_wallet).call()
        return round(raw_balance / 1_000_000, 2)
    except Exception as e:
        log_error(f"Balance fetch error: {e}")
        return 0.0

async def async_get_balance():
    """Asynchronous version using threading to avoid blocking"""
    return await asyncio.to_thread(get_balance)

def get_virtual_balance() -> float:
    if not os.path.exists(VIRTUAL_BALANCE_FILE):
        return round(float(VIRTUAL_BALANCE_START), 2)
    try:
        with open(VIRTUAL_BALANCE_FILE, "r") as f:
            data = json.load(f)
            return round(float(data.get("balance", VIRTUAL_BALANCE_START)), 2)
    except: return round(float(VIRTUAL_BALANCE_START), 2)

async def async_get_virtual_balance():
    return await asyncio.to_thread(get_virtual_balance)

def update_virtual_balance(amount_change: float):
    current_balance = get_virtual_balance()
    new_balance = round(current_balance + amount_change, 2)
    try:
        with open(VIRTUAL_BALANCE_FILE, "w") as f:
            json.dump({"balance": new_balance}, f)
    except Exception as e:
        log_error(f"Failed to update virtual balance: {e}")

async def async_update_virtual_balance(amount_change: float):
    return await asyncio.to_thread(update_virtual_balance, amount_change)

def place_bet(coin, direction, amount):
    if DRY_RUN: return True
    try:
        client = _get_client()
        order_args = OrderArgs(price=0.99, size=amount, side="BUY", token_id=coin)
        signed_order = client.create_order(order_args)
        resp = client.post_order(signed_order, OrderType.FOK)
        return resp and resp.get("success")
    except Exception as e:
        log_error(f"Trade error: {e}")
        return False

async def async_place_bet(coin, direction, amount):
    return await asyncio.to_thread(place_bet, coin, direction, amount)
