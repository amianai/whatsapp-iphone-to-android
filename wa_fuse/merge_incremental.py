"""Incremental merger: extracts messages received after a given timestamp from a new Android backup

and inserts them cleanly into the merged database.
"""

from pathlib import Path
import sqlite3
import datetime
from wa_fuse.android_db import AndroidDB
from wa_fuse.crypto import decrypt_android_backup, encrypt_android_backup

LAST_BACKUP_TIMESTAMP_MS = 1791309212767  # 2026-10-06 10:53:32


def merge_incremental_messages(
    incremental_db_path: Path | str,
    target_merged_db_path: Path | str,
    since_timestamp_ms: int = LAST_BACKUP_TIMESTAMP_MS,
) -> int:
    """Merges messages newer than since_timestamp_ms from incremental_db into target_merged_db."""
    inc_conn = sqlite3.connect(incremental_db_path)
    inc_cur = inc_conn.cursor()

    target_db = AndroidDB(target_merged_db_path)

    # Find messages newer than since_timestamp_ms
    query = """
        SELECT 
            m._id, m.timestamp, j.raw_string, m.from_me, m.text_data, 
            m.message_type, m.status, m.key_id, sj.raw_string
        FROM message m
        LEFT JOIN chat c ON m.chat_row_id = c._id
        LEFT JOIN jid j ON c.jid_row_id = j._id
        LEFT JOIN jid sj ON m.sender_jid_row_id = sj._id
        WHERE m.timestamp > ?
        ORDER BY m.timestamp ASC
    """
    new_msgs = inc_cur.execute(query, (since_timestamp_ms,)).fetchall()

    inserted_count = 0
    for row in new_msgs:
        (
            _id,
            ts,
            chat_raw_jid,
            from_me,
            text,
            msg_type,
            status,
            key_id,
            sender_raw_jid,
        ) = row

        if not chat_raw_jid or "status" in chat_raw_jid:
            continue

        is_group = chat_raw_jid.endswith("@g.us")
        jid_id = target_db.get_or_create_jid(chat_raw_jid)
        if jid_id <= 0:
            continue

        chat_id = target_db.get_or_create_chat(
            jid_id,
            is_group=is_group,
            timestamp_ms=ts,
        )
        if chat_id <= 0:
            continue

        # Check duplicate
        if target_db.is_duplicate_message(
            key_id=key_id,
            chat_row_id=chat_id,
            from_me=bool(from_me),
            timestamp_ms=ts,
            text=text,
        ):
            continue

        sender_jid_id = 0
        if sender_raw_jid and is_group:
            sender_jid_id = target_db.get_or_create_jid(sender_raw_jid)

        msg_row_id = target_db.insert_message(
            chat_row_id=chat_id,
            from_me=bool(from_me),
            timestamp_ms=ts,
            text=text,
            msg_type=msg_type,
            status=status,
            key_id=key_id,
            sender_jid_row_id=sender_jid_id,
        )

        # Check if it had media
        if msg_type in (1, 2, 3, 9, 20):
            target_db.insert_message_media(
                message_row_id=msg_row_id,
                chat_row_id=chat_id,
                file_path=None,
                file_size=0,
            )

        inserted_count += 1

    target_db.refresh_chat_metadata()
    target_db.commit()
    target_db.close()
    inc_conn.close()

    return inserted_count
