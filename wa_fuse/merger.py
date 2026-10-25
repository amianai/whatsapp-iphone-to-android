"""Backup merger: orchestrates ETL from iOS ChatStorage to Android msgstore.db."""

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
from typing import Callable

from wa_fuse.android_db import AndroidDB
from wa_fuse.constants import (
    ANDROID_DOCUMENT,
    ANDROID_TEXT,
    IOS_CONTACT,
    IOS_LOCATION,
    IOS_SKIPPED_TYPES,
    IOS_TEXT,
    IOS_TO_ANDROID_MEDIA_TYPE,
    IOS_URL,
    IOS_VIEW_ONCE_LABELS,
)
from wa_fuse.ios_extractor import IOSExtractor, IOSMessage
from wa_fuse.media import MediaMigrator


@dataclass
class ChatReport:
    jid: str
    name: str | None
    ios_messages: int = 0
    inserted: int = 0
    skipped_duplicate: int = 0
    skipped_system_or_deleted: int = 0
    skipped_empty_unsupported: int = 0
    media_messages: int = 0
    media_copied: int = 0
    media_missing: int = 0


@dataclass
class MergeSummary:
    chats_created: int = 0
    chats_reused: int = 0
    messages_inserted: int = 0
    messages_skipped_duplicate: int = 0
    media_migrated: int = 0
    messages_read: int = 0
    messages_skipped_system_or_deleted: int = 0
    messages_skipped_empty_unsupported: int = 0
    media_missing: int = 0
    chats: dict[str, ChatReport] = field(default_factory=dict)

    def write_report(self, path: Path | str) -> Path:
        """Writes the per-chat comparison between the iPhone and the new backup as JSON."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data["chats"] = sorted(data["chats"].values(), key=lambda c: -c["ios_messages"])
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path


def _contact_text(msg: IOSMessage) -> str | None:
    """A shared contact card as readable text (name and phone numbers)."""
    lines = []
    vcard = msg.vcard_string or ""
    name = None
    for line in vcard.splitlines():
        key, _, value = line.partition(":")
        key = key.split(";", 1)[0].upper()
        if key == "FN" and value.strip():
            name = value.strip()
        elif key.endswith("TEL") and value.strip():
            lines.append(value.strip())
    name = name or msg.vcard_name or msg.text
    if not name and not lines:
        return None
    return "\n".join([f"👤 {name or ''}".rstrip()] + lines)


def _location_text(msg: IOSMessage) -> str | None:
    """A shared location as readable text with a map link."""
    parts = [p for p in (msg.media_title, msg.text) if p]
    if msg.latitude is not None and msg.longitude is not None and (msg.latitude or msg.longitude):
        parts.append(f"https://maps.google.com/?q={msg.latitude:.6f},{msg.longitude:.6f}")
    if not parts:
        return None
    return "📍 " + "\n".join(parts)


class BackupMerger:
    def __init__(
        self,
        ios_extractor: IOSExtractor,
        android_db: AndroidDB,
        android_media_dir: Path | str | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
        chat_filter: list[str] | None = None,
        move_media: bool = False,
    ):
        self.ios_extractor = ios_extractor
        self.android_db = android_db
        self.progress_callback = progress_callback
        self.chat_filter = [c.strip().lower() for c in (chat_filter or []) if c.strip()]

        self.media_migrator = None
        if android_media_dir:
            self.media_migrator = MediaMigrator(
                ios_extractor=self.ios_extractor,
                android_media_dir=android_media_dir,
                move_files=move_media and ios_extractor.media_is_staged,
            )

    def _selected(self, jid: str, name: str | None) -> bool:
        if not self.chat_filter:
            return True
        haystack = f"{jid} {name or ''}".lower()
        return any(f in haystack for f in self.chat_filter)

    def run(self) -> MergeSummary:
        """Executes the merge process."""
        summary = MergeSummary()

        # Step 1: select the iOS chats to import
        all_chats = self.ios_extractor.get_chats()
        ios_chats = [c for c in all_chats if self._selected(c.jid, c.name)]
        pk_to_jid = {c.pk: c.jid for c in ios_chats}
        names = {c.jid: c.name for c in ios_chats}
        archived = {c.jid for c in ios_chats if c.archived}
        # Only WhatsApp builds that keep jid_map know @lid chats.
        uses_lid = "jid_map" in self.android_db.tables
        lids = {c.jid: c.lid for c in ios_chats if c.lid} if uses_lid else {}
        chat_ids: dict[str, int] = {}

        # Every known @lid/phone pair, so group senders seen by @lid get their number too.
        for c in all_chats:
            if c.lid and uses_lid:
                self.android_db.map_lid(
                    self.android_db.get_or_create_jid(c.lid), self.android_db.get_or_create_jid(c.jid)
                )

        def chat_for(jid: str, timestamp_ms: int) -> int:
            """Android chat row for an iOS chat, created on its first message.

            1-on-1 chats are keyed by the contact's @lid when it is known, like
            the ones WhatsApp creates itself; the phone JID is linked in jid_map.
            """
            if jid in chat_ids:
                return chat_ids[jid]
            is_group = jid.endswith("@g.us")
            jid_id = self.android_db.get_or_create_jid(lids.get(jid, jid))
            if jid_id <= 0:
                chat_ids[jid] = 0
                return 0
            if jid in lids:
                self.android_db.map_lid(jid_id, self.android_db.get_or_create_jid(jid), chat=True)
            existed = jid_id in self.android_db._chat_cache
            chat_id = self.android_db.get_or_create_chat(
                jid_id,
                subject=names.get(jid) if is_group else None,
                is_group=is_group,
                timestamp_ms=timestamp_ms,
                archived=jid in archived,
            )
            if chat_id > 0:
                if existed:
                    summary.chats_reused += 1
                    if jid in archived:  # a chat WhatsApp already restored from the server
                        self.android_db.archive_chat(chat_id)
                else:
                    summary.chats_created += 1
            chat_ids[jid] = chat_id
            return chat_id

        # The standard copy of a photo or video sent in HD: the iPhone shows one bubble.
        hd_copies = self.ios_extractor.find_hd_copies(set(pk_to_jid))

        # Step 2: Iterate through iOS messages and insert them into Android DB
        for msg in self.ios_extractor.iter_messages(pk_to_jid):
            summary.messages_read += 1
            report = summary.chats.setdefault(msg.chat_jid, ChatReport(jid=msg.chat_jid, name=names.get(msg.chat_jid)))
            report.ios_messages += 1

            if msg.msg_type in IOS_SKIPPED_TYPES:
                report.skipped_system_or_deleted += 1
                summary.messages_skipped_system_or_deleted += 1
                continue

            if msg.pk in hd_copies:
                report.skipped_duplicate += 1
                summary.messages_skipped_duplicate += 1
                continue

            android_type, text, caption = self._android_content(msg)
            if android_type is None:
                report.skipped_empty_unsupported += 1
                summary.messages_skipped_empty_unsupported += 1
                continue

            chat_id = chat_for(msg.chat_jid, msg.timestamp_ms)
            if chat_id <= 0:
                report.skipped_empty_unsupported += 1
                summary.messages_skipped_empty_unsupported += 1
                continue

            if self.android_db.is_duplicate_message(
                key_id=msg.stanza_id,
                chat_row_id=chat_id,
                from_me=msg.from_me,
                timestamp_ms=msg.timestamp_ms,
                text=text,
            ):
                report.skipped_duplicate += 1
                summary.messages_skipped_duplicate += 1
                continue

            # Determine sender JID row id (for group chats only)
            sender_jid_id = 0
            if msg.from_jid and msg.chat_jid.endswith("@g.us"):
                sender_jid_id = self.android_db.get_or_create_jid(msg.from_jid)

            msg_row_id = self.android_db.insert_message(
                chat_row_id=chat_id,
                from_me=msg.from_me,
                timestamp_ms=msg.timestamp_ms,
                text=text,
                msg_type=android_type,
                status=msg.status,
                key_id=msg.stanza_id,
                sender_jid_row_id=sender_jid_id,
                starred=msg.starred,
            )
            report.inserted += 1
            summary.messages_inserted += 1

            if android_type != ANDROID_TEXT:
                report.media_messages += 1
                migrated = None
                if self.media_migrator and msg.media_local_path:
                    migrated = self.media_migrator.migrate_media_file(
                        ios_rel_path=msg.media_local_path,
                        msg_type=android_type,
                        filename_hint=msg.media_title,
                        from_me=msg.from_me,
                        mime_type=msg.media_mime,
                        timestamp_ms=msg.timestamp_ms,
                    )
                self.android_db.insert_message_media(
                    message_row_id=msg_row_id,
                    chat_row_id=chat_id,
                    file_path=migrated.relative_path if migrated else None,
                    file_size=migrated.size if migrated else 0,
                    mime_type=migrated.mime_type if migrated else msg.media_mime,
                    caption=caption,
                    width=self._dimension(msg.longitude, android_type),
                    height=self._dimension(msg.latitude, android_type),
                    duration=msg.media_duration,
                    file_hash=migrated.file_hash if migrated else None,
                )
                if migrated:
                    report.media_copied += 1
                    summary.media_migrated += 1
                else:
                    report.media_missing += 1
                    summary.media_missing += 1

            if self.progress_callback and summary.messages_read % 5000 == 0:
                self.progress_callback(summary.messages_read, summary.messages_inserted)

        # Step 3: chronological order, then chat list metadata
        self.android_db.renumber_sort_ids()
        self.android_db.refresh_chat_metadata()

        # Step 4: Commit changes
        self.android_db.commit()

        return summary

    @staticmethod
    def _android_content(msg: IOSMessage) -> tuple[int | None, str | None, str | None]:
        """(Android type, message text, document name) for an iOS message.

        Returns a None type for messages that carry nothing to import.
        """
        ios_type = msg.msg_type
        if ios_type in (IOS_TEXT, IOS_URL):
            return (ANDROID_TEXT, msg.text, None) if msg.text else (None, None, None)
        if ios_type == IOS_CONTACT:
            text = _contact_text(msg)
            return (ANDROID_TEXT, text, None) if text else (None, None, None)
        if ios_type == IOS_LOCATION:
            text = _location_text(msg)
            return (ANDROID_TEXT, text, None) if text else (None, None, None)
        if ios_type in IOS_VIEW_ONCE_LABELS:
            label = IOS_VIEW_ONCE_LABELS[ios_type]
            text = msg.text or msg.media_title
            return ANDROID_TEXT, f"{label}\n{text}" if text else label, None
        if ios_type in IOS_TO_ANDROID_MEDIA_TYPE:
            android_type = IOS_TO_ANDROID_MEDIA_TYPE[ios_type]
            if android_type == ANDROID_DOCUMENT:
                # For documents ZTITLE is the file name shown in the bubble.
                return android_type, msg.text, msg.media_title
            # For photos and videos ZTITLE is the caption.
            return android_type, msg.text or msg.media_title, None
        # Newer or rare types (polls, view once, ...): keep any text they carry.
        return (ANDROID_TEXT, msg.text, None) if msg.text else (None, None, None)

    @staticmethod
    def _dimension(value: float | None, android_type: int) -> int:
        """Photo/video size, which iOS stores in the lat/long columns.

        ZLATITUDE is the displayed height and ZLONGITUDE the displayed width
        (checked against the real files, rotated videos included).
        """
        if android_type == ANDROID_DOCUMENT or not value or value < 1 or value > 20000:
            return 0
        return int(round(value)) if re.fullmatch(r"\d+(\.0+)?", f"{value}") else 0
