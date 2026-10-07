"""Cryptographic helper functions for WhatsApp backups (crypt14, crypt15).

Supports modern protobuf varint-length headers and 64-character hex keys.
"""

import hashlib
import os
from pathlib import Path
import secrets
from typing import Any
import zlib
import javaobj
from Cryptodome.Cipher import AES
from wa_crypt_tools.proto import backup_prefix_pb2
from wa_crypt_tools.lib.key.key15 import Key15


class CryptoError(Exception):
    """Exception raised for backup encryption/decryption errors."""
    pass


def read_varint(stream) -> tuple[int, bytes]:
    """Reads a protobuf varint from stream."""
    size = 0
    shift = 0
    raw = b""
    while True:
        b = stream.read(1)
        if not b:
            break
        raw += b
        val = b[0]
        size |= (val & 0x7F) << shift
        if not (val & 0x80):
            break
        shift += 7
    return size, raw


def encode_varint(n: int) -> bytes:
    """Encodes an integer as a protobuf varint."""
    res = []
    while n > 0x7F:
        res.append((n & 0x7F) | 0x80)
        n >>= 7
    res.append(n)
    return bytes(res)


def parse_key_bytes(key_input: str | Path) -> bytes:
    """Extracts 32-byte AES key from either a 64-hex string or a key file."""
    key_str = str(key_input).strip()

    # Hex string (64 characters = 32 bytes root key)
    clean_hex = key_str.replace(" ", "").replace("-", "").lower()
    if len(clean_hex) == 64:
        try:
            root_bytes = bytes.fromhex(clean_hex)
            return Key15(root_bytes).get()
        except ValueError as e:
            raise CryptoError(f"Invalid hex characters in key: {e}") from e

    # File path
    key_path = Path(key_str)
    if key_path.is_file():
        try:
            with open(key_path, "rb") as f:
                content = f.read()

            # Direct 32-byte key
            if len(content) == 32:
                return Key15(content).get()

            # Java serialized object
            with open(key_path, "rb") as f:
                pobj = javaobj.load(f)
                if hasattr(pobj, "data"):
                    # Convert list of ints to bytes
                    key_ints = pobj.data
                    key_bytes = bytes([x & 0xFF for x in key_ints])
                    if len(key_bytes) == 32:
                        return Key15(key_bytes).get()
                    elif len(key_bytes) >= 131:
                        # crypt14 key file format (AES key is at end)
                        return key_bytes[-32:]
        except Exception as e:
            raise CryptoError(f"Failed to read key file: {e}") from e

    raise CryptoError(
        f"Invalid key input: '{key_str}' is neither a 64-digit hex key nor a valid key file."
    )


def decrypt_android_backup(
    key_input: str | Path,
    encrypted_path: Path | str,
    output_path: Path | str,
) -> Path:
    """Decrypts a WhatsApp crypt15 backup file to a plain SQLite database."""
    encrypted_path = Path(encrypted_path)
    output_path = Path(output_path)

    if not encrypted_path.exists():
        raise FileNotFoundError(f"Encrypted file not found: {encrypted_path}")

    key_bytes = parse_key_bytes(key_input)

    with open(encrypted_path, "rb") as f:
        # 1. Parse header varint
        proto_size, header_bytes = read_varint(f)
        if proto_size == 0 or proto_size > 10000:
            raise CryptoError(f"Invalid protobuf header size: {proto_size}")

        proto_raw = f.read(proto_size)
        prefix = backup_prefix_pb2.BackupPrefix()
        try:
            prefix.ParseFromString(proto_raw)
        except Exception as e:
            raise CryptoError(f"Failed to parse protobuf header: {e}") from e

        iv = prefix.c15_iv.IV
        if len(iv) != 16:
            raise CryptoError(f"Invalid IV length: {len(iv)} (expected 16)")

        # 2. Read rest of the file
        rest = f.read()
        if len(rest) < 32:
            raise CryptoError("File is too short to contain valid ciphertext and tags.")

        checksum = rest[-16:]
        tag = rest[-32:-16]
        ciphertext = rest[:-32]

        # Verify MD5 integrity
        md5_h = hashlib.md5()
        md5_h.update(header_bytes)
        md5_h.update(proto_raw)
        md5_h.update(ciphertext)
        md5_h.update(tag)
        if md5_h.digest() != checksum:
            raise CryptoError("Checksum mismatch! The backup file appears to be corrupted.")

        # 3. Decrypt AES-GCM
        cipher = AES.new(key_bytes, AES.MODE_GCM, iv)
        try:
            compressed = cipher.decrypt_and_verify(ciphertext, tag)
        except ValueError as e:
            raise CryptoError(
                "Decryption failed: Authentication tag mismatch. "
                "The 64-character key provided does not match this backup!"
            ) from e

        # 4. Decompress zlib
        try:
            sqlite_data = zlib.decompress(compressed)
        except Exception as e:
            # If not compressed, maybe raw
            sqlite_data = compressed

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(sqlite_data)

    return output_path


def encrypt_android_backup(
    key_input: str | Path,
    decrypted_path: Path | str,
    output_path: Path | str,
    reference_path: Path | str | None = None,
) -> Path:
    """Encrypts a SQLite database into a WhatsApp crypt15 file.

    Preserves the exact header version and flags from reference_path if provided.
    """
    decrypted_path = Path(decrypted_path)
    output_path = Path(output_path)

    if not decrypted_path.exists():
        raise FileNotFoundError(f"Decrypted SQLite file not found: {decrypted_path}")

    key_bytes = parse_key_bytes(key_input)

    with open(decrypted_path, "rb") as f:
        sqlite_data = f.read()

    # Compress with zlib level 1 (standard WhatsApp behavior)
    compressed_data = zlib.compress(sqlite_data, 1)

    iv = secrets.token_bytes(16)
    prefix = backup_prefix_pb2.BackupPrefix()
    prefix.key_type = 1 # HSM_CONTROLLED

    # If reference file exists, clone its header fields
    if reference_path and Path(reference_path).exists():
        with open(reference_path, "rb") as f:
            ref_size, _ = read_varint(f)
            ref_proto = f.read(ref_size)
            try:
                prefix.ParseFromString(ref_proto)
            except Exception:
                pass

    prefix.c15_iv.IV = iv
    proto_bytes = prefix.SerializeToString()
    header_bytes = encode_varint(len(proto_bytes))

    # Encrypt AES-GCM
    cipher = AES.new(key_bytes, AES.MODE_GCM, iv)
    ciphertext, tag = cipher.encrypt_and_digest(compressed_data)

    # Compute MD5 Checksum
    md5_h = hashlib.md5()
    md5_h.update(header_bytes)
    md5_h.update(proto_bytes)
    md5_h.update(ciphertext)
    md5_h.update(tag)
    checksum = md5_h.digest()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(header_bytes)
        f.write(proto_bytes)
        f.write(ciphertext)
        f.write(tag)
        f.write(checksum)

    return output_path
