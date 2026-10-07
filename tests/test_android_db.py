import sqlite3
from pathlib import Path
from wa_backup.android_db import AndroidDB


def create_synthetic_android_db(db_path: Path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE jid (
            _id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT,
            server TEXT,
            agent INTEGER DEFAULT 0,
            device INTEGER DEFAULT 0,
            type INTEGER DEFAULT 0,
            raw_string TEXT UNIQUE
        );
    """)

    cur.execute("""
        CREATE TABLE chat (
            _id INTEGER PRIMARY KEY AUTOINCREMENT,
            jid_row_id INTEGER UNIQUE,
            hidden INTEGER DEFAULT 0,
            subject TEXT,
            created_timestamp INTEGER,
            sort_timestamp INTEGER,
            last_message_row_id INTEGER,
            last_read_message_row_id INTEGER,
            unseen_message_count INTEGER DEFAULT 0,
            archived INTEGER DEFAULT 0
        );
    """)

    cur.execute("""
        CREATE TABLE message (
            _id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_row_id INTEGER,
            from_me INTEGER,
            key_id TEXT,
            sender_jid_row_id INTEGER,
            timestamp INTEGER,
            received_timestamp INTEGER,
            receipt_server_timestamp INTEGER,
            message_type INTEGER,
            text_data TEXT,
            status INTEGER,
            starred INTEGER DEFAULT 0
        );
    """)

    cur.execute("""
        CREATE TABLE message_media (
            message_row_id INTEGER PRIMARY KEY,
            chat_row_id INTEGER,
            file_path TEXT,
            file_size INTEGER,
            media_name TEXT,
            mime_type TEXT,
            transferred INTEGER DEFAULT 1
        );
    """)

    conn.commit()
    conn.close()


def test_android_db_operations(tmp_path):
    android_db_file = tmp_path / "msgstore.db"
    create_synthetic_android_db(android_db_file)

    db = AndroidDB(android_db_file)

    # 1. Create JID
    jid_id = db.get_or_create_jid("34600112233@s.whatsapp.net")
    assert jid_id > 0
    # Re-fetch should use cache
    assert db.get_or_create_jid("34600112233@s.whatsapp.net") == jid_id

    # 2. Create Chat
    chat_id = db.get_or_create_chat(jid_id, subject="Alice")
    assert chat_id > 0

    # 3. Insert Message
    msg_id = db.insert_message(
        chat_row_id=chat_id,
        from_me=False,
        timestamp_ms=1680000000000,
        text="Hola desde Android",
        key_id="KEY_ANDR_1",
    )
    assert msg_id > 0

    # 4. Check duplicate detection
    assert db.is_duplicate_message("KEY_ANDR_1", chat_id, False, 1680000000000, "Hola desde Android") is True
    assert db.is_duplicate_message("KEY_NEW", chat_id, False, 1700000000000, "Nuevo texto") is False

    # 5. Metadata refresh
    db.refresh_chat_metadata()
    db.commit()

    # Verify chat was updated with last_message_row_id
    cur = db.conn.cursor()
    cur.execute("SELECT last_message_row_id, sort_timestamp FROM chat WHERE _id = ?", (chat_id,))
    row = cur.fetchone()
    assert row[0] == msg_id
    assert row[1] == 1680000000000

    db.close()
