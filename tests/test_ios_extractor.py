import sqlite3
from pathlib import Path
from wa_fuse.ios_extractor import IOSExtractor


def create_synthetic_ios_db(db_path: Path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE ZWACHATSESSION (
            Z_PK INTEGER PRIMARY KEY,
            ZCONTACTJID TEXT,
            ZPARTNERNAME TEXT,
            ZUNREADCOUNT INTEGER,
            ZMESSAGECOUNTER INTEGER
        );
    """)

    cur.execute("""
        CREATE TABLE ZWAMEDIAITEM (
            Z_PK INTEGER PRIMARY KEY,
            ZMEDIALOCALPATH TEXT,
            ZFILESIZE INTEGER,
            ZMEDIAMIMETYPE TEXT,
            ZTITLE TEXT,
            ZVCARDSTRING TEXT,
            ZLATITUDE REAL,
            ZLONGITUDE REAL
        );
    """)

    cur.execute("""
        CREATE TABLE ZWAMESSAGE (
            Z_PK INTEGER PRIMARY KEY,
            ZCHATSESSION INTEGER,
            ZISFROMME INTEGER,
            ZMESSAGEDATE REAL,
            ZTEXT TEXT,
            ZMESSAGETYPE INTEGER,
            ZMESSAGESTATUS INTEGER,
            ZSTANZAID TEXT,
            ZFROMJID TEXT,
            ZMEDIAITEM INTEGER
        );
    """)

    # Insert test chat
    cur.execute(
        "INSERT INTO ZWACHATSESSION VALUES (1, '34600112233@s.whatsapp.net', 'Alice', 0, 2)"
    )

    # Insert test messages (Apple epoch seconds: 700000000 ~ 2023)
    cur.execute(
        "INSERT INTO ZWAMESSAGE VALUES (1, 1, 0, 700000000, 'Hola desde iPhone', 0, 13, 'STANZA_1', NULL, NULL)"
    )
    cur.execute(
        "INSERT INTO ZWAMESSAGE VALUES (2, 1, 1, 700000010, 'Respuesta desde iPhone', 0, 4, 'STANZA_2', NULL, NULL)"
    )

    conn.commit()
    conn.close()


def test_ios_extractor_reads_chats_and_messages(tmp_path):
    ios_db_file = tmp_path / "ChatStorage.sqlite"
    create_synthetic_ios_db(ios_db_file)

    extractor = IOSExtractor(ios_db_file)
    chats = extractor.get_chats()
    assert len(chats) == 1
    assert chats[0].jid == "34600112233@s.whatsapp.net"
    assert chats[0].name == "Alice"

    messages = list(extractor.iter_messages())
    assert len(messages) == 2
    assert messages[0].text == "Hola desde iPhone"
    assert messages[0].from_me is False
    assert messages[1].text == "Respuesta desde iPhone"
    assert messages[1].from_me is True
