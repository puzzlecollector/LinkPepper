# backend/core/templatetags/chain.py
from django import template

register = template.Library()

_EXPLORERS = {
    "ETH": "https://etherscan.io/tx/{tx}",
    "BASE": "https://basescan.org/tx/{tx}",
    "BNB": "https://bscscan.com/tx/{tx}",
    "POL": "https://polygonscan.com/tx/{tx}",   # Polygon (PoS) / POL ticker
    "SOL": "https://solscan.io/tx/{tx}",
}

@register.simple_tag
def tx_url(network: str, txid: str) -> str:
    """
    Returns a clickable explorer URL for the given network+txid, or "" if unknown.
    """
    if not txid:
        return ""
    net = (network or "").upper()
    pattern = _EXPLORERS.get(net)
    return pattern.format(tx=txid) if pattern else ""

@register.filter
def short_tx(txid: str, keep: int = 6) -> str:
    """
    Shorten a long hash: 0x123456…cdef01  (keep=6 => 6 head / 6 tail)
    """
    if not txid:
        return ""
    if len(txid) <= (keep * 2) + 1:
        return txid
    return f"{txid[:keep]}…{txid[-keep:]}"
