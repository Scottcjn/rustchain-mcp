"""Regression test for the BIP39 mnemonic entropy bug (rustchain_crypto).

Before the fix the wordlist held <2048 words and _generate_mnemonic indexed it
with `word_index % len(WORDLIST)`, collapsing each 11-bit index and producing
non-standard mnemonics with reduced entropy. These assertions fail on that code.
"""
from rustchain_mcp import rustchain_crypto as rc


def test_wordlist_is_full_2048_unique():
    assert len(rc.BIP39_WORDLIST) == 2048, "BIP39 needs exactly 2048 words for 11-bit indices"
    assert len(set(rc.BIP39_WORDLIST)) == 2048, "wordlist must have no duplicates"


def test_generated_mnemonic_is_valid_bip39():
    official = set(rc.BIP39_WORDLIST)
    for _ in range(50):
        words = rc._generate_mnemonic(128).split()
        assert len(words) == 12
        assert all(w in official for w in words), "every word must be a real BIP39 word"


def test_no_index_truncation_full_entropy():
    # 2048 == 2**11: an 11-bit index must map 1:1 with no modulo collapse.
    assert len(rc.BIP39_WORDLIST) == 2048
    seen = {rc.BIP39_WORDLIST[i] for i in range(2048)}
    assert len(seen) == 2048
