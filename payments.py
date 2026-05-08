import urllib.parse

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

def create_solana_pay_url(recipient: str, amount: float, reference: str, booking_id: str) -> str:
    """Creates a Solana Pay URL."""
    params = {
        "amount": f"{amount:.2f}",
        "spl-token": USDC_MINT,
        "reference": reference,
        "label": "ParkMaster",
        "message": "Parking booking deposit",
        "memo": f"booking_{booking_id}"
    }
    
    query = urllib.parse.urlencode(params)
    return f"solana:{recipient}?{query}"
