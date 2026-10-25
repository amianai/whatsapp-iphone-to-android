"""Regression tests for the iPhone -> Android migration fixes."""

import base64
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from tests.ios_fixtures import (
    ChatStorage,
    create_android_template,
    make_encrypted_backup,
    make_plain_backup,
)
from wa_fuse.android_db import AndroidDB
from wa_fuse.contacts import export_whatsapp_only_contacts
from wa_fuse.ios_extractor import IOSExtractor
from wa_fuse.merger import BackupMerger

ALICE = "391111111111@s.whatsapp.net"
BOB = "392222222222@s.whatsapp.net"
GROUP = "120363000000000001@g.us"
GROUP2 = "120363000000000002@g.us"
T0 = 1_700_000_000  # 2023-11-14


def run_merge(ios_source, android_db_path, media_dir=None, **kwargs):
    extractor_kwargs = {k: kwargs.pop(k) for k in ("backup_password", "staging_dir") if k in kwargs}
    extractor = IOSExtractor(ios_source, **extractor_kwargs)
    db = AndroidDB(android_db_path)
    summary = BackupMerger(extractor, db, android_media_dir=media_dir, **kwargs).run()
    db.close()
    return summary


def rows(db_path, sql, params=()):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def b64sha(data: bytes) -> str:
    return base64.b64encode(hashlib.sha256(data).digest()).decode()


def test_album_and_quick_replies_are_all_kept(tmp_path):
    """The original fuzzy check dropped messages sent within 2 seconds of each other."""
    ios = ChatStorage(tmp_path / "ChatStorage.sqlite")
    alice = ios.chat(ALICE, "Alice")
    for i in range(5):
        ios.message(alice, T0 + i * 0.2, ios_type=1, media={"path": f"Media/{ALICE}/a/b/foto{i}.jpg"})
    for i, text in enumerate(["ok", "arrivo", "5 minuti"]):
        ios.message(alice, T0 + 60 + i * 0.5, text=text, from_me=True)
    ios.close()
    android = create_android_template(tmp_path / "msgstore.db")

    summary = run_merge(tmp_path / "ChatStorage.sqlite", android)

    assert summary.messages_inserted == 8
    assert summary.messages_skipped_duplicate == 0
    texts = [r[0] for r in rows(android, "SELECT text_data FROM message WHERE message_type = 0 ORDER BY sort_id")]
    assert texts == ["ok", "arrivo", "5 minuti"]
    assert rows(android, "SELECT count(*) FROM message WHERE message_type = 1")[0][0] == 5


def test_messages_already_in_the_template_are_skipped(tmp_path):
    ios = ChatStorage(tmp_path / "ChatStorage.sqlite")
    alice = ios.chat(ALICE, "Alice")
    ios.message(alice, T0, text="same id", stanza="KEEP1")
    ios.message(alice, T0 + 100, text="same text, other id", stanza="IOSONLY")
    ios.message(alice, T0 + 200, text="new")
    ios.close()

    android = create_android_template(tmp_path / "msgstore.db")
    db = AndroidDB(android)
    chat = db.get_or_create_chat(db.get_or_create_jid(ALICE))
    db.insert_message(chat, False, T0 * 1000, "same id", key_id="KEEP1")
    db.insert_message(chat, False, (T0 + 100) * 1000 + 500, "same text, other id", key_id="ANDROID1")
    db.commit()
    db.close()

    summary = run_merge(tmp_path / "ChatStorage.sqlite", android)

    assert summary.messages_skipped_duplicate == 2
    assert summary.messages_inserted == 1
    assert rows(android, "SELECT count(*) FROM message")[0][0] == 3


def test_the_same_stanza_in_two_chats_is_kept_in_both(tmp_path):
    """A broadcast message reaches each recipient's chat with the same message id."""
    ios = ChatStorage(tmp_path / "ChatStorage.sqlite")
    alice, bob = ios.chat(ALICE, "Alice"), ios.chat(BOB, "Bob")
    ios.message(alice, T0, text="auguri!", from_me=True, stanza="BCAST1")
    ios.message(bob, T0, text="auguri!", from_me=True, stanza="BCAST1")
    ios.close()
    android = create_android_template(tmp_path / "msgstore.db")

    summary = run_merge(tmp_path / "ChatStorage.sqlite", android)

    assert summary.messages_inserted == 2


def test_finder_backup_media_keep_names_types_dates_and_hashes(tmp_path):
    (tmp_path / "build").mkdir()
    ios = ChatStorage(tmp_path / "build" / "ChatStorage.sqlite")
    alice = ios.chat(ALICE, "Alice")
    photo, video, note, doc = b"jpeg-bytes", b"mp4-bytes", b"opus-bytes", b"%PDF-1.4"
    ios.message(alice, T0, ios_type=1, media={"path": f"Media/{ALICE}/1/2/photo.jpg", "vcard": "image/jpeg",
                                               "title": "al mare", "lat": 1600.0, "lon": 1200.0})
    ios.message(alice, T0 + 1, ios_type=2, from_me=True,
                media={"path": f"Media/{ALICE}/1/2/clip.", "vcard": "video/mp4", "duration": 12})
    ios.message(alice, T0 + 2, ios_type=3, media={"path": f"Media/{ALICE}/1/2/voice.opus", "duration": 7})
    ios.message(alice, T0 + 3, ios_type=8, media={"path": f"Media/{ALICE}/1/2/abcd", "vcard": "application/pdf",
                                                   "title": "Contratto.pdf"})
    ios.message(alice, T0 + 4, ios_type=1, media={"path": f"Media/{ALICE}/1/2/never-downloaded.jpg"})
    ios.close()
    files = {
        "ChatStorage.sqlite": (tmp_path / "build" / "ChatStorage.sqlite").read_bytes(),
        f"Message/Media/{ALICE}/1/2/photo.jpg": photo,
        f"Message/Media/{ALICE}/1/2/clip.": video,
        f"Message/Media/{ALICE}/1/2/voice.opus": note,
        f"Message/Media/{ALICE}/1/2/abcd": doc,
    }
    backup = make_plain_backup(tmp_path / "backup", files)
    android = create_android_template(tmp_path / "msgstore.db")
    media_dir = tmp_path / "out" / "WhatsApp" / "Media"

    summary = run_merge(backup, android, media_dir, staging_dir=tmp_path / "staging")

    got = rows(android, """
        SELECT m.message_type, m.text_data, mm.file_path, mm.mime_type, mm.file_hash, mm.media_name,
               mm.media_duration, mm.width, mm.height, mm.file_size
        FROM message m JOIN message_media mm ON mm.message_row_id = m._id ORDER BY m.timestamp""")
    # iOS keeps the height in ZLATITUDE and the width in ZLONGITUDE.
    assert got[0] == (1, "al mare", "Media/WhatsApp Images/photo.jpg", "image/jpeg", b64sha(photo), None, 0,
                      1200, 1600, len(photo))
    assert got[1][:4] == (3, None, "Media/WhatsApp Video/Sent/clip.mp4", "video/mp4")
    assert got[1][6] == 12
    assert got[2][:3] == (2, None, "Media/WhatsApp Voice Notes/voice.opus")
    assert got[3][:6] == (9, None, "Media/WhatsApp Documents/abcd.pdf", "application/pdf", b64sha(doc), "Contratto.pdf")
    assert got[4][2] is None  # media the iPhone never downloaded stays a placeholder
    assert summary.media_migrated == 4 and summary.media_missing == 1

    out = media_dir.parent
    assert (out / "Media/WhatsApp Images/photo.jpg").read_bytes() == photo
    assert (out / "Media/WhatsApp Video/Sent/.nomedia").exists()
    assert int(os.path.getmtime(out / "Media/WhatsApp Images/photo.jpg")) == T0
    # Files are copied out of an unencrypted backup, never moved.
    assert all((tmp_path / "backup").joinpath(fid[:2], fid).exists()
               for fid in (r[0] for r in rows(tmp_path / "backup" / "Manifest.db",
                                               "SELECT fileID FROM Files WHERE flags = 1")))


def test_view_once_media_become_placeholders_and_video_notes_are_kept(tmp_path):
    (tmp_path / "build").mkdir()
    ios = ChatStorage(tmp_path / "build" / "ChatStorage.sqlite")
    alice = ios.chat(ALICE, "Alice")
    round_video = b"mp4-54"
    # View-once media: the iPhone keeps the path but the opened file is gone.
    ios.message(alice, T0, ios_type=38, media={"path": f"Media/{ALICE}/a/b/p.jpg", "vcard": "image/jpeg",
                                                "title": "guarda qui"})
    ios.message(alice, T0 + 1, ios_type=39, from_me=True,
                media={"path": f"Media/{ALICE}/a/b/v.mp4", "vcard": "video/mp4", "duration": 9})
    ios.message(alice, T0 + 2, ios_type=53, media={"path": f"Media/{ALICE}/a/b/n.opus",
                                                    "vcard": "audio/ogg; codecs=opus", "duration": 4})
    ios.message(alice, T0 + 3, ios_type=54, media={"path": f"Media/{ALICE}/a/b/r.mp4", "vcard": "video/mp4",
                                                    "duration": 15})
    ios.close()
    files = {
        "ChatStorage.sqlite": (tmp_path / "build" / "ChatStorage.sqlite").read_bytes(),
        f"Message/Media/{ALICE}/a/b/r.mp4": round_video,
    }
    backup = make_plain_backup(tmp_path / "backup", files)
    android = create_android_template(tmp_path / "msgstore.db")
    media_dir = tmp_path / "out" / "WhatsApp" / "Media"

    summary = run_merge(backup, android, media_dir, staging_dir=tmp_path / "staging")

    got = rows(android, """
        SELECT m.message_type, m.from_me, m.text_data, mm.file_path, mm.media_duration
        FROM message m LEFT JOIN message_media mm ON mm.message_row_id = m._id ORDER BY m.timestamp""")
    assert got == [
        (0, 0, "📷 View-once photo\nguarda qui", None, None),
        (0, 1, "🎥 View-once video", None, None),
        (0, 0, "🎤 View-once voice message", None, None),
        (3, 0, None, "Media/WhatsApp Video/r.mp4", 15),
    ]
    assert summary.media_migrated == 1 and summary.media_missing == 0
    assert summary.messages_skipped_empty_unsupported == 0


def _jpeg(tmp_path, name, source, size):
    out = tmp_path / name
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"{source}=size={size}", "-frames:v", "1",
                    str(out)], check=True)
    return out.read_bytes()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_standard_copy_of_an_hd_photo_is_left_out(tmp_path):
    (tmp_path / "build").mkdir()
    hd = _jpeg(tmp_path, "hd.jpg", "testsrc2", "3200x2400")
    sd = tmp_path / "sd.jpg"
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(tmp_path / "hd.jpg"), "-vf", "scale=1600:1200", str(sd)],
                   check=True)
    other = _jpeg(tmp_path, "other.jpg", "smptebars", "400x300")
    same_size = _jpeg(tmp_path, "same.jpg", "mandelbrot", "800x600")
    ios = ChatStorage(tmp_path / "build" / "ChatStorage.sqlite")
    alice = ios.chat(ALICE, "Alice")
    # lat = height, lon = width
    ios.message(alice, T0, ios_type=1, media={"path": f"Media/{ALICE}/sd.jpg", "lat": 1200.0, "lon": 1600.0})
    ios.message(alice, T0 + 1, ios_type=1, media={"path": f"Media/{ALICE}/hd.jpg", "lat": 2400.0, "lon": 3200.0})
    ios.message(alice, T0 + 60, ios_type=1, media={"path": f"Media/{ALICE}/other.jpg", "lat": 300.0, "lon": 400.0})
    ios.message(alice, T0 + 61, ios_type=1, media={"path": f"Media/{ALICE}/same.jpg", "lat": 600.0, "lon": 800.0})
    ios.close()
    files = {
        "ChatStorage.sqlite": (tmp_path / "build" / "ChatStorage.sqlite").read_bytes(),
        f"Message/Media/{ALICE}/sd.jpg": sd.read_bytes(),
        f"Message/Media/{ALICE}/hd.jpg": hd,
        f"Message/Media/{ALICE}/other.jpg": other,
        f"Message/Media/{ALICE}/same.jpg": same_size,
    }
    backup = make_plain_backup(tmp_path / "backup", files)
    android = create_android_template(tmp_path / "msgstore.db")

    summary = run_merge(backup, android, tmp_path / "out" / "WhatsApp" / "Media", staging_dir=tmp_path / "staging")

    got = rows(android, "SELECT mm.file_path FROM message m JOIN message_media mm ON mm.message_row_id = m._id "
                        "ORDER BY m.timestamp")
    # Only the standard copy goes; different photos stay even when sizes and timing look alike.
    assert [r[0] for r in got] == ["Media/WhatsApp Images/hd.jpg", "Media/WhatsApp Images/other.jpg",
                                   "Media/WhatsApp Images/same.jpg"]
    assert summary.messages_skipped_duplicate == 1


def _mp4(tmp_path, name, source, size, seconds=2):
    out = tmp_path / name
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"{source}=size={size}:duration={seconds}",
                    "-pix_fmt", "yuv420p", str(out)], check=True)
    return out.read_bytes()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_hd_videos_sent_together_keep_only_the_hd_copies(tmp_path):
    (tmp_path / "build").mkdir()
    media = {
        "hd1.mp4": _mp4(tmp_path, "hd1.mp4", "testsrc2", "640x480"),
        "hd2.mp4": _mp4(tmp_path, "hd2.mp4", "smptebars", "640x480"),
        "other.mp4": _mp4(tmp_path, "other.mp4", "rgbtestsrc", "320x240"),
    }
    for n in (1, 2):  # the standard copy is the HD video scaled down
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(tmp_path / f"hd{n}.mp4"), "-vf", "scale=320:240",
                        "-pix_fmt", "yuv420p", str(tmp_path / f"sd{n}.mp4")], check=True)
        media[f"sd{n}.mp4"] = (tmp_path / f"sd{n}.mp4").read_bytes()
    ios = ChatStorage(tmp_path / "build" / "ChatStorage.sqlite")
    alice = ios.chat(ALICE, "Alice")
    # Standard copies first, the HD ones up to a minute later; then a different video.
    for ts, name, h, w in ((0, "sd1", 240, 320), (1, "sd2", 240, 320), (40, "hd1", 480, 640),
                           (55, "hd2", 480, 640), (70, "other", 240, 320)):
        ios.message(alice, T0 + ts, ios_type=2, from_me=True,
                    media={"path": f"Media/{ALICE}/{name}.mp4", "vcard": "video/mp4", "duration": 2,
                           "lat": float(h), "lon": float(w)})
    ios.close()
    files = {"ChatStorage.sqlite": (tmp_path / "build" / "ChatStorage.sqlite").read_bytes()}
    files.update({f"Message/Media/{ALICE}/{name}": data for name, data in media.items()})
    backup = make_plain_backup(tmp_path / "backup", files)
    android = create_android_template(tmp_path / "msgstore.db")

    summary = run_merge(backup, android, tmp_path / "out" / "WhatsApp" / "Media", staging_dir=tmp_path / "staging")

    got = rows(android, "SELECT mm.file_path FROM message m JOIN message_media mm ON mm.message_row_id = m._id "
                        "ORDER BY m.timestamp")
    assert [r[0] for r in got] == ["Media/WhatsApp Video/Sent/hd1.mp4", "Media/WhatsApp Video/Sent/hd2.mp4",
                                   "Media/WhatsApp Video/Sent/other.mp4"]
    assert summary.messages_skipped_duplicate == 2


def test_messages_still_in_the_wal_file_are_read(tmp_path):
    build = tmp_path / "build"
    build.mkdir()
    ios = ChatStorage(build / "ChatStorage.sqlite", wal=True)
    alice = ios.chat(ALICE, "Alice")
    ios.message(alice, T0, text="old")
    ios.commit()
    ios.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    ios.message(alice, T0 + 10, text="only in the wal")
    ios.commit()
    # Copy while WhatsApp (the open connection) still holds the WAL, like a live backup.
    files = {
        "ChatStorage.sqlite": (build / "ChatStorage.sqlite").read_bytes(),
        "ChatStorage.sqlite-wal": (build / "ChatStorage.sqlite-wal").read_bytes(),
    }
    ios.close()
    backup = make_plain_backup(tmp_path / "backup", files)
    android = create_android_template(tmp_path / "msgstore.db")

    run_merge(backup, android, staging_dir=tmp_path / "staging")

    texts = [r[0] for r in rows(android, "SELECT text_data FROM message ORDER BY sort_id")]
    assert texts == ["old", "only in the wal"]


def test_encrypted_backup_is_decrypted_and_merged(tmp_path):
    build = tmp_path / "build"
    build.mkdir()
    ios = ChatStorage(build / "ChatStorage.sqlite")
    alice = ios.chat(ALICE, "Alice")
    ios.message(alice, T0, text="ciao")
    ios.message(alice, T0 + 1, ios_type=1, media={"path": f"Media/{ALICE}/9/9/pic.jpg", "vcard": "image/jpeg"})
    ios.close()
    files = {
        "ChatStorage.sqlite": (build / "ChatStorage.sqlite").read_bytes(),
        f"Message/Media/{ALICE}/9/9/pic.jpg": b"secret-photo",
        "Library/Preferences/unrelated.plist": b"not needed",
    }
    backup = make_encrypted_backup(tmp_path / "backup", files, password="segreta")
    android = create_android_template(tmp_path / "msgstore.db")
    staging = tmp_path / "staging"
    media_dir = tmp_path / "out" / "Media"

    summary = run_merge(backup, android, media_dir, backup_password="segreta", staging_dir=staging,
                        move_media=True)

    assert summary.messages_inserted == 2 and summary.media_migrated == 1
    assert (media_dir / "WhatsApp Images" / "pic.jpg").read_bytes() == b"secret-photo"
    assert not (staging / "Library").exists()  # only WhatsApp files are decrypted
    assert not (staging / f"Message/Media/{ALICE}/9/9/pic.jpg").exists()  # moved, not copied


def test_encrypted_backup_needs_the_right_password(tmp_path):
    build = tmp_path / "build"
    build.mkdir()
    ChatStorage(build / "ChatStorage.sqlite").close()
    backup = make_encrypted_backup(
        tmp_path / "backup", {"ChatStorage.sqlite": (build / "ChatStorage.sqlite").read_bytes()}, "giusta"
    )
    with pytest.raises(ValueError):
        IOSExtractor(backup, staging_dir=tmp_path / "s")
    with pytest.raises(Exception):
        IOSExtractor(backup, staging_dir=tmp_path / "s", backup_password="sbagliata")


def test_message_types(tmp_path):
    ios = ChatStorage(tmp_path / "ChatStorage.sqlite")
    alice = ios.chat(ALICE, "Alice")
    vcard = "BEGIN:VCARD\nVERSION:3.0\nFN:Jane Example\nitem1.TEL;type=CELL:+1 202 555 0143\nEND:VCARD"
    ios.message(alice, T0, ios_type=4, media={"vcard": vcard, "vcard_name": "Jane Example"})
    ios.message(alice, T0 + 1, ios_type=5, media={"title": "Colosseo", "lat": 41.890251, "lon": 12.492373})
    ios.message(alice, T0 + 2, ios_type=6, text="12345")  # group/system event
    ios.message(alice, T0 + 3, ios_type=14)  # deleted
    ios.message(alice, T0 + 4, ios_type=7, text="https://example.com")
    ios.message(alice, T0 + 5, ios_type=11, media={"path": f"Media/{ALICE}/g.mp4"})
    ios.message(alice, T0 + 6, ios_type=15, media={"path": f"Media/{ALICE}/s.webp"})
    ios.message(alice, T0 + 7, ios_type=46, text="Pizza o sushi?")  # poll: keep the text
    ios.message(alice, T0 + 8, ios_type=46)  # nothing to keep
    ios.message(alice, T0 + 9, text=None)  # empty text
    ios.close()
    android = create_android_template(tmp_path / "msgstore.db")

    summary = run_merge(tmp_path / "ChatStorage.sqlite", android)

    got = rows(android, "SELECT message_type, text_data FROM message ORDER BY sort_id")
    assert got[0] == (0, "👤 Jane Example\n+1 202 555 0143")
    assert got[1] == (0, "📍 Colosseo\nhttps://maps.google.com/?q=41.890251,12.492373")
    assert got[2] == (0, "https://example.com")
    assert got[3][0] == 13 and got[4][0] == 20
    assert got[5] == (0, "Pizza o sushi?")
    assert len(got) == 6
    assert summary.messages_skipped_system_or_deleted == 2
    assert summary.messages_skipped_empty_unsupported == 2


def test_sort_ids_follow_time_even_after_template_messages(tmp_path):
    """Messages delivered right after registering must not sort before years of history."""
    ios = ChatStorage(tmp_path / "ChatStorage.sqlite")
    alice = ios.chat(ALICE, "Alice")
    ios.message(alice, T0, text="2023")
    ios.message(alice, T0 + 86400, text="2023 + 1 day")
    ios.close()
    android = create_android_template(tmp_path / "msgstore.db")
    db = AndroidDB(android)
    chat = db.get_or_create_chat(db.get_or_create_jid(ALICE))
    newest = db.insert_message(chat, False, (T0 + 400 * 86400) * 1000, "delivered at registration", key_id="NEW")
    db.commit()
    db.close()

    run_merge(tmp_path / "ChatStorage.sqlite", android)

    texts = [r[0] for r in rows(android, "SELECT text_data FROM message ORDER BY sort_id")]
    assert texts == ["2023", "2023 + 1 day", "delivered at registration"]
    last_row, last_sort = rows(android, "SELECT last_message_row_id, last_message_sort_id FROM chat")[0]
    assert last_row == newest
    assert last_sort == rows(android, "SELECT sort_id FROM message WHERE _id = ?", (newest,))[0][0]


def test_status_broadcast_and_channels_are_left_out(tmp_path):
    ios = ChatStorage(tmp_path / "ChatStorage.sqlite")
    for jid, stype in (("status@broadcast", 3), ("1234@broadcast", 2), ("999@newsletter", 0)):
        ios.message(ios.chat(jid, session_type=stype), T0, text="x")
    ios.message(ios.chat(ALICE, "Alice"), T0, text="kept")
    ios.close()
    android = create_android_template(tmp_path / "msgstore.db")

    summary = run_merge(tmp_path / "ChatStorage.sqlite", android)

    assert summary.messages_inserted == 1
    assert [r[0] for r in rows(android, "SELECT raw_string FROM jid")] == [ALICE]


def test_one_to_one_chats_are_keyed_by_lid_like_whatsapp_does(tmp_path):
    alice_lid, bob_lid, carol_lid = "11111111111111@lid", "22222222222222@lid", "33333333333333@lid"
    ios = ChatStorage(tmp_path / "ChatStorage.sqlite")
    # iOS keys a chat by the phone JID with the @lid as identifier, or the other way round.
    ios.message(ios.chat(ALICE, "Alice", identifier=alice_lid), T0, text="ciao")
    ios.message(ios.chat(bob_lid, "Bob", identifier=BOB), T0 + 1, text="hey")
    group = ios.chat(GROUP, "Gita", session_type=1)
    ios.message(group, T0 + 2, text="nel gruppo", member=ios.member(group, carol_lid))
    ios.chat("390000000003@s.whatsapp.net", "Carol", identifier=carol_lid)  # no messages, only the pair
    ios.close()
    android = create_android_template(tmp_path / "msgstore.db")

    run_merge(tmp_path / "ChatStorage.sqlite", android)

    chats = rows(android, """
        SELECT j.raw_string, c.account_jid_row_id = c.jid_row_id, count(m._id)
        FROM chat c JOIN jid j ON j._id = c.jid_row_id LEFT JOIN message m ON m.chat_row_id = c._id
        GROUP BY c._id ORDER BY c._id""")
    assert chats == [(alice_lid, 1, 1), (bob_lid, 1, 1), (GROUP, 1, 1)]
    links = rows(android, """
        SELECT l.raw_string, p.raw_string FROM jid_map m
        JOIN jid l ON l._id = m.lid_row_id JOIN jid p ON p._id = m.jid_row_id ORDER BY m.sort_id""")
    assert sorted(links) == [(alice_lid, ALICE), (bob_lid, BOB), (carol_lid, "390000000003@s.whatsapp.net")]
    assert [r[0] for r in rows(android, "SELECT sort_id FROM jid_map ORDER BY sort_id")] == [1, 2, 3]
    assert rows(android, """
        SELECT j.raw_string, s.is_pn_shared FROM lid_chat_state s JOIN jid j ON j._id = s.jid_row_id
        ORDER BY j.raw_string""") == [(alice_lid, 1), (bob_lid, 1)]
    assert rows(android, "SELECT type FROM jid WHERE raw_string LIKE '%@lid'") == [(18,), (18,), (18,)]


def test_archived_chats_stay_archived(tmp_path):
    ios = ChatStorage(tmp_path / "ChatStorage.sqlite")
    ios.message(ios.chat(ALICE, "Alice"), T0, text="in vista")
    ios.message(ios.chat(GROUP, "Vecchio gruppo", session_type=1, archived=True), T0 + 1, text="archiviata")
    ios.message(ios.chat(GROUP2, "Gruppo dal server", session_type=1, archived=True), T0 + 2, text="anche questa")
    ios.close()
    android = create_android_template(tmp_path / "msgstore.db")
    # WhatsApp already restored this group from the server, not archived.
    db = AndroidDB(android)
    db.get_or_create_chat(db.get_or_create_jid(GROUP2), subject="Gruppo dal server", is_group=True)
    db.commit()
    db.close()

    run_merge(tmp_path / "ChatStorage.sqlite", android)

    assert rows(android, "SELECT j.raw_string, c.archived FROM chat c JOIN jid j ON j._id = c.jid_row_id "
                         "ORDER BY c._id") == [(GROUP2, 1), (ALICE, 0), (GROUP, 1)]


def test_chat_filter_and_report(tmp_path):
    ios = ChatStorage(tmp_path / "ChatStorage.sqlite")
    alice, bob = ios.chat(ALICE, "Alice"), ios.chat(BOB, "Bob")
    group = ios.chat(GROUP, "Calcetto", session_type=1)
    member = ios.member(group, "390000000003@s.whatsapp.net")
    ios.message(alice, T0, text="a")
    ios.message(bob, T0, text="b")
    ios.message(group, T0, text="g", member=member)
    ios.message(group, T0 + 1, ios_type=1, member=member, media={"path": "Media/x/missing.jpg"})
    ios.close()
    android = create_android_template(tmp_path / "msgstore.db")

    summary = run_merge(tmp_path / "ChatStorage.sqlite", android, chat_filter=["alice", "calcetto"])

    assert summary.messages_inserted == 3
    report = json.loads(summary.write_report(tmp_path / "report.json").read_text())
    by_name = {c["name"]: c for c in report["chats"]}
    assert set(by_name) == {"Alice", "Calcetto"}
    assert by_name["Calcetto"]["ios_messages"] == 2
    assert by_name["Calcetto"]["media_missing"] == 1
    sender = rows(android, """SELECT j.raw_string FROM message m JOIN jid j ON j._id = m.sender_jid_row_id
                              WHERE m.text_data = 'g'""")
    assert sender == [("390000000003@s.whatsapp.net",)]


def test_export_whatsapp_only_contacts(tmp_path):
    ios = ChatStorage(tmp_path / "ChatStorage.sqlite")
    ios.chat(ALICE, "Alice Rubrica")
    ios.chat(BOB, "+39 222 222222")
    group = ios.chat(GROUP, "Calcetto", session_type=1)
    ios.member(group, "390000000003@s.whatsapp.net")
    ios.push_name(BOB, "Bob")
    ios.push_name("390000000003@s.whatsapp.net", "Carla ☀️")
    ios.close()
    contacts = sqlite3.connect(tmp_path / "ContactsV2.sqlite")
    contacts.execute("CREATE TABLE ZWAADDRESSBOOKCONTACT (Z_PK INTEGER PRIMARY KEY, ZWHATSAPPID TEXT, ZFULLNAME TEXT)")
    contacts.execute("INSERT INTO ZWAADDRESSBOOKCONTACT VALUES (1, '391111111111', 'Alice Rubrica')")
    contacts.commit()
    contacts.close()

    path, count = export_whatsapp_only_contacts(IOSExtractor(tmp_path), tmp_path / "solo_whatsapp.vcf")

    vcf = path.read_bytes().decode("utf-8")
    assert count == 2
    assert "FN:Bob\r\n" in vcf and "TEL;TYPE=CELL:+392222222222" in vcf
    assert "FN:Carla ☀️" in vcf
    assert "Alice" not in vcf


def test_a_newer_encrypted_backup_refreshes_the_staged_database(tmp_path):
    """Phase 3 re-extracts after a newer iPhone backup: new messages must be seen."""
    build = tmp_path / "build"
    build.mkdir()
    ios = ChatStorage(build / "ChatStorage.sqlite")
    alice = ios.chat(ALICE, "Alice")
    ios.message(alice, T0, text="first backup")
    ios.commit()
    backup = make_encrypted_backup(
        tmp_path / "backup", {"ChatStorage.sqlite": (build / "ChatStorage.sqlite").read_bytes()}, "pw"
    )
    staging = tmp_path / "staging"
    first = IOSExtractor(backup, staging_dir=staging, backup_password="pw")
    assert [m.text for m in first.iter_messages()] == ["first backup"]

    ios.message(alice, T0 + 3600, text="arrived later")
    ios.close()
    shutil.rmtree(backup)
    make_encrypted_backup(backup, {"ChatStorage.sqlite": (build / "ChatStorage.sqlite").read_bytes()}, "pw")

    second = IOSExtractor(backup, staging_dir=staging, backup_password="pw")
    assert [m.text for m in second.iter_messages()] == ["first backup", "arrived later"]
