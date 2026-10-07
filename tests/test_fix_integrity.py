import sqlite3
from pathlib import Path
from wa_fuse.android_db import AndroidDB
from wa_fuse.ios_extractor import IOSExtractor
from wa_fuse.merger import BackupMerger


def test_status_jids_filtered_and_media_complete(tmp_path):
    # Setup synthetic iOS DB with a status chat, a 1-on-1 LID chat with PN identifier, and a group
    ios_file = tmp_path / "ChatStorage.sqlite"
    conn = sqlite3.connect(ios_file)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE ZWACHATSESSION (
            Z_PK INTEGER PRIMARY KEY,
            ZCONTACTJID TEXT,
            ZCONTACTIDENTIFIER TEXT,
            ZSESSIONTYPE INTEGER,
            ZPARTNERNAME TEXT,
            ZUNREADCOUNT INTEGER,
            ZMESSAGECOUNTER INTEGER
        );
    """)
    cur.execute("""
        CREATE TABLE ZWAGROUPMEMBER (
            Z_PK INTEGER PRIMARY KEY,
            ZMEMBERJID TEXT,
            ZCONTACTIDENTIFIER TEXT
        );
    """)
    cur.execute("""
        CREATE TABLE ZWAMESSAGE (
            Z_PK INTEGER PRIMARY KEY,
            ZCHATSESSION INTEGER,
            ZISFROMME INTEGER,
            ZMESSAGEDATE REAL,
            ZTEXT TEXT,
            ZMESSAGETYPE INTEGER,
            ZMESSAGESTATUS INTEGER,
            ZSTANZAID TEXT,
            ZFROMJID TEXT,
            ZMEDIAITEM INTEGER,
            ZGROUPMEMBER INTEGER
        );
    """)
    # 1: 1-on-1 chat with LID as ZCONTACTJID but PN as ZCONTACTIDENTIFIER
    cur.execute(
        "INSERT INTO ZWACHATSESSION VALUES (1, '12345@lid', '5213110000001@s.whatsapp.net', 0, 'Alice', 0, 1)"
    )
    # 2: Status session (ZSESSIONTYPE = 3)
    cur.execute(
        "INSERT INTO ZWACHATSESSION VALUES (2, '5213110000002@status', '5213110000002@status', 3, 'StatusUser', 0, 1)"
    )
    # 3: Group chat
    cur.execute(
        "INSERT INTO ZWACHATSESSION VALUES (3, '120363000@g.us', NULL, 1, 'My Group', 0, 1)"
    )
    cur.execute("INSERT INTO ZWAGROUPMEMBER VALUES (10, '5213119999999@s.whatsapp.net', NULL)")

    # Messages:
    # Msg 1 in 1-on-1 chat
    cur.execute("INSERT INTO ZWAMESSAGE VALUES (1, 1, 0, 700000000, 'Hola', 0, 13, 'S1', NULL, NULL, NULL)")
    # Msg 2 in 1-on-1 chat (image without local file)
    cur.execute("INSERT INTO ZWAMESSAGE VALUES (2, 1, 0, 700000010, NULL, 1, 13, 'S2', NULL, NULL, NULL)")
    # Msg 3 in group from member 10
    cur.execute("INSERT INTO ZWAMESSAGE VALUES (3, 3, 0, 700000020, 'Group msg', 0, 13, 'S3', '120363000@g.us', NULL, 10)")

    conn.commit()
    conn.close()

    # Setup synthetic Android DB
    andr_file = tmp_path / "msgstore.db"
    conn_a = sqlite3.connect(andr_file)
    cur_a = conn_a.cursor()
    cur_a.execute("""
        CREATE TABLE jid (
            _id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT, server TEXT, agent INTEGER DEFAULT 0, device INTEGER DEFAULT 0,
            type INTEGER DEFAULT 0, raw_string TEXT UNIQUE
        );
    """)
    cur_a.execute("""
        CREATE TABLE chat (
            _id INTEGER PRIMARY KEY AUTOINCREMENT,
            jid_row_id INTEGER UNIQUE, account_jid_row_id INTEGER,
            hidden INTEGER DEFAULT 0, subject TEXT, created_timestamp INTEGER,
            sort_timestamp INTEGER, last_message_row_id INTEGER, display_message_row_id INTEGER,
            last_message_sort_id INTEGER, display_message_sort_id INTEGER,
            last_read_message_sort_id INTEGER, last_read_receipt_sent_message_sort_id INTEGER,
            unseen_message_count INTEGER DEFAULT 0, archived INTEGER DEFAULT 0,
            chat_origin TEXT
        );
    """)
    cur_a.execute("""
        CREATE TABLE message (
            _id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_row_id INTEGER, from_me INTEGER, key_id TEXT, sender_jid_row_id INTEGER,
            timestamp INTEGER, received_timestamp INTEGER, receipt_server_timestamp INTEGER,
            message_type INTEGER, text_data TEXT, status INTEGER, starred INTEGER DEFAULT 0,
            broadcast INTEGER, recipient_count INTEGER, origination_flags INTEGER,
            origin INTEGER, lookup_tables INTEGER, sort_id INTEGER DEFAULT 0,
            message_add_on_flags INTEGER, view_mode INTEGER
        );
    """)
    cur_a.execute("""
        CREATE TABLE message_media (
            message_row_id INTEGER PRIMARY KEY, chat_row_id INTEGER,
            autotransfer_retry_enabled INTEGER, transferred INTEGER, transcoded INTEGER,
            file_path TEXT, file_size INTEGER, file_length INTEGER, suspicious_content INTEGER,
            trim_from INTEGER, trim_to INTEGER, face_x INTEGER, face_y INTEGER,
            media_key_timestamp INTEGER, width INTEGER, height INTEGER,
            has_streaming_sidecar INTEGER, gif_attribution INTEGER,
            thumbnail_height_width_ratio REAL, first_scan_length INTEGER,
            mime_type TEXT, media_name TEXT, file_hash TEXT, media_duration INTEGER,
            page_count INTEGER, mute_video INTEGER, media_transcode_quality INTEGER
        );
    """)
    conn_a.commit()
    conn_a.close()

    # Run merger
    ext = IOSExtractor(ios_file)
    adb = AndroidDB(andr_file)
    merger = BackupMerger(ext, adb)
    summary = merger.run()
    adb.close()

    conn_check = sqlite3.connect(andr_file)
    cur_c = conn_check.cursor()

    # Verify status chats were NEVER created
    cur_c.execute("SELECT raw_string FROM jid WHERE raw_string LIKE '%status%'")
    assert cur_c.fetchall() == []

    # Verify 1-on-1 chat used PN JID
    cur_c.execute("SELECT j.raw_string, c.subject, c.account_jid_row_id FROM chat c JOIN jid j ON c.jid_row_id = j._id WHERE j.raw_string LIKE '%5213110000001%'")
    alice_chat = cur_c.fetchone()
    assert alice_chat is not None
    assert alice_chat[0] == "5213110000001@s.whatsapp.net"
    assert alice_chat[1] is None # 1-on-1 chat must NOT have subject
    assert alice_chat[2] > 0 # account_jid_row_id must be populated

    # Verify group chat subject IS populated
    cur_c.execute("SELECT c.subject FROM chat c JOIN jid j ON c.jid_row_id = j._id WHERE j.raw_string = '120363000@g.us'")
    group_chat = cur_c.fetchone()
    assert group_chat is not None
    assert group_chat[0] == "My Group"

    # Verify group message sender JID was resolved to member, NOT the group
    cur_c.execute("SELECT m.sender_jid_row_id, j.raw_string FROM message m JOIN jid j ON m.sender_jid_row_id = j._id WHERE m.key_id = 'S3'")
    group_msg = cur_c.fetchone()
    assert group_msg is not None
    assert group_msg[1] == "5213119999999@s.whatsapp.net"

    # Verify image message (S2) has a row in message_media even without local file
    cur_c.execute("SELECT mm.message_row_id, mm.transferred, mm.file_path, mm.file_hash FROM message_media mm JOIN message m ON mm.message_row_id = m._id WHERE m.key_id = 'S2'")
    media_row = cur_c.fetchone()
    assert media_row is not None
    assert media_row[1] == 0 # transferred = 0
    assert media_row[2] is None # file_path = None
    assert media_row[3] is not None # valid dummy hash

    # Verify message columns are non-null
    cur_c.execute("SELECT broadcast, recipient_count, origination_flags, origin, lookup_tables, sort_id FROM message WHERE key_id = 'S1'")
    msg_row = cur_c.fetchone()
    assert msg_row == (0, 0, 0, 0, 0, 1)

    # Verify chat metadata updated display_message_row_id and last_message_sort_id
    cur_c.execute("SELECT last_message_row_id, display_message_row_id, last_message_sort_id, display_message_sort_id FROM chat")
    for r in cur_c.fetchall():
        assert r[0] == r[1]
        assert r[2] == r[3]
        assert r[0] is not None

    conn_check.close()
