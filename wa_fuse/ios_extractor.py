"""iOS WhatsApp Backup Extractor and Parser.

Supports a direct ChatStorage.sqlite file, an already extracted folder, and full
iTunes/Finder backups, both unencrypted and encrypted (with the backup password).
"""

from dataclasses import dataclass
from pathlib import Path
import plistlib
import re
import shutil
import sqlite3
import subprocess
from typing import Callable, Generator

from wa_fuse.constants import apple_time_to_unix_ms

WA_DOMAIN = "AppDomainGroup-group.net.whatsapp.WhatsApp.shared"
WA_BUSINESS_DOMAIN = "AppDomainGroup-group.net.whatsapp.WhatsAppSMB.shared"
CHAT_DB = "ChatStorage.sqlite"
CONTACTS_DB = "ContactsV2.sqlite"
# Only these parts of the WhatsApp container are needed.
_WANTED_PREFIXES = (CHAT_DB, CONTACTS_DB, "Message/Media/")
# SQLite keeps recent writes in the -wal file until a checkpoint. A backup taken
# while WhatsApp was running can hold the newest messages only there.
_DB_SIDECARS = ("-wal",)

_MIME_RE = re.compile(r"^[a-z]+/[\w.+-]+(;.*)?$", re.IGNORECASE)


def _tiny_gray(path: Path) -> bytes | None:
    """First frame of a photo or video as 16x16 grey pixels (needs ffmpeg)."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    try:
        out = subprocess.run(
            [ffmpeg, "-v", "error", "-i", str(path), "-frames:v", "1",
             "-vf", "scale=16:16:flags=area,format=gray", "-f", "rawvideo", "-"],
            capture_output=True, timeout=60, check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return out if len(out) == 256 else None


# Mean grey-level difference (0-255) below which two pictures are the same one.
# Measured on a real database: SD/HD copies stay under 1.5, burst shots and
# different videos start around 3.
_SAME_PICTURE = 2.0
# WhatsApp sends standard-quality photos at most this many pixels on the long side.
_STANDARD_PHOTO_SIDE = 1600


def _difference(a: bytes | None, b: bytes | None) -> float | None:
    """Mean grey-level difference of two tiny pictures, None if one is missing."""
    if a is None or b is None:
        return None
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


@dataclass
class IOSChat:
    pk: int
    jid: str
    name: str | None
    unread_count: int = 0
    message_count: int = 0
    session_type: int = 0
    lid: str | None = None  # the contact's @lid, for 1-on-1 chats
    archived: bool = False


@dataclass
class IOSMessage:
    pk: int
    chat_jid: str
    from_me: bool
    timestamp_ms: int
    text: str | None
    msg_type: int  # raw iOS ZMESSAGETYPE
    status: int
    stanza_id: str | None
    from_jid: str | None = None
    media_local_path: str | None = None
    media_size: int = 0
    media_mime: str | None = None
    media_title: str | None = None
    vcard_string: str | None = None
    vcard_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    media_duration: int = 0
    starred: bool = False


def is_encrypted_backup(backup_dir: Path) -> bool:
    """True when the Finder/iTunes backup folder holds an encrypted backup."""
    manifest_plist = Path(backup_dir) / "Manifest.plist"
    if not manifest_plist.exists():
        return False
    with open(manifest_plist, "rb") as f:
        return bool(plistlib.load(f).get("IsEncrypted"))


def _wanted(relative_path: str) -> bool:
    return relative_path.startswith(_WANTED_PREFIXES)


class IOSExtractor:
    def __init__(
        self,
        source_path: Path | str,
        staging_dir: Path | str | None = None,
        is_business: bool = False,
        backup_password: str | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ):
        self.source_path = Path(source_path)
        self.staging_dir = Path(staging_dir) if staging_dir else self.source_path.parent / "ios_extracted"
        self.is_business = is_business
        self.backup_password = backup_password
        self.progress_callback = progress_callback
        self.chat_storage_path: Path | None = None
        self.contacts_db_path: Path | None = None
        self.media_dir: Path | None = None
        self.manifest_db_path: Path | None = None
        self.domain: str = WA_BUSINESS_DOMAIN if is_business else WA_DOMAIN
        # True when media files live in a staging copy we own and may move.
        self.media_is_staged = False
        self._media_map: dict[str, str] = {}

        self._resolve_paths()

    def _resolve_paths(self):
        """Identifies if source is a direct sqlite file, a directory with ChatStorage,

        or an iTunes backup folder with Manifest.db.
        """
        if self.source_path.is_file():
            if self.source_path.name.lower().endswith((".sqlite", ".db")):
                self.chat_storage_path = self.source_path
                self.media_dir = self.source_path.parent
                contacts = self.source_path.parent / CONTACTS_DB
                self.contacts_db_path = contacts if contacts.exists() else None
                return
            raise ValueError(f"Unrecognized file type: {self.source_path}")

        # A directory that already contains ChatStorage.sqlite (extracted backup)
        direct_db = self.source_path / CHAT_DB
        if direct_db.exists():
            self.chat_storage_path = direct_db
            self.media_dir = self.source_path
            contacts = self.source_path / CONTACTS_DB
            self.contacts_db_path = contacts if contacts.exists() else None
            return

        manifest_db = self.source_path / "Manifest.db"
        if manifest_db.exists():
            self.manifest_db_path = manifest_db
            if is_encrypted_backup(self.source_path):
                self._setup_from_encrypted_backup()
            else:
                self._setup_from_itunes_backup(manifest_db)
            return

        raise FileNotFoundError(
            f"Could not find ChatStorage.sqlite or Manifest.db in {self.source_path}"
        )

    def _setup_from_encrypted_backup(self):
        """Decrypts only the WhatsApp files of an encrypted backup into staging_dir.

        Extraction is incremental: running it again after a newer backup only
        decrypts the files that changed.
        """
        if not self.backup_password:
            raise ValueError(
                "This iPhone backup is encrypted: pass the backup password "
                "(--backup-password or the IOS_BACKUP_PASSWORD environment variable)."
            )
        from iphone_backup_decrypt import EncryptedBackup

        backup = EncryptedBackup(backup_directory=str(self.source_path), passphrase=self.backup_password)
        backup.test_decryption()
        self.staging_dir.mkdir(parents=True, exist_ok=True)

        domain = self.domain
        with backup.manifest_db_cursor() as cur:
            cur.execute("SELECT 1 FROM Files WHERE domain = ? AND relativePath = ?", (domain, CHAT_DB))
            if cur.fetchone() is None:
                raise FileNotFoundError(f"{CHAT_DB} not found in the encrypted backup for domain {domain}")

        # The databases are always decrypted again. Opening them updates their
        # modification time, so the incremental check would keep a stale copy,
        # and an old -wal would be replayed into a newer database.
        for db_name in (CHAT_DB, CONTACTS_DB):
            for suffix in ("",) + _DB_SIDECARS + ("-shm",):
                stale = self.staging_dir / (db_name + suffix)
                if stale.exists():
                    stale.unlink()

        def keep(*, relative_path, n, total_files, **kwargs):
            if self.progress_callback and n % 2000 == 0:
                self.progress_callback(n, total_files)
            return _wanted(relative_path)

        backup.extract_files(
            relative_paths_like="%",
            domain_like=domain,
            output_folder=str(self.staging_dir),
            preserve_folders=True,
            incremental=True,
            filter_callback=keep,
        )

        self.chat_storage_path = self.staging_dir / CHAT_DB
        contacts = self.staging_dir / CONTACTS_DB
        self.contacts_db_path = contacts if contacts.exists() else None
        self.media_dir = self.staging_dir
        self.media_is_staged = True

    def _setup_from_itunes_backup(self, manifest_db: Path):
        """Copies the WhatsApp databases out of an unencrypted backup and maps its media files."""
        conn = sqlite3.connect(f"file:{manifest_db}?mode=ro", uri=True)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT 1 FROM Files WHERE domain = ? AND relativePath = ?", (self.domain, CHAT_DB)
        )
        if cursor.fetchone() is None:
            if self.is_business:
                conn.close()
                raise FileNotFoundError(
                    f"ChatStorage.sqlite not found in iTunes backup Manifest.db for domain {self.domain}"
                )
            # Fallback to any WhatsApp domain if standard not found
            cursor.execute(
                """
                SELECT domain FROM Files
                WHERE (domain LIKE '%whatsapp%' OR domain LIKE '%WhatsApp%')
                AND relativePath = ?
                ORDER BY domain ASC LIMIT 1
                """,
                (CHAT_DB,),
            )
            row = cursor.fetchone()
            if row is None:
                conn.close()
                raise FileNotFoundError(
                    f"ChatStorage.sqlite not found in iTunes backup Manifest.db for domain {self.domain}"
                )
            self.domain = row[0]

        # flags = 1 marks regular files (2 = folder, 4 = symlink)
        cursor.execute("SELECT relativePath, fileID FROM Files WHERE domain = ? AND flags = 1", (self.domain,))
        files = {rel: fid for rel, fid in cursor.fetchall() if rel and _wanted(rel)}
        conn.close()

        # Work on a private copy of the databases so the backup is never touched
        # and the -wal file is replayed under its expected name.
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        for db_name in (CHAT_DB, CONTACTS_DB):
            for suffix in ("",) + _DB_SIDECARS:
                rel = db_name + suffix
                target = self.staging_dir / rel
                if rel in files:
                    shutil.copyfile(self._blob_path(files[rel]), target)
                elif target.exists():
                    target.unlink()  # stale copy from an older run

        self.chat_storage_path = self.staging_dir / CHAT_DB
        contacts = self.staging_dir / CONTACTS_DB
        self.contacts_db_path = contacts if contacts.exists() else None
        self._media_map = {rel: fid for rel, fid in files.items() if rel.startswith("Message/Media/")}

    def _blob_path(self, file_id: str) -> Path:
        """In iOS 10+ backups a file lives at <backup_dir>/xx/xxxxxxxx..."""
        nested = self.source_path / file_id[:2] / file_id
        return nested if nested.exists() else self.source_path / file_id

    def resolve_media_file(self, rel_path: str | None) -> Path | None:
        """Resolves an iOS ZMEDIALOCALPATH to an actual file on disk."""
        if not rel_path:
            return None

        clean_rel = rel_path.lstrip("/\\")
        if clean_rel.startswith("Message/"):
            clean_rel = clean_rel[len("Message/"):]

        # 1. Unencrypted iTunes / Finder backup: hashed blobs listed in Manifest.db
        if self._media_map:
            fid = self._media_map.get(f"Message/{clean_rel}")
            if fid:
                disk_path = self._blob_path(fid)
                if disk_path.is_file():
                    return disk_path

        # 2. Extracted or staged folder (relative paths preserved)
        if self.media_dir and self.media_dir.exists():
            candidates = [self.media_dir / "Message" / clean_rel, self.media_dir / clean_rel]
            if clean_rel.startswith("Media/"):
                candidates.append(self.media_dir / clean_rel[len("Media/"):])
            for candidate in candidates:
                if candidate.is_file():
                    return candidate

        return None

    def _connect(self) -> sqlite3.Connection:
        if not self.chat_storage_path or not self.chat_storage_path.exists():
            raise FileNotFoundError("ChatStorage.sqlite not available")
        return sqlite3.connect(self.chat_storage_path)

    def get_chats(self) -> list[IOSChat]:
        """Loads all chat sessions from ChatStorage.sqlite.

        Status updates, broadcast lists and channels are left out: Android keeps
        them elsewhere, and a broadcast message also sits in each recipient's chat.
        """
        conn = self._connect()
        cursor = conn.cursor()

        cursor.execute("PRAGMA table_info(ZWACHATSESSION)")
        columns = {col[1] for col in cursor.fetchall()}

        name_col = "ZPARTNERNAME" if "ZPARTNERNAME" in columns else "NULL"
        unread_col = "ZUNREADCOUNT" if "ZUNREADCOUNT" in columns else "0"
        msg_count_col = "ZMESSAGECOUNTER" if "ZMESSAGECOUNTER" in columns else "0"
        ident_col = "ZCONTACTIDENTIFIER" if "ZCONTACTIDENTIFIER" in columns else "NULL"
        stype_col = "ZSESSIONTYPE" if "ZSESSIONTYPE" in columns else "0"
        archived_col = "ZARCHIVED" if "ZARCHIVED" in columns else "0"

        where_clauses = ["ZCONTACTJID IS NOT NULL"]
        if "ZSESSIONTYPE" in columns:
            where_clauses.append("ZSESSIONTYPE NOT IN (2, 3)")
        where_clauses.append("ZCONTACTJID NOT LIKE '%status%'")
        where_clauses.append("ZCONTACTJID NOT LIKE '%@broadcast'")
        where_clauses.append("ZCONTACTJID NOT LIKE '%@newsletter'")

        query = f"""
            SELECT Z_PK, ZCONTACTJID, {ident_col}, {stype_col}, {name_col}, {unread_col}, {msg_count_col},
                   {archived_col}
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

            # Modern iOS can key 1-on-1 chats by an opaque @lid; prefer the phone JID.
            # The other identifier is kept: it is either the @lid or the phone JID.
            resolved_jid = raw_jid
            lid = None
            if stype == 0:
                if ident.endswith("@s.whatsapp.net"):
                    resolved_jid = ident
                elif raw_jid.endswith("@s.whatsapp.net"):
                    resolved_jid = raw_jid
                if raw_jid.endswith("@lid"):
                    lid = raw_jid
                elif ident.endswith("@lid"):
                    lid = ident

            if "@status" in resolved_jid or "@lid.status" in resolved_jid:
                continue

            chats.append(
                IOSChat(
                    pk=pk,
                    jid=resolved_jid,
                    name=name,
                    unread_count=unread,
                    archived=bool(row[7]),
                    message_count=mcount,
                    session_type=stype,
                    lid=lid if resolved_jid != lid else None,
                )
            )
        conn.close()
        return chats

    def iter_messages(self, chat_pk_map: dict[int, str] | None = None) -> Generator[IOSMessage, None, None]:
        """Iterates through all messages of the given chats in chronological order."""
        conn = self._connect()
        cursor = conn.cursor()

        if chat_pk_map is None:
            chat_pk_map = {chat.pk: chat.jid for chat in self.get_chats()}

        def columns_of(table: str) -> set[str]:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
            if cursor.fetchone() is None:
                return set()
            cursor.execute(f"PRAGMA table_info({table})")
            return {col[1] for col in cursor.fetchall()}

        msg_cols = columns_of("ZWAMESSAGE")
        med_cols = columns_of("ZWAMEDIAITEM")
        gm_cols = columns_of("ZWAGROUPMEMBER")

        def col(alias: str, name: str, cols: set[str], default: str = "NULL") -> str:
            return f"{alias}.{name}" if name in cols else default

        joins = []
        if med_cols:
            if "ZMEDIAITEM" in msg_cols:
                joins.append("LEFT JOIN ZWAMEDIAITEM med ON m.ZMEDIAITEM = med.Z_PK")
            elif "ZMESSAGE" in med_cols:
                joins.append("LEFT JOIN ZWAMEDIAITEM med ON med.ZMESSAGE = m.Z_PK")
            else:
                med_cols = set()
        if gm_cols and "ZGROUPMEMBER" in msg_cols:
            joins.append("LEFT JOIN ZWAGROUPMEMBER gm ON m.ZGROUPMEMBER = gm.Z_PK")
        else:
            gm_cols = set()

        query = f"""
            SELECT
                m.Z_PK,
                m.ZCHATSESSION,
                m.ZISFROMME,
                m.ZMESSAGEDATE,
                m.ZTEXT,
                {col('m', 'ZMESSAGETYPE', msg_cols, '0')},
                {col('m', 'ZMESSAGESTATUS', msg_cols, '0')},
                {col('m', 'ZSTANZAID', msg_cols)},
                {col('gm', 'ZMEMBERJID', gm_cols)},
                {col('gm', 'ZCONTACTIDENTIFIER', gm_cols)},
                {col('med', 'ZMEDIALOCALPATH', med_cols)},
                {col('med', 'ZFILESIZE', med_cols, '0')},
                {col('med', 'ZVCARDSTRING', med_cols)},
                {col('med', 'ZVCARDNAME', med_cols)},
                {col('med', 'ZTITLE', med_cols)},
                {col('med', 'ZLATITUDE', med_cols)},
                {col('med', 'ZLONGITUDE', med_cols)},
                {col('med', 'ZMOVIEDURATION', med_cols, '0')},
                {col('m', 'ZSTARRED', msg_cols, '0')}
            FROM ZWAMESSAGE m
            {' '.join(joins)}
            ORDER BY m.ZMESSAGEDATE ASC, m.Z_PK ASC
        """

        cursor.execute(query)
        for row in cursor:
            chat_jid = chat_pk_map.get(row[1])
            if not chat_jid:
                continue

            from_me = bool(row[2])
            ios_type = row[5] or 0

            # Determine sender JID for group messages
            sender_jid = None
            if not from_me and chat_jid.endswith("@g.us"):
                sender_jid = row[9] or row[8]
                if sender_jid and (sender_jid.endswith("@g.us") or "status" in sender_jid):
                    sender_jid = None

            # ZVCARDSTRING holds the MIME type for media and the vCard text for contacts.
            vcard_field = row[12]
            mime = vcard_field if vcard_field and _MIME_RE.match(vcard_field) else None

            yield IOSMessage(
                pk=row[0],
                chat_jid=chat_jid,
                from_me=from_me,
                timestamp_ms=apple_time_to_unix_ms(row[3]),
                text=row[4],
                msg_type=ios_type,
                status=row[6] or 0,
                stanza_id=row[7],
                from_jid=sender_jid,
                media_local_path=row[10],
                media_size=row[11] or 0,
                media_mime=mime,
                media_title=row[14],
                vcard_string=vcard_field if vcard_field and not mime else None,
                vcard_name=row[13],
                latitude=row[15],
                longitude=row[16],
                media_duration=int(row[17] or 0),
                starred=bool(row[18]),
            )

        conn.close()

    def find_hd_copies(self, chat_pks: set[int] | None = None) -> set[int]:
        """Message pks of the standard copy of photos and videos also sent in HD.

        WhatsApp sends an HD photo or video twice, a standard copy and the HD one,
        and the iPhone shows a single bubble. The HD copy can arrive minutes later
        and, when several are sent together, after all the standard ones. A
        standard copy pairs with a larger one of the same chat, sender and type,
        with the same aspect ratio (videos: the same length) and the same picture
        (first frame for videos); the closest picture wins, so two different
        photos of an album are never merged. When a file is missing the pair must
        be two consecutive messages at most 3 seconds apart.
        """
        conn = self._connect()
        try:
            cols = {c[1] for c in conn.execute("PRAGMA table_info(ZWAMESSAGE)")}
            sort_col = "m.ZSORT" if "ZSORT" in cols else "NULL"
            rows = conn.execute(
                f"""SELECT m.Z_PK, m.ZCHATSESSION, m.ZMESSAGETYPE, m.ZISFROMME, m.ZMESSAGEDATE, {sort_col},
                          med.ZMOVIEDURATION, med.ZLATITUDE, med.ZLONGITUDE, med.ZMEDIALOCALPATH,
                          COALESCE(m.ZTEXT, med.ZTITLE, '') <> ''
                   FROM ZWAMESSAGE m JOIN ZWAMEDIAITEM med ON med.ZMESSAGE = m.Z_PK
                   WHERE m.ZMESSAGETYPE IN (1, 2)
                   ORDER BY m.ZCHATSESSION, m.ZMESSAGEDATE, m.Z_PK"""
            ).fetchall()
        except sqlite3.Error:
            return set()
        finally:
            conn.close()

        groups: dict[tuple, list] = {}
        for row in rows:
            if (chat_pks is None or row[1] in chat_pks) and row[7] and row[8]:
                groups.setdefault((row[1], row[2], row[3]), []).append(row)

        thumbs: dict[Path, bytes | None] = {}

        def thumb(path: Path) -> bytes | None:
            if path not in thumbs:
                thumbs[path] = _tiny_gray(path)
            return thumbs[path]

        copies: set[int] = set()
        for items in groups.values():
            files = {row[0]: self.resolve_media_file(row[9]) for row in items}
            taken: set[int] = set()
            for i, big in enumerate(items):
                pk_big, _, kind, _, date_big, sort_big, dur_big, h_big, w_big, _, cap_big = big
                if pk_big in taken:
                    continue
                window = 1800 if kind == 2 else 300
                best = None
                for small in items[max(0, i - 20):i + 21]:
                    pk, _, _, _, date, sort, dur, h, w, _, cap = small
                    if pk == pk_big or pk in taken or abs(date - date_big) > window or h * w >= h_big * w_big:
                        continue
                    if abs(h / w - h_big / w_big) > 0.03 or (kind == 2 and abs((dur or 0) - (dur_big or 0)) > 1):
                        continue
                    if kind == 1 and not max(h, w) <= _STANDARD_PHOTO_SIDE < max(h_big, w_big):
                        continue
                    if cap and not cap_big:
                        continue  # the standard copy carries the only caption
                    file_small, file_hd = files[pk], files[pk_big]
                    if file_small and file_hd:
                        diff = _difference(thumb(file_small), thumb(file_hd))
                        if diff is not None and diff <= _SAME_PICTURE and (best is None or diff < best[0]):
                            best = (diff, pk)
                    elif (file_small or file_hd) and best is None and sort is not None and \
                            abs(sort - sort_big) == 1 and abs(date - date_big) <= 3:
                        best = (_SAME_PICTURE + 1, pk if file_hd else pk_big)  # drop the copy without a file
                if best:
                    copies.add(best[1])
                    taken.update((best[1], pk_big))
        return copies

    def get_push_names(self) -> dict[str, str]:
        """JID -> name the person set in their own WhatsApp profile."""
        conn = self._connect()
        try:
            cur = conn.execute("SELECT ZJID, ZPUSHNAME FROM ZWAPROFILEPUSHNAME WHERE ZJID IS NOT NULL")
            return {jid: name for jid, name in cur.fetchall() if name}
        except sqlite3.Error:
            return {}
        finally:
            conn.close()

    def get_address_book_jids(self) -> set[str]:
        """JIDs that WhatsApp matched to the iPhone address book (ContactsV2.sqlite)."""
        if not self.contacts_db_path:
            return set()
        conn = sqlite3.connect(self.contacts_db_path)
        try:
            cur = conn.execute("SELECT ZWHATSAPPID FROM ZWAADDRESSBOOKCONTACT WHERE ZWHATSAPPID IS NOT NULL")
            jids = set()
            for (wa_id,) in cur.fetchall():
                wa_id = str(wa_id)
                jids.add(wa_id if "@" in wa_id else f"{wa_id}@s.whatsapp.net")
            return jids
        except sqlite3.Error:
            return set()
        finally:
            conn.close()

    def get_group_member_jids(self) -> set[str]:
        """Phone JIDs of everyone who appears as a member of a group."""
        conn = self._connect()
        try:
            cols = {c[1] for c in conn.execute("PRAGMA table_info(ZWAGROUPMEMBER)").fetchall()}
            if not cols:
                return set()
            ident = "ZCONTACTIDENTIFIER" if "ZCONTACTIDENTIFIER" in cols else "NULL"
            jids = set()
            for member_jid, identifier in conn.execute(f"SELECT ZMEMBERJID, {ident} FROM ZWAGROUPMEMBER"):
                for j in (identifier, member_jid):
                    if j and str(j).endswith("@s.whatsapp.net"):
                        jids.add(str(j))
                        break
            return jids
        finally:
            conn.close()
