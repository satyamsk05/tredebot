import os
import sys
import logging
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Polymarket Polygon Contracts
CONTRACTS = {
    "CTF_EXCHANGE": "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E",
    "NEG_RISK_EXCHANGE": "0xC5d563A36AE78145C45a50134d48A1215220f80a",
    "NEG_RISK_ADAPTER": "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296",
    "USDC_E": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
    "CTF": "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
}

ERC20_ABI = [
    {"constant": False, "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}, {"name": "_spender", "type": "address"}], "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "type": "function"}
]

ERC1155_ABI = [
    {"constant": False, "inputs": [{"name": "_operator", "type": "address"}, {"name": "_approved", "type": "bool"}], "name": "setApprovalForAll", "outputs": [], "type": "function"},
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}, {"name": "_operator", "type": "address"}], "name": "isApprovedForAll", "outputs": [{"name": "", "type": "bool"}], "type": "function"}
]

def setup_approvals():
    # Load .env from the project root (current script is in app/scripts/)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(script_dir))
    env_path = os.path.join(project_root, '.env')
    load_dotenv(env_path)
    
    rpc_url = os.getenv("RPC_URL", "https://polygon-bor-rpc.publicnode.com")
    pk = os.getenv("PRIVATE_KEY")
    
    if not pk:
        logging.error("PRIVATE_KEY not found in .env file!")
        return
    
    # Strip any possible whitespace or hidden chars
    pk = pk.strip()

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    # Inject POA middleware for Polygon
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    
    if not w3.is_connected():
        logging.error("Failed to connect to Polygon RPC!")
        return

    try:
        account = w3.eth.account.from_key(pk)
    except Exception as e:
        logging.error(f"Invalid Private Key format: {e}")
        return

    wallet_address = account.address
    config_address = os.getenv("WALLET_ADDRESS", "").strip()
    
    if config_address and config_address.lower() != wallet_address.lower():
        logging.warning(f"Configured WALLET_ADDRESS {config_address} does NOT match PK address {wallet_address}!")
        logging.info("Using PK address for approvals.")
        
    logging.info(f"Setting up approvals for wallet: {wallet_address}")

    # 1. Approve USDC.e for spending
    usdc_contract = w3.eth.contract(address=CONTRACTS["USDC_E"], abi=ERC20_ABI)
    max_approval = 2**256 - 1

    for name in ["CTF_EXCHANGE", "NEG_RISK_EXCHANGE", "NEG_RISK_ADAPTER"]:
        spender = CONTRACTS[name]
        try:
            current_allowance = usdc_contract.functions.allowance(wallet_address, spender).call()
            if current_allowance < 10**24: # Less than 1M USDC
                logging.info(f"Approving USDC.e for {name} ({spender})...")
                nonce = w3.eth.get_transaction_count(wallet_address)
                tx = usdc_contract.functions.approve(spender, max_approval).build_transaction({
                    'from': wallet_address,
                    'nonce': nonce,
                    'gas': 100000,
                    'gasPrice': w3.eth.gas_price
                })
                signed_tx = w3.eth.account.sign_transaction(tx, private_key=pk)
                tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                logging.info(f"TX Sent: {tx_hash.hex()}")
                w3.eth.wait_for_transaction_receipt(tx_hash)
                logging.info(f"Successfully approved USDC.e for {name}")
            else:
                logging.info(f"USDC.e already approved for {name}")
        except Exception as e:
            logging.error(f"Failed to approve USDC.e for {name}: {e}")

    # 2. Approve CTF (ERC1155) for trading
    ctf_contract = w3.eth.contract(address=CONTRACTS["CTF"], abi=ERC1155_ABI)
    
    for name in ["CTF_EXCHANGE", "NEG_RISK_EXCHANGE", "NEG_RISK_ADAPTER"]:
        operator = CONTRACTS[name]
        try:
            is_approved = ctf_contract.functions.isApprovedForAll(wallet_address, operator).call()
            if not is_approved:
                logging.info(f"Setting setApprovalForAll on CTF for {name} ({operator})...")
                nonce = w3.eth.get_transaction_count(wallet_address)
                tx = ctf_contract.functions.setApprovalForAll(operator, True).build_transaction({
                    'from': wallet_address,
                    'nonce': nonce,
                    'gas': 100000,
                    'gasPrice': w3.eth.gas_price
                })
                signed_tx = w3.eth.account.sign_transaction(tx, private_key=pk)
                tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
                logging.info(f"TX Sent: {tx_hash.hex()}")
                w3.eth.wait_for_transaction_receipt(tx_hash)
                logging.info(f"Successfully set ApprovalForAll for {name}")
            else:
                logging.info(f"CTF already approved for {name}")
        except Exception as e:
            logging.error(f"Failed to set ApprovalForAll for {name}: {e}")

    logging.info("All necessary approvals are checked and set!")

if __name__ == "__main__":
    setup_approvals()
