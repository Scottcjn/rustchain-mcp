#!/usr/bin/env python3
"""
Tests for RustChain Wallet Management Tools

Tests cover:
- Ed25519 key generation and signing
- BIP39 mnemonic generation and validation
- Encrypted keystore operations
- Wallet CRUD operations
- Transaction signing
"""

import os
import sys
import json
import tempfile
import shutil
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

# Skip tests if crypto libraries not available
try:
    from rustchain_mcp.rustchain_crypto import (
        WalletManager,
        generate_ed25519_keypair,
        private_key_to_hex,
        public_key_to_hex,
        hex_to_private_key,
        hex_to_public_key,
        sign_message,
        verify_signature,
        generate_mnemonic,
        mnemonic_to_seed,
        validate_mnemonic,
        derive_ed25519_key_from_seed,
        public_key_to_address,
        encrypt_private_key,
        decrypt_private_key,
        CRYPTO_AVAILABLE,
        BIP39_AVAILABLE,
    )
    CRYPTO_SKIP = not CRYPTO_AVAILABLE
    BIP39_SKIP = not BIP39_AVAILABLE
except ImportError:
    CRYPTO_SKIP = True
    BIP39_SKIP = True


@pytest.mark.skipif(CRYPTO_SKIP, reason="cryptography library not installed")
class TestEd25519Operations:
    """Test Ed25519 cryptographic operations."""

    def test_keypair_generation(self):
        """Test Ed25519 key pair generation."""
        private_key, public_key = generate_ed25519_keypair()
        
        assert private_key is not None
        assert public_key is not None

    def test_key_serialization(self):
        """Test key to hex conversion and back."""
        private_key, public_key = generate_ed25519_keypair()
        
        # Convert to hex
        private_hex = private_key_to_hex(private_key)
        public_hex = public_key_to_hex(public_key)
        
        assert len(private_hex) == 64  # 32 bytes = 64 hex chars
        assert len(public_hex) == 64
        
        # Convert back
        private_key2 = hex_to_private_key(private_hex)
        public_key2 = hex_to_public_key(public_hex)
        
        assert private_key_to_hex(private_key2) == private_hex
        assert public_key_to_hex(public_key2) == public_hex

    def test_signing_and_verification(self):
        """Test Ed25519 signing and verification."""
        private_key, public_key = generate_ed25519_keypair()
        
        message = b"Test message for signing"
        
        # Sign
        signature = sign_message(private_key, message)
        
        assert len(signature) == 128  # 64 bytes = 128 hex chars
        
        # Verify
        assert verify_signature(public_key, signature, message) is True
        
        # Wrong message should fail
        assert verify_signature(public_key, signature, b"Wrong message") is False

    def test_address_generation(self):
        """Test RTC address generation from public key."""
        private_key, public_key = generate_ed25519_keypair()
        public_hex = public_key_to_hex(public_key)
        
        address = public_key_to_address(public_hex)
        
        assert address.startswith("RTC")
        # Address length is 3 (RTC prefix) + 40 hex chars (20 bytes RIPEMD160)
        assert len(address) >= 35  # At least prefix + some hex chars


@pytest.mark.skipif(BIP39_SKIP, reason="mnemonic library not installed")
class TestBIP39Operations:
    """Test BIP39 mnemonic operations."""

    def test_mnemonic_generation_12_words(self):
        """Test 12-word mnemonic generation."""
        mnemonic = generate_mnemonic(strength=128)
        
        words = mnemonic.split()
        assert len(words) == 12
        assert validate_mnemonic(mnemonic) is True

    def test_mnemonic_generation_24_words(self):
        """Test 24-word mnemonic generation."""
        mnemonic = generate_mnemonic(strength=256)
        
        words = mnemonic.split()
        assert len(words) == 24
        assert validate_mnemonic(mnemonic) is True

    def test_mnemonic_to_seed(self):
        """Test mnemonic to seed conversion."""
        mnemonic = generate_mnemonic()
        seed = mnemonic_to_seed(mnemonic)
        
        assert len(seed) == 64  # 64 bytes

    def test_key_derivation_from_seed(self):
        """Test Ed25519 key derivation from seed."""
        mnemonic = generate_mnemonic()
        seed = mnemonic_to_seed(mnemonic)
        
        private_key, public_key = derive_ed25519_key_from_seed(seed)
        
        assert private_key is not None
        assert public_key is not None
        
        # Different index should give different key
        private_key2, public_key2 = derive_ed25519_key_from_seed(seed, index=1)
        
        assert private_key_to_hex(private_key) != private_key_to_hex(private_key2)

    def test_deterministic_derivation(self):
        """Test that same mnemonic gives same keys."""
        mnemonic = generate_mnemonic()
        seed = mnemonic_to_seed(mnemonic)
        
        private_key1, public_key1 = derive_ed25519_key_from_seed(seed, index=0)
        private_key2, public_key2 = derive_ed25519_key_from_seed(seed, index=0)
        
        assert private_key_to_hex(private_key1) == private_key_to_hex(private_key2)


@pytest.mark.skipif(CRYPTO_SKIP, reason="cryptography library not installed")
class TestEncryptedKeystore:
    """Test encrypted keystore operations."""

    def test_encrypt_decrypt_private_key(self):
        """Test private key encryption and decryption."""
        private_key, _ = generate_ed25519_keypair()
        private_hex = private_key_to_hex(private_key)
        password = "test-password-123"
        
        # Encrypt
        encrypted, salt, nonce = encrypt_private_key(private_hex, password)
        
        assert encrypted is not None
        assert salt is not None
        assert nonce is not None
        
        # Decrypt
        decrypted = decrypt_private_key(encrypted, salt, nonce, password)
        
        assert decrypted == private_hex

    def test_wrong_password_fails(self):
        """Test that wrong password fails to decrypt."""
        private_key, _ = generate_ed25519_keypair()
        private_hex = private_key_to_hex(private_key)
        
        encrypted, salt, nonce = encrypt_private_key(private_hex, "correct-password")
        
        with pytest.raises(Exception):
            decrypt_private_key(encrypted, salt, nonce, "wrong-password")


@pytest.mark.skipif(CRYPTO_SKIP or BIP39_SKIP, reason="crypto libraries not installed")
class TestWalletManager:
    """Test WalletManager class."""

    @pytest.fixture
    def temp_keystore(self):
        """Create a temporary keystore directory."""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        shutil.rmtree(temp_dir)

    def test_create_wallet(self, temp_keystore):
        """Test wallet creation."""
        manager = WalletManager(keystore_dir=temp_keystore)
        
        wallet = manager.create_wallet(
            name="test-wallet",
            password="password123",
            store_mnemonic=True
        )
        
        assert wallet.wallet_id is not None
        assert wallet.address.startswith("RTC")
        assert wallet.name == "test-wallet"
        assert wallet.public_key_hex is not None

    def test_create_wallet_without_mnemonic(self, temp_keystore):
        """Test wallet creation without mnemonic."""
        manager = WalletManager(keystore_dir=temp_keystore)
        
        wallet = manager.create_wallet(
            name="no-mnemonic-wallet",
            password="password123",
            store_mnemonic=False
        )
        
        assert wallet.wallet_id is not None
        assert wallet.address.startswith("RTC")

    def test_list_wallets(self, temp_keystore):
        """Test listing wallets."""
        manager = WalletManager(keystore_dir=temp_keystore)
        
        # Create multiple wallets
        wallet1 = manager.create_wallet("wallet1", "pass1")
        wallet2 = manager.create_wallet("wallet2", "pass2")
        
        wallets = manager.list_wallets()
        
        assert len(wallets) == 2
        assert any(w.wallet_id == wallet1.wallet_id for w in wallets)
        assert any(w.wallet_id == wallet2.wallet_id for w in wallets)

    def test_get_wallet(self, temp_keystore):
        """Test retrieving wallet with private key."""
        manager = WalletManager(keystore_dir=temp_keystore)
        
        created = manager.create_wallet("test", "password")
        
        # Get with correct password
        wallet, private_key = manager.get_wallet(created.wallet_id, "password")
        
        assert wallet.wallet_id == created.wallet_id
        assert private_key is not None

    def test_get_wallet_wrong_password(self, temp_keystore):
        """Test that wrong password fails."""
        manager = WalletManager(keystore_dir=temp_keystore)
        
        created = manager.create_wallet("test", "correct-password")
        
        with pytest.raises(Exception):
            manager.get_wallet(created.wallet_id, "wrong-password")

    def test_import_from_mnemonic(self, temp_keystore):
        """Test importing wallet from mnemonic."""
        manager = WalletManager(keystore_dir=temp_keystore)
        
        # Generate a mnemonic
        mnemonic = generate_mnemonic()
        
        wallet = manager.import_from_mnemonic(
            name="imported-wallet",
            mnemonic=mnemonic,
            password="password123"
        )
        
        assert wallet.wallet_id is not None
        assert wallet.address.startswith("RTC")

    def test_import_from_keystore(self, temp_keystore):
        """Test importing wallet from keystore JSON."""
        manager = WalletManager(keystore_dir=temp_keystore)
        
        # Create and export a wallet
        original = manager.create_wallet("original", "password")
        keystore_json = manager.export_keystore(original.wallet_id)
        
        # Delete original
        manager.delete_wallet(original.wallet_id)
        
        # Re-import
        imported = manager.import_from_keystore(keystore_json, "password")
        
        assert imported.address == original.address
        assert imported.public_key_hex == original.public_key_hex

    def test_export_mnemonic(self, temp_keystore):
        """Test exporting mnemonic."""
        manager = WalletManager(keystore_dir=temp_keystore)
        
        wallet = manager.create_wallet("test", "password")
        
        mnemonic = manager.export_mnemonic(wallet.wallet_id, "password")
        
        assert validate_mnemonic(mnemonic) is True
        assert len(mnemonic.split()) == 12  # Default 12 words

    def test_delete_wallet(self, temp_keystore):
        """Test deleting wallet."""
        manager = WalletManager(keystore_dir=temp_keystore)
        
        wallet = manager.create_wallet("to-delete", "password")
        
        assert len(manager.list_wallets()) == 1
        
        deleted = manager.delete_wallet(wallet.wallet_id)
        
        assert deleted is True
        assert len(manager.list_wallets()) == 0

    def test_sign_transaction(self, temp_keystore):
        """Test transaction signing."""
        manager = WalletManager(keystore_dir=temp_keystore)
        
        wallet = manager.create_wallet("signer", "password")
        
        signed = manager.sign_transaction(
            wallet_id=wallet.wallet_id,
            password="password",
            to_address="RTC1234567890abcdef1234567890abcd",
            amount_rtc=10.0,
            memo="Test transfer"
        )
        
        assert signed["from_address"] == wallet.address
        assert signed["to_address"] == "RTC1234567890abcdef1234567890abcd"
        assert signed["amount_rtc"] == 10.0
        assert signed["signature"] is not None
        assert signed["public_key"] == wallet.public_key_hex


@pytest.mark.skipif(CRYPTO_SKIP or BIP39_SKIP, reason="crypto libraries not installed")
class TestWalletTools:
    """Test MCP wallet tools (requires mocking HTTP calls)."""

    @pytest.fixture
    def temp_keystore(self):
        """Create a temporary keystore directory."""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        shutil.rmtree(temp_dir)

    def test_wallet_create_tool(self, temp_keystore):
        """Test wallet_create tool."""
        from rustchain_mcp.rustchain_crypto import WalletManager, get_wallet_manager
        
        # Override wallet manager with temp directory
        import rustchain_mcp.rustchain_crypto as crypto_module
        original_manager = crypto_module._wallet_manager
        crypto_module._wallet_manager = WalletManager(keystore_dir=temp_keystore)
        
        try:
            from rustchain_mcp.server import wallet_create
            
            result = wallet_create(
                name="test-tool-wallet",
                password="password123",
                store_mnemonic=True,
                mnemonic_words=12
            )
            
            assert "wallet_id" in result
            assert result["address"].startswith("RTC")
            assert "public_key" in result
            assert "mnemonic" not in result  # Should NOT expose mnemonic
            assert "private_key" not in result  # Should NOT expose private key
            
        finally:
            crypto_module._wallet_manager = original_manager

    def test_wallet_list_tool(self, temp_keystore):
        """Test wallet_list tool."""
        from rustchain_mcp.rustchain_crypto import WalletManager
        import rustchain_mcp.rustchain_crypto as crypto_module
        original_manager = crypto_module._wallet_manager
        crypto_module._wallet_manager = WalletManager(keystore_dir=temp_keystore)
        
        try:
            from rustchain_mcp.server import wallet_list, wallet_create
            
            # Create wallets with valid passwords (min 8 chars)
            wallet_create("wallet1", "password1")
            wallet_create("wallet2", "password2")
            
            result = wallet_list()
            
            assert result["total"] == 2
            assert len(result["wallets"]) == 2
            
        finally:
            crypto_module._wallet_manager = original_manager

    def test_wallet_export_import_roundtrip(self, temp_keystore):
        """Test export and import roundtrip."""
        from rustchain_mcp.rustchain_crypto import WalletManager
        import rustchain_mcp.rustchain_crypto as crypto_module
        original_manager = crypto_module._wallet_manager
        crypto_module._wallet_manager = WalletManager(keystore_dir=temp_keystore)
        
        try:
            from rustchain_mcp.server import (
                wallet_create, wallet_export, wallet_import, wallet_delete
            )
            
            # Create wallet
            created = wallet_create("export-test", "password")
            
            # Export
            exported = wallet_export(created["wallet_id"])
            
            # Delete original
            wallet_delete(created["wallet_id"], confirm=True)
            
            # Re-import
            imported = wallet_import(
                source="keystore",
                password="password",
                keystore_json=exported["keystore_json"]
            )
            
            assert imported["address"] == created["address"]
            assert imported["public_key"] == created["public_key"]
            
        finally:
            crypto_module._wallet_manager = original_manager


def run_tests():
    """Run all tests."""
    pytest.main([__file__, "-v"])


if __name__ == "__main__":
    run_tests()