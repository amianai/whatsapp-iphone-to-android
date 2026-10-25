"""Export of the people you chatted with on WhatsApp who are not in the iPhone address book.

An Android restore shows them as bare phone numbers. Importing this .vcf into
the phone's contacts brings their names back.
"""

from pathlib import Path

from wa_fuse.ios_extractor import IOSExtractor


def _vcard_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", " ")


def export_whatsapp_only_contacts(extractor: IOSExtractor, output: Path) -> tuple[Path, int]:
    """Writes a vCard 3.0 file and returns (path, number of contacts)."""
    push_names = extractor.get_push_names()
    in_address_book = extractor.get_address_book_jids()

    names: dict[str, str | None] = {}
    for chat in extractor.get_chats():
        if chat.jid.endswith("@s.whatsapp.net"):
            names[chat.jid] = chat.name
    for jid in extractor.get_group_member_jids():
        names.setdefault(jid, None)

    cards = []
    for jid in sorted(names):
        if jid in in_address_book:
            continue
        number = jid.split("@", 1)[0]
        if not number.isdigit():
            continue
        name = push_names.get(jid) or names[jid] or f"+{number}"
        cards.append(
            "BEGIN:VCARD\r\n"
            "VERSION:3.0\r\n"
            f"FN:{_vcard_escape(name)}\r\n"
            f"N:{_vcard_escape(name)};;;;\r\n"
            f"TEL;TYPE=CELL:+{number}\r\n"
            "NOTE:WhatsApp\r\n"
            "END:VCARD\r\n"
        )

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes("".join(cards).encode("utf-8"))
    return output, len(cards)
