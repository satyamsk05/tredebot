from app.config import DRY_RUN, POLY_API_KEY, POLY_API_SECRET, POLY_PASSPHRASE, POLY_PRIVATE_KEY, FUNDER_ADDRESS, WALLET_ADDRESS, RPC_URL
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType
from py_clob_client.constants import POLYGON
import logging
from web3 import Web3
from app.logger import log_error, log_trade

# Lazy-initialized CLOB client
_client = None

def _get_client():
    global _client
    if _client is None:
        creds = ApiCreds(
            api_key=POLY_API_KEY,
            api_secret=POLY_API_SECRET,
            api_passphrase=POLY_PASSPHRASE
        )
        pk = POLY_PRIVATE_KEY
        if pk and pk.startswith("0x"):
            pk = pk[2:]
            
        _client = ClobClient(
            "https://clob.polymarket.com",
            chain_id=POLYGON,
            key=pk,
            creds=creds,
            signature_type=1,
            funder=FUNDER_ADDRESS
        )
    return _client

def get_balance():
    """Fetch USDC.e balance from the on-chain Proxy/Funder Wallet."""
    try:
        w3 = Web3(Web3.HTTPProvider(RPC_URL))
        # Polymarket uses the Funder address (proxy wallet) for balances
        target_wallet = w3.to_checksum_address(FUNDER_ADDRESS if FUNDER_ADDRESS else WALLET_ADDRESS)
        
        # USDC.e contract on Polygon
        usdc_address = w3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
        
        erc20_abi = [
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function",
            }
        ]
        
        usdc_contract = w3.eth.contract(address=usdc_address, abi=erc20_abi)
        raw_balance = usdc_contract.functions.balanceOf(target_wallet).call()
        
        # USDC has 6 decimals
        val = round(raw_balance / 1_000_000, 2)
        return val
    except Exception as e:
        import traceback
        log_error(f"Balance fetch error: {e}")
        return "Error"

import json
import os
from app.config import VIRTUAL_BALANCE_START

VIRTUAL_BALANCE_FILE = "data/virtual_balance.json"

def get_virtual_balance() -> float:
    """Fetch the persistent virtual balance for DRY RUN mode."""
    if not os.path.exists(VIRTUAL_BALANCE_FILE):
        return round(float(VIRTUAL_BALANCE_START), 2)
    try:
        with open(VIRTUAL_BALANCE_FILE, "r") as f:
            data = json.load(f)
            return round(float(data.get("balance", VIRTUAL_BALANCE_START)), 2)
    except Exception:
        return round(float(VIRTUAL_BALANCE_START), 2)

def update_virtual_balance(amount_change: float):
    """Update the virtual balance by a given positive or negative amount."""
    current_balance = get_virtual_balance()
    new_balance = round(current_balance + amount_change, 2)
    try:
        with open(VIRTUAL_BALANCE_FILE, "w") as f:
            json.dump({"balance": new_balance}, f)
        log_info(f"[VIRTUAL PnL] {amount_change:+.2f} USD -> New Balance: ${new_balance:.2f}")
    except Exception as e:
        log_error(f"Failed to update virtual balance: {e}")
        
def place_bet(coin, direction, amount):
    if DRY_RUN:
        log_trade(f"[DRY RUN] {coin} {direction} bet {amount}")
        return True

    try:
        client = _get_client()
        order_args = OrderArgs(
            price=0.99,
            size=amount,
            side="BUY",
            token_id=coin
        )
        signed_order = client.create_order(order_args)
        resp = client.post_order(signed_order, OrderType.FOK)
        if resp and resp.get("success"):
            logging.info(f"Order placed: {resp.get('orderID')}")
            return True
        else:
            log_error(f"Trade error: {resp.get('errorMsg', resp)}")
            return False
    except Exception as e:
        log_error(f"Trade error: {e}")
        return False
