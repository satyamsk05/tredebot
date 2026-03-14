
import os
import logging
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds
from py_clob_client.constants import POLYGON

# Configure logging
logging.basicConfig(level=logging.INFO)

def onboard():
    load_dotenv(override=True)
    pk = os.getenv("PRIVATE_KEY") or os.getenv("POLY_PRIVATE_KEY")
    funder = os.getenv("POLY_FUNDER") or os.getenv("FUNDER_ADDRESS")
    
    if not pk:
        print("❌ Error: PRIVATE_KEY not found in .env!")
        return

    # EOA (Type 1) signatures need 0x prefix for Web3 but sometimes not for the client initialization
    # py-clob-client uses 'key' as the hex string.
    raw_pk = pk[2:] if pk.startswith("0x") else pk

    print("🚀 Attempting to Onboard & Create CLOB Trading Keys...")
    
    # Initialize client with just the private key (L1 Auth)
    client = ClobClient(
        "https://clob.polymarket.com",
        chain_id=POLYGON,
        key=raw_pk,
        signature_type=1,
        funder=funder
    )

    try:
        # Try to derive existing API keys
        print("🔍 Checking for existing Trading keys...")
        derived_creds = client.derive_api_key()
        
        print("\n✅ SUCCESS! YOUR TRADING KEYS ARE:")
        print("====================================")
        print(f"POLY_API_KEY={derived_creds.api_key}")
        print(f"POLY_API_SECRET={derived_creds.api_secret}")
        print(f"POLY_API_PASSPHRASE={derived_creds.api_passphrase}")
        print("====================================")
        print("\n👉 Inhe .env mein update karein aur bot restart karein.")

    except Exception as e:
        print(f"\n❌ Derivation Failed: {e}")
        print("Attempting to CREATE new keys as fallback...")
        try:
            new_creds = client.create_api_key()
            print("\n✅ SUCCESS! NEW KEYS CREATED.")
            # ... print keys ...
        except Exception as e2:
            print(f"❌ Fallback Create also failed: {e2}")

if __name__ == "__main__":
    onboard()
