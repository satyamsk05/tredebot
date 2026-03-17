import logging
import json
import os
import asyncio
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType
from py_clob_client.constants import POLYGON
from app.config import (
    DRY_RUN, POLY_API_KEY, POLY_API_SECRET, POLY_PASSPHRASE, 
    POLY_PRIVATE_KEY, FUNDER_ADDRESS, WALLET_ADDRESS, RPC_URL,
    VIRTUAL_BALANCE_START, BUILDER_API_KEY, BUILDER_SECRET, 
    BUILDER_PASSPHRASE, RELAYER_URL
)
import requests
import time
import hmac
import hashlib
from app.logger import log_info, log_success, log_warning, log_error, log_trade

VIRTUAL_BALANCE_FILE = "data/virtual_balance.json"
_client = None

def _get_client():
    global _client
    if _client is None:
        creds = ApiCreds(api_key=POLY_API_KEY, api_secret=POLY_API_SECRET, api_passphrase=POLY_PASSPHRASE)
        pk = POLY_PRIVATE_KEY[2:] if POLY_PRIVATE_KEY and POLY_PRIVATE_KEY.startswith("0x") else POLY_PRIVATE_KEY
        pk = POLY_PRIVATE_KEY[2:] if POLY_PRIVATE_KEY and POLY_PRIVATE_KEY.startswith("0x") else POLY_PRIVATE_KEY
        sig_type = 2 if FUNDER_ADDRESS else 1
        _client = ClobClient("https://clob.polymarket.com", chain_id=POLYGON, key=pk, creds=creds, signature_type=sig_type, funder=FUNDER_ADDRESS)
    return _client

# Network Settings
RPC_URLS = [
    os.getenv("RPC_URL", "https://polygon-rpc.com"),
    "https://polygon-bor.publicnode.com",
    "https://1rpc.io/matic",
    "https://rpc.ankr.com/polygon"
]

def get_w3():
    """Tries multiple RPCs to find a working one."""
    for url in RPC_URLS:
        try:
            w3 = Web3(Web3.HTTPProvider(url))
            # Inject POA middleware for Polygon (Bor)
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            if w3.is_connected():
                return w3, url
        except:
            continue
    return None, None

def get_balance():
    """Synchronous version for main.py"""
    try:
        w3, url = get_w3()
        if not w3: return 0.0
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

def get_matic_balance():
    """Fetches the MATIC balance of the signer wallet."""
    try:
        w3, url = get_w3()
        if not w3: return 0.0
        pk = POLY_PRIVATE_KEY
        if not pk: return 0.0
        if not pk.startswith("0x"): pk = "0x" + pk
        account = w3.eth.account.from_key(pk)
        balance_wei = w3.eth.get_balance(account.address)
        return round(w3.from_wei(balance_wei, 'ether'), 4)
    except Exception as e:
        log_error(f"MATIC balance fetch error: {e}")
        return 0.0

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

CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
USDC_NATIVE = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"

def redeem_winnings(condition_id, outcome_index, wallet_address=None):
    """
    Programmatically redeems winning positions using Web3.py.
    Supports both direct EOA redemptions and ProxyWallet redemptions.
    """
    if DRY_RUN:
        log_trade(f"[DRY RUN] Redeeming condition {condition_id[:10]}... (Index: {outcome_index})")
        return True
    
    try:
        w3, url = get_w3()
        if not w3:
            log_error("Redemption failed: No working RPC found")
            return False
            
        logging.info(f"Using RPC: {url} for redemption")
        
        # Ensure private key is valid
        pk = POLY_PRIVATE_KEY
        if not pk:
            log_error("Redemption failed: POLY_PRIVATE_KEY is missing in .env")
            return False
        if not pk.startswith("0x"): pk = "0x" + pk
        
        account = w3.eth.account.from_key(pk)
        signer_address = w3.to_checksum_address(account.address)
        
        # Ensure condition_id is bytes32
        if isinstance(condition_id, str):
            if not condition_id.startswith("0x"):
                condition_id = "0x" + condition_id
            if len(condition_id) != 66: # 0x + 64 hex chars
                log_error(f"Redemption failed: condition_id {condition_id} is not 32 bytes")
                return False

        # ABI for Redeemer contract
        redeemer_abi = [{
            "inputs": [
                {"name": "collateralToken", "type": "address"},
                {"name": "parentCollectionId", "type": "bytes32"},
                {"name": "conditionId", "type": "bytes32"},
                {"name": "indexSets", "type": "uint256[]"}
            ],
            "name": "redeem",
            "outputs": [],
            "stateMutability": "nonpayable",
            "type": "function"
        }]
        
        redeemer_contract = w3.eth.contract(address=w3.to_checksum_address(CTF_ADDRESS), abi=redeemer_abi)
        
        # Index sets should be the passed outcome_index (bitmask)
        index_sets = [outcome_index] if isinstance(outcome_index, int) else outcome_index
        if not isinstance(index_sets, list): index_sets = [index_sets]
        
        parent_id = "0x" + "00" * 32
        
        log_info(f"Redemption Params: Cond: {condition_id[:10]}... IndexSets: {index_sets}")

        # Prepare the call data for the CTF contract
        def get_calldata(token_addr):
            ctf_abi = [{"constant": False, "inputs": [{"name": "collateralToken", "type": "address"}, {"name": "parentCollectionId", "type": "bytes32"}, {"name": "conditionId", "type": "bytes32"}, {"name": "indexSets", "type": "uint256[]"}], "name": "redeemPositions", "outputs": [], "payable": False, "stateMutability": "nonpayable", "type": "function"}]
            ctf_contract = w3.eth.contract(address=w3.to_checksum_address(CTF_ADDRESS), abi=ctf_abi)
            return ctf_contract.encode_abi("redeemPositions", [
                w3.to_checksum_address(token_addr), parent_id, condition_id, index_sets
            ])

        def build_and_send(current_nonce, token_addr):
            redeem_call_data = get_calldata(token_addr)
            
            # Check if we need to go through a contract (Safe or Proxy)
            if wallet_address and w3.to_checksum_address(wallet_address) != signer_address:
                proxy_wallet_address = w3.to_checksum_address(wallet_address)
                
                # Check if it's a contract
                code = w3.eth.get_code(proxy_wallet_address)
                if not code or code == b'\x00' or code == '0x':
                    log_warning(f"Target {proxy_wallet_address[:10]} is an EOA. Signer must be the owner.")
                else:
                    # 1. Detection: Is it a Gnosis Safe?
                    is_safe = False
                    try:
                        # Safes have a VERSION() function
                        safe_ver_abi = [{"constant":True,"inputs":[],"name":"VERSION","outputs":[{"name":"","type":"string"}],"payable":False,"stateMutability":"view","type":"function"}]
                        safe_ver_contract = w3.eth.contract(address=proxy_wallet_address, abi=safe_ver_abi)
                        ver = safe_ver_contract.functions.VERSION().call()
                        if ver: 
                            is_safe = True
                            log_info(f"Detected Gnosis Safe (v{ver}) at {proxy_wallet_address[:10]}")
                    except:
                        pass
                        
                    if is_safe:
                        # Gnosis Safe execTransaction
                        safe_abi = [{"inputs": [{"name": "to", "type": "address"}, {"name": "value", "type": "uint256"}, {"name": "data", "type": "bytes"}, {"name": "operation", "type": "uint8"}, {"name": "safeTxGas", "type": "uint256"}, {"name": "baseGas", "type": "uint256"}, {"name": "gasPrice", "type": "uint256"}, {"name": "gasToken", "type": "address"}, {"name": "refundReceiver", "type": "address"}, {"name": "signatures", "type": "bytes"}], "name": "execTransaction", "outputs": [{"name": "success", "type": "bool"}], "stateMutability": "payable", "type": "function"}]
                        safe_contract = w3.eth.contract(address=proxy_wallet_address, abi=safe_abi)
                        
                        # Owner signature shortcut (v=1)
                        signature = "0x" + "00" * 12 + signer_address[2:].lower() + "00" * 32 + "01"
                        
                        base_fee = w3.eth.get_block('latest')['baseFeePerGas']
                        max_priority_fee = w3.to_wei('50', 'gwei')
                        max_fee = int(base_fee * 3 + max_priority_fee)
                        
                        tx = safe_contract.functions.execTransaction(
                            w3.to_checksum_address(CTF_ADDRESS),
                            0, bytes.fromhex(redeem_call_data[2:]), 0, 0, 0, 0, 
                            "0x0000000000000000000000000000000000000000", "0x0000000000000000000000000000000000000000",
                            bytes.fromhex(signature[2:])
                        ).build_transaction({
                            'from': signer_address,
                            'nonce': current_nonce,
                            'gas': 450000,
                            'maxFeePerGas': max_fee,
                            'maxPriorityFeePerGas': max_priority_fee,
                            'chainId': 137
                        })
                        signed_tx = w3.eth.account.sign_transaction(tx, private_key=pk)
                        return w3.eth.send_raw_transaction(signed_tx.raw_transaction)

                    else:
                        # 2. Try Polymarket Proxy Wallet (Magic/Email)
                        try:
                            proxy_abi = [{"constant": False, "inputs": [{"components": [{"name": "typeCode", "type": "uint8"}, {"name": "to", "type": "address"}, {"name": "value", "type": "uint256"}, {"name": "data", "type": "bytes"}], "name": "calls", "type": "tuple[]"}], "name": "proxy", "outputs": [{"name": "returnValues", "type": "bytes[]"}], "payable": True, "stateMutability": "payable", "type": "function"}]
                            proxy_contract = w3.eth.contract(address=proxy_wallet_address, abi=proxy_abi)
                            proxy_call = (1, w3.to_checksum_address(CTF_ADDRESS), 0, bytes.fromhex(redeem_call_data[2:]))
                            
                            base_fee = w3.eth.get_block('latest')['baseFeePerGas']
                            max_priority_fee = w3.to_wei('50', 'gwei') 
                            max_fee = int(base_fee * 3 + max_priority_fee)
                            
                            tx = proxy_contract.functions.proxy([proxy_call]).build_transaction({
                                'from': signer_address,
                                'nonce': current_nonce,
                                'gas': 350000,
                                'maxFeePerGas': max_fee,
                                'maxPriorityFeePerGas': max_priority_fee,
                                'chainId': 137
                            })
                            signed_tx = w3.eth.account.sign_transaction(tx, private_key=pk)
                            return w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                        except Exception as pe:
                            log_info(f"Proxy attempt failed: {pe}. Trying direct call.")

            # Direct EOA fallback
            base_fee = w3.eth.get_block('latest')['baseFeePerGas']
            max_priority_fee = w3.to_wei('50', 'gwei')
            max_fee = int(base_fee * 3 + max_priority_fee)
            
            ctf_abi_direct = [{"constant": False, "inputs": [{"name": "collateralToken", "type": "address"}, {"name": "parentCollectionId", "type": "bytes32"}, {"name": "conditionId", "type": "bytes32"}, {"name": "indexSets", "type": "uint256[]"}], "name": "redeemPositions", "outputs": [], "payable": False, "stateMutability": "nonpayable", "type": "function"}]
            ctf_contract_direct = w3.eth.contract(address=w3.to_checksum_address(CTF_ADDRESS), abi=ctf_abi_direct)

            tx = ctf_contract_direct.functions.redeemPositions(
                w3.to_checksum_address(token_addr), parent_id, condition_id, index_sets
            ).build_transaction({
                'from': signer_address,
                'nonce': current_nonce,
                'gas': 250000,
                'maxFeePerGas': max_fee,
                'maxPriorityFeePerGas': max_priority_fee,
                'chainId': 137
            })
            
            signed_tx = w3.eth.account.sign_transaction(tx, private_key=pk)
            return w3.eth.send_raw_transaction(signed_tx.raw_transaction)

        # Execution Logic with Nonce and Token Retry
        nonce = w3.eth.get_transaction_count(signer_address, 'pending')
        
        for token_name, token_addr in [("USDC.e", USDC_E), ("USDC Native", USDC_NATIVE)]:
            log_info(f"Attempting redemption with {token_name} ({token_addr[:10]}...)")
            try:
                tx_hash = build_and_send(nonce, token_addr)
                if tx_hash is None: return False
                
                log_info(f"TX Sent: {tx_hash.hex()[:10]}... (Waiting 300s...)")
                receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
                
                if receipt.status == 1:
                    gas_matic = (receipt.gasUsed * receipt.effectiveGasPrice) / 1e18
                    log_success(f"TX Confirmed! Gas: {gas_matic:.4f} MATIC")
                    return True
                else:
                    log_warning(f"TX Reverted with {token_name}. Retrying with next token...")
                    nonce += 1 # Increment nonce for retry
            except Exception as e:
                if "underpriced" in str(e).lower() or "nonce too low" in str(e).lower():
                    nonce += 1
                    log_warning(f"Nonce issue, retrying...")
                else:
                    log_error(f"Redemption with {token_name} failed: {e}")
        
        return False
        
    except Exception as e:
        log_error(f"Redemption execution failed: {str(e)}")
        return False

def gasless_redeem(condition_id, outcome_bitmask, wallet_address):
    """
    Official Gasless Redemption using Builder API and Relayer.
    Zero-gas for user, paid by Polymarket Builder program.
    """
    api_key = BUILDER_API_KEY
    api_secret = BUILDER_SECRET
    api_passphrase = BUILDER_PASSPHRASE

    if not api_key or not api_secret or not api_passphrase:
        log_warning("Gasless Redeem: Builder keys missing. Falling back to local on-chain.")
        return False

    if DRY_RUN:
        log_trade(f"[DRY RUN] Gasless Redeem: {condition_id[:10]}... (Mask: {outcome_bitmask})")
        return True

    try:
        w3, url = get_w3()
        if not w3: return False

        index_sets = [outcome_bitmask] if isinstance(outcome_bitmask, int) else outcome_bitmask
        if not isinstance(index_sets, list): index_sets = [index_sets]
        parent_id = "0x" + "00" * 32
        
        ctf_abi = [{"constant": False, "inputs": [{"name": "collateralToken", "type": "address"}, {"name": "parentCollectionId", "type": "bytes32"}, {"name": "conditionId", "type": "bytes32"}, {"name": "indexSets", "type": "uint256[]"}], "name": "redeemPositions", "outputs": [], "payable": False, "stateMutability": "nonpayable", "type": "function"}]
        ctf_contract = w3.eth.contract(address=w3.to_checksum_address(CTF_ADDRESS), abi=ctf_abi)
        
        redeem_call_data = ctf_contract.encode_abi("redeemPositions", [
            w3.to_checksum_address(USDC_E), parent_id, condition_id, index_sets
        ])

        payload = {
            "transactions": [{
                "to": w3.to_checksum_address(CTF_ADDRESS),
                "data": redeem_call_data,
                "value": "0"
            }],
            "description": f"Gasless redeem for {condition_id[:10]}"
        }

        # Authentication 
        timestamp = str(int(time.time() * 1000))
        body = json.dumps(payload, separators=(',', ':'))
        msg = f"{timestamp}POST/execute{body}"
        
        signature = hmac.new(
            api_secret.encode('utf-8'),
            msg.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        headers = {
            "POLY-API-KEY": api_key,
            "POLY-API-SECRET": api_secret,
            "POLY-API-PASSPHRASE": api_passphrase,
            "POLY-API-TIMESTAMP": timestamp,
            "POLY-API-SIGNATURE": signature,
            "Content-Type": "application/json"
        }

        # Try multiple common relayer endpoints
        endpoints = [
            f"{RELAYER_URL.rstrip('/')}/execute",
            "https://relayer-v2.polymarket.com/execute",
            "https://relayer-v2.polymarket.com/"
        ]
        
        for endpoint in endpoints:
            log_info(f"Relaying Gasless Redeem to {endpoint}...")
            try:
                resp = requests.post(endpoint, json=payload, headers=headers, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    tx_hash = data.get("transactionHash")
                    log_success(f"Gasless redemption successful! TX: {tx_hash}")
                    return True
                else:
                    log_warning(f"Relayer {endpoint} rejected with {resp.status_code}: {resp.text[:100]}")
            except Exception as e:
                log_warning(f"Relayer {endpoint} error: {e}")
        
        return False

    except Exception as e:
        log_error(f"Gasless redemption crash: {e}")
        return False

async def async_gasless_redeem(condition_id, outcome_index, wallet_address):
    return await asyncio.to_thread(gasless_redeem, condition_id, outcome_index, wallet_address)
