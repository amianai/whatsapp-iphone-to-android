"""Backup merger: orchestrates ETL from iOS ChatStorage to Android msgstore.db."""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from wa_fuse.android_db import AndroidDB
from wa_fuse.ios_extractor import IOSExtractor
from wa_fuse.media import MediaMigrator


@dataclass
class MergeSummary:
    chats_created: int = 0
    chats_reused: int = 0
    messages_inserted: int = 0
    messages_skipped_duplicate: int = 0
    media_migrated: int = 0


class BackupMerger:
    def __init__(
        self,
        ios_extractor: IOSExtractor,
        android_db: AndroidDB,
        android_media_dir: Path | str | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ):
        self.ios_extractor = ios_extractor
        self.android_db = android_db
        self.progress_callback = progress_callback

        self.media_migrator = None
        if android_media_dir:
            self.media_migrator = MediaMigrator(
                ios_extractor=self.ios_extractor,
                android_media_dir=android_media_dir,
            )

    def run(self) -> MergeSummary:
        """Executes the merge process."""
        summary = MergeSummary()

        # Step 1: Map all iOS chats into Android JIDs and Chats
        ios_chats = self.ios_extractor.get_chats()
        ios_to_android_chat_map: dict[str, int] = {}

        for chat in ios_chats:
            is_group = chat.jid.endswith("@g.us")
            jid_id = self.android_db.get_or_create_jid(chat.jid)
            if jid_id <= 0:
                continue
            prior_count = len(self.android_db._chat_cache)
            chat_id = self.android_db.get_or_create_chat(
                jid_id,
                subject=chat.name if is_group else None,
                is_group=is_group,
            )
            if chat_id <= 0:
                continue
            if len(self.android_db._chat_cache) > prior_count:
                summary.chats_created += 1
            else:
                summary.chats_reused += 1

            ios_to_android_chat_map[chat.jid] = chat_id

        # Step 2: Iterate through iOS messages and insert them into Android DB
        msg_count = 0
        for msg in self.ios_extractor.iter_messages():
            msg_count += 1
            chat_id = ios_to_android_chat_map.get(msg.chat_jid)
            if not chat_id:
                if "status" in msg.chat_jid:
                    continue
                is_group = msg.chat_jid.endswith("@g.us")
                jid_id = self.android_db.get_or_create_jid(msg.chat_jid)
                if jid_id <= 0:
                    continue
                chat_id = self.android_db.get_or_create_chat(
                    jid_id,
                    is_group=is_group,
                    timestamp_ms=msg.timestamp_ms,
                )
                if chat_id <= 0:
                    continue
                ios_to_android_chat_map[msg.chat_jid] = chat_id
                summary.chats_created += 1

            # Check for duplicate
            if self.android_db.is_duplicate_message(
                key_id=msg.stanza_id,
                chat_row_id=chat_id,
                from_me=msg.from_me,
                timestamp_ms=msg.timestamp_ms,
                text=msg.text,
            ):
                summary.messages_skipped_duplicate += 1
                continue

            # Determine sender JID row id (for group chats only)
            sender_jid_id = 0
            if msg.from_jid and msg.chat_jid.endswith("@g.us"):
                sender_jid_id = self.android_db.get_or_create_jid(msg.from_jid)

            # Insert message
            msg_row_id = self.android_db.insert_message(
                chat_row_id=chat_id,
                from_me=msg.from_me,
                timestamp_ms=msg.timestamp_ms,
                text=msg.text,
                msg_type=msg.msg_type,
                status=msg.status,
                key_id=msg.stanza_id,
                sender_jid_row_id=sender_jid_id,
            )
            summary.messages_inserted += 1

            # Handle media if present or if msg_type is media
            if msg.msg_type in (1, 2, 3, 9, 20):
                migrated_path = None
                if self.media_migrator and msg.media_local_path:
                    migrated_path = self.media_migrator.migrate_media_file(
                        ios_rel_path=msg.media_local_path,
                        msg_type=msg.msg_type,
                        filename_hint=msg.media_title,
                    )
                self.android_db.insert_message_media(
                    message_row_id=msg_row_id,
                    chat_row_id=chat_id,
                    file_path=migrated_path,
                    file_size=msg.media_size if migrated_path else 0,
                    mime_type=msg.media_mime,
                    caption=msg.media_title,
                )
                if migrated_path:
                    summary.media_migrated += 1

            if self.progress_callback and msg_count % 5000 == 0:
                self.progress_callback(msg_count, summary.messages_inserted)

        # Step 3: Refresh chat metadata (sorting and last message references)
        self.android_db.refresh_chat_metadata()

        # Step 4: Commit changes
        self.android_db.commit()

        return summary
