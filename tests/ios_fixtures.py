"""Builders for synthetic iOS WhatsApp databases and iPhone backups.

The encrypted backup is written with the same format iphone_backup_decrypt
reads: a passphrase-protected keybag in Manifest.plist, an AES-CBC encrypted
Manifest.db, and per-file keys wrapped with the protection class key.
"""

import hashlib
import os
import plistlib
import sqlite3
import struct
from pathlib import Path

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

APPLE_EPOCH = 978307200
DOMAIN = "AppDomainGroup-group.net.whatsapp.WhatsApp.shared"

IOS_SCHEMA = """
CREATE TABLE ZWACHATSESSION (
    Z_PK INTEGER PRIMARY KEY, ZCONTACTJID TEXT, ZCONTACTIDENTIFIER TEXT, ZSESSIONTYPE INTEGER,
    ZPARTNERNAME TEXT, ZUNREADCOUNT INTEGER, ZMESSAGECOUNTER INTEGER, ZARCHIVED INTEGER);
CREATE TABLE ZWAGROUPMEMBER (
    Z_PK INTEGER PRIMARY KEY, ZCHATSESSION INTEGER, ZMEMBERJID TEXT, ZCONTACTIDENTIFIER TEXT,
    ZCONTACTNAME TEXT);
CREATE TABLE ZWAMEDIAITEM (
    Z_PK INTEGER PRIMARY KEY, ZMESSAGE INTEGER, ZMEDIALOCALPATH TEXT, ZFILESIZE INTEGER,
    ZVCARDSTRING TEXT, ZVCARDNAME TEXT, ZTITLE TEXT, ZLATITUDE REAL, ZLONGITUDE REAL,
    ZMOVIEDURATION INTEGER);
CREATE TABLE ZWAMESSAGE (
    Z_PK INTEGER PRIMARY KEY, ZCHATSESSION INTEGER, ZISFROMME INTEGER, ZMESSAGEDATE REAL,
    ZTEXT TEXT, ZMESSAGETYPE INTEGER, ZMESSAGESTATUS INTEGER, ZSTANZAID TEXT, ZFROMJID TEXT,
    ZMEDIAITEM INTEGER, ZGROUPMEMBER INTEGER, ZSTARRED INTEGER, ZSORT INTEGER);
CREATE TABLE ZWAPROFILEPUSHNAME (Z_PK INTEGER PRIMARY KEY, ZJID TEXT, ZPUSHNAME TEXT);
"""

# Columns modelled on a modern msgstore.db (same shape as tests/test_fix_integrity.py).
ANDROID_SCHEMA = """
CREATE TABLE jid (
    _id INTEGER PRIMARY KEY AUTOINCREMENT,
    user TEXT, server TEXT, agent INTEGER DEFAULT 0, device INTEGER DEFAULT 0,
    type INTEGER DEFAULT 0, raw_string TEXT UNIQUE);
CREATE TABLE chat (
    _id INTEGER PRIMARY KEY AUTOINCREMENT,
    jid_row_id INTEGER UNIQUE, account_jid_row_id INTEGER,
    hidden INTEGER DEFAULT 0, subject TEXT, created_timestamp INTEGER,
    sort_timestamp INTEGER, last_message_row_id INTEGER, display_message_row_id INTEGER,
    last_message_sort_id INTEGER, display_message_sort_id INTEGER,
    last_read_message_sort_id INTEGER, last_read_receipt_sent_message_sort_id INTEGER,
    unseen_message_count INTEGER DEFAULT 0, archived INTEGER DEFAULT 0, chat_origin TEXT);
CREATE TABLE message (
    _id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_row_id INTEGER, from_me INTEGER, key_id TEXT, sender_jid_row_id INTEGER,
    timestamp INTEGER, received_timestamp INTEGER, receipt_server_timestamp INTEGER,
    message_type INTEGER, text_data TEXT, status INTEGER, starred INTEGER DEFAULT 0,
    broadcast INTEGER, recipient_count INTEGER, origination_flags INTEGER,
    origin INTEGER, lookup_tables INTEGER, sort_id INTEGER DEFAULT 0,
    message_add_on_flags INTEGER, view_mode INTEGER);
CREATE UNIQUE INDEX message_key_index ON message (chat_row_id, from_me, key_id, sender_jid_row_id);
CREATE TABLE message_media (
    message_row_id INTEGER PRIMARY KEY, chat_row_id INTEGER,
    autotransfer_retry_enabled INTEGER, transferred INTEGER, transcoded INTEGER,
    file_path TEXT, file_size INTEGER, file_length INTEGER, suspicious_content INTEGER,
    trim_from INTEGER, trim_to INTEGER, face_x INTEGER, face_y INTEGER,
    media_key_timestamp INTEGER, width INTEGER, height INTEGER,
    has_streaming_sidecar INTEGER, gif_attribution INTEGER,
    thumbnail_height_width_ratio REAL, first_scan_length INTEGER,
    mime_type TEXT, media_name TEXT, file_hash TEXT, media_duration INTEGER,
    page_count INTEGER, mute_video INTEGER, media_transcode_quality INTEGER);
CREATE TABLE jid_map(lid_row_id INTEGER PRIMARY KEY NOT NULL, jid_row_id INTEGER NOT NULL, sort_id INTEGER);
CREATE TABLE lid_chat_state(
    jid_row_id INTEGER PRIMARY KEY NOT NULL, is_pn_shared INTEGER NOT NULL DEFAULT 0,
    pn_requested_ts INTEGER NOT NULL DEFAULT 0, pnh_duplicate_lid_thread INTEGER NOT NULL DEFAULT 0);
"""


def create_android_template(path: Path) -> Path:
    conn = sqlite3.connect(path)
    conn.executescript(ANDROID_SCHEMA)
    conn.commit()
    conn.close()
    return path


class ChatStorage:
    """A small ChatStorage.sqlite with helpers to add chats and messages."""

    def __init__(self, path: Path, wal: bool = False):
        self.path = Path(path)
        self.conn = sqlite3.connect(self.path)
        if wal:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA wal_autocheckpoint=0")
        self.conn.executescript(IOS_SCHEMA)
        self.conn.commit()
        self._pk = 0
        self._sort: dict[int, int] = {}  # per-chat ZSORT, like WhatsApp

    def _next(self) -> int:
        self._pk += 1
        return self._pk

    def chat(self, jid, name=None, session_type=0, identifier=None, archived=False) -> int:
        pk = self._next()
        self.conn.execute(
            "INSERT INTO ZWACHATSESSION VALUES (?,?,?,?,?,0,0,?)",
            (pk, jid, identifier, session_type, name, 1 if archived else 0),
        )
        return pk

    def member(self, chat_pk, jid, identifier=None) -> int:
        pk = self._next()
        self.conn.execute("INSERT INTO ZWAGROUPMEMBER VALUES (?,?,?,?,NULL)", (pk, chat_pk, jid, identifier))
        return pk

    def push_name(self, jid, name):
        self.conn.execute("INSERT INTO ZWAPROFILEPUSHNAME VALUES (?,?,?)", (self._next(), jid, name))

    def message(self, chat_pk, unix_ts, text=None, from_me=False, ios_type=0, stanza=None,
                member=None, media=None, starred=False) -> int:
        pk = self._next()
        media_pk = None
        if media is not None:
            media_pk = self._next()
            self.conn.execute(
                "INSERT INTO ZWAMEDIAITEM VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    media_pk, pk, media.get("path"), media.get("size", 0), media.get("vcard"),
                    media.get("vcard_name"), media.get("title"), media.get("lat"), media.get("lon"),
                    media.get("duration", 0),
                ),
            )
        self.conn.execute(
            "INSERT INTO ZWAMESSAGE VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                pk, chat_pk, 1 if from_me else 0, unix_ts - APPLE_EPOCH, text, ios_type, 0,
                stanza or f"STANZA{pk}", None, media_pk, member, 1 if starred else 0,
                self._sort.setdefault(chat_pk, 0) + 1,
            ),
        )
        self._sort[chat_pk] += 1
        return pk

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.commit()
        self.conn.close()


def _file_id(domain: str, rel: str) -> str:
    return hashlib.sha1(f"{domain}-{rel}".encode()).hexdigest()


def _manifest_db(path: Path, rows):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE Files (fileID TEXT PRIMARY KEY, domain TEXT, relativePath TEXT, flags INTEGER, file BLOB)"
    )
    conn.executemany("INSERT INTO Files VALUES (?,?,?,?,?)", rows)
    conn.commit()
    conn.close()


def make_plain_backup(backup_dir: Path, files: dict[str, bytes], domain: str = DOMAIN) -> Path:
    """Unencrypted Finder backup holding the given files of the WhatsApp container."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for rel, data in files.items():
        fid = _file_id(domain, rel)
        (backup_dir / fid[:2]).mkdir(exist_ok=True)
        (backup_dir / fid[:2] / fid).write_bytes(data)
        rows.append((fid, domain, rel, 1, plistlib.dumps({"Size": len(data)}, fmt=plistlib.FMT_BINARY)))
    rows.append((_file_id(domain, "Message"), domain, "Message", 2, b""))  # a folder entry
    _manifest_db(backup_dir / "Manifest.db", rows)
    with open(backup_dir / "Manifest.plist", "wb") as f:
        plistlib.dump({"IsEncrypted": False}, f)
    return backup_dir


def _tlv(tag: bytes, value) -> bytes:
    data = struct.pack(">L", value) if isinstance(value, int) else value
    return tag + struct.pack(">L", len(data)) + data


def _wrap(kek: bytes, key: bytes) -> bytes:
    return AES.new(kek, AES.MODE_KW).seal(key)


def _cbc(key: bytes, data: bytes) -> bytes:
    return AES.new(key, AES.MODE_CBC, iv=b"\x00" * 16).encrypt(pad(data, 16))


def _file_plist(size: int, wrapped_key: bytes, protection_class: int, mtime: int) -> bytes:
    root = {
        "Size": size,
        "ProtectionClass": protection_class,
        "LastModified": mtime,
        "Birth": mtime,
        "Mode": 0o100644,
        "EncryptionKey": plistlib.UID(2),
    }
    archive = {
        "$version": 100000,
        "$archiver": "NSKeyedArchiver",
        "$top": {"root": plistlib.UID(1)},
        "$objects": ["$null", root, {"NS.data": struct.pack("<l", protection_class) + wrapped_key}],
    }
    return plistlib.dumps(archive, fmt=plistlib.FMT_BINARY)


def make_encrypted_backup(backup_dir: Path, files: dict[str, bytes], password: str,
                          domain: str = DOMAIN, mtime: int = 1_700_000_000) -> Path:
    """Encrypted Finder backup holding the given files of the WhatsApp container."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    protection_class = 3
    dpsl, salt = os.urandom(20), os.urandom(20)
    dpic, iterations = 1, 1
    round1 = hashlib.pbkdf2_hmac("sha256", password.encode(), dpsl, dpic, 32)
    passphrase_key = hashlib.pbkdf2_hmac("sha1", round1, salt, iterations, 32)
    class_key = os.urandom(32)

    keybag = b"".join([
        _tlv(b"VERS", 3), _tlv(b"TYPE", 1), _tlv(b"UUID", os.urandom(16)), _tlv(b"HMCK", os.urandom(40)),
        _tlv(b"WRAP", 0), _tlv(b"SALT", salt), _tlv(b"ITER", iterations),
        _tlv(b"DPWT", 1), _tlv(b"DPIC", dpic), _tlv(b"DPSL", dpsl),
        _tlv(b"UUID", os.urandom(16)), _tlv(b"CLAS", protection_class), _tlv(b"WRAP", 2),
        _tlv(b"KTYP", 0), _tlv(b"WPKY", _wrap(passphrase_key, class_key)),
    ])

    rows = []
    for rel, data in files.items():
        fid = _file_id(domain, rel)
        file_key = os.urandom(32)
        (backup_dir / fid[:2]).mkdir(exist_ok=True)
        (backup_dir / fid[:2] / fid).write_bytes(_cbc(file_key, data))
        plist = _file_plist(len(data), _wrap(class_key, file_key), protection_class, mtime)
        rows.append((fid, domain, rel, 1, plist))

    plain_manifest = backup_dir / "Manifest.plain.db"
    _manifest_db(plain_manifest, rows)
    manifest_key = os.urandom(32)
    (backup_dir / "Manifest.db").write_bytes(_cbc(manifest_key, plain_manifest.read_bytes()))
    plain_manifest.unlink()

    with open(backup_dir / "Manifest.plist", "wb") as f:
        plistlib.dump(
            {
                "IsEncrypted": True,
                "BackupKeyBag": keybag,
                "ManifestKey": struct.pack("<l", protection_class) + _wrap(class_key, manifest_key),
            },
            f,
        )
    return backup_dir
