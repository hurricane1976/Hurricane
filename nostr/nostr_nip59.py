#!/usr/bin/env python3
"""NIP-59 gift wrap / NIP-17 private direct messages, built on nostr_nip44.py.

rumor (unsigned event) -> seal (kind:13, NIP-44-encrypted rumor, signed by the
real sender) -> gift wrap (kind:1059, NIP-44-encrypted seal, signed by a
random one-time-use key so the real sender's pubkey never appears on the
wire). This is what modern Nostr clients (Amethyst, Damus, etc.) use for DMs
instead of legacy NIP-04 -- a DM sent by one of those won't decrypt with the
kind:4 path nostr_listen.py already has; it arrives as kind:1059 and needs
this module to open.

Self-test on `__main__` decrypts the two worked examples published in the
NIP-59 and NIP-17 spec text themselves (real gift-wrap events built by their
reference JS implementation, with the private keys given) and checks the
recovered plaintext matches exactly -- a genuine cross-implementation check,
not just a round-trip-with-itself test.

    nostr/.venv/bin/python nostr/nostr_nip59.py
"""
import hashlib
import json
import secrets
import time

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

import bech32
import nostr_build_event as builder
import nostr_nip44 as nip44

TWO_DAYS = 2 * 24 * 60 * 60


def _random_past_ts(not_after=None):
    """NIP-17: randomize created_at up to 2 days in the past so timestamp
    correlation doesn't leak metadata. Never in the future (some relays reject
    that)."""
    base = not_after if not_after is not None else int(time.time())
    return base - secrets.randbelow(TWO_DAYS + 1)


def gen_ephemeral_keypair():
    """A fresh, one-time-use secp256k1 keypair -- NIP-59 requires a new one
    per gift wrap so the wrapper pubkey never links back to the real sender."""
    priv = ec.generate_private_key(ec.SECP256K1())
    priv_int = priv.private_numbers().private_value
    comp = priv.public_key().public_bytes(Encoding.X962, PublicFormat.CompressedPoint)
    return priv_int, comp[1:].hex()


def make_rumor(sender_pubkey_hex, kind, content, tags=None, created_at=None):
    """An unsigned event -- NIP-59 sec. 1: 'the same thing as an unsigned
    event.' Still gets a real `id` (hash of the same NIP-01 serialization),
    just no `sig`."""
    tags = tags or []
    created_at = created_at if created_at is not None else int(time.time())
    ser = builder.serialize_for_id(sender_pubkey_hex, created_at, kind, tags, content)
    rumor_id = hashlib.sha256(ser.encode("utf-8")).hexdigest()
    return {
        "id": rumor_id, "pubkey": sender_pubkey_hex, "created_at": created_at,
        "kind": kind, "tags": tags, "content": content,
    }


def _dump(obj):
    return json.dumps(obj, separators=(",", ":"))


def seal_rumor(rumor, sender_priv_int, sender_pubkey_hex, recipient_pubkey_hex):
    """kind:13 -- NIP-59 sec. 2. Tags MUST be empty; signed by the real sender."""
    conv = nip44.get_conversation_key(format(sender_priv_int, "064x"), recipient_pubkey_hex)
    encrypted = nip44.encrypt(_dump(rumor), conv)
    return builder.build_event(
        sender_priv_int, sender_pubkey_hex, kind=13, content=encrypted, tags=[],
        created_at=_random_past_ts(rumor["created_at"]),
    )


def wrap_seal(seal_event, recipient_pubkey_hex):
    """kind:1059 -- NIP-59 sec. 3. Signed by a throwaway key, never the real sender's."""
    eph_priv_int, eph_pub_hex = gen_ephemeral_keypair()
    conv = nip44.get_conversation_key(format(eph_priv_int, "064x"), recipient_pubkey_hex)
    encrypted = nip44.encrypt(_dump(seal_event), conv)
    return builder.build_event(
        eph_priv_int, eph_pub_hex, kind=1059, content=encrypted,
        tags=[["p", recipient_pubkey_hex]], created_at=_random_past_ts(seal_event["created_at"]),
    )


def wrap_dm(sender_priv_int, sender_pubkey_hex, recipient_pubkey_hex, content,
            extra_tags=None, reply_to_event_id=None):
    """Build a NIP-17 kind:14 chat message, gift-wrapped twice: once addressed
    to the recipient (what actually needs broadcasting) and once addressed to
    the sender (so the sender keeps a copy they can decrypt later -- NIP-17's
    "seal + wrap to each receiver and the sender individually"). Returns
    (wrap_for_recipient, wrap_for_self, rumor)."""
    tags = [["p", recipient_pubkey_hex]]
    if reply_to_event_id:
        tags.append(["e", reply_to_event_id])
    tags += (extra_tags or [])
    rumor = make_rumor(sender_pubkey_hex, 14, content, tags)

    seal_for_recipient = seal_rumor(rumor, sender_priv_int, sender_pubkey_hex, recipient_pubkey_hex)
    wrap_for_recipient = wrap_seal(seal_for_recipient, recipient_pubkey_hex)

    seal_for_self = seal_rumor(rumor, sender_priv_int, sender_pubkey_hex, sender_pubkey_hex)
    wrap_for_self = wrap_seal(seal_for_self, sender_pubkey_hex)

    return wrap_for_recipient, wrap_for_self, rumor


def unwrap_gift_wrap(my_priv_hex, gift_wrap_event):
    """Undo wrap -> seal -> rumor using our own private key. Verifies the
    seal's signature and (per NIP-17's explicit anti-impersonation rule)
    that the rumor's pubkey matches the seal's signer -- otherwise anyone
    could put any pubkey on the inner rumor and impersonate them. Returns
    (seal, rumor); raises ValueError/nip44.Nip44Error on any failure."""
    conv_wrap = nip44.get_conversation_key(my_priv_hex, gift_wrap_event["pubkey"])
    seal = json.loads(nip44.decrypt(gift_wrap_event["content"], conv_wrap))
    ok, why = builder.verify_event(seal)
    if not ok:
        raise ValueError(f"seal signature invalid: {why}")
    if seal.get("kind") != 13:
        raise ValueError(f"expected kind:13 seal, got {seal.get('kind')}")
    conv_seal = nip44.get_conversation_key(my_priv_hex, seal["pubkey"])
    rumor = json.loads(nip44.decrypt(seal["content"], conv_seal))
    if rumor.get("pubkey") != seal["pubkey"]:
        raise ValueError("rumor pubkey != seal signer -- possible impersonation, discarding")
    return seal, rumor


def _xonly_pub_hex(priv_hex):
    priv = ec.derive_private_key(int(priv_hex, 16), ec.SECP256K1())
    comp = priv.public_key().public_bytes(Encoding.X962, PublicFormat.CompressedPoint)
    return comp[1:].hex()


def _self_test():
    failures = []

    def check(label, cond):
        if not cond:
            failures.append(label)

    # --- NIP-59's own worked example: decrypt the exact kind:1059 event the
    # spec prints, using the exact recipient private key it gives, and
    # confirm we recover the exact kind:1 rumor + content it started from.
    author_priv = "0beebd062ec8735f4243466049d7747ef5d6594ee838de147f8aab842b15e273"
    recipient_priv = "e108399bd8424357a710b606ae0c13166d853d327e47a6e5e038197346bdbf45"
    check("nip59.author_pub", _xonly_pub_hex(author_priv) == "611df01bfcf85c26ae65453b772d8f1dfd25c264621c0277e1fc1518686faef9")
    check("nip59.recipient_pub", _xonly_pub_hex(recipient_priv) == "166bf3765ebd1fc55decfe395beff2ea3b2a4e0a8946e7eb578512b555737c99")
    gift_wrap_event = {
        "content": "AhC3Qj/QsKJFWuf6xroiYip+2yK95qPwJjVvFujhzSguJWb/6TlPpBW0CGFwfufCs2Zyb0JeuLmZhNlnqecAAalC4ZCugB+I9ViA5pxLyFfQjs1lcE6KdX3euCHBLAnE9GL/+IzdV9vZnfJH6atVjvBkNPNzxU+OLCHO/DAPmzmMVx0SR63frRTCz6Cuth40D+VzluKu1/Fg2Q1LSst65DE7o2efTtZ4Z9j15rQAOZfE9jwMCQZt27rBBK3yVwqVEriFpg2mHXc1DDwHhDADO8eiyOTWF1ghDds/DxhMcjkIi/o+FS3gG1dG7gJHu3KkGK5UXpmgyFKt+421m5o++RMD/BylS3iazS1S93IzTLeGfMCk+7IKxuSCO06k1+DaasJJe8RE4/rmismUvwrHu/HDutZWkvOAhd4z4khZo7bJLtiCzZCZ74lZcjOB4CYtuAX2ZGpc4I1iOKkvwTuQy9BWYpkzGg3ZoSWRD6ty7U+KN+fTTmIS4CelhBTT15QVqD02JxfLF7nA6sg3UlYgtiGw61oH68lSbx16P3vwSeQQpEB5JbhofW7t9TLZIbIW/ODnI4hpwj8didtk7IMBI3Ra3uUP7ya6vptkd9TwQkd/7cOFaSJmU+BIsLpOXbirJACMn+URoDXhuEtiO6xirNtrPN8jYqpwvMUm5lMMVzGT3kMMVNBqgbj8Ln8VmqouK0DR+gRyNb8fHT0BFPwsHxDskFk5yhe5c/2VUUoKCGe0kfCcX/EsHbJLUUtlHXmTqaOJpmQnW1tZ/siPwKRl6oEsIJWTUYxPQmrM2fUpYZCuAo/29lTLHiHMlTbarFOd6J/ybIbICy2gRRH/LFSryty3Cnf6aae+A9uizFBUdCwTwffc3vCBae802+R92OL78bbqHKPbSZOXNC+6ybqziezwG+OPWHx1Qk39RYaF0aFsM4uZWrFic97WwVrH5i+/Nsf/OtwWiuH0gV/SqvN1hnkxCTF/+XNn/laWKmS3e7wFzBsG8+qwqwmO9aVbDVMhOmeUXRMkxcj4QreQkHxLkCx97euZpC7xhvYnCHarHTDeD6nVK+xzbPNtzeGzNpYoiMqxZ9bBJwMaHnEoI944Vxoodf51cMIIwpTmmRvAzI1QgrfnOLOUS7uUjQ/IZ1Qa3lY08Nqm9MAGxZ2Ou6R0/Z5z30ha/Q71q6meAs3uHQcpSuRaQeV29IASmye2A2Nif+lmbhV7w8hjFYoaLCRsdchiVyNjOEM4VmxUhX4VEvw6KoCAZ/XvO2eBF/SyNU3Of4SO",
        "kind": 1059, "created_at": 1703021488,
        "pubkey": "18b1a75918f1f2c90c23da616bce317d36e348bcf5f7ba55e75949319210c87c",
        "id": "5c005f3ccf01950aa8d131203248544fb1e41a0d698e846bd419cec3890903ac",
        "sig": "35fabdae4634eb630880a1896a886e40fd6ea8a60958e30b89b33a93e6235df750097b04f9e13053764251b8bc5dd7e8e0794a3426a90b6bcc7e5ff660f54259",
        "tags": [["p", "166bf3765ebd1fc55decfe395beff2ea3b2a4e0a8946e7eb578512b555737c99"]],
    }
    check("nip59.wrap.self_verify", builder.verify_event(gift_wrap_event)[0])
    try:
        seal, rumor = unwrap_gift_wrap(recipient_priv, gift_wrap_event)
        check("nip59.seal.pubkey", seal["pubkey"] == "611df01bfcf85c26ae65453b772d8f1dfd25c264621c0277e1fc1518686faef9")
        check("nip59.seal.kind", seal["kind"] == 13)
        check("nip59.rumor.kind", rumor["kind"] == 1)
        check("nip59.rumor.content", rumor["content"] == "Are you going to the party tonight?")
    except Exception as exc:
        failures.append(f"nip59.unwrap raised: {exc.__class__.__name__}: {exc}")

    # --- NIP-17's worked example: same idea, "Hola, que tal?" DM, decoded
    # from real nsec1... bech32 keys given in the spec.
    sender_priv17 = bech32.decode("nsec", "nsec1w8udu59ydjvedgs3yv5qccshcj8k05fh3l60k9x57asjrqdpa00qkmr89m").hex()
    recipient_priv17 = bech32.decode("nsec", "nsec12ywtkplvyq5t6twdqwwygavp5lm4fhuang89c943nf2z92eez43szvn4dt").hex()
    wrap_to_receiver = {
        "id": "2886780f7349afc1344047524540ee716f7bdc1b64191699855662330bf235d8",
        "pubkey": "8f8a7ec43b77d25799281207e1a47f7a654755055788f7482653f9c9661c6d51",
        "created_at": 1703128320, "kind": 1059,
        "tags": [["p", "918e2da906df4ccd12c8ac672d8335add131a4cf9d27ce42b3bb3625755f0788"]],
        "content": "AsqzdlMsG304G8h08bE67dhAR1gFTzTckUUyuvndZ8LrGCvwI4pgC3d6hyAK0Wo9gtkLqSr2rT2RyHlE5wRqbCOlQ8WvJEKwqwIJwT5PO3l2RxvGCHDbd1b1o40ZgIVwwLCfOWJ86I5upXe8K5AgpxYTOM1BD+SbgI5jOMA8tgpRoitJedVSvBZsmwAxXM7o7sbOON4MXHzOqOZpALpS2zgBDXSAaYAsTdEM4qqFeik+zTk3+L6NYuftGidqVluicwSGS2viYWr5OiJ1zrj1ERhYSGLpQnPKrqDaDi7R1KrHGFGyLgkJveY/45y0rv9aVIw9IWF11u53cf2CP7akACel2WvZdl1htEwFu/v9cFXD06fNVZjfx3OssKM/uHPE9XvZttQboAvP5UoK6lv9o3d+0GM4/3zP+yO3C0NExz1ZgFmbGFz703YJzM+zpKCOXaZyzPjADXp8qBBeVc5lmJqiCL4solZpxA1865yPigPAZcc9acSUlg23J1dptFK4n3Tl5HfSHP+oZ/QS/SHWbVFCtq7ZMQSRxLgEitfglTNz9P1CnpMwmW/Y4Gm5zdkv0JrdUVrn2UO9ARdHlPsW5ARgDmzaxnJypkfoHXNfxGGXWRk0sKLbz/ipnaQP/eFJv/ibNuSfqL6E4BnN/tHJSHYEaTQ/PdrA2i9laG3vJti3kAl5Ih87ct0w/tzYfp4SRPhEF1zzue9G/16eJEMzwmhQ5Ec7jJVcVGa4RltqnuF8unUu3iSRTQ+/MNNUkK6Mk+YuaJJs6Fjw6tRHuWi57SdKKv7GGkr0zlBUU2Dyo1MwpAqzsCcCTeQSv+8qt4wLf4uhU9Br7F/L0ZY9bFgh6iLDCdB+4iABXyZwT7Ufn762195hrSHcU4Okt0Zns9EeiBOFxnmpXEslYkYBpXw70GmymQfJlFOfoEp93QKCMS2DAEVeI51dJV1e+6t3pCSsQN69Vg6jUCsm1TMxSs2VX4BRbq562+VffchvW2BB4gMjsvHVUSRl8i5/ZSDlfzSPXcSGALLHBRzy+gn0oXXJ/447VHYZJDL3Ig8+QW5oFMgnWYhuwI5QSLEyflUrfSz+Pdwn/5eyjybXKJftePBD9Q+8NQ8zulU5sqvsMeIx/bBUx0fmOXsS3vjqCXW5IjkmSUV7q54GewZqTQBlcx+90xh/LSUxXex7UwZwRnifvyCbZ+zwNTHNb12chYeNjMV7kAIr3cGQv8vlOMM8ajyaZ5KVy7HpSXQjz4PGT2/nXbL5jKt8Lx0erGXsSsazkdoYDG3U",
        "sig": "a3c6ce632b145c0869423c1afaff4a6d764a9b64dedaf15f170b944ead67227518a72e455567ca1c2a0d187832cecbde7ed478395ec4c95dd3e71749ed66c480",
    }
    check("nip17.wrap.self_verify", builder.verify_event(wrap_to_receiver)[0])
    try:
        seal17, rumor17 = unwrap_gift_wrap(recipient_priv17, wrap_to_receiver)
        check("nip17.rumor.kind", rumor17["kind"] == 14)
        check("nip17.rumor.content", rumor17["content"] == "Hola, que tal?")
        check("nip17.seal.pubkey_matches_rumor", seal17["pubkey"] == rumor17["pubkey"])
    except Exception as exc:
        failures.append(f"nip17.unwrap raised: {exc.__class__.__name__}: {exc}")

    # --- our own round trip: wrap_dm() then unwrap_gift_wrap() both copies.
    a_priv_int = int(author_priv, 16)
    a_pub = _xonly_pub_hex(author_priv)
    b_priv_int = int(recipient_priv, 16)
    b_pub = _xonly_pub_hex(recipient_priv)
    wrap_for_b, wrap_for_a, rumor = wrap_dm(a_priv_int, a_pub, b_pub, "round-trip self-test message")
    check("roundtrip.wrap_for_recipient.self_verify", builder.verify_event(wrap_for_b)[0])
    check("roundtrip.wrap_for_sender.self_verify", builder.verify_event(wrap_for_a)[0])
    check("roundtrip.wrap_for_recipient.ephemeral_pubkey_differs", wrap_for_b["pubkey"] != a_pub)
    _, recovered_by_b = unwrap_gift_wrap(recipient_priv, wrap_for_b)
    check("roundtrip.recipient_decrypts", recovered_by_b["content"] == "round-trip self-test message")
    check("roundtrip.recipient_sees_real_sender", recovered_by_b["pubkey"] == a_pub)
    _, recovered_by_a = unwrap_gift_wrap(author_priv, wrap_for_a)
    check("roundtrip.sender_self_copy_decrypts", recovered_by_a["content"] == "round-trip self-test message")

    total = 15
    print(f"{total - len(failures)}/{total} checks passed")
    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("NIP-59/NIP-17 gift-wrap round trip verified against the spec's own worked "
          "examples (real cross-implementation events, not just self-consistency) "
          "plus a full wrap_dm()/unwrap_gift_wrap() round trip.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
