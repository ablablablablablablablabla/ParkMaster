"""Solana Pay USDC devnet integration.

- Solana Pay URL spec: https://docs.solanapay.com/spec
- Devnet USDC mint (Circle): 4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU
- Reference must be a base58 pubkey; included as a read-only account in the
  payment tx so we can find the signature via getSignaturesForAddress.
"""

import os
import urllib.parse
from typing import Optional

import httpx
from solders.keypair import Keypair

USDC_DEVNET_MINT = os.getenv("USDC_MINT", "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU")
USDC_DECIMALS = 6
RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.devnet.solana.com")


def new_reference_pubkey() -> str:
    """Generate a random ed25519 pubkey (base58) for use as Solana Pay reference."""
    return str(Keypair().pubkey())


def create_solana_pay_url(
    recipient: str,
    amount: float,
    reference: str,
    booking_id: str,
    label: str = "ParkMaster",
    message: str = "Parking booking deposit",
    mint: str = USDC_DEVNET_MINT,
) -> str:
    params = {
        "amount": f"{amount:.2f}",
        "spl-token": mint,
        "reference": reference,
        "label": label,
        "message": message,
        "memo": f"booking_{booking_id}",
    }
    query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    return f"solana:{recipient}?{query}"


async def _rpc(method: str, params: list) -> dict:
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            RPC_URL,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        )
        r.raise_for_status()
        return r.json()


async def _check_tx_for_payment(sig: str, expected_recipient: str, expected_amount: float, mint: str) -> bool:
    """Return True if the tx contains an SPL transfer >= expected_amount to expected_recipient."""
    try:
        tx_resp = await _rpc(
            "getTransaction",
            [sig, {"encoding": "jsonParsed", "commitment": "confirmed", "maxSupportedTransactionVersion": 0}],
        )
    except Exception as e:
        print(f"[verify_payment] RPC error fetching tx {sig}: {e}")
        return False

    tx = tx_resp.get("result")
    if not tx or not tx.get("meta") or tx["meta"].get("err"):
        return False

    meta = tx["meta"]
    expected_raw = int(round(expected_amount * (10 ** USDC_DECIMALS)))
    pre = {
        (b["owner"], b["mint"]): int(b["uiTokenAmount"]["amount"])
        for b in meta.get("preTokenBalances", [])
        if "owner" in b and "mint" in b
    }
    post = {
        (b["owner"], b["mint"]): int(b["uiTokenAmount"]["amount"])
        for b in meta.get("postTokenBalances", [])
        if "owner" in b and "mint" in b
    }
    key = (expected_recipient, mint)
    delta = post.get(key, 0) - pre.get(key, 0)
    return delta >= expected_raw


async def _get_recipient_ata(owner: str, mint: str) -> Optional[str]:
    """Resolve the owner's ATA pubkey for a given mint via RPC."""
    try:
        resp = await _rpc(
            "getTokenAccountsByOwner",
            [owner, {"mint": mint}, {"encoding": "jsonParsed"}],
        )
        accounts = (resp.get("result") or {}).get("value") or []
        if accounts:
            return accounts[0]["pubkey"]
    except Exception as e:
        print(f"[verify_payment] RPC error getting ATA: {e}")
    return None


async def verify_payment(
    reference: str,
    expected_recipient: str,
    expected_amount: float,
    mint: str = USDC_DEVNET_MINT,
    created_after: float = 0.0,
) -> Optional[str]:
    """Return tx signature if a matching payment is found on-chain, else None.

    First checks by reference pubkey (Solana Pay QR scan path).
    Falls back to scanning recipient's ATA for recent matching transfers
    (manual transfer path — no reference in tx accounts).
    """
    # --- reference-based lookup (Solana Pay QR scan) ---
    try:
        sigs_resp = await _rpc("getSignaturesForAddress", [reference, {"limit": 10}])
        sigs = sigs_resp.get("result") or []
        for entry in sigs:
            sig = entry.get("signature")
            if entry.get("err") is not None:
                continue
            if await _check_tx_for_payment(sig, expected_recipient, expected_amount, mint):
                return sig
    except Exception as e:
        print(f"[verify_payment] reference lookup error: {e}")

    # --- ATA fallback (manual transfer, no reference in tx) ---
    ata = await _get_recipient_ata(expected_recipient, mint)
    if not ata:
        return None

    try:
        sigs_resp = await _rpc("getSignaturesForAddress", [ata, {"limit": 20}])
        sigs = sigs_resp.get("result") or []
        for entry in sigs:
            sig = entry.get("signature")
            if entry.get("err") is not None:
                continue
            # skip txs that happened before this booking was created
            if created_after and (entry.get("blockTime") or 0) < created_after:
                continue
            if await _check_tx_for_payment(sig, expected_recipient, expected_amount, mint):
                return sig
    except Exception as e:
        print(f"[verify_payment] ATA fallback error: {e}")

    return None
