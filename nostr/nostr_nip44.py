#!/usr/bin/env python3
"""NIP-44 v2 payload encryption/decryption.

secp256k1 ECDH -> HKDF-extract -> conversation_key; HKDF-expand(conversation_key,
nonce) -> chacha_key/chacha_nonce/hmac_key; custom power-of-two padding; ChaCha20
(RFC 8439, counter=0); HMAC-SHA256 over nonce||ciphertext as AAD; base64(version
0x02 || nonce || ciphertext || mac).

This replaces NIP-04 (AES-CBC) for anything built after w228 -- NIP-04 is what
the read-only listener already decrypts *inbound* with (legacy clients still
send it), but modern clients (and NIP-17 gift-wrapped DMs) use this. Pure
stdlib + `cryptography` (already a dependency here for NIP-04/ECDSA); no new
package.

Self-test on `__main__` runs the real vectors published at
https://github.com/paulmillr/nip44 (`nip44.vectors.json`, referenced by NIP-44
itself) -- get_conversation_key, get_message_keys, calc_padded_len,
encrypt_decrypt, encrypt_decrypt_long_msg, and the invalid/decrypt rejection
cases. Run: `nostr/.venv/bin/python nostr/nostr_nip44.py [path/to/vectors.json]`
"""
import base64
import hashlib
import hmac as hmac_mod
import math
import os
import sys

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

VERSION = 0x02
MIN_PLAINTEXT = 1
MAX_PLAINTEXT = 0xFFFFFFFF
EXTENDED_PREFIX_THRESHOLD = 65536


class Nip44Error(Exception):
    pass


def _privkey_from_hex(priv_hex):
    return ec.derive_private_key(int(priv_hex, 16), ec.SECP256K1())


def _pubkey_point_from_xonly_hex(pub_hex):
    """Lift a 32-byte x-only pubkey to a full point (even-Y, BIP-340 convention)."""
    return ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256K1(), b"\x02" + bytes.fromhex(pub_hex)
    )


def hkdf_extract(salt, ikm):
    return hmac_mod.new(salt, ikm, hashlib.sha256).digest()


def hkdf_expand(prk, info, length):
    out = b""
    t = b""
    counter = 1
    while len(out) < length:
        t = hmac_mod.new(prk, t + info + bytes([counter]), hashlib.sha256).digest()
        out += t
        counter += 1
    return out[:length]


def get_conversation_key(privkey_hex, pubkey_xonly_hex):
    """conv(a, B) == conv(b, A) -- symmetric regardless of who initiates."""
    priv = _privkey_from_hex(privkey_hex)
    pub_point = _pubkey_point_from_xonly_hex(pubkey_xonly_hex)
    shared_x = priv.exchange(ec.ECDH(), pub_point)  # 32-byte unhashed x coordinate
    if len(shared_x) != 32:
        raise Nip44Error("invalid shared point")
    return hkdf_extract(salt=b"nip44-v2", ikm=shared_x)


def get_message_keys(conversation_key, nonce):
    if len(conversation_key) != 32:
        raise Nip44Error("invalid conversation_key length")
    if len(nonce) != 32:
        raise Nip44Error("invalid nonce length")
    keys = hkdf_expand(prk=conversation_key, info=nonce, length=76)
    return keys[0:32], keys[32:44], keys[44:76]  # chacha_key, chacha_nonce, hmac_key


def calc_padded_len(unpadded_len):
    if unpadded_len <= 32:
        return 32
    next_power = 1 << (math.floor(math.log2(unpadded_len - 1)) + 1)
    chunk = 32 if next_power <= 256 else next_power // 8
    return chunk * (math.floor((unpadded_len - 1) / chunk) + 1)


def _pad(plaintext):
    unpadded = plaintext.encode("utf-8")
    n = len(unpadded)
    if n < MIN_PLAINTEXT or n > MAX_PLAINTEXT:
        raise Nip44Error("invalid plaintext length")
    if n >= EXTENDED_PREFIX_THRESHOLD:
        prefix = b"\x00\x00" + n.to_bytes(4, "big")
    else:
        prefix = n.to_bytes(2, "big")
    suffix = b"\x00" * (calc_padded_len(n) - n)
    return prefix + unpadded + suffix


def _unpad(padded):
    first_two = int.from_bytes(padded[0:2], "big")
    if first_two == 0:
        unpadded_len = int.from_bytes(padded[2:6], "big")
        if unpadded_len < EXTENDED_PREFIX_THRESHOLD:
            raise Nip44Error("invalid padding")
        prefix_len = 6
    else:
        unpadded_len = first_two
        prefix_len = 2
    unpadded = padded[prefix_len:prefix_len + unpadded_len]
    if (unpadded_len == 0
            or len(unpadded) != unpadded_len
            or len(padded) != prefix_len + calc_padded_len(unpadded_len)):
        raise Nip44Error("invalid padding")
    return unpadded.decode("utf-8")


def _chacha20(key, nonce12, data):
    cipher = Cipher(algorithms.ChaCha20(key, b"\x00\x00\x00\x00" + nonce12), mode=None)
    return cipher.encryptor().update(data)  # ChaCha20 is its own inverse (XOR stream)


def _hmac_aad(key, message, aad):
    if len(aad) != 32:
        raise Nip44Error("AAD must be 32 bytes")
    return hmac_mod.new(key, aad + message, hashlib.sha256).digest()


def encrypt(plaintext, conversation_key, nonce=None):
    nonce = nonce or os.urandom(32)
    chacha_key, chacha_nonce, hmac_key = get_message_keys(conversation_key, nonce)
    padded = _pad(plaintext)
    ciphertext = _chacha20(chacha_key, chacha_nonce, padded)
    mac = _hmac_aad(hmac_key, ciphertext, nonce)
    return base64.b64encode(bytes([VERSION]) + nonce + ciphertext + mac).decode()


def decode_payload(payload):
    if not payload or payload[0] == "#":
        raise Nip44Error("unknown version")
    if len(payload) < 132:
        raise Nip44Error("invalid payload size")
    try:
        data = base64.b64decode(payload, validate=True)
    except Exception as exc:
        raise Nip44Error(f"invalid base64: {exc}") from exc
    if len(data) < 99:
        raise Nip44Error("invalid data size")
    if data[0] != VERSION:
        raise Nip44Error(f"unknown version {data[0]}")
    nonce = data[1:33]
    ciphertext = data[33:-32]
    mac = data[-32:]
    return nonce, ciphertext, mac


def decrypt(payload, conversation_key):
    nonce, ciphertext, mac = decode_payload(payload)
    chacha_key, chacha_nonce, hmac_key = get_message_keys(conversation_key, nonce)
    calculated_mac = _hmac_aad(hmac_key, ciphertext, nonce)
    if not hmac_mod.compare_digest(calculated_mac, mac):
        raise Nip44Error("invalid MAC")
    padded_plaintext = _chacha20(chacha_key, chacha_nonce, ciphertext)
    return _unpad(padded_plaintext)


def _self_test(vectors_path):
    import json

    with open(vectors_path) as fh:
        v = json.load(fh)["v2"]

    failures = []

    def check(label, cond):
        if not cond:
            failures.append(label)

    for i, tv in enumerate(v["valid"]["get_conversation_key"]):
        ck = get_conversation_key(tv["sec1"], tv["pub2"])
        check(f"get_conversation_key[{i}]", ck.hex() == tv["conversation_key"])

    gmk = v["valid"]["get_message_keys"]
    conv = bytes.fromhex(gmk["conversation_key"])
    for i, tv in enumerate(gmk["keys"]):
        ck, cn, hk = get_message_keys(conv, bytes.fromhex(tv["nonce"]))
        check(f"get_message_keys[{i}].chacha_key", ck.hex() == tv["chacha_key"])
        check(f"get_message_keys[{i}].chacha_nonce", cn.hex() == tv["chacha_nonce"])
        check(f"get_message_keys[{i}].hmac_key", hk.hex() == tv["hmac_key"])

    for i, (unpadded_len, padded_len) in enumerate(v["valid"]["calc_padded_len"]):
        check(f"calc_padded_len[{i}]", calc_padded_len(unpadded_len) == padded_len)

    for i, tv in enumerate(v["valid"]["encrypt_decrypt"]):
        ck = get_conversation_key(tv["sec1"], _xonly_pub(tv["sec2"]))
        check(f"encrypt_decrypt[{i}].conversation_key", ck.hex() == tv["conversation_key"])
        payload = encrypt(tv["plaintext"], ck, bytes.fromhex(tv["nonce"]))
        check(f"encrypt_decrypt[{i}].payload", payload == tv["payload"])
        ck2 = get_conversation_key(tv["sec2"], _xonly_pub(tv["sec1"]))
        check(f"encrypt_decrypt[{i}].conversation_key_swapped", ck2.hex() == tv["conversation_key"])
        pt = decrypt(tv["payload"], ck2)
        check(f"encrypt_decrypt[{i}].plaintext", pt == tv["plaintext"])

    for i, tv in enumerate(v["valid"]["encrypt_decrypt_long_msg"]):
        ck = bytes.fromhex(tv["conversation_key"])
        nonce = bytes.fromhex(tv["nonce"])
        plaintext = tv["pattern"] * tv["repeat"]
        check(f"encrypt_decrypt_long_msg[{i}].plaintext_sha256",
              hashlib.sha256(plaintext.encode()).hexdigest() == tv["plaintext_sha256"])
        payload = encrypt(plaintext, ck, nonce)
        check(f"encrypt_decrypt_long_msg[{i}].payload_sha256",
              hashlib.sha256(payload.encode()).hexdigest() == tv["payload_sha256"])
        check(f"encrypt_decrypt_long_msg[{i}].roundtrip", decrypt(payload, ck) == plaintext)

    # Extended (6-byte, u32) length-prefix boundary cases given verbatim in the
    # NIP-44 spec markdown itself (not in paulmillr/nip44's vectors.json, which
    # predates the spec's extended-prefix section and instead rejects these
    # lengths outright in invalid.encrypt_msg_lengths -- superseded by the
    # normative spec text, so not enforced here).
    ext_conv = bytes.fromhex("c41c775356fd92eadc63ff5a0dc1da211b268cbea22316767095b2871ea1412d")
    ext_nonce = bytes.fromhex("0000000000000000000000000000000000000000000000000000000000000001")
    for i, (length, padded_len, pt_sha, payload_sha) in enumerate([
        (65535, 65536, "6e1bebca6a8229364a162a72ef064826c4cd7457bf54f190ef782bd9deff3e42",
         "6d8c2810d1e870fbaa1f0a0937126cca837a15f9260e27060c331d70a3c0bc84"),
        (65536, 65536, "bf718b6f653bebc184e1479f1935b8da974d701b893afcf49e701f3e2f9f9c5a",
         "b7b4edb36ba92e267d322d56d9aebc22e7fa96ff52e3c12adc07f07a43cbc616"),
        (65537, 81920, "008ffc88d3c96a9f307524eb361e47c5222a887fc45fa0c1fb8d429c5c23b430",
         "eeb7c7c5373894ea2c1547cfd3ccb15d5a0b2d619da852e5c79df792dcc9e435"),
    ]):
        plaintext = "a" * length
        check(f"extended_prefix[{i}].calc_padded_len", calc_padded_len(length) == padded_len)
        check(f"extended_prefix[{i}].plaintext_sha256",
              hashlib.sha256(plaintext.encode()).hexdigest() == pt_sha)
        payload = encrypt(plaintext, ext_conv, ext_nonce)
        check(f"extended_prefix[{i}].payload_sha256",
              hashlib.sha256(payload.encode()).hexdigest() == payload_sha)
        check(f"extended_prefix[{i}].roundtrip", decrypt(payload, ext_conv) == plaintext)

    for i, tv in enumerate(v["invalid"]["get_conversation_key"]):
        try:
            get_conversation_key(tv["sec1"], tv["pub2"])
            failures.append(f"invalid.get_conversation_key[{i}] did not raise ({tv.get('note')})")
        except Exception:
            pass

    for i, tv in enumerate(v["invalid"]["decrypt"]):
        try:
            decrypt(tv["payload"], bytes.fromhex(tv["conversation_key"]))
            failures.append(f"invalid.decrypt[{i}] did not raise ({tv.get('note')})")
        except Exception:
            pass

    total = (len(v["valid"]["get_conversation_key"]) + len(gmk["keys"]) * 3
             + len(v["valid"]["calc_padded_len"])
             + len(v["valid"]["encrypt_decrypt"]) * 4
             + len(v["valid"]["encrypt_decrypt_long_msg"]) * 3
             + 3 * 4  # extended_prefix boundary cases from the spec markdown
             + len(v["invalid"]["get_conversation_key"])
             + len(v["invalid"]["decrypt"]))
    print(f"{total - len(failures)}/{total} checks passed")
    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("all NIP-44 v2 spec vectors pass (get_conversation_key, get_message_keys, "
          "calc_padded_len, encrypt_decrypt incl. long-msg extended-prefix cases, "
          "invalid/get_conversation_key + invalid/decrypt rejections)")
    return 0


def _xonly_pub(privkey_hex):
    priv = _privkey_from_hex(privkey_hex)
    comp = priv.public_key().public_bytes(Encoding.X962, PublicFormat.CompressedPoint)
    return comp[1:].hex()


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "nip44.vectors.json"
    )
    if not os.path.exists(path):
        sys.exit(f"vectors file not found: {path} (pass a path, or curl the "
                  "paulmillr/nip44 nip44.vectors.json into nostr/)")
    raise SystemExit(_self_test(path))
