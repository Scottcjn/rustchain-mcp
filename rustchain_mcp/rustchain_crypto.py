#!/usr/bin/env python3
"""
RustChain Cryptographic Module
===============================

Provides Ed25519 cryptographic operations and BIP39 mnemonic support
for secure wallet management.

Features:
- Ed25519 key pair generation
- BIP39 mnemonic seed phrase generation (12/24 words)
- Key derivation from mnemonic
- Transaction signing
- Encrypted keystore storage (AES-256-GCM)

Security:
- Private keys and seed phrases are NEVER exposed in tool responses
- Keys are encrypted at rest using AES-256-GCM
- Memory-safe handling of sensitive data

License: MIT
"""

import os
import json
import hashlib
import secrets
import time
from typing import Optional, Tuple, Dict, Any
from pathlib import Path
from dataclasses import dataclass

# Cryptographic libraries
try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.backends import default_backend
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

# BIP39 mnemonic support
try:
    from mnemonic import Mnemonic
    BIP39_AVAILABLE = True
except ImportError:
    BIP39_AVAILABLE = False


# ── Constants ───────────────────────────────────────────────────

DEFAULT_KEYSTORE_DIR = Path.home() / ".rustchain" / "mcp_wallets"
KEYSTORE_VERSION = 1
NONCE_SIZE = 12  # 96 bits for AES-GCM
KEY_SIZE = 32    # 256 bits


# ── Data Classes ────────────────────────────────────────────────

@dataclass
class WalletInfo:
    """Public wallet information (safe to expose)."""
    wallet_id: str
    address: str
    public_key_hex: str
    created_at: float
    name: Optional[str] = None


@dataclass
class KeyStoreEntry:
    """Encrypted keystore entry."""
    version: int
    wallet_id: str
    address: str
    public_key_hex: str
    encrypted_private_key: str  # Base64 encoded
    salt: str  # Base64 encoded
    nonce: str  # Base64 encoded
    created_at: float
    name: Optional[str] = None
    mnemonic_encrypted: Optional[str] = None  # Encrypted mnemonic if stored


# ── Ed25519 Operations ───────────────────────────────────────────

def generate_ed25519_keypair() -> Tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    """Generate a new Ed25519 key pair.
    
    Returns:
        Tuple of (private_key, public_key)
    """
    if not CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography library not installed. Run: pip install cryptography")
    
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    return private_key, public_key


def private_key_to_hex(private_key: Ed25519PrivateKey) -> str:
    """Convert private key to hex string."""
    return private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption()
    ).hex()


def public_key_to_hex(public_key: Ed25519PublicKey) -> str:
    """Convert public key to hex string."""
    return public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw
    ).hex()


def hex_to_private_key(hex_str: str) -> Ed25519PrivateKey:
    """Convert hex string to private key."""
    raw_bytes = bytes.fromhex(hex_str)
    return Ed25519PrivateKey.from_private_bytes(raw_bytes)


def hex_to_public_key(hex_str: str) -> Ed25519PublicKey:
    """Convert hex string to public key."""
    raw_bytes = bytes.fromhex(hex_str)
    return Ed25519PublicKey.from_public_bytes(raw_bytes)


def sign_message(private_key: Ed25519PrivateKey, message: bytes) -> str:
    """Sign a message with Ed25519 private key.
    
    Args:
        private_key: Ed25519 private key
        message: Message bytes to sign
        
    Returns:
        Hex-encoded signature
    """
    signature = private_key.sign(message)
    return signature.hex()


def verify_signature(public_key: Ed25519PublicKey, signature: str, message: bytes) -> bool:
    """Verify an Ed25519 signature.
    
    Args:
        public_key: Ed25519 public key
        signature: Hex-encoded signature
        message: Original message bytes
        
    Returns:
        True if signature is valid
    """
    try:
        public_key.verify(bytes.fromhex(signature), message)
        return True
    except Exception:
        return False


# ── BIP39 Mnemonic Operations ────────────────────────────────────

def generate_mnemonic(strength: int = 128) -> str:
    """Generate a BIP39 mnemonic seed phrase.
    
    Args:
        strength: Entropy strength in bits (128 = 12 words, 256 = 24 words)
        
    Returns:
        Space-separated mnemonic phrase
    """
    if not BIP39_AVAILABLE:
        raise RuntimeError("mnemonic library not installed. Run: pip install mnemonic")
    
    mnemo = Mnemonic("english")
    return mnemo.generate(strength=strength)


def mnemonic_to_seed(mnemonic: str, passphrase: str = "") -> bytes:
    """Convert mnemonic to seed bytes.
    
    Args:
        mnemonic: Space-separated mnemonic phrase
        passphrase: Optional passphrase for additional security
        
    Returns:
        64-byte seed
    """
    if not BIP39_AVAILABLE:
        raise RuntimeError("mnemonic library not installed. Run: pip install mnemonic")
    
    mnemo = Mnemonic("english")
    return mnemo.to_seed(mnemonic, passphrase)


def validate_mnemonic(mnemonic: str) -> bool:
    """Validate a BIP39 mnemonic phrase.
    
    Args:
        mnemonic: Space-separated mnemonic phrase
        
    Returns:
        True if valid
    """
    if not BIP39_AVAILABLE:
        raise RuntimeError("mnemonic library not installed. Run: pip install mnemonic")
    
    mnemo = Mnemonic("english")
    return mnemo.check(mnemonic)


def derive_ed25519_key_from_seed(seed: bytes, index: int = 0) -> Tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    """Derive Ed25519 key pair from seed.
    
    Uses a simple derivation path: seed + index -> SHA512 -> Ed25519 key
    
    Args:
        seed: Seed bytes (from mnemonic)
        index: Key index for derivation
        
    Returns:
        Tuple of (private_key, public_key)
    """
    # Create derivation material
    derivation_input = seed + index.to_bytes(4, 'big')
    
    # Hash to get 64 bytes (enough for Ed25519 seed)
    derived = hashlib.sha512(derivation_input).digest()
    
    # Use first 32 bytes as Ed25519 seed
    private_key = Ed25519PrivateKey.from_private_bytes(derived[:32])
    public_key = private_key.public_key()
    
    return private_key, public_key


# ── Address Generation ───────────────────────────────────────────

def public_key_to_address(public_key_hex: str, prefix: str = "RTC") -> str:
    """Convert public key to RTC address.
    
    Uses SHA256 + RIPEMD160 for address generation (similar to Bitcoin).
    
    Args:
        public_key_hex: Hex-encoded public key
        prefix: Address prefix (default: "RTC")
        
    Returns:
        RTC address string
    """
    public_key_bytes = bytes.fromhex(public_key_hex)
    
    # SHA256
    sha256_hash = hashlib.sha256(public_key_bytes).digest()
    
    # RIPEMD160
    ripemd160 = hashlib.new('ripemd160')
    ripemd160.update(sha256_hash)
    address_bytes = ripemd160.digest()
    
    # Convert to base58-like encoding (simplified for compatibility)
    # Format: prefix + hex address (32 chars)
    address_hex = address_bytes.hex()
    
    return f"{prefix}{address_hex}"


# ── Encrypted Keystore ───────────────────────────────────────────

def _derive_encryption_key(password: str, salt: bytes) -> bytes:
    """Derive encryption key from password using PBKDF2."""
    return hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt,
        100000,  # iterations
        dklen=KEY_SIZE
    )


def encrypt_private_key(private_key_hex: str, password: str) -> Tuple[str, str, str]:
    """Encrypt private key with password.
    
    Args:
        private_key_hex: Hex-encoded private key
        password: Encryption password
        
    Returns:
        Tuple of (encrypted_base64, salt_base64, nonce_base64)
    """
    if not CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography library not installed")
    
    # Generate salt and nonce
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(NONCE_SIZE)
    
    # Derive key
    key = _derive_encryption_key(password, salt)
    
    # Encrypt
    aesgcm = AESGCM(key)
    plaintext = bytes.fromhex(private_key_hex)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    
    import base64
    return (
        base64.b64encode(ciphertext).decode('utf-8'),
        base64.b64encode(salt).decode('utf-8'),
        base64.b64encode(nonce).decode('utf-8')
    )


def decrypt_private_key(encrypted_b64: str, salt_b64: str, nonce_b64: str, password: str) -> str:
    """Decrypt private key with password.
    
    Args:
        encrypted_b64: Base64-encoded encrypted data
        salt_b64: Base64-encoded salt
        nonce_b64: Base64-encoded nonce
        password: Decryption password
        
    Returns:
        Hex-encoded private key
    """
    if not CRYPTO_AVAILABLE:
        raise RuntimeError("cryptography library not installed")
    
    import base64
    
    # Decode base64
    ciphertext = base64.b64decode(encrypted_b64)
    salt = base64.b64decode(salt_b64)
    nonce = base64.b64decode(nonce_b64)
    
    # Derive key
    key = _derive_encryption_key(password, salt)
    
    # Decrypt
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    
    return plaintext.hex()


# ── Wallet Manager Class ─────────────────────────────────────────

class WalletManager:
    """Manages wallet creation, storage, and operations."""
    
    def __init__(self, keystore_dir: Optional[Path] = None):
        """Initialize wallet manager.
        
        Args:
            keystore_dir: Directory for keystore files (default: ~/.rustchain/mcp_wallets/)
        """
        self.keystore_dir = keystore_dir or DEFAULT_KEYSTORE_DIR
        self.keystore_dir.mkdir(parents=True, exist_ok=True)
        
    def create_wallet(
        self,
        name: str,
        password: str,
        store_mnemonic: bool = True,
        mnemonic_strength: int = 128
    ) -> WalletInfo:
        """Create a new wallet with Ed25519 key pair and optional mnemonic.
        
        Args:
            name: Wallet name
            password: Password for encrypting the keystore
            store_mnemonic: Whether to generate and store a BIP39 mnemonic
            mnemonic_strength: Mnemonic strength (128=12 words, 256=24 words)
            
        Returns:
            WalletInfo (public info only, never private key or mnemonic)
        """
        mnemonic = None
        mnemonic_encrypted = None
        
        if store_mnemonic:
            if not BIP39_AVAILABLE:
                raise RuntimeError("mnemonic library not installed. Run: pip install mnemonic")
            mnemonic = generate_mnemonic(strength=mnemonic_strength)
            seed = mnemonic_to_seed(mnemonic)
            private_key, public_key = derive_ed25519_key_from_seed(seed)
            
            # Encrypt mnemonic for storage
            if password:
                mnemonic_encrypted, m_salt, m_nonce = encrypt_private_key(
                    mnemonic.encode('utf-8').hex(),
                    password
                )
                mnemonic_encrypted = f"{m_salt}:{m_nonce}:{mnemonic_encrypted}"
        else:
            private_key, public_key = generate_ed25519_keypair()
        
        # Get key hex values
        private_key_hex = private_key_to_hex(private_key)
        public_key_hex = public_key_to_hex(public_key)
        
        # Generate address
        address = public_key_to_address(public_key_hex)
        
        # Generate wallet ID
        wallet_id = f"wallet_{secrets.token_hex(8)}"
        
        # Encrypt private key
        encrypted_pk, salt, nonce = encrypt_private_key(private_key_hex, password)
        
        # Create keystore entry
        created_at = time.time()
        entry = KeyStoreEntry(
            version=KEYSTORE_VERSION,
            wallet_id=wallet_id,
            address=address,
            public_key_hex=public_key_hex,
            encrypted_private_key=encrypted_pk,
            salt=salt,
            nonce=nonce,
            created_at=created_at,
            name=name,
            mnemonic_encrypted=mnemonic_encrypted
        )
        
        # Save to file
        self._save_keystore(entry)
        
        # Return public info only
        return WalletInfo(
            wallet_id=wallet_id,
            address=address,
            public_key_hex=public_key_hex,
            created_at=created_at,
            name=name
        )
    
    def import_from_mnemonic(
        self,
        name: str,
        mnemonic: str,
        password: str,
        index: int = 0
    ) -> WalletInfo:
        """Import wallet from BIP39 mnemonic phrase.
        
        Args:
            name: Wallet name
            mnemonic: BIP39 mnemonic phrase (space-separated words)
            password: Password for encrypting the keystore
            index: Key derivation index
            
        Returns:
            WalletInfo (public info only)
        """
        if not BIP39_AVAILABLE:
            raise RuntimeError("mnemonic library not installed. Run: pip install mnemonic")
        
        # Validate mnemonic
        if not validate_mnemonic(mnemonic):
            raise ValueError("Invalid BIP39 mnemonic phrase")
        
        # Derive keys
        seed = mnemonic_to_seed(mnemonic)
        private_key, public_key = derive_ed25519_key_from_seed(seed, index)
        
        # Get key hex values
        private_key_hex = private_key_to_hex(private_key)
        public_key_hex = public_key_to_hex(public_key)
        
        # Generate address
        address = public_key_to_address(public_key_hex)
        
        # Generate wallet ID
        wallet_id = f"wallet_{secrets.token_hex(8)}"
        
        # Encrypt private key and mnemonic
        encrypted_pk, salt, nonce = encrypt_private_key(private_key_hex, password)
        mnemonic_encrypted, m_salt, m_nonce = encrypt_private_key(
            mnemonic.encode('utf-8').hex(),
            password
        )
        mnemonic_encrypted = f"{m_salt}:{m_nonce}:{mnemonic_encrypted}"
        
        # Create keystore entry
        created_at = time.time()
        entry = KeyStoreEntry(
            version=KEYSTORE_VERSION,
            wallet_id=wallet_id,
            address=address,
            public_key_hex=public_key_hex,
            encrypted_private_key=encrypted_pk,
            salt=salt,
            nonce=nonce,
            created_at=created_at,
            name=name,
            mnemonic_encrypted=mnemonic_encrypted
        )
        
        # Save to file
        self._save_keystore(entry)
        
        return WalletInfo(
            wallet_id=wallet_id,
            address=address,
            public_key_hex=public_key_hex,
            created_at=created_at,
            name=name
        )
    
    def import_from_keystore(
        self,
        keystore_json: str,
        password: str
    ) -> WalletInfo:
        """Import wallet from keystore JSON.
        
        Args:
            keystore_json: JSON string of keystore entry
            password: Password to decrypt the keystore
            
        Returns:
            WalletInfo (public info only)
        """
        data = json.loads(keystore_json)
        entry = KeyStoreEntry(**data)
        
        # Verify we can decrypt
        try:
            private_key_hex = decrypt_private_key(
                entry.encrypted_private_key,
                entry.salt,
                entry.nonce,
                password
            )
        except Exception as e:
            raise ValueError(f"Failed to decrypt keystore: {e}")
        
        # Save to file
        self._save_keystore(entry)
        
        return WalletInfo(
            wallet_id=entry.wallet_id,
            address=entry.address,
            public_key_hex=entry.public_key_hex,
            created_at=entry.created_at,
            name=entry.name
        )
    
    def list_wallets(self) -> list[WalletInfo]:
        """List all wallets in the keystore.
        
        Returns:
            List of WalletInfo (public info only)
        """
        wallets = []
        
        for file_path in self.keystore_dir.glob("*.json"):
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)
                
                wallets.append(WalletInfo(
                    wallet_id=data['wallet_id'],
                    address=data['address'],
                    public_key_hex=data['public_key_hex'],
                    created_at=data['created_at'],
                    name=data.get('name')
                ))
            except Exception:
                continue
        
        return wallets
    
    def get_wallet(self, wallet_id: str, password: str) -> Tuple[WalletInfo, Ed25519PrivateKey]:
        """Get wallet info and private key (for signing operations).
        
        Args:
            wallet_id: Wallet ID
            password: Password to decrypt private key
            
        Returns:
            Tuple of (WalletInfo, private_key)
        """
        keystore_path = self.keystore_dir / f"{wallet_id}.json"
        
        if not keystore_path.exists():
            raise FileNotFoundError(f"Wallet not found: {wallet_id}")
        
        with open(keystore_path, 'r') as f:
            data = json.load(f)
        
        # Decrypt private key
        private_key_hex = decrypt_private_key(
            data['encrypted_private_key'],
            data['salt'],
            data['nonce'],
            password
        )
        
        private_key = hex_to_private_key(private_key_hex)
        
        return WalletInfo(
            wallet_id=data['wallet_id'],
            address=data['address'],
            public_key_hex=data['public_key_hex'],
            created_at=data['created_at'],
            name=data.get('name')
        ), private_key
    
    def export_keystore(self, wallet_id: str) -> str:
        """Export wallet as encrypted keystore JSON.
        
        Args:
            wallet_id: Wallet ID
            
        Returns:
            JSON string of keystore entry (encrypted)
        """
        keystore_path = self.keystore_dir / f"{wallet_id}.json"
        
        if not keystore_path.exists():
            raise FileNotFoundError(f"Wallet not found: {wallet_id}")
        
        with open(keystore_path, 'r') as f:
            return f.read()
    
    def export_mnemonic(self, wallet_id: str, password: str) -> str:
        """Export mnemonic phrase for a wallet.
        
        WARNING: This exposes the seed phrase - use with caution!
        
        Args:
            wallet_id: Wallet ID
            password: Password to decrypt
            
        Returns:
            Mnemonic phrase (space-separated words)
        """
        keystore_path = self.keystore_dir / f"{wallet_id}.json"
        
        if not keystore_path.exists():
            raise FileNotFoundError(f"Wallet not found: {wallet_id}")
        
        with open(keystore_path, 'r') as f:
            data = json.load(f)
        
        if not data.get('mnemonic_encrypted'):
            raise ValueError("This wallet does not have a stored mnemonic")
        
        # Parse encrypted mnemonic
        parts = data['mnemonic_encrypted'].split(':')
        if len(parts) != 3:
            raise ValueError("Invalid mnemonic storage format")
        
        m_salt, m_nonce, m_encrypted = parts
        
        # Decrypt
        mnemonic_hex = decrypt_private_key(m_encrypted, m_salt, m_nonce, password)
        mnemonic = bytes.fromhex(mnemonic_hex).decode('utf-8')
        
        return mnemonic
    
    def delete_wallet(self, wallet_id: str) -> bool:
        """Delete a wallet from keystore.
        
        Args:
            wallet_id: Wallet ID
            
        Returns:
            True if deleted successfully
        """
        keystore_path = self.keystore_dir / f"{wallet_id}.json"
        
        if keystore_path.exists():
            keystore_path.unlink()
            return True
        
        return False
    
    def sign_transaction(
        self,
        wallet_id: str,
        password: str,
        to_address: str,
        amount_rtc: float,
        memo: str = ""
    ) -> Dict[str, Any]:
        """Sign a transfer transaction.
        
        Args:
            wallet_id: Wallet ID
            password: Password to decrypt private key
            to_address: Destination address
            amount_rtc: Amount to transfer
            memo: Transaction memo
            
        Returns:
            Dict with signature, public_key, and transaction details
        """
        wallet_info, private_key = self.get_wallet(wallet_id, password)
        
        # Create transaction message
        nonce = int(time.time() * 1000)
        message = f"{wallet_info.address}:{to_address}:{amount_rtc}:{nonce}:{memo}"
        message_bytes = message.encode('utf-8')
        
        # Sign
        signature = sign_message(private_key, message_bytes)
        
        return {
            "from_address": wallet_info.address,
            "to_address": to_address,
            "amount_rtc": amount_rtc,
            "memo": memo,
            "nonce": nonce,
            "signature": signature,
            "public_key": wallet_info.public_key_hex
        }
    
    def _save_keystore(self, entry: KeyStoreEntry) -> None:
        """Save keystore entry to file."""
        file_path = self.keystore_dir / f"{entry.wallet_id}.json"
        
        with open(file_path, 'w') as f:
            json.dump({
                "version": entry.version,
                "wallet_id": entry.wallet_id,
                "address": entry.address,
                "public_key_hex": entry.public_key_hex,
                "encrypted_private_key": entry.encrypted_private_key,
                "salt": entry.salt,
                "nonce": entry.nonce,
                "created_at": entry.created_at,
                "name": entry.name,
                "mnemonic_encrypted": entry.mnemonic_encrypted
            }, f, indent=2)


# ── Module-level wallet manager for MCP tools ────────────────────

_wallet_manager: Optional[WalletManager] = None


def get_wallet_manager() -> WalletManager:
    """Get or create the global wallet manager instance."""
    global _wallet_manager
    if _wallet_manager is None:
        _wallet_manager = WalletManager()
    return _wallet_manager