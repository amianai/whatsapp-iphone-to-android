"""Command-Line Interface (CLI) for WhatsApp Backup Merger."""

import argparse
import sys
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from wa_backup.crypto import decrypt_android_backup, encrypt_android_backup
from wa_backup.ios_extractor import IOSExtractor
from wa_backup.android_db import AndroidDB
from wa_backup.merger import BackupMerger

console = Console()


def cmd_decrypt(args):
    console.print(Panel("[bold green]Descifrando respaldo de Android[/bold green]"))
    try:
        out = decrypt_android_backup(
            key_input=args.key,
            encrypted_path=Path(args.input),
            output_path=Path(args.output),
        )
        console.print(f"[bold green]✓[/bold green] Base de datos descifrada guardada en: [cyan]{out}[/cyan]")
    except Exception as e:
        console.print(f"[bold red]Error al descifrar:[/bold red] {e}")
        sys.exit(1)


def cmd_encrypt(args):
    console.print(Panel("[bold green]Re-cifrando base de datos para Android[/bold green]"))
    try:
        ref_path = Path(args.reference) if args.reference else None
        out = encrypt_android_backup(
            key_input=args.key,
            decrypted_path=Path(args.input),
            output_path=Path(args.output),
            reference_path=ref_path,
        )
        console.print(f"[bold green]✓[/bold green] Archivo cifrado generado en: [cyan]{out}[/cyan]")
    except Exception as e:
        console.print(f"[bold red]Error al cifrar:[/bold red] {e}")
        sys.exit(1)


def cmd_inspect_ios(args):
    account_type = "WhatsApp Business" if getattr(args, "business", False) else "WhatsApp Estándar"
    console.print(Panel(f"[bold blue]Inspeccionando respaldo de iOS ({account_type})[/bold blue]"))
    try:
        extractor = IOSExtractor(args.input, is_business=getattr(args, "business", False))
        chats = extractor.get_chats()

        table = Table(title=f"Chats encontrados ({len(chats)} total)")
        table.add_column("PK", style="dim")
        table.add_column("JID", style="cyan")
        table.add_column("Nombre / Contacto", style="green")
        table.add_column("Mensajes", justify="right")

        for c in chats[:25]: # Show first 25
            table.add_row(str(c.pk), c.jid, c.name or "(Sin nombre)", str(c.message_count))

        console.print(table)
        if len(chats) > 25:
            console.print(f"[dim]... y {len(chats) - 25} chats adicionales.[/dim]")

        # Count total messages
        msg_count = sum(1 for _ in extractor.iter_messages())
        console.print(f"\n[bold]Total de mensajes en iOS:[/bold] {msg_count}")
        if extractor.media_dir:
            console.print(f"[bold]Directorio multimedia:[/bold] [cyan]{extractor.media_dir}[/cyan]")

    except Exception as e:
        console.print(f"[bold red]Error al inspeccionar iOS:[/bold red] {e}")
        sys.exit(1)


def cmd_merge(args):
    console.print(Panel("[bold yellow]Uniendo respaldo de iOS dentro de la base de Android[/bold yellow]"))
    try:
        extractor = IOSExtractor(args.ios, is_business=getattr(args, "business", False))
        android_db = AndroidDB(args.android_db)

        def on_progress(processed, inserted):
            console.print(f"[dim]Progreso: {processed} mensajes procesados ({inserted} insertados)...[/dim]")

        merger = BackupMerger(
            ios_extractor=extractor,
            android_db=android_db,
            android_media_dir=args.android_media,
            progress_callback=on_progress,
        )

        summary = merger.run()
        android_db.close()

        res_table = Table(title="Resultados de la Fusión")
        res_table.add_column("Métrica", style="bold")
        res_table.add_column("Cantidad", justify="right", style="green")

        res_table.add_row("Chats creados (nuevos)", str(summary.chats_created))
        res_table.add_row("Chats combinados (existentes)", str(summary.chats_reused))
        res_table.add_row("Mensajes nuevos insertados", str(summary.messages_inserted))
        res_table.add_row("Mensajes duplicados omitidos", str(summary.messages_skipped_duplicate))
        res_table.add_row("Archivos multimedia migrados", str(summary.media_migrated))

        console.print(res_table)
        console.print("\n[bold green]✓ Fusión completada con éxito.[/bold green]")

    except Exception as e:
        console.print(f"[bold red]Error durante la fusión:[/bold red] {e}")
        sys.exit(1)


def cmd_pipeline(args):
    console.print(Panel.fit("[bold magenta]WhatsApp Backup Merger: Pipeline Completo[/bold magenta]"))

    ios_path = Path(args.ios)
    android_crypt = Path(args.android_crypt)
    key = args.key
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    decrypted_db = output_dir / "msgstore_decrypted.db"
    merged_crypt = output_dir / "msgstore.db.crypt15"
    media_out = output_dir / "WhatsApp" / "Media"

    console.print("\n[bold]1. Descifrando base de Android...[/bold]")
    decrypt_android_backup(key_input=key, encrypted_path=android_crypt, output_path=decrypted_db)
    console.print(f"[green]✓ Android descifrado en {decrypted_db}[/green]")

    console.print("\n[bold]2. Uniendo datos de iOS en la base de Android...[/bold]")
    extractor = IOSExtractor(ios_path, is_business=getattr(args, "business", False))
    android_db = AndroidDB(decrypted_db)
    merger = BackupMerger(
        ios_extractor=extractor,
        android_db=android_db,
        android_media_dir=media_out,
    )
    summary = merger.run()
    android_db.close()
    console.print(f"[green]✓ Se insertaron {summary.messages_inserted} mensajes ({summary.messages_skipped_duplicate} duplicados omitidos).[/green]")

    console.print("\n[bold]3. Re-cifrando base combinada para Android...[/bold]")
    encrypt_android_backup(
        key_input=key,
        decrypted_path=decrypted_db,
        output_path=merged_crypt,
        reference_path=android_crypt,
    )
    console.print(f"[bold green]✓ Respaldo final generado: {merged_crypt}[/bold green]")
    console.print(f"[bold green]✓ Archivos multimedia listos en: {media_out}[/bold green]")
    console.print(
        "\n[cyan]Para restaurar en Android:\n"
        f"1. Copia '{merged_crypt}' a tu teléfono en 'Android/media/com.whatsapp/WhatsApp/Databases/msgstore.db.crypt15'\n"
        f"2. Copia la carpeta de multimedia '{media_out}' a 'Android/media/com.whatsapp/WhatsApp/Media'\n"
        "3. Inicia sesión en WhatsApp para que detecte y restaure la copia local.[/cyan]"
    )


def cmd_wizard(args):
    from wa_backup.tui import start_wizard
    start_wizard()


def main():
    if len(sys.argv) == 1:
        from wa_backup.tui import start_wizard
        start_wizard()
        return

    parser = argparse.ArgumentParser(description="WhatsApp iOS to Android Backup Merger")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Wizard
    p_wiz = subparsers.add_parser("wizard", help="Inicia el asistente interactivo paso a paso (TUI)")
    p_wiz.set_defaults(func=cmd_wizard)

    # Decrypt
    p_dec = subparsers.add_parser("decrypt", help="Descifra msgstore.db.crypt14/15 de Android")
    p_dec.add_argument("--key", required=True, help="Ruta al archivo key o cadena hex de 64 caracteres")
    p_dec.add_argument("--input", required=True, help="Archivo cifrado (msgstore.db.crypt14/15)")
    p_dec.add_argument("--output", default="msgstore.db", help="Ruta de salida descifrada (default: msgstore.db)")
    p_dec.set_defaults(func=cmd_decrypt)

    # Encrypt
    p_enc = subparsers.add_parser("encrypt", help="Re-cifra msgstore.db a formato crypt15")
    p_enc.add_argument("--key", required=True, help="Ruta al archivo key o cadena hex de 64 caracteres")
    p_enc.add_argument("--input", required=True, help="Base de datos descifrada (msgstore.db)")
    p_enc.add_argument("--output", default="msgstore.db.crypt15", help="Ruta de salida cifrada")
    p_enc.add_argument("--reference", help="Archivo cifrado original de referencia (recomendado)")
    p_enc.set_defaults(func=cmd_encrypt)

    # Inspect iOS
    p_ins = subparsers.add_parser("inspect-ios", help="Inspecciona respaldo de iOS")
    p_ins.add_argument("input", help="Ruta a ChatStorage.sqlite o carpeta de respaldo iTunes")
    p_ins.add_argument("--business", action="store_true", help="Usar WhatsApp Business en lugar de estándar")
    p_ins.set_defaults(func=cmd_inspect_ios)

    # Merge
    p_mer = subparsers.add_parser("merge", help="Fusiona respaldo iOS dentro de base Android descifrada")
    p_mer.add_argument("--ios", required=True, help="Ruta a ChatStorage.sqlite o carpeta de respaldo de iTunes")
    p_mer.add_argument("--android-db", required=True, help="Ruta a msgstore.db (descifrado)")
    p_mer.add_argument("--android-media", help="Carpeta de destino para archivos multimedia de Android")
    p_mer.add_argument("--business", action="store_true", help="Usar WhatsApp Business en lugar de estándar")
    p_mer.set_defaults(func=cmd_merge)

    # Pipeline
    p_pipe = subparsers.add_parser("pipeline", help="Flujo completo: descifra, fusiona y re-cifra")
    p_pipe.add_argument("--ios", required=True, help="Ruta a ChatStorage.sqlite o respaldo iTunes")
    p_pipe.add_argument("--android-crypt", required=True, help="Archivo msgstore.db.crypt14/15 original")
    p_pipe.add_argument("--key", required=True, help="Clave de cifrado (archivo o 64 caracteres hex)")
    p_pipe.add_argument("--output-dir", default="./output", help="Directorio para los archivos generados")
    p_pipe.add_argument("--business", action="store_true", help="Usar WhatsApp Business en lugar de estándar")
    p_pipe.set_defaults(func=cmd_pipeline)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

