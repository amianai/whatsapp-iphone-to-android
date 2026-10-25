"""Media file migration handler from iOS to Android WhatsApp structure."""

import base64
from dataclasses import dataclass
import hashlib
import mimetypes
import os
from pathlib import Path
import shutil
from typing import TYPE_CHECKING

from wa_fuse.constants import (
    ANDROID_AUDIO,
    ANDROID_MEDIA_SUBFOLDERS,
    ANDROID_STICKER,
    DEFAULT_MIME_BY_ANDROID_TYPE,
    VOICE_NOTES_SUBFOLDER,
)

if TYPE_CHECKING:
    from wa_fuse.ios_extractor import IOSExtractor

# mimetypes picks odd extensions for a few common WhatsApp types (e.g. .jpe).
_PREFERRED_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "audio/ogg": ".opus",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/aac": ".aac",
    "application/pdf": ".pdf",
}
_CHUNK = 1024 * 1024


@dataclass
class MigratedMedia:
    relative_path: str  # path stored in message_media.file_path, e.g. "Media/WhatsApp Images/x.jpg"
    size: int
    file_hash: str  # base64 SHA-256 of the file, the format WhatsApp uses
    mime_type: str


def _extension_for(mime: str | None) -> str:
    if not mime:
        return ""
    base = mime.split(";", 1)[0].strip().lower()
    return _PREFERRED_EXTENSIONS.get(base) or mimetypes.guess_extension(base) or ""


class MediaMigrator:
    def __init__(
        self,
        ios_extractor: "IOSExtractor | None",
        android_media_dir: Path | str,
        move_files: bool = False,
    ):
        self.ios_extractor = ios_extractor
        self.android_media_dir = Path(android_media_dir)
        self.android_media_dir.mkdir(parents=True, exist_ok=True)
        # Moving is only safe when the source is a staging copy we own.
        self.move_files = move_files
        # iOS path -> result, so several messages sharing one file reuse it
        # (necessary when files are moved out of the staging folder).
        self._done: dict[str, MigratedMedia] = {}

    def migrate_media_file(
        self,
        ios_rel_path: str | None,
        msg_type: int,
        filename_hint: str | None = None,
        from_me: bool = False,
        mime_type: str | None = None,
        timestamp_ms: int | None = None,
    ) -> MigratedMedia | None:
        """Copies (or moves) one media file into the Android WhatsApp media tree.

        msg_type is the Android message type. Returns None when the file is not
        in the backup (for instance media never downloaded on the iPhone).
        """
        if not self.ios_extractor or not ios_rel_path:
            return None

        key = ios_rel_path.lstrip("/\\")
        if key in self._done:
            return self._done[key]
        candidate = self.ios_extractor.resolve_media_file(ios_rel_path)
        if candidate is None:
            return None

        # The original iOS name, not the backup blob name, with a real extension.
        name = Path(ios_rel_path).name.rstrip(".") or candidate.name
        stem, ext = os.path.splitext(name)
        if not ext:
            ext = _extension_for(mime_type) or os.path.splitext(candidate.name)[1]
        if not ext:
            ext = _extension_for(DEFAULT_MIME_BY_ANDROID_TYPE.get(msg_type))
        mime = mime_type or mimetypes.guess_type(f"x{ext}")[0] or DEFAULT_MIME_BY_ANDROID_TYPE.get(msg_type)

        if msg_type == ANDROID_AUDIO and ext.lower() == ".opus":
            subfolder = VOICE_NOTES_SUBFOLDER
        else:
            subfolder = ANDROID_MEDIA_SUBFOLDERS.get(msg_type, "WhatsApp Documents")
        target_dir = self.android_media_dir / subfolder
        if from_me and subfolder != VOICE_NOTES_SUBFOLDER and msg_type != ANDROID_STICKER:
            # Android keeps your own media in Sent/, hidden from the gallery.
            target_dir = target_dir / "Sent"
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / ".nomedia").touch(exist_ok=True)
        target_dir.mkdir(parents=True, exist_ok=True)

        target_file = target_dir / f"{stem}{ext}"
        n = 1
        while target_file.exists():
            if target_file.stat().st_size == candidate.stat().st_size and _sha256_b64(target_file) == _sha256_b64(candidate):
                break  # same file from an earlier run
            target_file = target_dir / f"{stem}-{n}{ext}"
            n += 1

        if not target_file.exists():
            if self.move_files:
                shutil.move(candidate, target_file)
            else:
                shutil.copyfile(candidate, target_file)
        if timestamp_ms:
            # The gallery sorts by file date: use the date of the message.
            ts = timestamp_ms / 1000
            os.utime(target_file, (ts, ts))

        result = MigratedMedia(
            relative_path=f"Media/{target_file.relative_to(self.android_media_dir).as_posix()}",
            size=target_file.stat().st_size,
            file_hash=_sha256_b64(target_file),
            mime_type=mime,
        )
        self._done[key] = result
        return result


def _sha256_b64(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return base64.b64encode(h.digest()).decode()
