"""Unit tests for internationalization (i18n) module."""

from wa_fuse.i18n import detect_system_language, get_language, set_language, t


def test_set_and_get_language():
    set_language("es")
    assert get_language() == "es"
    assert "MIGRACIÓN" in t("app_title")

    set_language("en")
    assert get_language() == "en"
    assert "MIGRATION" in t("app_title")


def test_translation_formatting():
    set_language("en")
    msg = t("restore_file_found", name="test.db", size=12.34)
    assert "test.db" in msg
    assert "12.3" in msg

    set_language("es")
    msg_es = t("restore_file_found", name="test.db", size=12.34)
    assert "test.db" in msg_es
    assert "12.3" in msg_es


def test_missing_key_fallback():
    set_language("es")
    assert t("non_existent_key_xyz") == "non_existent_key_xyz"


def test_detect_language(monkeypatch):
    monkeypatch.setenv("WA_LANG", "es_MX.UTF-8")
    assert detect_system_language() == "es"

    monkeypatch.setenv("WA_LANG", "en_US.UTF-8")
    assert detect_system_language() == "en"
