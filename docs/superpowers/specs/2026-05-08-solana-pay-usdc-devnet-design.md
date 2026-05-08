# Solana Pay USDC Devnet Integration — ParkMaster Bot

## Goal

Replace mock payment confirmation with real on-chain USDC payment tracking on
Solana devnet. Driver must pay before receiving access instructions.

## Scope

- Generate Solana Pay URL with valid base58 pubkey reference per booking.
- Show user two QR codes: Solana Pay link + raw recipient wallet address.
- Track payment by polling devnet RPC for the reference pubkey.
- Gate `get_access_instructions` until booking status is `paid`.
- Replace `confirm_mock_payment` with `verify_payment_onchain`.

Out of scope: refunds, multi-sig, mainnet, payer wallet on bot side (driver
sends from their own wallet — bot only watches).

## Architecture

```
Driver → Telegram bot → ADK agent → create_booking
                                       ↓
                               Solana Pay URL + reference pubkey
                                       ↓
                  Bot sends 2 QRs (Pay URL + wallet addr) + "I paid" / "Cancel"
                                       ↓
                Background asyncio watcher polls devnet RPC every 5s (10min cap)
                                       ↓
              getSignaturesForAddress(reference) → getTransaction → validate
                                       ↓
                    booking.status = 'paid' → send access instructions
```

## Components

### `payments.py`

- `USDC_DEVNET_MINT = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"` (Circle devnet USDC).
- `RPC_URL = "https://api.devnet.solana.com"` (override via env).
- `new_reference_pubkey() -> str`: random ed25519 keypair pubkey via `solders`.
- `create_solana_pay_url(recipient, amount, reference, label, message, memo) -> str`.
- `async verify_payment(reference, expected_recipient, expected_amount, mint) -> Optional[str]`:
  1. POST `getSignaturesForAddress(reference, limit=10)` to RPC.
  2. For each sig with `err is None`: `getTransaction(sig, jsonParsed, maxSupportedTransactionVersion=0)`.
  3. Diff `meta.preTokenBalances` vs `meta.postTokenBalances` for recipient ATA.
  4. Confirm delta ≥ expected_amount AND mint matches.
  5. Return signature string or `None`.

### `qr.py`

Add `make_qr_bytes(data: str) -> io.BytesIO` (existing already does this).

### `agents.py`

- `create_booking` now stores `reference_pubkey`, `recipient_wallet`,
  uses devnet mint via `payments.create_solana_pay_url`.
- Remove `confirm_mock_payment`. Add `verify_payment_onchain(booking_id)`
  tool that calls `payments.verify_payment` and updates status if paid.
- `get_access_instructions` keeps gate (`status == 'paid'`).
- Agent prompt: "Never release access instructions before
  verify_payment_onchain returns success."

### `bot_handlers.py`

- `book_<spot_id>` callback:
  - Run agent → booking created.
  - Send 2 photos:
    - Solana Pay URL QR — caption with link, amount, mint label.
    - Wallet address QR — caption with address (for manual USDC send).
  - Inline buttons: `Check payment` (`check_<id>`), `Cancel` (`cancel_<id>`).
  - Spawn `asyncio.create_task(payment_watcher(...))`.
- `payment_watcher(booking_id, chat_id, ...)`: poll every 5s, max 10min.
  On confirm: call agent with `Я оплатил booking <id>` → agent calls
  `verify_payment_onchain` → `get_access_instructions`. Send result to chat.
- `check_<id>` button: same verify call, immediate response.
- `cancel_<id>`: mark booking `cancelled`, stop watcher.

### `state.py`

Booking dict gains: `reference_pubkey`, `recipient_wallet`,
`expected_amount_lamports` (raw units, USDC has 6 decimals), `payment_signature`.

### `mock_data.py`

Replace fake `DemoOwnerWallet111...` with real devnet pubkey from env
(`DEMO_RECIPIENT_PUBKEY`). Hackathon shortcut: all spots share one wallet.

### `requirements.txt`

```
python-telegram-bot>=21
google-adk
google-genai
qrcode[pil]
python-dotenv
httpx
solders
```

## Error Handling

- RPC error → log, retry on next tick.
- Watcher timeout (10min) → mark booking `expired`, notify user.
- Amount mismatch (paid less) → log, do not mark paid.
- Cancel during watcher → check flag each tick, exit.

## Testing (manual, devnet)

1. Set env: `DEMO_RECIPIENT_PUBKEY`, `TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY`.
2. Fund a devnet wallet (Phantom/CLI) with SOL + USDC (faucet.circle.com).
3. `/start` → driver → location → book → scan Solana Pay QR with Phantom devnet.
4. Approve in wallet → bot auto-confirms in <30s → access instructions appear.
5. Verify on Solana Explorer (devnet) using returned signature.
