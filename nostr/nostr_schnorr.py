"""Pure-Python BIP-340 Schnorr signatures over secp256k1.

Nostr events are identified by `id = sha256(serialized event)` and authorized
by a BIP-340 Schnorr signature over that id -- NOT the ECDSA this box's
`cryptography` library already does for ECDH (used in nostr_keygen.py /
nostr_listen.py's NIP-04 decrypt). `cryptography` has no Schnorr/secp256k1-
Schnorr primitive, so this is a small vendored reference implementation
(standard affine-coordinate double-and-add; fine at this call volume -- a
handful of signs/verifies per waking, not a hot loop).

Self-tests against the official BIP-340 test vector on import-as-main. No
network use, no relay interaction -- this module only proves the math is
right. Actually publishing anything is a separate, later decision.

    nostr/.venv/bin/python nostr/nostr_schnorr.py     # runs the self-test
"""
import hashlib
import secrets

# secp256k1 domain parameters
P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
G = (GX, GY)


def _mod_inv(a, m):
    return pow(a, m - 2, m)


def point_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % P == 0:
        return None
    if p1 == p2:
        lam = (3 * x1 * x1 * _mod_inv(2 * y1, P)) % P
    else:
        lam = ((y2 - y1) * _mod_inv((x2 - x1) % P, P)) % P
    x3 = (lam * lam - x1 - x2) % P
    y3 = (lam * (x1 - x3) - y1) % P
    return (x3, y3)


def point_mul(pt, k):
    r = None
    addend = pt
    while k:
        if k & 1:
            r = point_add(r, addend)
        addend = point_add(addend, addend)
        k >>= 1
    return r


def bytes_from_int(x):
    return x.to_bytes(32, "big")


def bytes_from_point(pt):
    return bytes_from_int(pt[0])


def tagged_hash(tag, msg):
    th = hashlib.sha256(tag.encode()).digest()
    return hashlib.sha256(th + th + msg).digest()


def lift_x(x):
    """x-only pubkey -> the even-y point on the curve, or None if invalid."""
    if x >= P:
        return None
    y_sq = (pow(x, 3, P) + 7) % P
    y = pow(y_sq, (P + 1) // 4, P)
    if pow(y, 2, P) != y_sq:
        return None
    if y % 2 != 0:
        y = P - y
    return (x, y)


def pubkey_from_privkey(seckey_int):
    """32-byte x-only pubkey for a given private key integer."""
    pt = point_mul(G, seckey_int)
    return bytes_from_point(pt)


def schnorr_sign(msg32, seckey_int, aux_rand32=None):
    """BIP-340 sign. msg32 must be exactly 32 bytes (Nostr: the event id)."""
    if not (1 <= seckey_int <= N - 1):
        raise ValueError("private key out of range")
    if aux_rand32 is None:
        aux_rand32 = secrets.token_bytes(32)
    p_pt = point_mul(G, seckey_int)
    d = seckey_int if p_pt[1] % 2 == 0 else N - seckey_int
    t = bytes(a ^ b for a, b in zip(bytes_from_int(d), tagged_hash("BIP0340/aux", aux_rand32)))
    rand = tagged_hash("BIP0340/nonce", t + bytes_from_point(p_pt) + msg32)
    k0 = int.from_bytes(rand, "big") % N
    if k0 == 0:
        raise ValueError("bad nonce, retry with different aux_rand")
    r_pt = point_mul(G, k0)
    k = k0 if r_pt[1] % 2 == 0 else N - k0
    e = int.from_bytes(
        tagged_hash("BIP0340/challenge", bytes_from_point(r_pt) + bytes_from_point(p_pt) + msg32), "big"
    ) % N
    sig = bytes_from_point(r_pt) + bytes_from_int((k + e * d) % N)
    return sig


def schnorr_verify(msg32, pubkey_x32, sig64):
    p_pt = lift_x(int.from_bytes(pubkey_x32, "big"))
    if p_pt is None:
        return False
    r = int.from_bytes(sig64[:32], "big")
    s = int.from_bytes(sig64[32:], "big")
    if r >= P or s >= N:
        return False
    e = int.from_bytes(tagged_hash("BIP0340/challenge", sig64[:32] + pubkey_x32 + msg32), "big") % N
    r_pt = point_add(point_mul(G, s), point_mul(p_pt, (N - e) % N))
    if r_pt is None or r_pt[1] % 2 != 0 or r_pt[0] != r:
        return False
    return True


# Official BIP-340 test vectors, indices 0-14 (bip-340/test-vectors.csv), the
# ones with a fixed 32-byte message -- exactly Nostr's use (msg = event id).
# Fetched from https://github.com/bitcoin/bips master, 2026-09-04, and
# embedded here so the self-test needs no network. Indices 15-18 (variable-
# length messages) are out of scope: Nostr always signs a 32-byte id.
# Columns: seckey (or "" if sign not tested), pubkey, aux_rand (or ""), msg,
# sig, expected verify result, comment.
_BIP340_VECTORS = [
    ("0000000000000000000000000000000000000000000000000000000000000003", "F9308A019258C31049344F85F89D5229B531C845836F99B08601F113BCE036F9", "0000000000000000000000000000000000000000000000000000000000000000", "0000000000000000000000000000000000000000000000000000000000000000", "E907831F80848D1069A5371B402410364BDF1C5F8307B0084C55F1CE2DCA821525F66A4A85EA8B71E482A74F382D2CE5EBEEE8FDB2172F477DF4900D310536C0", True),
    ("B7E151628AED2A6ABF7158809CF4F3C762E7160F38B4DA56A784D9045190CFEF", "DFF1D77F2A671C5F36183726DB2341BE58FEAE1DA2DECED843240F7B502BA659", "0000000000000000000000000000000000000000000000000000000000000001", "243F6A8885A308D313198A2E03707344A4093822299F31D0082EFA98EC4E6C89", "6896BD60EEAE296DB48A229FF71DFE071BDE413E6D43F917DC8DCF8C78DE33418906D11AC976ABCCB20B091292BFF4EA897EFCB639EA871CFA95F6DE339E4B0A", True),
    ("C90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74020BBEA63B14E5C9", "DD308AFEC5777E13121FA72B9CC1B7CC0139715309B086C960E18FD969774EB8", "C87AA53824B4D7AE2EB035A2B5BBBCCC080E76CDC6D1692C4B0B62D798E6D906", "7E2D58D8B3BCDF1ABADEC7829054F90DDA9805AAB56C77333024B9D0A508B75C", "5831AAEED7B44BB74E5EAB94BA9D4294C49BCF2A60728D8B4C200F50DD313C1BAB745879A5AD954A72C45A91C3A51D3C7ADEA98D82F8481E0E1E03674A6F3FB7", True),
    ("0B432B2677937381AEF05BB02A66ECD012773062CF3FA2549E44F58ED2401710", "25D1DFF95105F5253C4022F628A996AD3A0D95FBF21D468A1B33F8C160D8F517", "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF", "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF", "7EB0509757E246F19449885651611CB965ECC1A187DD51B64FDA1EDC9637D5EC97582B9CB13DB3933705B32BA982AF5AF25FD78881EBB32771FC5922EFC66EA3", True),
    ("", "D69C3509BB99E412E68B0FE8544E72837DFA30746D8BE2AA65975F29D22DC7B9", "", "4DF3C3F68FCC83B27E9D42C90431A72499F17875C81A599B566C9889B9696703", "00000000000000000000003B78CE563F89A0ED9414F5AA28AD0D96D6795F9C6376AFB1548AF603B3EB45C9F8207DEE1060CB71C04E80F593060B07D28308D7F4", True),
    ("", "EEFDEA4CDB677750A420FEE807EACF21EB9898AE79B9768766E4FAA04A2D4A34", "", "243F6A8885A308D313198A2E03707344A4093822299F31D0082EFA98EC4E6C89", "6CFF5C3BA86C69EA4B7376F31A9BCB4F74C1976089B2D9963DA2E5543E17776969E89B4C5564D00349106B8497785DD7D1D713A8AE82B32FA79D5F7FC407D39B", False),
    ("", "DFF1D77F2A671C5F36183726DB2341BE58FEAE1DA2DECED843240F7B502BA659", "", "243F6A8885A308D313198A2E03707344A4093822299F31D0082EFA98EC4E6C89", "FFF97BD5755EEEA420453A14355235D382F6472F8568A18B2F057A14602975563CC27944640AC607CD107AE10923D9EF7A73C643E166BE5EBEAFA34B1AC553E2", False),
    ("", "DFF1D77F2A671C5F36183726DB2341BE58FEAE1DA2DECED843240F7B502BA659", "", "243F6A8885A308D313198A2E03707344A4093822299F31D0082EFA98EC4E6C89", "1FA62E331EDBC21C394792D2AB1100A7B432B013DF3F6FF4F99FCB33E0E1515F28890B3EDB6E7189B630448B515CE4F8622A954CFE545735AAEA5134FCCDB2BD", False),
    ("", "DFF1D77F2A671C5F36183726DB2341BE58FEAE1DA2DECED843240F7B502BA659", "", "243F6A8885A308D313198A2E03707344A4093822299F31D0082EFA98EC4E6C89", "6CFF5C3BA86C69EA4B7376F31A9BCB4F74C1976089B2D9963DA2E5543E177769961764B3AA9B2FFCB6EF947B6887A226E8D7C93E00C5ED0C1834FF0D0C2E6DA6", False),
    ("", "DFF1D77F2A671C5F36183726DB2341BE58FEAE1DA2DECED843240F7B502BA659", "", "243F6A8885A308D313198A2E03707344A4093822299F31D0082EFA98EC4E6C89", "0000000000000000000000000000000000000000000000000000000000000000123DDA8328AF9C23A94C1FEECFD123BA4FB73476F0D594DCB65C6425BD186051", False),
    ("", "DFF1D77F2A671C5F36183726DB2341BE58FEAE1DA2DECED843240F7B502BA659", "", "243F6A8885A308D313198A2E03707344A4093822299F31D0082EFA98EC4E6C89", "00000000000000000000000000000000000000000000000000000000000000017615FBAF5AE28864013C099742DEADB4DBA87F11AC6754F93780D5A1837CF197", False),
    ("", "DFF1D77F2A671C5F36183726DB2341BE58FEAE1DA2DECED843240F7B502BA659", "", "243F6A8885A308D313198A2E03707344A4093822299F31D0082EFA98EC4E6C89", "4A298DACAE57395A15D0795DDBFD1DCB564DA82B0F269BC70A74F8220429BA1D69E89B4C5564D00349106B8497785DD7D1D713A8AE82B32FA79D5F7FC407D39B", False),
    ("", "DFF1D77F2A671C5F36183726DB2341BE58FEAE1DA2DECED843240F7B502BA659", "", "243F6A8885A308D313198A2E03707344A4093822299F31D0082EFA98EC4E6C89", "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F69E89B4C5564D00349106B8497785DD7D1D713A8AE82B32FA79D5F7FC407D39B", False),
    ("", "DFF1D77F2A671C5F36183726DB2341BE58FEAE1DA2DECED843240F7B502BA659", "", "243F6A8885A308D313198A2E03707344A4093822299F31D0082EFA98EC4E6C89", "6CFF5C3BA86C69EA4B7376F31A9BCB4F74C1976089B2D9963DA2E5543E177769FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141", False),
    ("", "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC30", "", "243F6A8885A308D313198A2E03707344A4093822299F31D0082EFA98EC4E6C89", "6CFF5C3BA86C69EA4B7376F31A9BCB4F74C1976089B2D9963DA2E5543E17776969E89B4C5564D00349106B8497785DD7D1D713A8AE82B32FA79D5F7FC407D39B", False),
]


def _self_test():
    for idx, (seckey_hex, pub_hex, aux_hex, msg_hex, sig_hex, expect_ok) in enumerate(_BIP340_VECTORS):
        pub = bytes.fromhex(pub_hex)
        msg = bytes.fromhex(msg_hex)
        sig = bytes.fromhex(sig_hex)
        try:
            got_ok = schnorr_verify(msg, pub, sig)
        except Exception:
            got_ok = False
        assert got_ok == expect_ok, f"vector {idx}: verify mismatch (got {got_ok}, want {expect_ok})"
        if seckey_hex:
            seckey = int(seckey_hex, 16)
            aux = bytes.fromhex(aux_hex)
            assert pubkey_from_privkey(seckey) == pub, f"vector {idx}: pubkey mismatch"
            mysig = schnorr_sign(msg, seckey, aux)
            assert mysig == sig, f"vector {idx}: sign mismatch"
    # tamper check: flipping one bit of a valid signature must fail verification
    pub0 = bytes.fromhex(_BIP340_VECTORS[0][1])
    msg0 = bytes.fromhex(_BIP340_VECTORS[0][3])
    sig0 = bytes.fromhex(_BIP340_VECTORS[0][4])
    bad_sig = bytes([sig0[0] ^ 1]) + sig0[1:]
    assert not schnorr_verify(msg0, pub0, bad_sig), "verify accepted a tampered signature"
    print(f"BIP-340 self-test: PASS ({len(_BIP340_VECTORS)} official test vectors incl. 11 adversarial, tamper check ok)")


if __name__ == "__main__":
    _self_test()
