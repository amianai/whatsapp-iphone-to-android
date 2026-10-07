#!/usr/bin/env python3
"""Script to extract today's incremental messages from Pixel, merge into msgstore_merged.db,

and produce the final ready-to-restore crypt15.
"""

import os
import sys
import shutil
from pathlib import Path

ROOT_DIR = Path(__file__).parent.resolve()
venv_python = ROOT_DIR / ".venv" / "bin" / "python3"
if venv_python.exists() and sys.executable != str(venv_python):
    os.execv(str(venv_python), [str(venv_python)] + sys.argv)

from wa_backup.crypto import decrypt_android_backup, encrypt_android_backup
from wa_backup.merge_incremental import merge_incremental_messages

ROOT_DIR = Path(__file__).parent.resolve()
BACKUP_DIR = Path(os.environ.get("WA_OUTPUT_DIR", str(ROOT_DIR / "output")))
MERGED_DB = BACKUP_DIR / "msgstore_merged.db"
FINAL_CRYPT15 = BACKUP_DIR / "msgstore.db.crypt15"

DEFAULT_KEY = os.environ.get("WA_BACKUP_KEY", "")


def main():
    print("=" * 60)
    print(" FUSIÓN INCREMENTAL: INCORPORAR MENSAJES DE HOY")
    print("=" * 60)

    if len(sys.argv) > 1:
        today_crypt15 = Path(sys.argv[1])
    else:
        # Check standard location or prompt
        candidates = [
            ROOT_DIR / "today_backup" / "msgstore.db.crypt15",
            ROOT_DIR / "android_today" / "msgstore.db.crypt15",
            Path("/tmp/msgstore_today.crypt15"),
        ]
        found = None
        for c in candidates:
            if c.exists():
                found = c
                break
        if found:
            today_crypt15 = found
        else:
            path_str = input("Ruta al msgstore.db.crypt15 de hoy: ").strip()
            today_crypt15 = Path(path_str)

    if not today_crypt15.exists():
        print(f"Error: No se encontró el archivo: {today_crypt15}")
        sys.exit(1)

    if DEFAULT_KEY:
        key_input = input(f"Clave de 64 dígitos [{DEFAULT_KEY}]: ").strip()
        if not key_input:
            key_input = DEFAULT_KEY
    else:
        key_input = input("Clave de cifrado de 64 dígitos: ").strip()

    if not key_input:
        print("Error: Se requiere una clave de 64 dígitos válida.")
        sys.exit(1)

    # 1. Decrypt today's backup
    work_dir = ROOT_DIR / "today_backup"
    work_dir.mkdir(parents=True, exist_ok=True)
    today_decrypted = work_dir / "today_decrypted.db"

    print(f"\n[1/4] Descifrando copia de hoy ({today_crypt15.name})...")
    decrypt_android_backup(key_input, today_crypt15, today_decrypted)
    print("  -> Descifrado exitoso.")

    # 2. Backup current merged db before modifying
    backup_copy = BACKUP_DIR / "msgstore_merged_before_today.db"
    shutil.copy(MERGED_DB, backup_copy)
    print(f"[2/4] Respaldo de seguridad previo guardado en: {backup_copy.name}")

    # 3. Merge incremental messages
    print("[3/4] Extrayendo e insertando mensajes recibidos hoy...")
    count = merge_incremental_messages(today_decrypted, MERGED_DB)
    print(f"  -> {count} mensajes nuevos agregados a la base de datos combinada.")

    # 4. Re-encrypt to final crypt15
    print("[4/4] Re-encriptando base de datos completa a crypt15...")
    encrypt_android_backup(
        key_input=key_input,
        decrypted_path=MERGED_DB,
        output_path=FINAL_CRYPT15,
        reference_path=today_crypt15,
    )
    print(f"  -> Archivo final listo en: {FINAL_CRYPT15}")
    print("\n¡Listo! Ahora puedes restaurar este archivo en tu Pixel sin perder ningún mensaje de hoy.")


if __name__ == "__main__":
    main()
