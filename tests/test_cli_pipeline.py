"""End-to-end run of the CLI pipeline on an encrypted iPhone backup and a crypt15 template."""

import secrets
import sqlite3
import sys

from tests.ios_fixtures import ChatStorage, create_android_template, make_encrypted_backup
from wa_fuse import cli
from wa_fuse.crypto import decrypt_android_backup, encrypt_android_backup

ALICE = "391111111111@s.whatsapp.net"
T0 = 1_700_000_000


def test_pipeline_end_to_end(tmp_path, monkeypatch):
    build = tmp_path / "build"
    build.mkdir()
    ios = ChatStorage(build / "ChatStorage.sqlite")
    alice = ios.chat(ALICE, "Alice")
    ios.push_name(ALICE, "Alice")
    for i in range(3):
        ios.message(alice, T0 + i * 0.3, ios_type=1, media={"path": f"Media/{ALICE}/1/1/p{i}.jpg", "vcard": "image/jpeg"})
    ios.message(alice, T0 + 5, text="ciao", from_me=True)
    ios.close()
    files = {"ChatStorage.sqlite": (build / "ChatStorage.sqlite").read_bytes()}
    files.update({f"Message/Media/{ALICE}/1/1/p{i}.jpg": f"photo{i}".encode() for i in range(3)})
    backup = make_encrypted_backup(tmp_path / "iphone_backup", files, password="pw")

    key = secrets.token_hex(32)
    template_db = create_android_template(tmp_path / "template.db")
    template = encrypt_android_backup(key, template_db, tmp_path / "msgstore.db.crypt15")

    out = tmp_path / "output"
    monkeypatch.setenv("IOS_BACKUP_PASSWORD", "pw")
    monkeypatch.setattr(sys, "argv", [
        "wa-fuse", "pipeline", "--ios", str(backup), "--android-crypt", str(template), "--key", key,
        "--output-dir", str(out), "--staging-dir", str(tmp_path / "staging"), "--move-media",
    ])
    cli.main()

    restored = decrypt_android_backup(key, out / "msgstore.db.crypt15", tmp_path / "check.db")
    conn = sqlite3.connect(restored)
    assert conn.execute("SELECT count(*) FROM message").fetchone()[0] == 4
    paths = [r[0] for r in conn.execute("SELECT file_path FROM message_media ORDER BY message_row_id")]
    conn.close()
    assert paths == [f"Media/WhatsApp Images/p{i}.jpg" for i in range(3)]
    assert all((out / "WhatsApp" / p).exists() for p in paths)
    assert (out / "report.json").exists()

    monkeypatch.setattr(sys, "argv", [
        "wa-fuse", "export-contacts", "--ios", str(backup), "--staging-dir", str(tmp_path / "staging"),
        "--output", str(tmp_path / "c.vcf"),
    ])
    cli.main()
    assert "TEL;TYPE=CELL:+391111111111" in (tmp_path / "c.vcf").read_bytes().decode()
