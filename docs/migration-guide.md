# Migration guide

The procedure that was used for a real migration (iPhone on iOS 26 → Pixel on GrapheneOS, macOS 15
computer). It works the same on stock Android. Read it all once before starting.

**Plan:** a full encrypted backup of the iPhone, a **dry run with a second phone number** and a few
chats, then the **final migration** with your main number. Your WhatsApp stays on the iPhone until the
final step, and the iPhone keeps a complete copy of the chats afterwards.

Time: 1–3 hours for the first iPhone backup; about 1.5 hours for the final migration, of which about
one hour without WhatsApp (incoming messages wait on WhatsApp's servers, nothing is lost).

---

## 0. Prepare the computer

```bash
brew install libimobiledevice android-platform-tools uv ffmpeg
git clone <this repository> && cd whatsapp-iphone-to-android
uv sync && uv run pytest -q tests
```

Work in a folder outside the repository, e.g. `~/wa/` with `staging/`, `output-test/`, `output/`.
Space on the internal disk: about the size of WhatsApp on the iPhone (Settings → General → iPhone
Storage). The iPhone backup itself can go on an external drive.

## 1. Encrypted backup of the iPhone

1. Connect the iPhone **directly** to the computer (no hub), unlock it, tap **Trust** and enter the
   passcode. Check with `idevice_id -l`.
2. Encryption: `ideviceinfo -q com.apple.mobile.backup -k WillEncrypt`.
   * If it is on, you need the password chosen in the past in Finder/iTunes.
   * If it is off, choose a strong password, save it in your password manager, then
     `BACKUP_PASSWORD=... idevicebackup2 encryption on` (the iPhone asks for its passcode).
3. On the iPhone: **Settings → Display & Brightness → Auto-Lock → Never**, close WhatsApp, leave the
   phone on the table.
4. Back up: `idevicebackup2 backup --full /Volumes/<drive>/iphone-backup` (a sub-folder named after
   the device UDID is created). The iPhone asks for its passcode to start.
5. Check: `IOS_BACKUP_PASSWORD=... uv run wa-fuse inspect-ios /Volumes/<drive>/iphone-backup/<UDID> --staging-dir ~/wa/staging`
   lists the chats and the total of messages. The first run decrypts WhatsApp's files into `staging`.

> **A backup interrupted for even a second is unusable** (`ERROR: Could not receive from mobilebackup2 (-4)`).
> The per-file encryption keys are written in `Manifest.db` only at the very end, so the files already
> copied cannot be decrypted. Typical causes: the phone picked up, the cable moved, the iPhone locked
> for a long time. Delete the partial folder and start again with Auto-Lock on *Never*.
> Later backups without `--full` are incremental and take minutes.

## 2. Dry run with a second number

1. Android phone: Developer options → **USB debugging**, connect, allow the computer, `adb devices`.
   On GrapheneOS the USB port carries no data while the phone is locked: keep it unlocked
   (Developer options → **Stay awake** helps).
2. Install WhatsApp (or clear it: `adb shell pm clear com.whatsapp`) and register the **second number**.
   Skip "restore from Google Drive" and "transfer from old phone". Do not use "Continue with Instagram".
3. In WhatsApp: Settings → Chats → Chat backup → **End-to-end encrypted backup** → More options →
   **64-digit encryption key** → generate it, save it in your password manager → Create.
   The first local backup is written immediately.
4. Pull it and clear WhatsApp:
   ```bash
   adb pull /sdcard/Android/media/com.whatsapp/WhatsApp/Databases/msgstore.db.crypt15 ~/wa/template-test.crypt15
   adb shell pm clear com.whatsapp
   ```
   Check the key with `uv run wa-fuse decrypt --key "$WA_BACKUP_KEY" --input ~/wa/template-test.crypt15 --output /tmp/t.db`.
5. Pick 5–8 varied chats (a big group, a chat with many photos and voice notes, one with documents,
   a very old one) and run the pipeline **without** `--move-media` (the staging folder is needed again):
   ```bash
   uv run wa-fuse pipeline --ios <backup>/<UDID> --staging-dir ~/wa/staging \
     --android-crypt ~/wa/template-test.crypt15 --key "$WA_BACKUP_KEY" \
     --output-dir ~/wa/output-test --chats "name1,name2,…"
   ```
   `--chats` matches parts of chat names or of the phone number / group id.
6. Push (WhatsApp cleared and **not opened**): `tools/push_media.sh ~/wa/output-test`.
   On Android 13+ "clear data" also deletes `Android/media/com.whatsapp`, so always push *after* clearing.
7. Open WhatsApp, register the second number again, choose **Restore from backup**, enter the 64-digit key.
8. Check the chats: order, photos (open them full screen), videos, voice notes, groups, and that
   **1-on-1 chats open** with their messages.

## 3. Final migration with the main number

Do it right after the dry run, with the same WhatsApp version (on GrapheneOS you can pause automatic
updates of WhatsApp in the store).

1. Update the iPhone backup (incremental, a few minutes) and run `inspect-ios` again.
2. `adb shell pm clear com.whatsapp`, then register the **main number** on Android. The iPhone may ask
   to allow the account move: **Allow** moves the account only, the chats stay on the iPhone.
   From now on WhatsApp on the iPhone and WhatsApp Web are logged out. Skip the chat transfer.
3. Immediately: 64-digit key backup as in step 2.3 → `adb pull` to `~/wa/template.crypt15` →
   `adb shell pm clear com.whatsapp`. Use a **new** key for the main number and save it.
   The template already contains groups and system notices restored from the server: they are kept.
4. Full pipeline, all chats, with `--move-media`, output in `~/wa/output`. Read `output/report.json`.
5. `tools/push_media.sh ~/wa/output` (tens of GB: parallel pushes take about 15 minutes over USB 3).
6. Open WhatsApp, register the main number (the SMS code arrives wherever that SIM is), **Restore**,
   enter the key. A restore of ~30 GB takes a couple of minutes.
7. Verify (next section). Then in WhatsApp choose whether to back up to Google Drive; the free 15 GB
   may not be enough for a large WhatsApp.

## 4. Verify

* Look at your most important chats, a few groups and the archived chats.
* Technical check: make a new local backup in WhatsApp, pull it, decrypt it with `wa-fuse decrypt`
  and compare the number of messages per chat with `report.json`.
* Contact names: Android shows phone numbers until the contacts are on the phone. On the iPhone,
  Contacts → Lists → long-press *All Contacts* → Export, send the `.vcf` to the computer,
  `adb push` it to `/sdcard/Download/` and import it from the Contacts app.
  `uv run wa-fuse export-contacts` adds people you only knew on WhatsApp.

## 5. Clean up (only when everything is fine)

* Delete `~/wa/staging`, `~/wa/output*`, the `.crypt15` templates and any decrypted `.db`.
* Delete the iPhone backup from the external drive. **On macOS, emptying the Trash with an external
  drive connected also empties that drive's own trash** (`.Trashes`): eject other drives first.
* Turn off USB debugging on the phone. Keep the iPhone untouched for a while before resetting it.

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| iPhone backup stops with `Could not receive from mobilebackup2 (-4)` | The connection dropped (cable moved, phone locked for long). The partial backup is unusable: delete it, set Auto-Lock to Never, do not touch the phone, start again. |
| The computer does not see the Android phone | GrapheneOS disables USB data while locked: unlock it. Some USB-C cables are charge-only. |
| 1-on-1 chats show a preview in the list but open empty | WhatsApp keys personal chats by `@lid`. Fixed in this version: re-run the pipeline and restore again. |
| Photos look stretched in WhatsApp's viewer, fine in the gallery | Width/height swapped. Fixed in this version. |
| Some videos appear twice | Standard + HD copies. Fixed in this version (needs `ffmpeg`). |
| `adb push` runs at a few MB/s | Tens of thousands of small files: use `tools/push_media.sh` (parallel, resumable). |
| Many messages skipped as "empty/unsupported" in `report.json` | Mostly call events (iOS types 59/66) and system notices: they carry no content. |
| Thousands of media "missing" | Check the message types: view-once media (38/39/53) have no file once opened and become placeholders. |
| "Restore" does not find the backup | The file must be `Android/media/com.whatsapp/WhatsApp/Databases/msgstore.db.crypt15`, pushed after `pm clear`, from the same number as the template. |
| Verification code not arriving | Wait, do not request again and again: repeated requests block registration for hours. |
| A prompt asks to unblock the microphone during the restore | Not needed: cancel it. |
