# whatsapp-iphone-to-android

Move your WhatsApp chats from an **iPhone to an Android phone without a bridge phone, without
Google's "Copy apps & data" tool and without paid software** — everything runs locally on your computer.

The tool reads WhatsApp's database and media from a local iPhone backup, merges them into a real
backup made by WhatsApp on the Android phone (encrypted with a 64-digit key), re-encrypts the result
with the same header and lets WhatsApp restore it as if it were its own backup.

It started as a fork of [pl402/wa-fuse](https://github.com/pl402/wa-fuse) and fixes the problems found
while doing a real migration: lost messages, chats that would not open, distorted photos, duplicated
HD media and more (see [What was fixed](#what-was-fixed-compared-to-wa-fuse-100)).

> **Unofficial project.** Not affiliated with, endorsed by or connected to WhatsApp or Meta.
> Use it only on your own data, read the [risks](#risks) first and keep your iPhone untouched
> until you have checked everything on the new phone.

---

## Why

WhatsApp's official iPhone → Android transfer needs Google's setup tool (or a cable transfer during
setup). On phones without it — for example **GrapheneOS** — or when the wireless transfer keeps failing
halfway, there is no official path. Commercial tools exist, but they read all your chats in clear text.

This project does the migration offline, with open-source tools, and was tested end to end on
**iOS 26.6 → WhatsApp for Android 2.26 on GrapheneOS (Android 17)**, with a macOS 15 computer and a
real account of several hundred thousand messages and ~30 GB of media.

## What is transferred

| Transferred | Not transferred |
|---|---|
| Text messages, in order, in every 1-on-1 chat, group and community | Reactions |
| Photos, videos, voice notes, documents, GIFs, stickers (original names, dates, real hashes) | Quoted-reply preview box (the message itself is there) |
| Captions, starred messages, archived chats | Call history and call bubbles |
| Shared contacts and locations (as readable text) | Status updates, channel posts, broadcast lists |
| View-once media as a text placeholder (the files no longer exist) | Polls (only their text, if any) |
| A `.vcf` of people you only knew on WhatsApp (optional) | Media that the iPhone never downloaded |

Your sticker *collection* (installed packs and favourites) is not part of the chats: a separate
[sticker tool](#stickers) turns it into Android sticker packs.

## How it works

```
iPhone ──idevicebackup2──▶ encrypted local backup ──wa-fuse──▶ ChatStorage.sqlite + media
                                                                   │
Android phone ── WhatsApp backup (64-digit key) ──▶ msgstore.db ──┤ merge, fix, re-encrypt
                                                                   ▼
                     msgstore.db.crypt15 + WhatsApp/Media ──adb push──▶ restore on the phone
```

1. Make an **encrypted** local backup of the iPhone (Finder or `idevicebackup2`).
2. Register WhatsApp on Android, turn on the end-to-end encrypted backup with a **64-digit key** and
   pull the backup file: it is the template that WhatsApp will accept back.
3. Run `wa-fuse pipeline`: it decrypts only WhatsApp's files from the iPhone backup, inserts every
   message into the Android database, copies the media into the Android folder layout and
   re-encrypts the database with the template's header.
4. Clear WhatsApp's data on the phone, push the files, register again and choose **Restore**.

The complete, tested procedure — including a dry run with a second phone number — is in
**[docs/migration-guide.md](docs/migration-guide.md)**.

## Requirements

* macOS or Linux with Python 3.12+ and [uv](https://docs.astral.sh/uv/)
* [libimobiledevice](https://libimobiledevice.org) (`idevicebackup2`) for the iPhone backup
* Android platform tools (`adb`) and USB debugging on the phone
* `ffmpeg`, used to recognise the standard copies of photos and videos sent in HD
* Free space: the iPhone backup (an external drive is fine) plus about the size of WhatsApp on the
  iPhone on the internal disk
* Recommended: a **second phone number** for the dry run

```bash
brew install libimobiledevice android-platform-tools uv ffmpeg   # macOS
uv sync
uv run pytest -q tests                                           # all tests must pass
```

## Quick start

```bash
# what is in the iPhone backup (decrypts only WhatsApp's files into the staging folder)
IOS_BACKUP_PASSWORD=... uv run wa-fuse inspect-ios /path/to/iphone-backup --staging-dir ~/wa/staging

# rebuild the Android backup (add --chats "name1,name2" for a dry run on a few chats)
export WA_BACKUP_KEY=<64 hex digits> IOS_BACKUP_PASSWORD=...
uv run wa-fuse pipeline \
  --ios /path/to/iphone-backup --staging-dir ~/wa/staging \
  --android-crypt ~/wa/template.crypt15 --key "$WA_BACKUP_KEY" \
  --output-dir ~/wa/output --move-media

# copy it to the phone after `adb shell pm clear com.whatsapp`
tools/push_media.sh ~/wa/output
```

`--move-media` moves the media out of the staging folder instead of copying them, so the internal
disk needs the WhatsApp size only once. `output/report.json` lists, for every chat, how many messages
were read, inserted or skipped and how many media files were copied or missing.

Other commands: `decrypt` / `encrypt` (`.crypt14/15`), `merge`, `export-contacts`
(`uv run wa-fuse --help`). The command keeps the upstream name `wa-fuse`.

## What was fixed compared to wa-fuse 1.0.0

Every fix is covered by a test in `tests/test_migration_fixes.py` or `tests/test_cli_pipeline.py`.

* **1-on-1 chats did not open on recent WhatsApp versions.** WhatsApp now keys personal chats by the
  contact's `@lid` identity: a chat restored under the phone number showed its preview in the list but
  opened empty, and WhatsApp created a new empty chat. Chats are now created under the `@lid` taken
  from the iPhone database, with the `jid_map` link to the phone number, like WhatsApp does.
* **Messages lost as false duplicates.** Messages of the same chat sent within 2 seconds (albums, quick
  replies) were dropped: an album of 5 photos became 1.
* **Photos and videos distorted** in WhatsApp's viewer: width and height were swapped (iOS stores the
  height in `ZLATITUDE` and the width in `ZLONGITUDE`, rotated videos included).
* **HD photos and videos appeared twice.** WhatsApp stores a standard copy and an HD copy as two
  messages and shows one bubble; the standard copy is now left out, only when the two pictures
  (first frame for videos) really match.
* **View-once media** (newer iOS message types 38/39/53) became empty bubbles or were dropped: they
  are now a short text placeholder, so replies still make sense. Round video messages are kept.
* **Media from Finder backups** lost their names and extensions; MIME types were read from the wrong
  field; file dates, SHA-256 hashes, durations and the `Sent/` folder are now correct.
* Shared **contacts and locations** were swapped; they now become readable text. GIFs and stickers are
  mapped; system and deleted messages are skipped instead of becoming empty bubbles.
* **Encrypted iPhone backups** are supported (only WhatsApp's files are decrypted, incrementally) and
  the `ChatStorage.sqlite-wal` file is read, otherwise the newest messages were missing.
* Chronological order is guaranteed (`sort_id`), **archived chats** stay archived, `--chats` limits a
  run to some chats, `report.json` gives per-chat counts, `export-contacts` writes a `.vcf`.

## Stickers

WhatsApp on Android cannot import loose stickers or favourites, but it accepts sticker packs offered
by an app. `tools/stickers/` turns the iPhone collection into such an app:

```bash
uv sync --extra stickers && brew install webp
IOS_BACKUP_PASSWORD=... uv run python tools/stickers/ios_stickers_to_android.py /path/to/iphone-backup ~/wa/sticker-assets
tools/stickers/build_sticker_app.sh ~/wa/sticker-assets com.yourname.iphonestickers
adb install --user 0 <the APK printed by the script>
```

Installed packs keep their name; stickers that belong to no pack (favourites, recents, your own)
become "Favourites from iPhone". Everything is resized, compressed and split to WhatsApp's limits
(512×512, 100 KB static / 500 KB animated, 3–30 per pack, static and animated never mixed).
Official WhatsApp packs keep no files on the iPhone: download them again from WhatsApp's store.
Open the app, tap **+** on every pack and confirm **Add to WhatsApp**. Keep the app installed:
WhatsApp reads the stickers from it.

## Safety rules

* **Never uninstall WhatsApp or delete its data on the iPhone** until the new phone has been checked:
  the iPhone keeps a full copy even after the account moves.
* Make the iPhone backup **encrypted**; keep decrypted files (`staging`, `output`) on the computer's
  internal disk and delete them at the end.
* Pass the backup password and the 64-digit key through `IOS_BACKUP_PASSWORD` and `WA_BACKUP_KEY`,
  never in files you keep. Save the 64-digit key in your password manager.
* Do not request WhatsApp verification codes repeatedly: after a few attempts registration is blocked
  for hours.
* When WhatsApp asks to restore from Google Drive or to transfer from the old phone, **skip** it.

## Risks

* WhatsApp might refuse a rebuilt backup or change its database format in an update. Do the dry run
  with a second number and the final migration right after it, with the same WhatsApp version.
* Restoring a modified backup is outside WhatsApp's supported paths and may conflict with its terms
  of service. No account suspension was observed, but it cannot be ruled out.
* Messages that reach the iPhone after its last backup are not migrated: make a fresh (incremental)
  backup right before the final migration.

## Credits and license

* [pl402/wa-fuse](https://github.com/pl402/wa-fuse) by Elias Portugal — the original merger (MIT).
* [ElDavoo/wa-crypt-tools](https://github.com/ElDavoo/wa-crypt-tools) — `.crypt15` encryption.
* [jsharkey13/iphone_backup_decrypt](https://github.com/jsharkey13/iphone_backup_decrypt) — encrypted iPhone backups.
* [KnugiHK/WhatsApp-Chat-Exporter](https://github.com/KnugiHK/WhatsApp-Chat-Exporter) — reference for the iOS database.
* [WhatsApp/stickers](https://github.com/WhatsApp/stickers) — official sample sticker app, built by the sticker tool.

MIT license, see [LICENSE](LICENSE). WhatsApp is a trademark of WhatsApp LLC.
