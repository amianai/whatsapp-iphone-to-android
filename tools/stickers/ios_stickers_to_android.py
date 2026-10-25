"""Turn the WhatsApp sticker collection of an iPhone backup into Android sticker packs.

WhatsApp on Android cannot import loose stickers or favourites, but it accepts sticker packs
provided by an app. This script reads the stickers from an iPhone backup (Finder/iTunes or
idevicebackup2, encrypted or not) and writes the `assets` folder of WhatsApp's official sample
app (https://github.com/WhatsApp/stickers, Android folder), ready to be built and installed.

What becomes a pack:
  * every installed pack that still has its files on the iPhone, with its own name;
  * the stickers that belong to no pack (favourites, recents, stickers made by you),
    as "Favourites from iPhone".
Official WhatsApp packs keep no files on the iPhone: download them again from WhatsApp's
sticker store. Lottie stickers (`.was`) cannot go into third-party packs and are skipped.

Limits from the sample app README: 512x512, static <= 100 KB, animated <= 500 KB, frames
>= 8 ms and <= 10 s in total, 3-30 stickers per pack, never static and animated in the same
pack, tray icon 96x96 PNG <= 50 KB, 1-3 emoji per sticker.

Usage:
  IOS_BACKUP_PASSWORD=... python ios_stickers_to_android.py BACKUP_DIR ASSETS_DIR [--publisher NAME]
Needs Pillow, iphone_backup_decrypt and `webpmux` (brew install webp).
"""
import argparse
import hashlib
import io
import json
import math
import os
import plistlib
import re
import shutil
import sqlite3
import subprocess
import tempfile
from concurrent.futures import ProcessPoolExecutor

from PIL import Image, ImageSequence

WA_DOMAIN = "AppDomainGroup-group.net.whatsapp.WhatsApp.shared"
STATIC_MAX, ANIM_MAX, TRAY_MAX = 100 * 1024, 500 * 1024, 50 * 1024
FAVOURITES = "Favourites from iPhone"


# --- reading the backup ------------------------------------------------------------------------

def extract(backup_dir, work_dir):
    """Copy Sticker.sqlite and the stickers/ folder of WhatsApp out of the backup (read-only)."""
    with open(os.path.join(backup_dir, "Manifest.plist"), "rb") as fh:
        encrypted = plistlib.load(fh).get("IsEncrypted", False)
    if encrypted:
        from iphone_backup_decrypt import EncryptedBackup
        password = os.environ.get("IOS_BACKUP_PASSWORD")
        if not password:
            raise SystemExit("The backup is encrypted: set IOS_BACKUP_PASSWORD.")
        b = EncryptedBackup(backup_directory=backup_dir, passphrase=password)
        b.extract_file(relative_path="Sticker.sqlite", domain_like=WA_DOMAIN,
                       output_filename=os.path.join(work_dir, "Sticker.sqlite"))
        b.extract_files(relative_paths_like="stickers/%", domain_like=WA_DOMAIN,
                        output_folder=work_dir, preserve_folders=True)
        return
    with sqlite3.connect(f"file:{os.path.join(backup_dir, 'Manifest.db')}?mode=ro", uri=True) as c:
        rows = c.execute("SELECT fileID, relativePath FROM Files WHERE domain = ? AND flags = 1 AND "
                         "(relativePath = 'Sticker.sqlite' OR relativePath LIKE 'stickers/%')", (WA_DOMAIN,))
        for file_id, rel in rows:
            target = os.path.join(work_dir, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(os.path.join(backup_dir, file_id[:2], file_id), target)


def groups(work_dir):
    """(name, folder) for every installed pack with files, favourites first."""
    db = os.path.join(work_dir, "Sticker.sqlite")
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as c:
        ent = dict(c.execute("SELECT Z_NAME, Z_ENT FROM Z_PRIMARYKEY"))
        installed = ent.get("WACDStickerPack")
        rows = c.execute("""SELECT p.Z_ENT, p.ZNAME, s.ZRELATIVEIMAGEPATH FROM ZWACDSTICKER s
                            LEFT JOIN ZWACDABSTRACTSTICKERPACK p ON p.Z_PK = s.ZSTICKERPACK
                            WHERE s.ZRELATIVEIMAGEPATH IS NOT NULL""").fetchall()
        emoji = {os.path.basename(rel): emojis.split()[:3]
                 for rel, emojis in c.execute("SELECT ZRELATIVEIMAGEPATH, ZEMOJIS FROM ZWACDSTICKER "
                                              "WHERE ZRELATIVEIMAGEPATH IS NOT NULL AND ZEMOJIS IS NOT NULL")
                 if emojis.split()}
    found = {}  # label -> folders, in order; loose stickers first
    for kind, name, rel in sorted(rows, key=lambda r: r[0] is not None):
        if kind is not None and kind != installed:
            continue  # store catalogue previews
        label = FAVOURITES if kind is None else re.sub(r"\s*\[[A-Z0-9]{4,}\]$", "", name or "Pack").strip()
        folders = found.setdefault(label, [])
        if rel.split("/")[0] not in folders:
            folders.append(rel.split("/")[0])
    return list(found.items()), emoji


# --- making valid stickers ---------------------------------------------------------------------

def webp_info(path):
    """Canvas size and frame durations as written in the file (Pillow misreports the durations)."""
    out = subprocess.run(["webpmux", "-info", path], capture_output=True, text=True).stdout
    m = re.search(r"Canvas size: (\d+) x (\d+)", out)
    size = (int(m.group(1)), int(m.group(2))) if m else None
    durations = [int(x) for x in re.findall(r"^\s*\d+:\s+\d+\s+\d+\s+\w+\s+-?\d+\s+-?\d+\s+(\d+)", out, re.M)]
    return size, durations


def is_animated(path):
    with Image.open(path) as im:
        return getattr(im, "is_animated", False)


def fit_512(frame):
    frame = frame.convert("RGBA")
    if frame.size == (512, 512):
        return frame
    k = 512 / max(frame.size)
    frame = frame.resize((max(1, round(frame.width * k)), max(1, round(frame.height * k))), Image.LANCZOS)
    canvas = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    canvas.paste(frame, ((512 - frame.width) // 2, (512 - frame.height) // 2))
    return canvas


def static_bytes(path):
    with Image.open(path) as im:
        if im.size == (512, 512) and os.path.getsize(path) <= STATIC_MAX:
            return open(path, "rb").read()  # already valid: keep the original bytes
        img = fit_512(im)
    for q in (95, 90, 85, 80, 70, 60, 50, 40):
        buf = io.BytesIO()
        img.save(buf, "WEBP", quality=q, method=4)
        if buf.tell() <= STATIC_MAX:
            return buf.getvalue()
    return None


def anim_bytes(path):
    size, durations = webp_info(path)
    if size == (512, 512) and durations and os.path.getsize(path) <= ANIM_MAX \
            and min(durations) >= 8 and sum(durations) <= 10000:
        return open(path, "rb").read()  # already valid: keep the original bytes
    with Image.open(path) as im:
        frames = [fit_512(f.copy()) for f in ImageSequence.Iterator(im)]
    if len(durations) != len(frames):
        durations = [100] * len(frames)
    durations = [max(8, d) for d in durations]
    step = 1
    while True:
        fr = frames[::step]
        du = [sum(durations[i:i + step]) for i in range(0, len(frames), step)]
        if sum(du) > 10000:  # keep the animation within 10 s
            k = 10000 / sum(du)
            du = [max(8, int(d * k)) for d in du]
        for q in (80, 65, 50, 35):
            buf = io.BytesIO()
            fr[0].save(buf, "WEBP", save_all=True, append_images=fr[1:], duration=du, loop=0, quality=q, method=4)
            if buf.tell() <= ANIM_MAX:
                return buf.getvalue()
        if len(fr) <= 2:
            return None
        step *= 2  # drop every other frame, same speed


def tray_png(sticker_bytes):
    with Image.open(io.BytesIO(sticker_bytes)) as im:
        img = im.convert("RGBA").resize((96, 96), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def chunks(items):
    n = math.ceil(len(items) / 30)
    size = math.ceil(len(items) / n)
    return [items[i:i + size] for i in range(0, len(items), size)]


# --- writing the packs -------------------------------------------------------------------------

def build(work_dir, out, publisher):
    found, emoji = groups(work_dir)
    src = os.path.join(work_dir, "stickers")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    packs, seen = [], set()
    with ProcessPoolExecutor() as pool:
        for name, folders in found:
            static, animated = [], []
            files = [os.path.join(src, d, f) for d in folders if os.path.isdir(os.path.join(src, d))
                     for f in sorted(os.listdir(os.path.join(src, d)))]
            for p in files:
                f = os.path.basename(p)
                if not f.endswith(".webp"):
                    continue
                h = hashlib.sha256(open(p, "rb").read()).hexdigest()
                if h in seen:
                    continue
                seen.add(h)
                (animated if is_animated(p) else static).append(p)
            for kind, files in (("static", static), ("animated", animated)):
                if len(files) < 3:
                    if files:
                        print(f"{name} ({kind}): {len(files)} sticker(s), fewer than the minimum of 3, skipped")
                    continue
                parts = chunks(files)
                for i, part in enumerate(parts, 1):
                    ident = str(len(packs) + 1)
                    label = name if len(parts) == 1 else f"{name} {i}"
                    if kind == "animated":
                        label += " (animated)"
                    datas = list(pool.map(anim_bytes if kind == "animated" else static_bytes, part))
                    os.makedirs(os.path.join(out, ident))
                    stickers = []
                    for p, data in zip(part, datas):
                        if data is None:
                            continue
                        fname = f"{len(stickers) + 1:02d}.webp"
                        with open(os.path.join(out, ident, fname), "wb") as fh:
                            fh.write(data)
                        stickers.append({"image_file": fname, "emojis": emoji.get(os.path.basename(p), ["😀"])})
                    tray = tray_png(open(os.path.join(out, ident, stickers[0]["image_file"]), "rb").read())
                    assert len(tray) <= TRAY_MAX
                    with open(os.path.join(out, ident, "tray.png"), "wb") as fh:
                        fh.write(tray)
                    pack = {"identifier": ident, "name": label[:128], "publisher": publisher,
                            "tray_image_file": "tray.png", "image_data_version": "1", "avoid_cache": False,
                            "publisher_email": "", "publisher_website": "", "privacy_policy_website": "",
                            "license_agreement_website": "", "stickers": stickers}
                    if kind == "animated":
                        pack["animated_sticker_pack"] = True
                    packs.append(pack)
                    print(f"{label}: {len(stickers)} stickers")
    with open(os.path.join(out, "contents.json"), "w", encoding="utf-8") as fh:
        json.dump({"android_play_store_link": "", "ios_app_store_link": "", "sticker_packs": packs}, fh,
                  ensure_ascii=False, indent=2)
    print(f"{len(packs)} packs, {sum(len(p['stickers']) for p in packs)} stickers written to {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("backup_dir", help="iPhone backup folder (the one with Manifest.db)")
    ap.add_argument("assets_dir", help="Output: app/src/main/assets of the WhatsApp/stickers sample app")
    ap.add_argument("--publisher", default="My iPhone", help="Publisher name shown in WhatsApp")
    args = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix="ios-stickers-") as work:
        extract(args.backup_dir, work)
        build(work, args.assets_dir, args.publisher)


if __name__ == "__main__":
    main()
