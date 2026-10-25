"""Android SQLite msgstore.db database manager and schema adapter."""

import sqlite3
from pathlib import Path
from typing import Any
import secrets


class AndroidDB:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"Android database file not found: {self.db_path}")

        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()

        # Cache existing tables and columns
        self.tables: dict[str, set[str]] = {}
        self._inspect_schema()

        # In-memory lookup caches for performance
        self._jid_cache: dict[str, int] = {}
        self._chat_cache: dict[int, int] = {} # jid_row_id -> chat_row_id
        # (chat_row_id, from_me, key_id) of every message, and the highest
        # message _id that was already in the database when it was opened.
        # Duplicate checks only ever look at those pre-existing rows: messages
        # inserted by this run are never compared by time with each other.
        self._existing_keys: set[tuple[int, int, str]] = set()
        self._preexisting_max_id = 0

        self._load_caches()

    def _inspect_schema(self):
        """Discovers existing tables and their column names."""
        self.cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        table_names = [row[0] for row in self.cursor.fetchall()]
        for table in table_names:
            self.cursor.execute(f"PRAGMA table_info({table})")
            self.tables[table] = {col[1] for col in self.cursor.fetchall()}

    def _load_caches(self):
        """Preloads JIDs, Chats and existing key_ids to speed up merge and deduplication."""
        # Preload JIDs
        if "jid" in self.tables:
            raw_col = "raw_string" if "raw_string" in self.tables["jid"] else "user"
            self.cursor.execute(f"SELECT _id, {raw_col} FROM jid WHERE {raw_col} IS NOT NULL")
            for row in self.cursor.fetchall():
                self._jid_cache[str(row[1])] = row[0]

        # Preload Chats
        if "chat" in self.tables and "jid_row_id" in self.tables["chat"]:
            self.cursor.execute("SELECT _id, jid_row_id FROM chat")
            for row in self.cursor.fetchall():
                self._chat_cache[row[1]] = row[0]

        # Preload message keys
        if "message" in self.tables and "key_id" in self.tables["message"]:
            self.cursor.execute(
                "SELECT chat_row_id, from_me, key_id FROM message WHERE key_id IS NOT NULL"
            )
            self._existing_keys = {(row[0], row[1], row[2]) for row in self.cursor.fetchall()}
        if "message" in self.tables:
            self.cursor.execute("SELECT COALESCE(MAX(_id), 0) FROM message")
            self._preexisting_max_id = self.cursor.fetchone()[0]

        # Create temporary index to make timestamp deduplication instant
        if "message" in self.tables:
            self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_temp_msg_dedup ON message (chat_row_id, from_me, timestamp)"
            )

    def get_or_create_jid(self, raw_jid: str) -> int:
        """Gets or inserts a JID in the jid table."""
        raw_jid = raw_jid.strip()
        if raw_jid in self._jid_cache:
            return self._jid_cache[raw_jid]

        if "jid" not in self.tables:
            return 0

        # Disallow fake status JIDs that cause InvalidJidException in WhatsApp Android
        if ("status" in raw_jid and raw_jid != "status@broadcast") or "@lid.status" in raw_jid:
            return 0

        # Parse user and server from raw_jid (e.g. 123456789@s.whatsapp.net)
        user = raw_jid
        server = "s.whatsapp.net"
        jid_type = 0

        if "@" in raw_jid:
            user, server = raw_jid.split("@", 1)
            if server == "g.us":
                jid_type = 1
            elif "broadcast" in server:
                jid_type = 3
            elif "newsletter" in server:
                jid_type = 21
            elif "lid" in server:
                jid_type = 18
            elif server == "s.whatsapp.net":
                jid_type = 0
            else:
                return 0

        cols = self.tables["jid"]
        fields: dict[str, Any] = {}
        if "raw_string" in cols:
            fields["raw_string"] = raw_jid
        if "user" in cols:
            fields["user"] = user
        if "server" in cols:
            fields["server"] = server
        if "type" in cols:
            fields["type"] = jid_type
        if "agent" in cols:
            fields["agent"] = 0
        if "device" in cols:
            fields["device"] = 0

        keys = list(fields.keys())
        placeholders = ", ".join(["?"] * len(keys))
        sql = f"INSERT INTO jid ({', '.join(keys)}) VALUES ({placeholders})"
        self.cursor.execute(sql, [fields[k] for k in keys])
        jid_id = self.cursor.lastrowid
        self._jid_cache[raw_jid] = jid_id
        return jid_id

    def map_lid(self, lid_row_id: int, jid_row_id: int, chat: bool = False) -> None:
        """Links a contact's @lid to its phone JID, as WhatsApp does in jid_map.

        Modern WhatsApp opens a 1-on-1 chat through the contact's @lid: without
        this link it starts a new, empty @lid chat next to the imported one.
        A chat keyed by the @lid also gets its lid_chat_state row.
        """
        if lid_row_id <= 0 or jid_row_id <= 0:
            return
        if "jid_map" in self.tables:
            self.cursor.execute(
                "INSERT OR IGNORE INTO jid_map (lid_row_id, jid_row_id, sort_id) "
                "SELECT ?, ?, COALESCE(MAX(sort_id), 0) + 1 FROM jid_map",
                (lid_row_id, jid_row_id),
            )
        if chat and "lid_chat_state" in self.tables:
            self.cursor.execute(
                "INSERT OR IGNORE INTO lid_chat_state (jid_row_id, is_pn_shared) VALUES (?, 1)",
                (lid_row_id,),
            )

    def archive_chat(self, chat_row_id: int) -> None:
        """Marks an existing chat as archived."""
        if chat_row_id > 0 and "archived" in self.tables.get("chat", set()):
            self.cursor.execute("UPDATE chat SET archived = 1 WHERE _id = ?", (chat_row_id,))

    def get_or_create_chat(
        self,
        jid_row_id: int,
        subject: str | None = None,
        is_group: bool = False,
        timestamp_ms: int | None = None,
        archived: bool = False,
    ) -> int:
        """Gets or creates a conversation row in the chat table."""
        if jid_row_id <= 0:
            return 0

        if jid_row_id in self._chat_cache:
            return self._chat_cache[jid_row_id]

        if "chat" not in self.tables:
            return 0

        cols = self.tables["chat"]
        fields: dict[str, Any] = {}
        if "jid_row_id" in cols:
            fields["jid_row_id"] = jid_row_id
        if "account_jid_row_id" in cols:
            fields["account_jid_row_id"] = jid_row_id
        if "subject" in cols and is_group and subject:
            fields["subject"] = subject
        if "hidden" in cols:
            fields["hidden"] = 0
        if "archived" in cols:
            fields["archived"] = 1 if archived else 0
        if "unseen_message_count" in cols:
            fields["unseen_message_count"] = 0
        if "unseen_important_message_count" in cols:
            fields["unseen_important_message_count"] = 0
        if "created_timestamp" in cols and timestamp_ms:
            fields["created_timestamp"] = timestamp_ms
        if "sort_timestamp" in cols and timestamp_ms:
            fields["sort_timestamp"] = timestamp_ms
        if "chat_origin" in cols:
            fields["chat_origin"] = "general"
        if "group_type" in cols:
            fields["group_type"] = 0
        if "plaintext_disabled" in cols:
            fields["plaintext_disabled"] = 1
        if "spam_detection" in cols:
            fields["spam_detection"] = -1

        keys = list(fields.keys())
        placeholders = ", ".join(["?"] * len(keys))
        sql = f"INSERT INTO chat ({', '.join(keys)}) VALUES ({placeholders})"
        self.cursor.execute(sql, [fields[k] for k in keys])
        chat_id = self.cursor.lastrowid
        self._chat_cache[jid_row_id] = chat_id
        return chat_id

    def is_duplicate_message(
        self,
        key_id: str | None,
        chat_row_id: int,
        from_me: bool,
        timestamp_ms: int,
        text: str | None,
    ) -> bool:
        """True if this message is already in the chat.

        A message is a duplicate when the same chat already holds its key_id
        (WhatsApp's message id is the same on every device), or when a message
        that was in the database before this run has the same direction, the
        same text and a timestamp within 2 seconds.

        Messages inserted during this run are only matched by key_id: albums
        and quick replies are often sent within the same second.
        """
        if key_id and (chat_row_id, 1 if from_me else 0, key_id) in self._existing_keys:
            return True

        if "message" not in self.tables or not self._preexisting_max_id or not text:
            return False

        text_col = "text_data" if "text_data" in self.tables["message"] else "data"
        if text_col not in self.tables["message"]:
            return False
        self.cursor.execute(
            f"""
            SELECT _id FROM message
            WHERE chat_row_id = ?
            AND from_me = ?
            AND timestamp BETWEEN ? AND ?
            AND _id <= ?
            AND {text_col} = ?
            LIMIT 1
            """,
            (
                chat_row_id,
                1 if from_me else 0,
                timestamp_ms - 2000,
                timestamp_ms + 2000,
                self._preexisting_max_id,
                text,
            ),
        )
        return self.cursor.fetchone() is not None

    def insert_message(
        self,
        chat_row_id: int,
        from_me: bool,
        timestamp_ms: int,
        text: str | None,
        msg_type: int = 0,
        status: int = 0,
        key_id: str | None = None,
        sender_jid_row_id: int = 0,
        starred: bool = False,
    ) -> int:
        """Inserts a new message row into the Android message table."""
        if "message" not in self.tables:
            return 0

        if not key_id:
            # Generate valid random stanza ID: 3EB0 + 12 hex chars or similar
            key_id = f"3EB0{secrets.token_hex(8).upper()}"

        cols = self.tables["message"]
        fields: dict[str, Any] = {}

        if "chat_row_id" in cols:
            fields["chat_row_id"] = chat_row_id
        if "from_me" in cols:
            fields["from_me"] = 1 if from_me else 0
        if "key_id" in cols:
            fields["key_id"] = key_id
        if "sender_jid_row_id" in cols:
            fields["sender_jid_row_id"] = sender_jid_row_id
        if "timestamp" in cols:
            fields["timestamp"] = timestamp_ms
        if "received_timestamp" in cols:
            fields["received_timestamp"] = timestamp_ms
        if "receipt_server_timestamp" in cols:
            fields["receipt_server_timestamp"] = timestamp_ms
        if "message_type" in cols:
            fields["message_type"] = msg_type
        if "text_data" in cols:
            fields["text_data"] = text
        elif "data" in cols:
            fields["data"] = text
        if "status" in cols:
            # Standard WhatsApp status (13 = read/seen, 4 = sent/delivered)
            fields["status"] = 13 if not from_me else 4
        if "starred" in cols:
            fields["starred"] = 1 if starred else 0
        if "broadcast" in cols:
            fields["broadcast"] = 0
        if "recipient_count" in cols:
            fields["recipient_count"] = 0
        if "origination_flags" in cols:
            fields["origination_flags"] = 0
        if "origin" in cols:
            fields["origin"] = 0
        if "lookup_tables" in cols:
            fields["lookup_tables"] = 0
        if "message_add_on_flags" in cols:
            fields["message_add_on_flags"] = 0
        if "view_mode" in cols:
            fields["view_mode"] = 0

        keys = list(fields.keys())
        placeholders = ", ".join(["?"] * len(keys))
        sql = f"INSERT INTO message ({', '.join(keys)}) VALUES ({placeholders})"
        self.cursor.execute(sql, [fields[k] for k in keys])
        msg_id = self.cursor.lastrowid
        if "sort_id" in cols:
            self.cursor.execute("UPDATE message SET sort_id = ? WHERE _id = ?", (msg_id, msg_id))

        self._existing_keys.add((chat_row_id, 1 if from_me else 0, key_id))
        return msg_id

    def insert_message_media(
        self,
        message_row_id: int,
        chat_row_id: int,
        file_path: str | None = None,
        file_size: int = 0,
        mime_type: str | None = None,
        caption: str | None = None,
        width: int = 0,
        height: int = 0,
        duration: int = 0,
        file_hash: str | None = None,
    ):
        """Inserts media metadata into message_media table with full WhatsApp Android parity."""
        if "message_media" not in self.tables:
            return

        cols = self.tables["message_media"]
        fields: dict[str, Any] = {}
        has_file = bool(file_path)

        if "message_row_id" in cols:
            fields["message_row_id"] = message_row_id
        if "chat_row_id" in cols:
            fields["chat_row_id"] = chat_row_id
        if "autotransfer_retry_enabled" in cols:
            fields["autotransfer_retry_enabled"] = 1 if has_file else 0
        if "transferred" in cols:
            fields["transferred"] = 1 if has_file else 0
        if "transcoded" in cols:
            fields["transcoded"] = 0
        if "file_path" in cols:
            fields["file_path"] = file_path
        if "file_size" in cols:
            fields["file_size"] = file_size if has_file else 0
        if "file_length" in cols:
            fields["file_length"] = file_size if has_file else 0
        if "suspicious_content" in cols:
            fields["suspicious_content"] = 0
        if "trim_from" in cols:
            fields["trim_from"] = 0
        if "trim_to" in cols:
            fields["trim_to"] = 0
        if "face_x" in cols:
            fields["face_x"] = 0
        if "face_y" in cols:
            fields["face_y"] = 0
        if "media_key_timestamp" in cols:
            fields["media_key_timestamp"] = 0
        if "width" in cols:
            fields["width"] = width
        if "height" in cols:
            fields["height"] = height
        if "has_streaming_sidecar" in cols:
            fields["has_streaming_sidecar"] = 0
        if "gif_attribution" in cols:
            fields["gif_attribution"] = 0
        if "thumbnail_height_width_ratio" in cols:
            ratio = (height / width) if (width and height) else 0.0
            fields["thumbnail_height_width_ratio"] = ratio
        if "first_scan_length" in cols:
            fields["first_scan_length"] = 0
        if "mime_type" in cols and mime_type:
            fields["mime_type"] = mime_type
        if "media_name" in cols and caption:
            fields["media_name"] = caption
        if "file_hash" in cols:
            fields["file_hash"] = file_hash or "dummy_hash_placeholder="
        if "media_duration" in cols:
            fields["media_duration"] = duration
        if "page_count" in cols:
            fields["page_count"] = 0
        if "mute_video" in cols:
            fields["mute_video"] = 0
        if "media_transcode_quality" in cols:
            fields["media_transcode_quality"] = 0

        keys = list(fields.keys())
        placeholders = ", ".join(["?"] * len(keys))
        sql = f"INSERT OR REPLACE INTO message_media ({', '.join(keys)}) VALUES ({placeholders})"
        self.cursor.execute(sql, [fields[k] for k in keys])

    def renumber_sort_ids(self):
        """Gives every message a sort_id that follows its timestamp.

        WhatsApp orders a chat by sort_id. Rows inserted by this run get a
        sort_id equal to their _id, which puts years of iPhone history after
        any message the template backup already held (for instance messages
        delivered right after registering the number). Renumbering by
        (timestamp, _id) restores chronological order everywhere.
        """
        if "message" not in self.tables or "sort_id" not in self.tables["message"]:
            return
        # Nothing to do when sort_id already follows time (e.g. an empty template).
        self.cursor.execute(
            """
            SELECT 1 FROM (
                SELECT timestamp, LAG(timestamp) OVER (ORDER BY sort_id, _id) AS prev_ts
                FROM message
            )
            WHERE timestamp < prev_ts
            LIMIT 1
            """
        )
        if self.cursor.fetchone() is None:
            return
        self.cursor.execute("DROP TABLE IF EXISTS temp.wa_fuse_sort")
        self.cursor.execute(
            """
            CREATE TEMP TABLE wa_fuse_sort AS
            SELECT _id, ROW_NUMBER() OVER (ORDER BY timestamp, _id) AS new_sort
            FROM message
            """
        )
        self.cursor.execute("CREATE INDEX temp.wa_fuse_sort_id ON wa_fuse_sort (_id)")
        # Two passes through negative values, so the update never collides with
        # an old sort_id if the schema has a unique index on it.
        self.cursor.execute(
            """
            UPDATE message
            SET sort_id = -(SELECT new_sort FROM wa_fuse_sort WHERE wa_fuse_sort._id = message._id)
            """
        )
        self.cursor.execute("UPDATE message SET sort_id = -sort_id")
        self.cursor.execute("DROP TABLE temp.wa_fuse_sort")

    def refresh_chat_metadata(self):
        """Points every chat at its latest message (by timestamp) and its sort_id."""
        if "chat" not in self.tables or "message" not in self.tables:
            return

        chat_cols = self.tables["chat"]
        has_sort = "sort_id" in self.tables["message"]

        # Latest message for each chat; ties on timestamp go to the highest _id.
        sql = f"""
            SELECT chat_row_id, _id, timestamp, {"sort_id" if has_sort else "_id"}
            FROM (
                SELECT chat_row_id, _id, timestamp, {"sort_id," if has_sort else ""}
                       ROW_NUMBER() OVER (PARTITION BY chat_row_id ORDER BY timestamp DESC, _id DESC) AS rn
                FROM message
                WHERE chat_row_id IS NOT NULL AND chat_row_id > 0
            )
            WHERE rn = 1
        """
        self.cursor.execute(sql)
        for chat_id, latest_msg_id, max_ts, latest_sort_id in self.cursor.fetchall():
            values = {
                "sort_timestamp": max_ts,
                "last_message_row_id": latest_msg_id,
                "display_message_row_id": latest_msg_id,
                "last_message_sort_id": latest_sort_id,
                "display_message_sort_id": latest_sort_id,
                "last_read_message_sort_id": latest_sort_id,
                "last_read_receipt_sent_message_sort_id": latest_sort_id,
            }
            updates = [(col, val) for col, val in values.items() if col in chat_cols]
            if updates:
                up_sql = f"UPDATE chat SET {', '.join(f'{c} = ?' for c, _ in updates)} WHERE _id = ?"
                self.cursor.execute(up_sql, [v for _, v in updates] + [chat_id])

    def commit(self):
        """Commits the current transaction."""
        self.conn.commit()

    def close(self):
        """Drops temporary index and closes the database connection."""
        try:
            self.cursor.execute("DROP INDEX IF EXISTS idx_temp_msg_dedup")
            self.conn.commit()
        except Exception:
            pass
        self.conn.close()
