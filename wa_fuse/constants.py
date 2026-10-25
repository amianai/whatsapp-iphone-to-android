"""Constants and mappings for WhatsApp iOS and Android backup structures."""

# Seconds between Unix Epoch (1970-01-01) and Apple Cocoa Epoch (2001-01-01)
# 31 years (including 7 leap years: 72, 76, 80, 84, 88, 92, 96, 2000 -> 8 leap days)
# 31 * 365 + 8 = 11323 days * 86400 = 978,307,200 seconds
APPLE_EPOCH_OFFSET = 978307200


def apple_time_to_unix_ms(apple_seconds: float | int | None) -> int:
    """Convert Apple Cocoa Core Data timestamp (seconds since 2001-01-01)

    to Unix timestamp in milliseconds (since 1970-01-01).
    """
    if apple_seconds is None:
        return 0
    unix_seconds = float(apple_seconds) + APPLE_EPOCH_OFFSET
    return int(unix_seconds * 1000)


def unix_ms_to_apple_time(unix_ms: int | None) -> float:
    """Convert Unix timestamp in milliseconds to Apple Cocoa seconds."""
    if unix_ms is None or unix_ms == 0:
        return 0.0
    unix_seconds = unix_ms / 1000.0
    return unix_seconds - APPLE_EPOCH_OFFSET


# iOS ZMESSAGETYPE values (ChatStorage.sqlite, ZWAMESSAGE.ZMESSAGETYPE).
# Cross-checked against WhatsApp-Chat-Exporter and the schema notes of
# rayistern/whatsapp-transfer (both built from real iOS databases).
IOS_TEXT = 0
IOS_IMAGE = 1
IOS_VIDEO = 2
IOS_AUDIO = 3  # voice notes and audio files
IOS_CONTACT = 4  # vCard
IOS_LOCATION = 5
IOS_SYSTEM = 6  # group events (created, added, subject changed, ...)
IOS_URL = 7  # text message with a link preview
IOS_DOCUMENT = 8
IOS_CALL_EVENT = 10
IOS_GIF = 11
IOS_DELETED = 14
IOS_STICKER = 15
# Newer codes, checked on a real 2026 database. View-once media keep their path
# and MIME type (ZVCARDSTRING) but the file is gone once opened: none of them
# was in the backup. Round video messages keep their file.
IOS_VIEW_ONCE_IMAGE = 38  # image/jpeg
IOS_VIEW_ONCE_VIDEO = 39  # video/mp4
IOS_VIEW_ONCE_AUDIO = 53  # audio/ogg; codecs=opus
IOS_VIDEO_NOTE = 54  # round video message, video/mp4

# View-once media become a text placeholder, so the conversation keeps its flow.
# These texts end up inside the restored chats: translate them before running if you like.
IOS_VIEW_ONCE_LABELS = {
    IOS_VIEW_ONCE_IMAGE: "📷 View-once photo",
    IOS_VIEW_ONCE_VIDEO: "🎥 View-once video",
    IOS_VIEW_ONCE_AUDIO: "🎤 View-once voice message",
}

# Android message.message_type values.
ANDROID_TEXT = 0
ANDROID_IMAGE = 1
ANDROID_AUDIO = 2
ANDROID_VIDEO = 3
ANDROID_DOCUMENT = 9
ANDROID_GIF = 13
ANDROID_STICKER = 20

# iOS types carried over as media messages.
IOS_TO_ANDROID_MEDIA_TYPE = {
    IOS_IMAGE: ANDROID_IMAGE,
    IOS_VIDEO: ANDROID_VIDEO,  # video/audio codes are swapped between platforms
    IOS_AUDIO: ANDROID_AUDIO,
    IOS_DOCUMENT: ANDROID_DOCUMENT,
    IOS_GIF: ANDROID_GIF,
    IOS_STICKER: ANDROID_STICKER,
    IOS_VIDEO_NOTE: ANDROID_VIDEO,  # shown as a normal video
}

# Kept for backwards compatibility with callers of the original module.
IOS_TO_ANDROID_MSG_TYPE = {IOS_TEXT: ANDROID_TEXT, IOS_URL: ANDROID_TEXT, **IOS_TO_ANDROID_MEDIA_TYPE}

# iOS types that are never imported: they carry no user content, and Android
# keeps them in tables this tool does not write (message_system, revoked rows).
IOS_SKIPPED_TYPES = {IOS_SYSTEM, IOS_DELETED, IOS_CALL_EVENT}

# Android media subfolder names by Android message type
ANDROID_MEDIA_SUBFOLDERS = {
    ANDROID_IMAGE: "WhatsApp Images",
    ANDROID_AUDIO: "WhatsApp Audio",
    ANDROID_VIDEO: "WhatsApp Video",
    ANDROID_DOCUMENT: "WhatsApp Documents",
    ANDROID_GIF: "WhatsApp Animated Gifs",
    ANDROID_STICKER: "WhatsApp Stickers",
}
VOICE_NOTES_SUBFOLDER = "WhatsApp Voice Notes"

# Fallback MIME types when iOS does not record one.
DEFAULT_MIME_BY_ANDROID_TYPE = {
    ANDROID_IMAGE: "image/jpeg",
    ANDROID_VIDEO: "video/mp4",
    ANDROID_AUDIO: "audio/ogg; codecs=opus",
    ANDROID_GIF: "video/mp4",
    ANDROID_STICKER: "image/webp",
    ANDROID_DOCUMENT: "application/octet-stream",
}
