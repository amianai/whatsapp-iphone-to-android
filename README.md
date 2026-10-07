# 📱 WhatsApp Backup Merger (iOS ➔ Android)

<p align="center">
  <a href="README.md"><b>🇺🇸 English</b></a> • <a href="README.es.md"><b>🇪🇸 Español</b></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12+-blue.svg?style=flat-square&logo=python" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/WhatsApp-Crypt14%20%2F%20Crypt15-25D366.svg?style=flat-square&logo=whatsapp" alt="Crypt14 / Crypt15">
  <img src="https://img.shields.io/badge/License-MIT-green.svg?style=flat-square&logo=open-source-initiative" alt="License MIT">
  <img src="https://img.shields.io/badge/Tests-Passing-brightgreen.svg?style=flat-square" alt="Tests Passing">
</p>

An open-source, standalone toolkit designed to **merge WhatsApp chat histories from an iPhone (iOS) into an existing Android backup**, unifying multi-year conversation histories into a single, clean database ready to be restored on Android — **without overwriting existing chats and bypassing the notorious 69% restoration crash.**

---

## 💡 Why Does This Project Exist?

1. **Official WhatsApp Transfer Overwrites Data:** The official "Move to Android" tool only works on a freshly formatted or unconfigured phone. If you have been using Android for weeks or months and want to bring over your 10-year iPhone history, the official tool wipes your current Android chats.
2. **Paid Tools Are Expensive and Risky:** Commercial proprietary tools charge $30–$50/year, require root or third-party desktop drivers, and handle your private decrypted conversations on closed servers.
3. **The "69% Restore Bug":** Most legacy community scripts fail on modern WhatsApp versions. During restoration on Android, progress freezes or crashes at **69%**, permanently failing the restoration.

---

## 🛠️ The "69% Restore Bug" Solved

At approximately ~69% progress, WhatsApp for Android concludes sequential message insertion and executes three internal maintenance tasks:
1. Contact & JID validation to construct the thread list (`JidFactory`).
2. Media metadata reindexing (`message_media`).
3. Thread collision and multi-account migration (`local_chat_db_lid_migration`).

This tool eliminates all root causes of the 69% crash:

| Failure Cause | What Happened | How We Fix It |
| :--- | :--- | :--- |
| **Invalid `@status` JIDs** | iOS saves contact stories in `ZWACHATSESSION` (`ZSESSIONTYPE = 3`). Android crashes with `InvalidJidException: Invalid server status`. | Filters out status sessions and enforces valid Android JID servers (`s.whatsapp.net`, `g.us`, `status@broadcast`). |
| **LID vs. Phone Thread Collisions** | Modern iOS indexes 1-on-1 chats using opaque `@lid` identifiers instead of phone numbers. Android creates duplicate threads for existing contacts and crashes. | Automatically resolves `@lid` sessions to canonical phone numbers (`ZCONTACTIDENTIFIER`) and unifies them into existing Android chats. |
| **Missing `message_media` Rows** | If an iPhone photo/video file was missing, old scripts skipped inserting a row in `message_media`. Android throws `NullPointerException` during media indexing. | Enforces 100% coverage in `message_media` for every media message with proper transfer flags and dummy hashes. |
| **Relative Path Prefixes** | Android expects media paths relative to its root folder (e.g., `Media/WhatsApp Images/...`). | Sanitizes and prepends `Media/` to all media file paths. |
| **Multi-Account & Control Flags** | Modern WhatsApp Android requires `account_jid_row_id = jid_row_id` and non-null values for `broadcast`, `origin`, and `sort_id`. | Generates fully populated schema values compliant with Android's `available_message_view` and `chat_view`. |

---

## ✨ Features

* **🔄 Bidirectional History Merge:** Merges individual and group chats from iPhone (`ChatStorage.sqlite`) into Android (`msgstore.db`).
* **⏱️ Epoch Translation:** Automatically converts Apple Core Data Cocoa timestamps (seconds since 2001) into Unix timestamps in milliseconds (since 1970).
* **🧹 Intelligent Deduplication:** Matches messages by `stanza_id` (`key_id`), sender, timestamp, and content to avoid duplicate messages.
* **🔐 Crypt14 & Crypt15 Encryption:** Natively decrypts and re-encrypts Android backups using modern 64-hex root keys, cloning official Protobuf varint headers.
* **📥 Zero-Loss Incremental Merge:** Allows you to extract and incorporate messages received on your phone *today* before restoring, preventing any message loss.
* **📸 Media Migration:** Copies photos, videos, voice notes, audio, GIFs, and documents into the official Android directory structure (`Android/media/com.whatsapp/WhatsApp/Media/`).
* **🧙 Interactive TUI Wizard:** Step-by-step terminal UI (`wizard.py`) with automatic USB/MTP/ADB device detection and integrity diagnostics.

---

## 📋 Prerequisites

You will need:

1. **iPhone Backup:**
   * An unencrypted local iTunes/Finder backup folder (containing `Manifest.db`), **OR**
   * Extracted `ChatStorage.sqlite` (and optionally the `Media/` folder).
2. **Android Backup:**
   * Your `msgstore.db.crypt14` or `msgstore.db.crypt15` file (from `Android/media/com.whatsapp/WhatsApp/Databases/`).
3. **64-Digit Hex Encryption Key:**
   * Generated when enabling "End-to-End Encrypted Backup" in WhatsApp (**Settings > Chats > Chat backup > End-to-end encrypted backup**).
4. **Python 3.12+** (with [uv](https://github.com/astral-sh/uv) recommended).

---

## 🚀 Quick Start

### 1. Installation

Clone this repository and install dependencies using `uv` (or standard `pip`):

```bash
git clone https://github.com/yourusername/wa-backup.git
cd wa-backup

# Using uv (fastest)
uv sync

# Or using standard pip
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Run the Interactive Wizard (Recommended)

Launch the interactive terminal assistant:

```bash
./wizard.py
# or: uv run wa-wizard

# Explicitly choose language (English / Spanish):
./wizard.py --lang en
./wizard.py --lang es
```

> **Tip:** You can also press `L` in the wizard's main menu at any time to instantly toggle between English and Spanish.

The wizard guides you through:
1. Detecting or selecting your iPhone backup and Android `.crypt15`.
2. Decrypting, sanitizing, merging, and re-encrypting the combined database.
3. Automatically detecting your connected Android phone via USB (MTP or ADB).
4. Transferring the database and media files to the phone.
5. Verifying database integrity and copying your 64-digit key to the clipboard.

---

## 💻 CLI Usage (Headless / Advanced)

If you prefer command-line automation:

### Full Pipeline in One Command
```bash
uv run wa-backup pipeline \
  --ios /path/to/ChatStorage.sqlite \
  --android-crypt /path/to/msgstore.db.crypt15 \
  --key "YOUR_64_CHARACTER_HEX_KEY" \
  --output-dir ./output
```

### Step-by-Step Commands

1. **Decrypt Android Backup:**
   ```bash
   uv run wa-backup decrypt \
     --key "YOUR_64_CHARACTER_HEX_KEY" \
     --input msgstore.db.crypt15 \
     --output msgstore_decrypted.db
   ```

2. **Merge iPhone Database into Android SQLite:**
   ```bash
   uv run wa-backup merge \
     --ios /path/to/ChatStorage.sqlite \
     --android-db msgstore_decrypted.db \
     --android-media ./output/WhatsApp/Media
   ```

3. **Re-Encrypt Merged Database to crypt15:**
   ```bash
   uv run wa-backup encrypt \
     --key "YOUR_64_CHARACTER_HEX_KEY" \
     --input msgstore_decrypted.db \
     --output ./output/msgstore.db.crypt15 \
     --reference msgstore.db.crypt15
   ```

---

## 📲 How to Restore on Your Android Phone

Follow these steps carefully to ensure Android 14/15 and WhatsApp read the local backup properly:

1. **Clear WhatsApp Storage on the Phone:**
   * Go to: **Settings > Apps > WhatsApp > Storage and cache > Clear storage**.
   * *(⚠️ Note: In Android 13+, clearing app storage deletes the `com.whatsapp` directory. Therefore, always copy your backup file AFTER clearing storage).*

2. **Grant Permissions in Advance:**
   * Go to: **Settings > Apps > WhatsApp > Permissions**.
   * Manually enable: **Photos and videos**, **Contacts**, and **Notifications**.
   *(This ensures WhatsApp has immediate storage read permissions upon first launch).*

3. **Transfer the Restored File:**
   * Copy the resulting `msgstore.db.crypt15` file into:
     ```
     Internal Storage/Android/media/com.whatsapp/WhatsApp/Databases/msgstore.db.crypt15
     ```
   * *(Optional: Copy the `WhatsApp/Media/` folder to `Internal Storage/Android/media/com.whatsapp/WhatsApp/Media/`)*.

4. **Open WhatsApp & Restore:**
   * Open WhatsApp, select language, accept terms, and verify your phone number via SMS.
   * **⚠️ Crucial:** If WhatsApp asks to look for backups on Google Drive, tap **SKIP**.
   * WhatsApp will immediately scan internal storage and display:
     **"Local backup found"** (Date: Today, Size: ~100–300 MB).
   * Tap **Restore** and enter your **64-digit hex key**.
   * The progress bar will advance smoothly past 69% and reach **100%**.

---

## 🧪 Testing

The test suite validates schema compatibility, JID sanitization, encryption roundtrips, and duplicate avoidance:

```bash
uv run pytest tests/
```

---

## 📄 License

Distributed under the [MIT License](LICENSE). Free for personal and commercial use.

---

## 🤝 Contributing

Contributions, issues, and feature requests are welcome! Feel free to check the [issues page](https://github.com/yourusername/wa-backup/issues).
