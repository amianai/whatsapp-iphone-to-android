"""Media file migration handler from iOS to Android WhatsApp structure."""

from pathlib import Path
import shutil
from typing import TYPE_CHECKING
from wa_fuse.constants import ANDROID_MEDIA_SUBFOLDERS

if TYPE_CHECKING:
    from wa_fuse.ios_extractor import IOSExtractor


class MediaMigrator:
    def __init__(
        self,
        ios_extractor: "IOSExtractor | None",
        android_media_dir: Path | str,
    ):
        self.ios_extractor = ios_extractor
        self.android_media_dir = Path(android_media_dir)
        self.android_media_dir.mkdir(parents=True, exist_ok=True)

    def migrate_media_file(
        self,
        ios_rel_path: str | None,
        msg_type: int,
        filename_hint: str | None = None,
    ) -> str | None:
        """Locates media file from iOS backup and copies it into Android WhatsApp media structure.

        Returns the new relative path inside Android Media directory.
        """
        if not self.ios_extractor or not ios_rel_path:
            return None

        # Resolve candidate path using IOSExtractor's on-demand resolver
        candidate = self.ios_extractor.resolve_media_file(ios_rel_path)
        if not candidate or not candidate.exists() or not candidate.is_file():
            return None

        # Determine target Android subfolder
        subfolder = ANDROID_MEDIA_SUBFOLDERS.get(msg_type, "WhatsApp Documents")
        target_dir = self.android_media_dir / subfolder
        target_dir.mkdir(parents=True, exist_ok=True)

        target_file = target_dir / candidate.name
        # If collision with different size, differentiate name
        if target_file.exists() and target_file.stat().st_size != candidate.stat().st_size:
            target_file = target_dir / f"{candidate.stem}_ios{candidate.suffix}"

        if not target_file.exists():
            shutil.copy2(candidate, target_file)

        return f"Media/{subfolder}/{target_file.name}"
