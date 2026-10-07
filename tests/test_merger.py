import sqlite3
from pathlib import Path
from wa_backup.android_db import AndroidDB
from wa_backup.ios_extractor import IOSExtractor
from wa_backup.merger import BackupMerger
from tests.test_ios_extractor import create_synthetic_ios_db
from tests.test_android_db import create_synthetic_android_db


def test_merger_end_to_end(tmp_path):
    # Setup iOS DB
    ios_file = tmp_path / "ChatStorage.sqlite"
    create_synthetic_ios_db(ios_file)

    # Setup Android DB with an existing message
    android_file = tmp_path / "msgstore.db"
    create_synthetic_android_db(android_file)

    # Pre-populate Android DB with 1 message for Bob and 1 existing duplicate for Alice
    andr_db = AndroidDB(android_file)
    bob_jid = andr_db.get_or_create_jid("34699887766@s.whatsapp.net")
    bob_chat = andr_db.get_or_create_chat(bob_jid, "Bob")
    andr_db.insert_message(bob_chat, True, 1690000000000, "Hola Bob", key_id="BOB_MSG_1")

    # Insert Alice's STANZA_1 in Android beforehand to test duplicate skipping
    alice_jid = andr_db.get_or_create_jid("34600112233@s.whatsapp.net")
    alice_chat = andr_db.get_or_create_chat(alice_jid, "Alice")
    andr_db.insert_message(alice_chat, False, 1678307200000, "Hola desde iPhone", key_id="STANZA_1")
    andr_db.commit()
    andr_db.close()

    # Run Merger
    extractor = IOSExtractor(ios_file)
    db_to_merge = AndroidDB(android_file)
    merger = BackupMerger(extractor, db_to_merge)
    summary = merger.run()
    db_to_merge.close()

    # Summary expectations:
    # Alice's chat was reused
    assert summary.chats_reused == 1
    # STANZA_1 was duplicate, STANZA_2 was new
    assert summary.messages_skipped_duplicate == 1
    assert summary.messages_inserted == 1

    # Verify Android DB contents
    conn = sqlite3.connect(android_file)
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM message")
    total_messages = cur.fetchone()[0]
    # Total: 1 (Bob) + 1 (Alice prior) + 1 (Alice merged STANZA_2) = 3
    assert total_messages == 3

    # Verify STANZA_2 is present with text
    cur.execute("SELECT text_data, from_me FROM message WHERE key_id = 'STANZA_2'")
    row = cur.fetchone()
    assert row is not None
    assert row[0] == "Respuesta desde iPhone"
    assert row[1] == 1
    conn.close()
