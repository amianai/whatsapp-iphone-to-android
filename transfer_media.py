#!/usr/bin/env python3
"""Incremental Media Transfer to Android Pixel."""

import os
import sys
import shutil
import time
from pathlib import Path

ROOT_DIR = Path(__file__).parent.resolve()
venv_python = ROOT_DIR / ".venv" / "bin" / "python3"
if venv_python.exists() and sys.executable != str(venv_python):
    os.execv(str(venv_python), [str(venv_python)] + sys.argv)

from wa_backup.tui import detect_android_devices

# Auto-detect source media
default_src = Path(os.environ.get("WA_MEDIA_SRC", str(ROOT_DIR / "output" / "WhatsApp" / "Media")))
if len(sys.argv) > 1:
    src_base = Path(sys.argv[1])
elif default_src.exists():
    src_base = default_src
else:
    input_src = input(f"Ruta a carpeta multimedia origen [{default_src}]: ").strip()
    src_base = Path(input_src) if input_src else default_src

if not src_base.exists():
    print(f"Error: Carpeta multimedia origen no encontrada: {src_base}")
    sys.exit(1)

# Auto-detect destination Android device
if len(sys.argv) > 2:
    dst_base = Path(sys.argv[2])
else:
    devices = detect_android_devices()
    if devices:
        target_dev = devices[0]
        dst_base = Path(target_dev.base_whatsapp_path) / "Media"
        print(f"✓ Dispositivo Android detectado: {target_dev.display_name}")
    else:
        input_dst = input("Ruta a la carpeta WhatsApp/Media en el teléfono: ").strip()
        dst_base = Path(input_dst)

if not dst_base.exists():
    try:
        dst_base.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"Error: No se pudo acceder o crear la ruta destino: {dst_base}\n{e}")
        sys.exit(1)

total_copied = 0
total_skipped = 0
total_errors = 0

print("=" * 60)
print(" SINCRONIZACIÓN MULTIMEDIA RESTANTE (iOS -> Pixel)")
print("=" * 60)

subdirs = [d for d in src_base.iterdir() if d.is_dir()]

for s_dir in subdirs:
    d_dir = dst_base / s_dir.name
    d_dir.mkdir(parents=True, exist_ok=True)

    src_files = list(s_dir.iterdir())
    try:
        existing_dst = {f.name for f in d_dir.iterdir()}
    except Exception:
        existing_dst = set()

    missing_files = [f for f in src_files if f.name not in existing_dst]
    print(f"\n📁 {s_dir.name}:")
    print(f"   Total origen: {len(src_files)} | Ya en teléfono: {len(existing_dst)} | Faltan: {len(missing_files)}")

    if not missing_files:
        total_skipped += len(src_files)
        print("   ✓ Al día.")
        continue

    total_skipped += (len(src_files) - len(missing_files))

    for idx, s_file in enumerate(missing_files, 1):
        d_file = d_dir / s_file.name
        try:
            shutil.copyfile(s_file, d_file)
            total_copied += 1
            if idx % 50 == 0 or idx == len(missing_files):
                print(f"   -> Copiando... {idx}/{len(missing_files)} ({total_copied} copiados en total)")
        except Exception as e:
            total_errors += 1
            print(f"   [!] Error en {s_file.name}: {e}")

print("\n" + "=" * 60)
print(f"✓ ¡Sincronización completada!")
print(f"  Archivos copiados ahora: {total_copied}")
print(f"  Archivos ya existentes:  {total_skipped}")
print(f"  Errores:                 {total_errors}")
print("=" * 60)
