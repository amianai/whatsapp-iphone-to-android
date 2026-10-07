import secrets
from pathlib import Path
from wa_backup.crypto import decrypt_android_backup, encrypt_android_backup


def test_crypto_roundtrip(tmp_path):
    dummy_db = tmp_path / "dummy.db"
    dummy_db.write_bytes(b"SQLite format 3\x00Dummy SQLite payload data for testing 1234567890")

    key_hex = secrets.token_hex(32) # 64 hex chars = 32 bytes
    encrypted_file = tmp_path / "msgstore.db.crypt15"
    decrypted_file = tmp_path / "msgstore_decrypted.db"

    # Encrypt
    encrypt_android_backup(
        key_input=key_hex,
        decrypted_path=dummy_db,
        output_path=encrypted_file,
    )
    assert encrypted_file.exists()
    assert encrypted_file.stat().st_size > len(dummy_db.read_bytes())

    # Decrypt
    decrypt_android_backup(
        key_input=key_hex,
        encrypted_path=encrypted_file,
        output_path=decrypted_file,
    )
    assert decrypted_file.exists()
    assert decrypted_file.read_bytes() == dummy_db.read_bytes()
