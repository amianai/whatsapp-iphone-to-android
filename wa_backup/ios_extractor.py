"""iOS WhatsApp Backup Extractor and Parser.

Supports both direct ChatStorage.sqlite files and full iTunes/Finder backups.
"""

from dataclasses import dataclass
from pathlib import Path
import shutil
import sqlite3
from typing import Generator

from wa_backup.constants import apple_time_to_unix_ms, IOS_TO_ANDROID_MSG_TYPE


@dataclass
class IOSChat:
    pk: int
    jid: str
    name: str | None
    unread_count: int = 0
    message_count: int = 0


@dataclass
class IOSMessage:
    pk: int
    chat_jid: str
    from_me: bool
    timestamp_ms: int
    text: str | None
    msg_type: int
    status: int
    stanza_id: str | None
    from_jid: str | None = None
    media_local_path: str | None = None
    media_size: int = 0
    media_mime: str | None = None
    media_title: str | None = None
    vcard_string: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class IOSExtractor:
    def __init__(
        self,
        source_path: Path | str,
        staging_dir: Path | str | None = None,
        is_business: bool = False,
    ):
        self.source_path = Path(source_path)
        self.staging_dir = Path(staging_dir) if staging_dir else self.source_path.parent / "ios_extracted"
        self.is_business = is_business
        self.chat_storage_path: Path | None = None
        self.media_dir: Path | None = None
        self.manifest_db_path: Path | None = None
        self.domain: str | None = None
        self._media_map: dict[str, str] = {}

        self._resolve_paths()

    def _resolve_paths(self):
        """Identifies if source is a direct sqlite file, a directory with ChatStorage,

        or an iTunes backup folder with Manifest.db.
        """
        if self.source_path.is_file():
            if self.source_path.name.lower().endswith((".sqlite", ".db")):
                self.chat_storage_path = self.source_path
                candidate_media = self.source_path.parent / "Media"
                if candidate_media.exists() and candidate_media.is_dir():
                    self.media_dir = candidate_media
                return
            else:
                raise ValueError(f"Unrecognized file type: {self.source_path}")

        # If it's a directory containing ChatStorage.sqlite directly
        direct_db = self.source_path / "ChatStorage.sqlite"
        if direct_db.exists():
            self.chat_storage_path = direct_db
            candidate_media = self.source_path / "Media"
            if candidate_media.exists() and candidate_media.is_dir():
                self.media_dir = candidate_media
            return

        # If it's an iTunes / Finder backup directory
        manifest_db = self.source_path / "Manifest.db"
        if manifest_db.exists():
            self.manifest_db_path = manifest_db
            self._setup_from_itunes_backup(manifest_db)
            return

        raise FileNotFoundError(
            f"Could not find ChatStorage.sqlite or Manifest.db in {self.source_path}"
        )

    def _setup_from_itunes_backup(self, manifest_db: Path):
        """Locates ChatStorage.sqlite and builds lazy media file map from Manifest.db."""
        conn = sqlite3.connect(manifest_db)
        cursor = conn.cursor()

        target_domain = (
            "AppDomainGroup-group.net.whatsapp.WhatsAppSMB.shared"
            if self.is_business
            else "AppDomainGroup-group.net.whatsapp.WhatsApp.shared"
        )
        self.domain = target_domain

        # Find ChatStorage.sqlite for this domain
        query_db = """
            SELECT fileID FROM Files
            WHERE domain = ? AND relativePath = 'ChatStorage.sqlite'
        """
        cursor.execute(query_db, (target_domain,))
        row = cursor.fetchone()

        if not row and not self.is_business:
            # Fallback to any WhatsApp domain if standard not found
            cursor.execute("""
                SELECT fileID, domain FROM Files
                WHERE (domain LIKE '%whatsapp%' OR domain LIKE '%WhatsApp%')
                AND relativePath = 'ChatStorage.sqlite'
                ORDER BY domain ASC LIMIT 1
            """)
            row = cursor.fetchone()
            if row:
                self.domain = row[1]

        if not row:
            conn.close()
            raise FileNotFoundError(
                f"ChatStorage.sqlite not found in iTunes backup Manifest.db for domain {target_domain}"
            )

        file_id = row[0]
        # In iOS 10+ file is at <backup_dir>/xx/xx...
        src_file = self.source_path / file_id[:2] / file_id
        if not src_file.exists():
            src_file = self.source_path / file_id
        if not src_file.exists():
            conn.close()
            raise FileNotFoundError(f"Backup file blob {file_id} not found on disk at {src_file}")

        self.chat_storage_path = src_file

        # Preload media mapping (relativePath -> fileID)
        cursor.execute(
            "SELECT relativePath, fileID FROM Files WHERE domain = ? AND relativePath LIKE '%Media%'",
            (self.domain,),
        )
        for rel_p, fid in cursor.fetchall():
            self._media_map[rel_p] = fid

        conn.close()

    def resolve_media_file(self, rel_path: str | None) -> Path | None:
        """Resolves relative media path to an actual file on disk."""
        if not rel_path:
            return None

        clean_rel = rel_path.lstrip("/\\")

        # 1. If using iTunes backup
        if self._media_map:
            # Check variations: Message/Media/..., Media/..., or exact
            candidates = [
                f"Message/{clean_rel}",
                clean_rel,
            ]
            if clean_rel.startswith("Media/"):
                candidates.append(f"Message/{clean_rel}")
            elif clean_rel.startswith("Message/Media/"):
                candidates.append(clean_rel[len("Message/"):])

            for cand in candidates:
                if cand in self._media_map:
                    fid = self._media_map[cand]
                    disk_path = self.source_path / fid[:2] / fid
                    if not disk_path.exists():
                        disk_path = self.source_path / fid
                    if disk_path.exists() and disk_path.is_file():
                        return disk_path

        # 2. If using extracted media folder
        if self.media_dir and self.media_dir.exists():
            candidate = self.media_dir / clean_rel
            if not candidate.exists():
                for prefix in ["Message/Media/", "Media/", "Message/"]:
                    if clean_rel.startswith(prefix):
                        alt = self.media_dir / clean_rel[len(prefix):]
                        if alt.exists():
                            candidate = alt
                            break
            if candidate.exists() and candidate.is_file():
                return candidate

        return None

    def get_chats(self) -> list[IOSChat]:
        """Loads all chat sessions from ChatStorage.sqlite."""
        if not self.chat_storage_path or not self.chat_storage_path.exists():
            raise FileNotFoundError("ChatStorage.sqlite not available")

        conn = sqlite3.connect(self.chat_storage_path)
        cursor = conn.cursor()

        cursor.execute("PRAGMA table_info(ZWACHATSESSION)")
        columns = {col[1] for col in cursor.fetchall()}

        name_col = "ZPARTNERNAME" if "ZPARTNERNAME" in columns else "NULL"
        unread_col = "ZUNREADCOUNT" if "ZUNREADCOUNT" in columns else "0"
        msg_count_col = "ZMESSAGECOUNTER" if "ZMESSAGECOUNTER" in columns else "0"
        ident_col = "ZCONTACTIDENTIFIER" if "ZCONTACTIDENTIFIER" in columns else "NULL"
        stype_col = "ZSESSIONTYPE" if "ZSESSIONTYPE" in columns else "0"

        where_clauses = ["ZCONTACTJID IS NOT NULL"]
        if "ZSESSIONTYPE" in columns:
            where_clauses.append("ZSESSIONTYPE != 3")
        where_clauses.append("(ZCONTACTJID NOT LIKE '%status%' OR ZCONTACTJID = 'status@broadcast')")

        query = f"""
            SELECT Z_PK, ZCONTACTJID, {ident_col}, {stype_col}, {name_col}, {unread_col}, {msg_count_col}
            FROM ZWACHATSESSION
            WHERE {' AND '.join(where_clauses)}
        """
        cursor.execute(query)
        chats = []
        for row in cursor.fetchall():
            pk = row[0]
            raw_jid = str(row[1]) if row[1] else ""
            ident = str(row[2]) if row[2] else ""
            stype = row[3] or 0
            name = row[4]
            unread = row[5] or 0
            mcount = row[6] or 0

            resolved_jid = raw_jid
            if stype == 0:
                if ident.endswith("@s.whatsapp.net"):
                    resolved_jid = ident
                elif raw_jid.endswith("@s.whatsapp.net"):
                    resolved_jid = raw_jid

            if "@status" in resolved_jid or "@lid.status" in resolved_jid:
                continue

            chats.append(
                IOSChat(
                    pk=pk,
                    jid=resolved_jid,
                    name=name,
                    unread_count=unread,
                    message_count=mcount,
                )
            )
        conn.close()
        return chats

    def iter_messages(self, chat_pk_map: dict[int, str] | None = None) -> Generator[IOSMessage, None, None]:
        """Iterates through all messages in chronological order."""
        if not self.chat_storage_path or not self.chat_storage_path.exists():
            raise FileNotFoundError("ChatStorage.sqlite not available")

        conn = sqlite3.connect(self.chat_storage_path)
        cursor = conn.cursor()

        if chat_pk_map is None:
            chat_pk_map = {chat.pk: chat.jid for chat in self.get_chats()}

        cursor.execute("PRAGMA table_info(ZWAMESSAGE)")
        msg_cols = {col[1] for col in cursor.fetchall()}

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ZWAMEDIAITEM'")
        has_media_table = cursor.fetchone() is not None
        med_cols = set()
        if has_media_table:
            cursor.execute("PRAGMA table_info(ZWAMEDIAITEM)")
            med_cols = {col[1] for col in cursor.fetchall()}

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ZWAGROUPMEMBER'")
        has_group_member = cursor.fetchone() is not None
        gm_cols = set()
        if has_group_member:
            cursor.execute("PRAGMA table_info(ZWAGROUPMEMBER)")
            gm_cols = {col[1] for col in cursor.fetchall()}

        stanza_col = "m.ZSTANZAID" if "ZSTANZAID" in msg_cols else "NULL"
        from_jid_col = "m.ZFROMJID" if "ZFROMJID" in msg_cols else "NULL"
        status_col = "m.ZMESSAGESTATUS" if "ZMESSAGESTATUS" in msg_cols else "0"
        type_col = "m.ZMESSAGETYPE" if "ZMESSAGETYPE" in msg_cols else "0"

        gm_jid_col = "gm.ZMEMBERJID" if has_group_member and "ZMEMBERJID" in gm_cols else "NULL"
        gm_ident_col = "gm.ZCONTACTIDENTIFIER" if has_group_member and "ZCONTACTIDENTIFIER" in gm_cols else "NULL"

        local_path_col = "med.ZMEDIALOCALPATH" if "ZMEDIALOCALPATH" in med_cols else "NULL"
        size_col = "med.ZFILESIZE" if "ZFILESIZE" in med_cols else "0"
        mime_col = "med.ZMEDIAMIMETYPE" if "ZMEDIAMIMETYPE" in med_cols else "NULL"
        title_col = "med.ZTITLE" if "ZTITLE" in med_cols else "NULL"
        vcard_col = "med.ZVCARDSTRING" if "ZVCARDSTRING" in med_cols else "NULL"
        lat_col = "med.ZLATITUDE" if "ZLATITUDE" in med_cols else "NULL"
        lon_col = "med.ZLONGITUDE" if "ZLONGITUDE" in med_cols else "NULL"

        joins = []
        if has_media_table:
            joins.append("LEFT JOIN ZWAMEDIAITEM med ON m.ZMEDIAITEM = med.Z_PK")
        if has_group_member and "ZGROUPMEMBER" in msg_cols:
            joins.append("LEFT JOIN ZWAGROUPMEMBER gm ON m.ZGROUPMEMBER = gm.Z_PK")

        query = f"""
            SELECT
                m.Z_PK,
                m.ZCHATSESSION,
                m.ZISFROMME,
                m.ZMESSAGEDATE,
                m.ZTEXT,
                {type_col},
                {status_col},
                {stanza_col},
                {from_jid_col},
                {gm_jid_col},
                {gm_ident_col},
                {local_path_col},
                {size_col},
                {mime_col},
                {title_col},
                {vcard_col},
                {lat_col},
                {lon_col}
            FROM ZWAMESSAGE m
            {' '.join(joins)}
            ORDER BY m.ZMESSAGEDATE ASC
        """

        cursor.execute(query)
        for row in cursor.fetchall():
            chat_session_pk = row[1]
            chat_jid = chat_pk_map.get(chat_session_pk)
            if not chat_jid:
                continue

            from_me = bool(row[2])
            apple_date = row[3]
            unix_ms = apple_time_to_unix_ms(apple_date)
            ios_msg_type = row[5] or 0
            android_msg_type = IOS_TO_ANDROID_MSG_TYPE.get(ios_msg_type, 0)

            # Determine sender JID
            sender_jid = None
            if not from_me:
                if chat_jid.endswith("@g.us"):
                    gm_jid = row[9]
                    gm_ident = row[10]
                    sender_jid = gm_ident or gm_jid
                    if sender_jid and (sender_jid.endswith("@g.us") or "status" in sender_jid):
                        sender_jid = None

            yield IOSMessage(
                pk=row[0],
                chat_jid=chat_jid,
                from_me=from_me,
                timestamp_ms=unix_ms,
                text=row[4],
                msg_type=android_msg_type,
                status=row[6] or 0,
                stanza_id=row[7],
                from_jid=sender_jid,
                media_local_path=row[11],
                media_size=row[12] or 0,
                media_mime=row[13],
                media_title=row[14],
                vcard_string=row[15],
                latitude=row[16],
                longitude=row[17],
            )

        conn.close()
