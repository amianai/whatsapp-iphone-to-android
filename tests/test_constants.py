from wa_fuse.constants import (
    apple_time_to_unix_ms,
    unix_ms_to_apple_time,
    APPLE_EPOCH_OFFSET,
)


def test_apple_time_conversion():
    # 0 seconds Apple time = 2001-01-01 00:00:00 UTC = 978307200 seconds Unix time
    unix_ms = apple_time_to_unix_ms(0)
    assert unix_ms == APPLE_EPOCH_OFFSET * 1000

    # Test reverse conversion
    apple_back = unix_ms_to_apple_time(unix_ms)
    assert apple_back == 0.0

    # 100 seconds after Apple epoch
    unix_ms_100 = apple_time_to_unix_ms(100.5)
    assert unix_ms_100 == int((APPLE_EPOCH_OFFSET + 100.5) * 1000)
