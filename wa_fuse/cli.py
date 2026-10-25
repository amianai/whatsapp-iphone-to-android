"""Command-Line Interface (CLI) for WhatsApp Backup Merger."""

import argparse
import os
from pathlib import Path
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from wa_fuse.android_db import AndroidDB
from wa_fuse.crypto import decrypt_android_backup, encrypt_android_backup
from wa_fuse.i18n import get_language, set_language, t
from wa_fuse.ios_extractor import IOSExtractor
from wa_fuse.merger import BackupMerger, MergeSummary
from wa_fuse.contacts import export_whatsapp_only_contacts

console = Console()


def _make_extractor(args, source) -> IOSExtractor:
    """IOSExtractor for a ChatStorage.sqlite, an extracted folder or a Finder backup.

    The backup password is read from --backup-password or IOS_BACKUP_PASSWORD
    (the environment keeps it out of the shell history).
    """
    password = getattr(args, "backup_password", None) or os.environ.get("IOS_BACKUP_PASSWORD")
    staging = getattr(args, "staging_dir", None)

    def on_extract(n, total):
        console.print(f"[dim]Decrypting WhatsApp files from the iPhone backup: {n}/{total}[/dim]")

    return IOSExtractor(
        source,
        staging_dir=staging,
        is_business=getattr(args, "business", False),
        backup_password=password,
        progress_callback=on_extract,
    )


def _print_summary(summary: MergeSummary, report_path: Path | None):
    res_table = Table(title=t("pipeline_summary_title"))
    res_table.add_column(t("pipeline_summary_metric"), style="bold")
    res_table.add_column(t("pipeline_summary_count"), justify="right", style="green")
    res_table.add_row("iPhone messages read", str(summary.messages_read))
    res_table.add_row(t("pipeline_summary_created"), str(summary.chats_created))
    res_table.add_row(t("pipeline_summary_reused"), str(summary.chats_reused))
    res_table.add_row(t("pipeline_summary_inserted"), str(summary.messages_inserted))
    res_table.add_row(t("pipeline_summary_skipped"), str(summary.messages_skipped_duplicate))
    res_table.add_row("Skipped: system / deleted", str(summary.messages_skipped_system_or_deleted))
    res_table.add_row("Skipped: empty / unsupported", str(summary.messages_skipped_empty_unsupported))
    res_table.add_row(t("pipeline_summary_media"), str(summary.media_migrated))
    res_table.add_row("Media missing from the iPhone backup", str(summary.media_missing))
    console.print(res_table)
    if report_path:
        summary.write_report(report_path)
        console.print(f"[bold]Per-chat report: {report_path}[/bold]")


def _merger_options(args) -> dict:
    chats = getattr(args, "chats", None)
    return {
        "chat_filter": chats.split(",") if chats else None,
        "move_media": getattr(args, "move_media", False),
    }


def cmd_decrypt(args):
    console.print(Panel(f"[bold green]{t('cli_decrypt_panel')}[/bold green]"))
    try:
        out = decrypt_android_backup(
            key_input=args.key,
            encrypted_path=Path(args.input),
            output_path=Path(args.output),
        )
        console.print(f"[bold green]{t('cli_decrypt_success', path=out)}[/bold green]")
    except Exception as e:
        console.print(f"[bold red]{t('cli_decrypt_error', e=e)}[/bold red]")
        sys.exit(1)


def cmd_encrypt(args):
    console.print(Panel(f"[bold green]{t('cli_encrypt_panel')}[/bold green]"))
    try:
        ref_path = Path(args.reference) if args.reference else None
        out = encrypt_android_backup(
            key_input=args.key,
            decrypted_path=Path(args.input),
            output_path=Path(args.output),
            reference_path=ref_path,
        )
        console.print(f"[bold green]{t('cli_encrypt_success', path=out)}[/bold green]")
    except Exception as e:
        console.print(f"[bold red]{t('cli_encrypt_error', e=e)}[/bold red]")
        sys.exit(1)


def cmd_inspect_ios(args):
    account_type = t("wa_business") if getattr(args, "business", False) else t("wa_standard")
    console.print(Panel(f"[bold blue]{t('cli_inspect_ios', type=account_type)}[/bold blue]"))
    try:
        extractor = _make_extractor(args, args.input)
        chats = extractor.get_chats()

        table = Table(title=t("cli_inspect_ios_title", count=len(chats)))
        table.add_column(t("cli_inspect_ios_col_pk"), style="dim")
        table.add_column(t("cli_inspect_ios_col_jid"), style="cyan")
        table.add_column(t("cli_inspect_ios_col_name"), style="green")
        table.add_column(t("cli_inspect_ios_col_msgs"), justify="right")

        for c in chats[:25]:  # Show first 25
            table.add_row(str(c.pk), c.jid, c.name or t("cli_inspect_ios_no_name"), str(c.message_count))

        console.print(table)
        if len(chats) > 25:
            console.print(f"[dim]{t('cli_inspect_ios_more', count=len(chats) - 25)}[/dim]")

        # Count total messages
        msg_count = sum(1 for _ in extractor.iter_messages())
        console.print(f"\n[bold]{t('cli_inspect_ios_total_msgs', count=msg_count)}[/bold]")
        if extractor.media_dir:
            console.print(f"[bold]{t('cli_inspect_ios_media_dir', path=extractor.media_dir)}[/bold]")

    except Exception as e:
        console.print(f"[bold red]{t('cli_inspect_ios_error', e=e)}[/bold red]")
        sys.exit(1)


def cmd_merge(args):
    console.print(Panel(f"[bold yellow]{t('cli_merge_panel')}[/bold yellow]"))
    try:
        extractor = _make_extractor(args, args.ios)
        android_db = AndroidDB(args.android_db)

        def on_progress(processed, inserted):
            console.print(f"[dim]{t('cli_merge_progress', processed=processed, inserted=inserted)}[/dim]")

        merger = BackupMerger(
            ios_extractor=extractor,
            android_db=android_db,
            android_media_dir=args.android_media,
            progress_callback=on_progress,
            **_merger_options(args),
        )

        summary = merger.run()
        android_db.close()
        _print_summary(summary, Path(args.report) if args.report else None)
        console.print(f"\n[bold green]{t('cli_merge_success')}[/bold green]")

    except Exception as e:
        console.print(f"[bold red]{t('cli_merge_error', e=e)}[/bold red]")
        sys.exit(1)


def cmd_pipeline(args):
    console.print(Panel.fit(f"[bold magenta]{t('cli_pipeline_panel')}[/bold magenta]"))

    ios_path = Path(args.ios)
    android_crypt = Path(args.android_crypt)
    key = args.key
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    decrypted_db = output_dir / "msgstore_decrypted.db"
    merged_crypt = output_dir / "msgstore.db.crypt15"
    media_out = output_dir / "WhatsApp" / "Media"

    console.print(f"\n[bold]{t('cli_pipeline_step1')}[/bold]")
    decrypt_android_backup(key_input=key, encrypted_path=android_crypt, output_path=decrypted_db)
    console.print(f"[green]{t('pipeline_decrypted_success', path=decrypted_db)}[/green]")

    console.print(f"\n[bold]{t('cli_pipeline_step2')}[/bold]")
    extractor = _make_extractor(args, ios_path)
    android_db = AndroidDB(decrypted_db)
    merger = BackupMerger(
        ios_extractor=extractor,
        android_db=android_db,
        android_media_dir=media_out,
        progress_callback=lambda n, ins: console.print(f"[dim]{n} read, {ins} inserted[/dim]"),
        **_merger_options(args),
    )
    summary = merger.run()
    android_db.close()
    _print_summary(summary, output_dir / "report.json")
    console.print(f"[green]{t('merge_today_success', count=summary.messages_inserted)}[/green]")

    console.print(f"\n[bold]{t('cli_pipeline_step3')}[/bold]")
    encrypt_android_backup(
        key_input=key,
        decrypted_path=decrypted_db,
        output_path=merged_crypt,
        reference_path=android_crypt,
    )
    console.print(f"[bold green]{t('pipeline_encrypt_success', path=merged_crypt)}[/bold green]")
    console.print(t("cli_pipeline_restore_note", crypt_path=merged_crypt, media_path=media_out))


def cmd_export_contacts(args):
    extractor = _make_extractor(args, args.ios)
    path, count = export_whatsapp_only_contacts(extractor, Path(args.output))
    console.print(f"[bold green]{count} contacts that were only in WhatsApp written to {path}[/bold green]")


def cmd_wizard(args):
    from wa_fuse.tui import start_wizard
    start_wizard(lang=getattr(args, "lang", None))


def main():
    # Pre-parse language argument if passed
    for idx, arg in enumerate(sys.argv):
        if arg in ("--lang", "-l") and idx + 1 < len(sys.argv):
            set_language(sys.argv[idx + 1])
            break
        elif arg.startswith("--lang="):
            set_language(arg.split("=", 1)[1])
            break

    # If no subcommand was provided (or only --lang was given), launch interactive wizard
    filtered_args = []
    skip_next = False
    for a in sys.argv[1:]:
        if skip_next:
            skip_next = False
            continue
        if a in ("--lang", "-l"):
            skip_next = True
            continue
        if a.startswith("--lang="):
            continue
        filtered_args.append(a)

    if not filtered_args:
        from wa_fuse.tui import start_wizard
        start_wizard()
        return

    parser = argparse.ArgumentParser(description=t("cli_desc"))
    parser.add_argument("--lang", "-l", choices=["en", "es"], default=None, help="Interface language / Idioma (en/es)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Wizard
    p_wiz = subparsers.add_parser("wizard", help=t("cli_wizard_help"))
    p_wiz.set_defaults(func=cmd_wizard)

    # Decrypt
    p_dec = subparsers.add_parser("decrypt", help=t("cli_decrypt_help"))
    p_dec.add_argument("--key", required=True, help="Path to key file or 64-char hex string")
    p_dec.add_argument("--input", required=True, help="Encrypted file (msgstore.db.crypt14/15)")
    p_dec.add_argument("--output", default="msgstore.db", help="Decrypted output path (default: msgstore.db)")
    p_dec.set_defaults(func=cmd_decrypt)

    # Encrypt
    p_enc = subparsers.add_parser("encrypt", help=t("cli_encrypt_help"))
    p_enc.add_argument("--key", required=True, help="Path to key file or 64-char hex string")
    p_enc.add_argument("--input", required=True, help="Decrypted database (msgstore.db)")
    p_enc.add_argument("--output", default="msgstore.db.crypt15", help="Encrypted output path")
    p_enc.add_argument("--reference", help="Original reference encrypted file (recommended)")
    p_enc.set_defaults(func=cmd_encrypt)

    # Inspect iOS
    p_ins = subparsers.add_parser("inspect-ios", help=t("cli_inspect_ios_help"))
    p_ins.add_argument("input", help="Path to ChatStorage.sqlite or iTunes backup folder")
    p_ins.add_argument("--business", action="store_true", help="Use WhatsApp Business database")
    p_ins.add_argument("--backup-password", help="Password of an encrypted iPhone backup (or set IOS_BACKUP_PASSWORD)")
    p_ins.add_argument("--staging-dir", help="Where to decrypt the WhatsApp files of the iPhone backup")
    p_ins.set_defaults(func=cmd_inspect_ios)

    # Merge
    p_mer = subparsers.add_parser("merge", help=t("cli_merge_help"))
    p_mer.add_argument("--ios", required=True, help="Path to ChatStorage.sqlite or iTunes backup")
    p_mer.add_argument("--android-db", required=True, help="Path to decrypted msgstore.db")
    p_mer.add_argument("--android-media", help="Output directory for Android media files")
    p_mer.add_argument("--business", action="store_true", help="Use WhatsApp Business")
    p_mer.add_argument("--backup-password", help="Password of an encrypted iPhone backup (or set IOS_BACKUP_PASSWORD)")
    p_mer.add_argument("--staging-dir", help="Where to decrypt the WhatsApp files of the iPhone backup")
    p_mer.add_argument("--chats", help="Only these chats: comma-separated parts of names or numbers")
    p_mer.add_argument("--move-media", action="store_true", help="Move media out of the staging folder instead of copying (saves space)")
    p_mer.add_argument("--report", help="Write a per-chat JSON report here")
    p_mer.set_defaults(func=cmd_merge)

    # Pipeline
    p_pipe = subparsers.add_parser("pipeline", help=t("cli_pipeline_help"))
    p_pipe.add_argument("--ios", required=True, help="Path to ChatStorage.sqlite or iTunes backup")
    p_pipe.add_argument("--android-crypt", required=True, help="Original msgstore.db.crypt14/15")
    p_pipe.add_argument("--key", required=True, help="Encryption key (file or 64 hex chars)")
    p_pipe.add_argument("--output-dir", default="./output", help="Directory for generated output")
    p_pipe.add_argument("--business", action="store_true", help="Use WhatsApp Business")
    p_pipe.add_argument("--backup-password", help="Password of an encrypted iPhone backup (or set IOS_BACKUP_PASSWORD)")
    p_pipe.add_argument("--staging-dir", help="Where to decrypt the WhatsApp files of the iPhone backup")
    p_pipe.add_argument("--chats", help="Only these chats: comma-separated parts of names or numbers")
    p_pipe.add_argument("--move-media", action="store_true", help="Move media out of the staging folder instead of copying (saves space)")
    p_pipe.set_defaults(func=cmd_pipeline)

    # Export contacts that were only in WhatsApp
    p_con = subparsers.add_parser("export-contacts", help="Write a .vcf of people you chatted with who are not in the iPhone address book")
    p_con.add_argument("--ios", required=True, help="Path to ChatStorage.sqlite, extracted folder or iTunes backup")
    p_con.add_argument("--output", default="whatsapp_only_contacts.vcf", help="Output .vcf file")
    p_con.add_argument("--business", action="store_true", help="Use WhatsApp Business")
    p_con.add_argument("--backup-password", help="Password of an encrypted iPhone backup (or set IOS_BACKUP_PASSWORD)")
    p_con.add_argument("--staging-dir", help="Where to decrypt the WhatsApp files of the iPhone backup")
    p_con.set_defaults(func=cmd_export_contacts)

    args = parser.parse_args()
    if getattr(args, "lang", None):
        set_language(args.lang)
    args.func(args)


if __name__ == "__main__":
    main()
