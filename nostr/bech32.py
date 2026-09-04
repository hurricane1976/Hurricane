"""Minimal bech32 (BIP-173) encode/decode for Nostr npub/nsec/note ids.

Nostr NIP-19 uses plain bech32 (not bech32m). This is the reference
implementation from BIP-173, trimmed to what we need: converting a 32-byte
key to/from an `npub1...` / `nsec1...` string.
"""

CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _polymod(values):
    generator = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for value in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ value
        for i in range(5):
            chk ^= generator[i] if ((top >> i) & 1) else 0
    return chk


def _hrp_expand(hrp):
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def _verify_checksum(hrp, data):
    return _polymod(_hrp_expand(hrp) + data) == 1


def _create_checksum(hrp, data):
    values = _hrp_expand(hrp) + data
    polymod = _polymod(values + [0, 0, 0, 0, 0, 0]) ^ 1
    return [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]


def _convertbits(data, frombits, tobits, pad=True):
    acc = 0
    bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    max_acc = (1 << (frombits + tobits - 1)) - 1
    for value in data:
        if value < 0 or (value >> frombits):
            return None
        acc = ((acc << frombits) | value) & max_acc
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad:
        if bits:
            ret.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
        return None
    return ret


def encode(hrp, data_bytes):
    """hrp e.g. 'npub', data_bytes = 32 raw bytes -> 'npub1...' string."""
    data = _convertbits(list(data_bytes), 8, 5)
    combined = data + _create_checksum(hrp, data)
    return hrp + "1" + "".join(CHARSET[d] for d in combined)


def decode(expected_hrp, bech):
    """'npub1...' -> 32 raw bytes (or raises ValueError)."""
    if bech.lower() != bech and bech.upper() != bech:
        raise ValueError("mixed case")
    bech = bech.lower()
    pos = bech.rfind("1")
    if pos < 1 or pos + 7 > len(bech):
        raise ValueError("bad separator position")
    hrp = bech[:pos]
    if hrp != expected_hrp:
        raise ValueError(f"expected hrp {expected_hrp!r}, got {hrp!r}")
    if any(c not in CHARSET for c in bech[pos + 1:]):
        raise ValueError("bad char")
    data = [CHARSET.find(c) for c in bech[pos + 1:]]
    if not _verify_checksum(hrp, data):
        raise ValueError("bad checksum")
    decoded = _convertbits(data[:-6], 5, 8, False)
    if decoded is None:
        raise ValueError("bad padding")
    return bytes(decoded)
