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


# iOS ZMESSAGETYPE to Android message_type
# iOS:
# 0: Text
# 1: Image
# 2: Video
# 3: Audio / Voice note
# 4: Location
# 5: Contact (vCard)
# 8: Document
# 15: Sticker
# Android:
# 0: Text
# 1: Image
# 2: Audio
# 3: Video
# 4: Contact
# 5: Location
# 9: Document
# 20: Sticker
IOS_TO_ANDROID_MSG_TYPE = {
    0: 0,   # Text -> Text
    1: 1,   # Image -> Image
    2: 3,   # Video -> Video
    3: 2,   # Audio -> Audio
    4: 5,   # Location -> Location
    5: 4,   # Contact -> Contact
    8: 9,   # Document -> Document
    15: 20, # Sticker -> Sticker
}

# Android media subfolder names by message type
ANDROID_MEDIA_SUBFOLDERS = {
    1: "WhatsApp Images",
    2: "WhatsApp Audio",
    3: "WhatsApp Video",
    4: "WhatsApp Documents",
    5: "WhatsApp Documents",
    9: "WhatsApp Documents",
    20: "WhatsApp Animated Gifs",
}
