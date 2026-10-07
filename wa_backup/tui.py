"""Interactive TUI Wizard for WhatsApp Migration (iOS -> Android).

Guides the user step-by-step through backup extraction, database merging,
encryption verification, phone preparation, file transfer, and restoration.
"""

from dataclasses import dataclass
import glob
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, DownloadColumn, Progress, SpinnerColumn, TextColumn, TimeRemainingColumn, TransferSpeedColumn
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from wa_backup.android_db import AndroidDB
from wa_backup.crypto import decrypt_android_backup, encrypt_android_backup
from wa_backup.ios_extractor import IOSExtractor
from wa_backup.merger import BackupMerger
from wa_backup.merge_incremental import merge_incremental_messages
from wa_backup.i18n import t, set_language, get_language

console = Console()

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_KEY = os.environ.get("WA_BACKUP_KEY", "")

# Output directories
DEFAULT_OUTPUT_DIR = Path(os.environ.get("WA_OUTPUT_DIR", str(PROJECT_ROOT / "output")))
DEFAULT_PREPARED_CRYPT15 = DEFAULT_OUTPUT_DIR / "msgstore.db.crypt15"
DEFAULT_PREPARED_MEDIA = DEFAULT_OUTPUT_DIR / "WhatsApp" / "Media"


def _find_candidate(*paths: Path) -> Path:
    for p in paths:
        if p.exists():
            return p
    return paths[0]


DEFAULT_IOS_BACKUP = _find_candidate(
    PROJECT_ROOT / "ios_backup",
    Path.home() / "ios_backup",
)
DEFAULT_ORIGINAL_ANDROID_CRYPT = _find_candidate(
    PROJECT_ROOT / "android_backup" / "msgstore.db.crypt15",
    PROJECT_ROOT / "android_backup" / "msgstore.db.crypt14",
    Path.home() / "android_backup" / "msgstore.db.crypt15",
)
DEFAULT_ORIGINAL_ANDROID_DB = _find_candidate(
    PROJECT_ROOT / "android_backup" / "msgstore_decrypted.db",
    Path.home() / "android_backup" / "msgstore_decrypted.db",
)


def format_hex_key(key: str) -> str:
    """Formats a 64-digit hex key in groups of 4 characters for readability."""
    if not key:
        return t("format_no_key")
    clean = key.replace(" ", "").replace("-", "").strip()
    return " ".join([clean[i:i + 4] for i in range(0, len(clean), 4)])


def copy_to_clipboard(text: str) -> bool:
    """Attempts to copy text to system clipboard using wl-copy or xclip."""
    for tool, args in [("wl-copy", []), ("xclip", ["-selection", "clipboard"])]:
        if shutil.which(tool):
            try:
                subprocess.run([tool] + args, input=text.encode(), check=True)
                return True
            except Exception:
                pass
    return False


@dataclass
class AndroidDevice:
    kind: str  # 'mtp' or 'adb'
    path_or_serial: str
    display_name: str
    base_whatsapp_path: Path | str


def detect_android_devices() -> list[AndroidDevice]:
    """Detects connected Android devices via MTP and ADB."""
    devices: list[AndroidDevice] = []

    # 1. Check ADB
    if shutil.which("adb"):
        try:
            res = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=2)
            lines = [l.strip() for l in res.stdout.splitlines() if l.strip() and not l.startswith("List of")]
            for line in lines:
                parts = line.split("\t")
                if len(parts) >= 2 and parts[1] == "device":
                    serial = parts[0]
                    # Get model
                    model = serial
                    try:
                        m_res = subprocess.run(
                            ["adb", "-s", serial, "shell", "getprop", "ro.product.model"],
                            capture_output=True,
                            text=True,
                            timeout=2,
                        )
                        if m_res.stdout.strip():
                            model = m_res.stdout.strip()
                    except Exception:
                        pass
                    devices.append(
                        AndroidDevice(
                            kind="adb",
                            path_or_serial=serial,
                            display_name=f"{model} (ADB)",
                            base_whatsapp_path="/sdcard/Android/media/com.whatsapp/WhatsApp",
                        )
                    )
        except Exception:
            pass

    # 2. Check GVFS MTP mounts
    mtp_mounts = glob.glob("/run/user/*/gvfs/mtp:*")
    for m in mtp_mounts:
        p = Path(m)
        name = p.name
        if "host=" in name:
            name = name.split("host=")[-1]
        name = name.replace("_", " ")

        # Check internal storage subfolder
        target_base = p
        for candidate in [
            "Almacenamiento interno compartido",
            "Internal shared storage",
            "Almacenamiento interno",
            "Internal storage",
        ]:
            if (p / candidate).exists():
                target_base = p / candidate
                break

        whatsapp_path = target_base / "Android" / "media" / "com.whatsapp" / "WhatsApp"
        devices.append(
            AndroidDevice(
                kind="mtp",
                path_or_serial=str(p),
                display_name=f"{name} (MTP)",
                base_whatsapp_path=whatsapp_path,
            )
        )

    return devices


def detect_ios_devices() -> list[str]:
    """Detects connected iOS devices using idevice_id."""
    if not shutil.which("idevice_id"):
        return []
    try:
        res = subprocess.run(["idevice_id", "-l"], capture_output=True, text=True, timeout=2)
        return [l.strip() for l in res.stdout.splitlines() if l.strip()]
    except Exception:
        return []


class WizardUI:
    def __init__(self):
        self.console = console
        self.current_key = DEFAULT_KEY

    def clear(self):
        self.console.clear()

    def show_header(self, subtitle: str = ""):
        self.clear()
        title = Text(t("app_title"), style="bold white on blue")
        header_text = Text()
        header_text.append(f"{t('app_subtitle')}\n", style="cyan")
        if subtitle:
            header_text.append(f"▶ {subtitle}", style="bold yellow")
        self.console.print(Panel(Align.center(header_text), title=title, border_style="blue", padding=(1, 2)))
        self.console.print()

    def menu_main(self):
        while True:
            self.show_header(t("menu_main"))

            # Check status of prepared backup
            prep_ok = DEFAULT_PREPARED_CRYPT15.exists()
            prep_size_mb = (DEFAULT_PREPARED_CRYPT15.stat().st_size / (1024 * 1024)) if prep_ok else 0

            status_table = Table(box=None, padding=(0, 2))
            status_table.add_column(t("diag_test_col"), style="bold")
            status_table.add_column(t("diag_res_col"), style="dim")
            if prep_ok:
                status_table.add_row(
                    t("status_backup"),
                    t("status_backup_ready", size=prep_size_mb),
                )
            else:
                status_table.add_row(t("status_backup"), f"[yellow]{t('status_backup_missing')}[/yellow]")

            devs = detect_android_devices()
            if devs:
                status_table.add_row(t("status_device"), f"[green]✓ {devs[0].display_name}[/green]")
            else:
                status_table.add_row(t("status_device"), f"[dim]{t('status_no_device')}[/dim]")

            self.console.print(Panel(status_table, title=f"[bold]{t('status_title')}[/bold]", border_style="dim"))
            self.console.print()

            self.console.print(f"[bold cyan]{t('select_option')}[/bold cyan]\n")
            self.console.print(f"  [bold green]1.[/bold green] [bold white]{t('opt_1')}[/bold white]")
            self.console.print(f"  [bold magenta]6.[/bold magenta] [bold white]{t('opt_6')}[/bold white]")
            self.console.print(f"  [bold cyan]2.[/bold cyan] {t('opt_2')}")
            self.console.print(f"  [bold cyan]3.[/bold cyan] {t('opt_3')}")
            self.console.print(f"  [bold cyan]4.[/bold cyan] {t('opt_4')}")
            self.console.print(f"  [bold cyan]5.[/bold cyan] {t('opt_5')}")
            self.console.print(f"  [bold yellow]L.[/bold yellow] {t('opt_lang')}")
            self.console.print(f"  [bold red]0.[/bold red] {t('opt_0')}\n")

            try:
                choice = Prompt.ask(t("option_prompt"), choices=["1", "6", "2", "3", "4", "5", "L", "l", "0"], default="1")
            except (EOFError, KeyboardInterrupt):
                self.console.print(f"\n\n[dim]{t('goodbye')}[/dim]")
                break

            choice_upper = choice.upper()
            if choice_upper == "L":
                new_lang = "en" if get_language() == "es" else "es"
                set_language(new_lang)
                continue
            elif choice == "1":
                self.flow_restore_prepared()
            elif choice == "6":
                self.flow_merge_today()
            elif choice == "2":
                self.flow_full_wizard()
            elif choice == "3":
                self.flow_remerge()
            elif choice == "4":
                self.flow_verify_tools()
            elif choice == "5":
                self.flow_show_key()
            elif choice == "0":
                self.console.print(f"\n[dim]{t('goodbye')}[/dim]")
                break

    # -------------------------------------------------------------------------
    # FLOW 1: Transfer and restore prepared backup
    # -------------------------------------------------------------------------
    def flow_restore_prepared(self):
        self.show_header(t("flow_restore_title"))

        if not DEFAULT_PREPARED_CRYPT15.exists():
            self.console.print(f"[bold red]{t('restore_not_found')}[/bold red]")
            self.console.print(f"[cyan]{DEFAULT_PREPARED_CRYPT15}[/cyan]")
            self.console.print(f"\n{t('restore_run_opt_3')}")
            Prompt.ask(f"\n{t('press_enter_back')}")
            return

        size_mb = DEFAULT_PREPARED_CRYPT15.stat().st_size / (1024 * 1024)
        self.console.print(f"[bold green]{t('restore_file_found', name=DEFAULT_PREPARED_CRYPT15.name, size=size_mb)}[/bold green]")
        self.console.print(f"[dim]{t('restore_contains_desc')}[/dim]\n")

        # Prior check: new messages from today
        if Confirm.ask(t("ask_today_messages"), default=False):
            self.console.print(f"\n[bold cyan]{t('redirecting_today')}[/bold cyan]")
            self.flow_merge_today()
            self.show_header(t("flow_restore_title"))

        # Step A: Scoped Storage critical warning
        self.console.print(
            Panel(
                t("scoped_storage_warning_body"),
                title=f"[bold red]{t('scoped_storage_warning_title')}[/bold red]",
                border_style="yellow",
            )
        )

        if not Confirm.ask(t("ask_cleared_storage"), default=True):
            self.console.print(f"\n[yellow]{t('clear_storage_first')}[/yellow]")
            Prompt.ask(f"\n{t('press_enter_continue')}")

        # Step B: Wait for USB phone connection
        self.console.print()
        self.console.print(Rule(f"[bold cyan]{t('conn_rule_title')}[/bold cyan]"))
        self.console.print(t("conn_instructions"))

        device = self.wait_for_android_device()
        if not device:
            return

        self.console.print(f"\n[bold green]{t('device_ready', name=device.display_name)}[/bold green]\n")

        # Step C: Copy database
        if device.kind == "mtp":
            base_p = Path(device.base_whatsapp_path)
            databases_dir = base_p / "Databases"
            try:
                databases_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                self.console.print(f"[bold red]{t('mtp_mkdir_error', e=e)}[/bold red]")
                self.console.print(f"[yellow]{t('unlock_screen_hint')}[/yellow]")
                Prompt.ask(f"\n{t('press_enter_back')}")
                return

            dest_file = databases_dir / "msgstore.db.crypt15"
            self.console.print(f"[bold]{t('copying_to', dest=dest_file)}[/bold]")
            self.copy_file_with_progress(DEFAULT_PREPARED_CRYPT15, dest_file)

        elif device.kind == "adb":
            dest_dir = "/sdcard/Android/media/com.whatsapp/WhatsApp/Databases"
            subprocess.run(["adb", "-s", device.path_or_serial, "shell", "mkdir", "-p", dest_dir], check=False)
            self.console.print(f"[bold]{t('adb_pushing')}[/bold]")
            res = subprocess.run(
                ["adb", "-s", device.path_or_serial, "push", str(DEFAULT_PREPARED_CRYPT15), f"{dest_dir}/msgstore.db.crypt15"],
                capture_output=True,
                text=True,
            )
            if res.returncode != 0:
                self.console.print(f"[bold red]{t('adb_push_error', e=res.stderr)}[/bold red]")
                Prompt.ask(f"\n{t('press_enter_back')}")
                return
            self.console.print(f"[bold green]{t('adb_push_success')}[/bold green]")

        # Step D: Optional media transfer
        self.console.print()
        if DEFAULT_PREPARED_MEDIA.exists():
            media_count = sum(len(files) for _, _, files in os.walk(DEFAULT_PREPARED_MEDIA))
            if Confirm.ask(
                t("ask_transfer_media", count=media_count),
                default=False,
            ):
                self.transfer_media_files(device)
            else:
                self.console.print(f"[dim]{t('skipping_media')}[/dim]")

        # Step E: Copy key to clipboard and show restoration guide
        copy_ok = copy_to_clipboard(self.current_key)
        formatted_key = format_hex_key(self.current_key)

        self.console.print()
        self.console.print(Rule(f"[bold green]{t('restore_guide_title')}[/bold green]"))

        key_panel_text = Text()
        key_panel_text.append(f"{formatted_key}\n\n", style="bold yellow")
        if copy_ok:
            key_panel_text.append(f"{t('key_copied')}\n", style="green")
        else:
            key_panel_text.append(f"{t('key_ready')}\n", style="dim")

        self.console.print(Panel(Align.center(key_panel_text), title=f"[bold]{t('key_title')}[/bold]", border_style="green"))
        self.console.print(Panel(t("restore_guide_body"), title=f"[bold]{t('restore_guide_title')}[/bold]", border_style="cyan"))
        Prompt.ask(f"\n{t('press_enter_finished_restore')}")

    # -------------------------------------------------------------------------
    # FLOW 2: Full step-by-step wizard
    # -------------------------------------------------------------------------
    def flow_full_wizard(self):
        self.show_header(t("full_wizard_title"))

        self.console.print(f"[bold]{t('full_wizard_desc')}[/bold]\n")
        self.console.print(f"  [cyan]{t('wizard_step1')}[/cyan]")
        self.console.print(f"  [cyan]{t('wizard_step2')}[/cyan]")
        self.console.print(f"  [cyan]{t('wizard_step3')}[/cyan]")
        self.console.print(f"  [cyan]{t('wizard_step4')}[/cyan]")
        self.console.print(f"  [cyan]{t('wizard_step5')}[/cyan]\n")

        if not Confirm.ask(t("ask_start_wizard"), default=True):
            return

        # 1. iPhone
        self.console.print()
        self.console.print(Rule(f"[bold cyan]{t('rule_step1_ios')}[/bold cyan]"))
        ios_path = DEFAULT_IOS_BACKUP
        if ios_path.exists():
            self.console.print(f"[green]{t('ios_detected', path=ios_path)}[/green]")
            if not Confirm.ask(t("ask_use_ios"), default=True):
                ios_path = Path(Prompt.ask(t("prompt_ios_path")))
        else:
            ios_path = Path(Prompt.ask(t("prompt_ios_path"), default=str(DEFAULT_IOS_BACKUP)))

        # 2. Android
        self.console.print()
        self.console.print(Rule(f"[bold cyan]{t('rule_step2_andr')}[/bold cyan]"))
        andr_crypt = DEFAULT_ORIGINAL_ANDROID_CRYPT
        if andr_crypt.exists():
            self.console.print(f"[green]{t('andr_detected', path=andr_crypt)}[/green]")
            if not Confirm.ask(t("ask_use_andr"), default=True):
                andr_crypt = Path(Prompt.ask(t("prompt_andr_path")))
        else:
            andr_crypt = Path(Prompt.ask(t("prompt_andr_path"), default=str(DEFAULT_ORIGINAL_ANDROID_CRYPT)))

        # 3. Key
        self.console.print()
        self.console.print(Rule(f"[bold cyan]{t('rule_step3_key')}[/bold cyan]"))
        key = Prompt.ask(t("prompt_hex_key"), default=DEFAULT_KEY)
        self.current_key = key

        # 4. Process
        self.console.print()
        self.console.print(Rule(f"[bold cyan]{t('rule_step4_merge')}[/bold cyan]"))
        out_dir = DEFAULT_OUTPUT_DIR
        out_dir.mkdir(parents=True, exist_ok=True)

        self.execute_full_merge_pipeline(
            ios_path=ios_path,
            android_crypt=andr_crypt,
            key=key,
            output_dir=out_dir,
        )

        # 5. Offer transfer
        if Confirm.ask(f"\n{t('ask_proceed_transfer')}", default=True):
            self.flow_restore_prepared()

    # -------------------------------------------------------------------------
    # FLOW 3: Re-run database merge
    # -------------------------------------------------------------------------
    def flow_remerge(self):
        self.show_header(t("remerge_title"))

        ios_path = Path(Prompt.ask(t("prompt_ios_path_short"), default=str(DEFAULT_IOS_BACKUP)))
        andr_crypt = Path(Prompt.ask(t("prompt_andr_path_short"), default=str(DEFAULT_ORIGINAL_ANDROID_CRYPT)))
        key = Prompt.ask(t("prompt_key_short"), default=self.current_key if self.current_key else None)
        out_dir = Path(Prompt.ask(t("prompt_out_dir"), default=str(DEFAULT_OUTPUT_DIR)))

        self.execute_full_merge_pipeline(ios_path, andr_crypt, key, out_dir)
        Prompt.ask(f"\n{t('press_enter_menu')}")

    # -------------------------------------------------------------------------
    # FLOW 4: Diagnostics and integrity tools
    # -------------------------------------------------------------------------
    def flow_verify_tools(self):
        self.show_header(t("diagnostics_title"))

        target_db = Path(Prompt.ask(t("prompt_db_path"), default=str(DEFAULT_PREPARED_CRYPT15.parent / "msgstore_merged.db")))
        if not target_db.exists():
            self.console.print(f"[bold red]{t('diag_file_not_found', path=target_db)}[/bold red]")
            Prompt.ask(f"\n{t('press_enter_back')}")
            return

        with self.console.status(f"[bold green]{t('diag_running')}[/bold green]"):
            import sqlite3
            conn = sqlite3.connect(target_db)
            cur = conn.cursor()

            cur.execute("PRAGMA quick_check;")
            qc = cur.fetchone()[0]

            cur.execute("PRAGMA foreign_key_check;")
            fk = len(cur.fetchall())

            cur.execute("SELECT count(*) FROM message")
            msg_count = cur.fetchone()[0]

            cur.execute("SELECT count(*) FROM chat")
            chat_count = cur.fetchone()[0]

            cur.execute("SELECT count(*) FROM jid WHERE raw_string LIKE '%status%' AND raw_string NOT IN ('status@broadcast', 'status_me')")
            bad_jids = cur.fetchone()[0]

            conn.close()

        tbl = Table(title=t("diag_table_title", name=target_db.name))
        tbl.add_column(t("diag_test_col"), style="bold")
        tbl.add_column(t("diag_res_col"), style="cyan")

        tbl.add_row(t("diag_btree"), f"[green]{qc}[/green]" if qc == "ok" else f"[red]{qc}[/red]")
        tbl.add_row(t("diag_fks"), f"[green]{t('diag_errors', count=0)}[/green]" if fk == 0 else f"[red]{t('diag_errors', count=fk)}[/red]")
        tbl.add_row(t("diag_total_msgs"), f"{msg_count:,}")
        tbl.add_row(t("diag_total_chats"), f"{chat_count:,}")
        tbl.add_row(t("diag_bad_jids"), f"[green]{bad_jids}[/green]" if bad_jids == 0 else f"[red]{bad_jids}[/red]")

        self.console.print(tbl)
        Prompt.ask(f"\n{t('press_enter_back')}")

    # -------------------------------------------------------------------------
    # FLOW 5: View 64-digit key
    # -------------------------------------------------------------------------
    def flow_show_key(self):
        self.show_header(t("show_key_title"))
        formatted = format_hex_key(self.current_key)
        copy_ok = copy_to_clipboard(self.current_key)

        txt = Text()
        txt.append(f"{formatted}\n\n", style="bold yellow")
        txt.append(f"{t('continuous_string')}\n{self.current_key}\n\n", style="dim")
        if copy_ok:
            txt.append(f"{t('key_copied')}\n", style="green")

        self.console.print(Panel(Align.center(txt), title=f"[bold]{t('key_panel_header')}[/bold]", border_style="yellow"))
        Prompt.ask(f"\n{t('press_enter_menu')}")

    # -------------------------------------------------------------------------
    # FLOW 6: Extract and merge today's new messages
    # -------------------------------------------------------------------------
    def flow_merge_today(self):
        self.show_header(t("merge_today_title"))

        self.console.print(f"[bold]{t('merge_today_desc')}[/bold]\n")

        self.console.print(
            Panel(
                t("today_step1_body"),
                title=f"[bold yellow]{t('today_step1_title')}[/bold yellow]",
                border_style="yellow",
            )
        )
        if not Confirm.ask(f"\n{t('ask_backup_finished')}", default=True):
            self.console.print(f"\n[yellow]{t('backup_first')}[/yellow]")
            Prompt.ask(f"\n{t('press_enter_back')}")
            return

        self.console.print()
        self.console.print(Rule(f"[bold cyan]{t('today_conn_title')}[/bold cyan]"))
        self.console.print(t("today_conn_instructions"))
        device = self.wait_for_android_device()
        if not device:
            return

        self.console.print(f"\n[bold green]{t('device_ready', name=device.display_name)}[/bold green]\n")

        # Locate msgstore.db.crypt on phone
        found_crypt = None
        work_dir = PROJECT_ROOT / "today_backup"
        work_dir.mkdir(parents=True, exist_ok=True)
        local_today_crypt = work_dir / "msgstore.db.crypt15"

        if device.kind == "mtp":
            base_p = Path(device.base_whatsapp_path) / "Databases"
            candidates = list(base_p.glob("msgstore.db.crypt*")) if base_p.exists() else []
            if candidates:
                candidates.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                found_crypt = candidates[0]
                self.console.print(f"[green]{t('today_found_phone', name=found_crypt.name)}[/green]")
                self.copy_file_with_progress(found_crypt, local_today_crypt)
            else:
                self.console.print(f"[yellow]{t('today_mtp_not_found')}[/yellow]")
                p_str = Prompt.ask(t("prompt_today_path"), default=str(local_today_crypt))
                local_today_crypt = Path(p_str)
        elif device.kind == "adb":
            self.console.print(f"[bold]{t('pulling_adb')}[/bold]")
            subprocess.run(
                ["adb", "-s", device.path_or_serial, "pull", f"{device.base_whatsapp_path}/Databases/msgstore.db.crypt15", str(local_today_crypt)],
                capture_output=True,
                text=True,
            )
            if local_today_crypt.exists():
                self.console.print(f"[green]{t('adb_pull_success', name=local_today_crypt.name)}[/green]")

        if not local_today_crypt.exists():
            self.console.print(f"[bold red]{t('today_file_not_found', path=local_today_crypt)}[/bold red]")
            Prompt.ask(f"\n{t('press_enter_back')}")
            return

        key = Prompt.ask(t("prompt_key"), default=self.current_key)
        self.current_key = key

        # Decrypt and merge
        today_decrypted = work_dir / "today_decrypted.db"
        with self.console.status(f"[bold green]{t('decrypting_today')}[/bold green]"):
            try:
                decrypt_android_backup(key_input=key, encrypted_path=local_today_crypt, output_path=today_decrypted)
            except Exception as e:
                self.console.print(f"[bold red]{t('decrypt_error', e=e)}[/bold red]")
                Prompt.ask(f"\n{t('press_enter_back')}")
                return

        target_merged_db = DEFAULT_PREPARED_CRYPT15.parent / "msgstore_merged.db"
        if not target_merged_db.exists():
            self.console.print(f"[bold red]{t('target_merged_missing', path=target_merged_db)}[/bold red]")
            Prompt.ask(f"\n{t('press_enter_back')}")
            return

        shutil.copyfile(target_merged_db, target_merged_db.parent / "msgstore_merged_before_today.db")

        with self.console.status(f"[bold green]{t('merging_today')}[/bold green]"):
            count = merge_incremental_messages(today_decrypted, target_merged_db)

        self.console.print(f"\n[bold green]{t('merge_today_success', count=count)}[/bold green]")

        # Re-encrypt
        with self.console.status(f"[bold green]{t('reencrypting')}[/bold green]"):
            encrypt_android_backup(
                key_input=key,
                decrypted_path=target_merged_db,
                output_path=DEFAULT_PREPARED_CRYPT15,
                reference_path=local_today_crypt,
            )

        self.console.print(f"[bold green]{t('merged_crypt_ready', path=DEFAULT_PREPARED_CRYPT15)}[/bold green]")
        self.console.print(f"\n[bold]{t('merge_today_all_done')}[/bold]")
        Prompt.ask(f"\n{t('press_enter_menu')}")

    # -------------------------------------------------------------------------
    # Helper: Wait for phone
    # -------------------------------------------------------------------------
    def wait_for_android_device(self) -> AndroidDevice | None:
        with self.console.status(f"[bold cyan]{t('waiting_device')}[/bold cyan]") as status:
            dots = 0
            while True:
                devs = detect_android_devices()
                if devs:
                    return devs[0]
                time.sleep(1.5)
                dots += 1
                status.update(f"[bold cyan]{t('waiting_device_dots', dots='.' * (dots % 4 + 1))}[/bold cyan]")

    # -------------------------------------------------------------------------
    # Helper: Copy file with progress
    # -------------------------------------------------------------------------
    def copy_file_with_progress(self, src: Path, dst: Path):
        total_size = src.stat().st_size
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
        )

        with progress:
            task = progress.add_task(t("copying_file_progress", name=src.name), total=total_size)
            chunk_size = 1024 * 1024  # 1 MB
            with open(src, "rb") as f_in, open(dst, "wb") as f_out:
                while True:
                    chunk = f_in.read(chunk_size)
                    if not chunk:
                        break
                    f_out.write(chunk)
                    progress.update(task, advance=len(chunk))

        self.console.print(f"[bold green]{t('copy_success', dest=dst)}[/bold green]")

    # -------------------------------------------------------------------------
    # Helper: Transfer media
    # -------------------------------------------------------------------------
    def transfer_media_files(self, device: AndroidDevice):
        if device.kind == "mtp":
            dest_media = Path(device.base_whatsapp_path) / "Media"
            dest_media.mkdir(parents=True, exist_ok=True)
            self.console.print(f"[bold]{t('transferring_mtp_to', dest=dest_media)}[/bold]")

            all_files = []
            for root, _, files in os.walk(DEFAULT_PREPARED_MEDIA):
                for f in files:
                    s_file = Path(root) / f
                    rel_p = s_file.relative_to(DEFAULT_PREPARED_MEDIA)
                    all_files.append((s_file, dest_media / rel_p))

            progress = Progress(
                SpinnerColumn(),
                TextColumn("[bold cyan]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeRemainingColumn(),
            )

            with progress:
                task = progress.add_task(t("transferring_media_task"), total=len(all_files))
                copied = 0
                for s_f, d_f in all_files:
                    d_f.parent.mkdir(parents=True, exist_ok=True)
                    if not d_f.exists() or d_f.stat().st_size != s_f.stat().st_size:
                        try:
                            shutil.copyfile(s_f, d_f)
                            copied += 1
                        except Exception:
                            pass
                    progress.update(task, advance=1)

            self.console.print(f"[bold green]{t('media_transferred_count', count=copied)}[/bold green]")

        elif device.kind == "adb":
            self.console.print(f"[bold]{t('transferring_adb_task')}[/bold]")
            subprocess.run(
                ["adb", "-s", device.path_or_serial, "push", str(DEFAULT_PREPARED_MEDIA), "/sdcard/Android/media/com.whatsapp/WhatsApp/"],
                check=False,
            )
            self.console.print(f"[bold green]{t('adb_media_success')}[/bold green]")

    # -------------------------------------------------------------------------
    # Helper: Full pipeline execution
    # -------------------------------------------------------------------------
    def execute_full_merge_pipeline(self, ios_path: Path, android_crypt: Path, key: str, output_dir: Path):
        decrypted_db = output_dir / "msgstore_decrypted.db"
        merged_db = output_dir / "msgstore_merged.db"
        merged_crypt = output_dir / "msgstore.db.crypt15"
        media_out = output_dir / "WhatsApp" / "Media"

        # 1. Decrypt
        with self.console.status(f"[bold green]{t('pipeline_decrypting')}[/bold green]"):
            decrypt_android_backup(key_input=key, encrypted_path=android_crypt, output_path=decrypted_db)
            shutil.copyfile(decrypted_db, merged_db)
        self.console.print(f"[green]{t('pipeline_decrypted_success', path=merged_db)}[/green]")

        # 2. Merge
        self.console.print(f"\n[bold]{t('pipeline_merging')}[/bold]")
        extractor = IOSExtractor(ios_path)
        android_db = AndroidDB(merged_db)

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total} msgs"),
        )
        with progress:
            task = progress.add_task(t("pipeline_processing_msgs"), total=76100)

            def on_progress(processed, inserted):
                progress.update(task, completed=processed)

            merger = BackupMerger(
                ios_extractor=extractor,
                android_db=android_db,
                android_media_dir=media_out,
                progress_callback=on_progress,
            )
            summary = merger.run()
            android_db.close()

        tbl = Table(title=t("pipeline_summary_title"))
        tbl.add_column(t("pipeline_summary_metric"), style="bold")
        tbl.add_column(t("pipeline_summary_count"), justify="right", style="green")
        tbl.add_row(t("pipeline_summary_reused"), str(summary.chats_reused))
        tbl.add_row(t("pipeline_summary_created"), str(summary.chats_created))
        tbl.add_row(t("pipeline_summary_inserted"), str(summary.messages_inserted))
        tbl.add_row(t("pipeline_summary_skipped"), str(summary.messages_skipped_duplicate))
        tbl.add_row(t("pipeline_summary_media"), str(summary.media_migrated))
        self.console.print(tbl)

        # 3. Re-encrypt
        with self.console.status(f"[bold green]{t('pipeline_encrypting')}[/bold green]"):
            encrypt_android_backup(
                key_input=key,
                decrypted_path=merged_db,
                output_path=merged_crypt,
                reference_path=android_crypt,
            )
        self.console.print(f"[bold green]{t('pipeline_encrypt_success', path=merged_crypt)}[/bold green]")


def start_wizard(lang: str | None = None):
    if lang:
        set_language(lang)
    elif len(sys.argv) > 1:
        for idx, arg in enumerate(sys.argv):
            if arg in ("--lang", "-l") and idx + 1 < len(sys.argv):
                set_language(sys.argv[idx + 1])
                break
            elif arg.startswith("--lang="):
                set_language(arg.split("=", 1)[1])
                break
    wizard = WizardUI()
    wizard.menu_main()


if __name__ == "__main__":
    start_wizard()
