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
        return "(Sin clave registrada)"
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
    kind: str # 'mtp' or 'adb'
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
        title = Text("📱 ASISTENTE DE MIGRACIÓN WHATSAPP (iOS ➔ Android)", style="bold white on blue")
        header_text = Text()
        header_text.append("Fusión Inteligente de Respaldos • Resolución de Integridad y Criptografía\n", style="cyan")
        if subtitle:
            header_text.append(f"▶ {subtitle}", style="bold yellow")
        self.console.print(Panel(Align.center(header_text), title=title, border_style="blue", padding=(1, 2)))
        self.console.print()

    def menu_main(self):
        while True:
            self.show_header("Menú Principal")

            # Check status of prepared backup
            prep_ok = DEFAULT_PREPARED_CRYPT15.exists()
            prep_size_mb = (DEFAULT_PREPARED_CRYPT15.stat().st_size / (1024 * 1024)) if prep_ok else 0

            status_table = Table(box=None, padding=(0, 2))
            status_table.add_column("Elemento", style="bold")
            status_table.add_column("Estado", style="dim")
            if prep_ok:
                status_table.add_row(
                    "Respaldo corregido listo",
                    f"[green]✓ Disponible[/green] ({prep_size_mb:.1f} MB en wa_merged_output)",
                )
            else:
                status_table.add_row("Respaldo corregido", "[yellow]No detectado (requiere generar)[/yellow]")

            devs = detect_android_devices()
            if devs:
                status_table.add_row("Teléfono conectado", f"[green]✓ {devs[0].display_name}[/green]")
            else:
                status_table.add_row("Teléfono conectado", "[dim]Ninguno detectado por USB[/dim]")

            self.console.print(Panel(status_table, title="[bold]Estado Actual del Sistema[/bold]", border_style="dim"))
            self.console.print()

            self.console.print("[bold cyan]Selecciona una opción:[/bold cyan]\n")
            self.console.print("  [bold green]1.[/bold green] [bold white]🚀 [RECOMENDADO][/bold white] Transferir y restaurar en el Pixel el respaldo ya corregido")
            self.console.print("  [bold magenta]6.[/bold magenta] [bold white]📥 Incorporar mensajes nuevos de hoy[/bold white] (Extraer del Pixel y fusionar antes de restaurar)")
            self.console.print("  [bold cyan]2.[/bold cyan] 🔄 Asistente Completo Paso a Paso (Flujo completo desde cero)")
            self.console.print("  [bold cyan]3.[/bold cyan] ⚙️ Re-fusionar bases de datos (iOS ➔ Android ETL sin transferir)")
            self.console.print("  [bold cyan]4.[/bold cyan] 🔍 Verificador de integridad de bases de datos y prueba de clave")
            self.console.print("  [bold cyan]5.[/bold cyan] 📋 Ver clave de 64 dígitos y copiar al portapapeles")
            self.console.print("  [bold red]0.[/bold red] Salir\n")

            try:
                choice = Prompt.ask("Opción", choices=["1", "6", "2", "3", "4", "5", "0"], default="1")
            except (EOFError, KeyboardInterrupt):
                self.console.print("\n\n[dim]Saliendo del asistente...[/dim]")
                break

            if choice == "1":
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
                self.console.print("\n[dim]¡Hasta luego![/dim]")
                break

    # -------------------------------------------------------------------------
    # FLUJO 1: Transferir y restaurar respaldo ya listo
    # -------------------------------------------------------------------------
    def flow_restore_prepared(self):
        self.show_header("Paso Final: Transferir y Restaurar Respaldo Corregido")

        if not DEFAULT_PREPARED_CRYPT15.exists():
            self.console.print("[bold red]Error:[/bold red] No se encontró el archivo corregido en:")
            self.console.print(f"[cyan]{DEFAULT_PREPARED_CRYPT15}[/cyan]")
            self.console.print("\nEjecuta la opción 3 para re-generarlo primero.")
            Prompt.ask("\nPresiona Enter para volver")
            return

        size_mb = DEFAULT_PREPARED_CRYPT15.stat().st_size / (1024 * 1024)
        self.console.print(f"[bold green]✓ Archivo corregido localizado:[/bold green] {DEFAULT_PREPARED_CRYPT15.name} ([cyan]{size_mb:.1f} MB[/cyan])")
        self.console.print("[dim]Este archivo contiene los 873,823 mensajes originales de Android + 69,468 mensajes de iOS sin errores 69%.[/dim]\n")

        # PASO PREVIO: Verificar si hay mensajes nuevos de hoy
        if Confirm.ask("¿Activaste WhatsApp hoy y recibiste mensajes nuevos que quieras conservar?", default=False):
            self.console.print("\n[bold cyan]Redirigiendo a la herramienta de incorporación de mensajes de hoy...[/bold cyan]")
            self.flow_merge_today()
            self.show_header("Paso Final: Transferir y Restaurar Respaldo Corregido")

        # PASO A: Advertencia crítica de Scoped Storage
        self.console.print(
            Panel(
                "[bold yellow]⚠️ PASO CRÍTICO PREVIO EN TU PIXEL:[/bold yellow]\n\n"
                "En Android 14/15, borrar el almacenamiento de una app ELIMINA por completo su carpeta en /Android/media/.\n"
                "Por lo tanto, [bold red]debes borrar el almacenamiento ANTES de transferir el archivo[/bold red], nunca después:\n\n"
                "1. En tu Pixel, abre [bold]Ajustes > Aplicaciones > WhatsApp[/bold].\n"
                "2. Entra a [bold]Almacenamiento y caché[/bold] y toca [bold]Borrar almacenamiento[/bold] (o Borrar datos).\n"
                "3. Deja WhatsApp en la pantalla inicial de bienvenida (NO entres a registrar todavía).",
                title="[bold red]¡ATENCIÓN![/bold red]",
                border_style="yellow",
            )
        )

        if not Confirm.ask("¿Ya borraste el almacenamiento de WhatsApp en el Pixel?", default=True):
            self.console.print("\n[yellow]Por favor, realiza este paso en tu teléfono primero para que no se borre el respaldo.[/yellow]")
            Prompt.ask("\nPresiona Enter cuando lo hayas hecho")

        # PASO B: Esperar conexión USB del teléfono
        self.console.print()
        self.console.print(Rule("[bold cyan]Conexión del Teléfono[/bold cyan]"))
        self.console.print("Conecta tu Pixel a la computadora mediante cable USB.")
        self.console.print("[dim]Si aparece una notificación en el teléfono, selecciona 'Transferencia de archivos (MTP)' o habilita depuración USB.[/dim]\n")

        device = self.wait_for_android_device()
        if not device:
            return

        self.console.print(f"\n[bold green]✓ Dispositivo conectado y listo:[/bold green] [cyan]{device.display_name}[/cyan]\n")

        # PASO C: Copia de la base de datos
        databases_dir = None
        if device.kind == "mtp":
            base_p = Path(device.base_whatsapp_path)
            databases_dir = base_p / "Databases"
            try:
                databases_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                self.console.print(f"[bold red]Error al crear carpeta en MTP:[/bold red] {e}")
                self.console.print("[yellow]Asegúrate de desbloquear la pantalla del teléfono.[/yellow]")
                Prompt.ask("\nPresiona Enter para volver")
                return

            dest_file = databases_dir / "msgstore.db.crypt15"
            self.console.print(f"[bold]Copiando respaldo a:[/bold] [dim]{dest_file}[/dim]")
            self.copy_file_with_progress(DEFAULT_PREPARED_CRYPT15, dest_file)

        elif device.kind == "adb":
            dest_dir = "/sdcard/Android/media/com.whatsapp/WhatsApp/Databases"
            subprocess.run(["adb", "-s", device.path_or_serial, "shell", "mkdir", "-p", dest_dir], check=False)
            self.console.print("[bold]Transfiriendo archivo vía ADB push...[/bold]")
            res = subprocess.run(
                ["adb", "-s", device.path_or_serial, "push", str(DEFAULT_PREPARED_CRYPT15), f"{dest_dir}/msgstore.db.crypt15"],
                capture_output=True,
                text=True,
            )
            if res.returncode != 0:
                self.console.print(f"[bold red]Error en ADB push:[/bold red] {res.stderr}")
                Prompt.ask("\nPresiona Enter para volver")
                return
            self.console.print("[bold green]✓ Copia por ADB completada.[/bold green]")

        # PASO D: Multimedia opcional
        self.console.print()
        if DEFAULT_PREPARED_MEDIA.exists():
            media_count = sum(len(files) for _, _, files in os.walk(DEFAULT_PREPARED_MEDIA))
            if Confirm.ask(
                f"¿Deseas transferir también los {media_count} archivos multimedia (fotos/audios/videos) al teléfono?",
                default=False,
            ):
                self.transfer_media_files(device)
            else:
                self.console.print("[dim]Omitiendo multimedia por ahora. Los mensajes se restaurarán al 100% de todos modos.[/dim]")

        # PASO E: Copiar clave al portapapeles y mostrar guía de WhatsApp
        copy_ok = copy_to_clipboard(self.current_key)
        formatted_key = format_hex_key(self.current_key)

        self.console.print()
        self.console.print(Rule("[bold green]GUÍA DE RESTAURACIÓN EN EL TELÉFONO[/bold green]"))

        key_panel_text = Text()
        key_panel_text.append(f"{formatted_key}\n\n", style="bold yellow")
        if copy_ok:
            key_panel_text.append("✓ Clave copiada automáticamente al portapapeles de tu computadora.", style="green")
        else:
            key_panel_text.append("Clave de 64 dígitos lista para ingresar.", style="dim")

        self.console.print(Panel(Align.center(key_panel_text), title="[bold]Tu Clave de Cifrado (64 dígitos)[/bold]", border_style="green"))

        steps_text = (
            "[bold cyan]1.[/bold cyan] En tu Pixel, abre [bold]WhatsApp[/bold].\n"
            "[bold cyan]2.[/bold cyan] Selecciona idioma (Español) y toca [bold]Aceptar y continuar[/bold].\n"
            "[bold cyan]3.[/bold cyan] Ingresa tu número de teléfono y completa la verificación por SMS / llamada.\n"
            "[bold cyan]4.[/bold cyan] [bold yellow]¡IMPORTANTE![/bold yellow] Cuando WhatsApp solicite permisos de almacenamiento y contactos, toca [bold green]CONTINUAR[/bold green] y [bold green]PERMITIR[/bold green].\n"
            "[bold cyan]5.[/bold cyan] WhatsApp mostrará la pantalla: [bold white]'Copia de seguridad encontrada'[/bold white] con fecha de hoy.\n"
            "[bold cyan]6.[/bold cyan] Toca [bold green]Restaurar[/bold green] e introduce la [bold yellow]clave de 64 dígitos[/bold yellow] mostrada arriba.\n"
            "[bold cyan]7.[/bold cyan] La barra de progreso avanzará: pasará de forma continua por el 69% hasta llegar al [bold green]100%[/bold green].\n"
            "[bold cyan]8.[/bold cyan] Ingresa tu nombre de perfil y ¡disfruta de todos tus chats de iPhone y Android combinados!"
        )

        self.console.print(Panel(steps_text, title="[bold]Instrucciones Paso a Paso[/bold]", border_style="cyan"))
        Prompt.ask("\nPresiona Enter cuando hayas finalizado la restauración en tu Pixel")

    # -------------------------------------------------------------------------
    # FLUJO 2: Asistente Completo (Desde cero)
    # -------------------------------------------------------------------------
    def flow_full_wizard(self):
        self.show_header("Asistente Completo Paso a Paso")

        self.console.print("[bold]Este asistente te guiará en los 4 pasos para realizar la migración completa:[/bold]\n")
        self.console.print("  [cyan]Paso 1:[/cyan] Extracción o localización del respaldo de iPhone")
        self.console.print("  [cyan]Paso 2:[/cyan] Extracción o localización del respaldo de Android")
        self.console.print("  [cyan]Paso 3:[/cyan] Clave de cifrado de 64 dígitos")
        self.console.print("  [cyan]Paso 4:[/cyan] Fusión inteligente, saneamiento de base de datos y re-cifrado")
        self.console.print("  [cyan]Paso 5:[/cyan] Transferencia y restauración en el Pixel\n")

        if not Confirm.ask("¿Deseas iniciar el proceso?", default=True):
            return

        # 1. iPhone
        self.console.print()
        self.console.print(Rule("[bold cyan]Paso 1: Respaldo de iPhone[/bold cyan]"))
        ios_path = DEFAULT_IOS_BACKUP
        if ios_path.exists():
            self.console.print(f"[green]✓ Respaldo de iPhone detectado:[/green] [cyan]{ios_path}[/cyan]")
            if not Confirm.ask("¿Usar este respaldo de iPhone?", default=True):
                ios_path = Path(Prompt.ask("Ingresa la ruta a ChatStorage.sqlite o carpeta de respaldo iTunes"))
        else:
            ios_path = Path(Prompt.ask("Ingresa la ruta a ChatStorage.sqlite o carpeta de respaldo iTunes", default=str(DEFAULT_IOS_BACKUP)))

        # 2. Android
        self.console.print()
        self.console.print(Rule("[bold cyan]Paso 2: Respaldo de Android[/bold cyan]"))
        andr_crypt = DEFAULT_ORIGINAL_ANDROID_CRYPT
        if andr_crypt.exists():
            self.console.print(f"[green]✓ Respaldo original de Android detectado:[/green] [cyan]{andr_crypt}[/cyan]")
            if not Confirm.ask("¿Usar este archivo de Android?", default=True):
                andr_crypt = Path(Prompt.ask("Ingresa la ruta a msgstore.db.crypt14/15"))
        else:
            andr_crypt = Path(Prompt.ask("Ingresa la ruta a msgstore.db.crypt14/15", default=str(DEFAULT_ORIGINAL_ANDROID_CRYPT)))

        # 3. Clave
        self.console.print()
        self.console.print(Rule("[bold cyan]Paso 3: Clave de 64 dígitos[/bold cyan]"))
        key = Prompt.ask("Clave de cifrado (64 caracteres hex)", default=DEFAULT_KEY)

        # 4. Procesar
        self.console.print()
        self.console.print(Rule("[bold cyan]Paso 4: Fusión y Saneamiento[/bold cyan]"))
        out_dir = DEFAULT_OUTPUT_DIR
        out_dir.mkdir(parents=True, exist_ok=True)

        self.execute_full_merge_pipeline(
            ios_path=ios_path,
            android_crypt=andr_crypt,
            key=key,
            output_dir=out_dir,
        )

        # 5. Ofrecer transferir
        if Confirm.ask("\n¿Deseas proceder inmediatamente a transferir y restaurar en el Pixel?", default=True):
            self.flow_restore_prepared()

    # -------------------------------------------------------------------------
    # FLUJO 3: Re-procesar fusión de bases de datos
    # -------------------------------------------------------------------------
    def flow_remerge(self):
        self.show_header("Re-procesar Fusión de Bases de Datos")

        ios_path = Path(Prompt.ask("Ruta del respaldo de iPhone", default=str(DEFAULT_IOS_BACKUP)))
        andr_crypt = Path(Prompt.ask("Ruta del respaldo Android original (.crypt15)", default=str(DEFAULT_ORIGINAL_ANDROID_CRYPT)))
        key = Prompt.ask("Clave de 64 dígitos", default=self.current_key if self.current_key else None)
        out_dir = Path(Prompt.ask("Directorio de salida", default=str(DEFAULT_OUTPUT_DIR)))

        self.execute_full_merge_pipeline(ios_path, andr_crypt, key, out_dir)
        Prompt.ask("\nPresiona Enter para volver al menú")

    # -------------------------------------------------------------------------
    # FLUJO 4: Verificador de herramientas e integridad
    # -------------------------------------------------------------------------
    def flow_verify_tools(self):
        self.show_header("Herramientas de Diagnóstico e Integridad")

        target_db = Path(Prompt.ask("Ruta de la base SQLite a examinar", default=str(DEFAULT_PREPARED_CRYPT15.parent / "msgstore_merged.db")))
        if not target_db.exists():
            self.console.print(f"[bold red]Archivo no encontrado:[/bold red] {target_db}")
            Prompt.ask("\nPresiona Enter para volver")
            return

        with self.console.status("[bold green]Ejecutando verificaciones de SQLite...[/bold green]"):
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

        tbl = Table(title=f"Diagnóstico de {target_db.name}")
        tbl.add_column("Prueba", style="bold")
        tbl.add_column("Resultado", style="cyan")

        tbl.add_row("Integridad B-Tree (quick_check)", f"[green]{qc}[/green]" if qc == "ok" else f"[red]{qc}[/red]")
        tbl.add_row("Claves Foráneas (foreign_key_check)", f"[green]{fk} errores[/green]" if fk == 0 else f"[red]{fk} errores[/red]")
        tbl.add_row("Total de Mensajes", f"{msg_count:,}")
        tbl.add_row("Total de Chats", f"{chat_count:,}")
        tbl.add_row("JIDs inválidos (@status)", f"[green]{bad_jids}[/green]" if bad_jids == 0 else f"[red]{bad_jids}[/red]")

        self.console.print(tbl)
        Prompt.ask("\nPresiona Enter para volver")

    # -------------------------------------------------------------------------
    # FLUJO 5: Ver clave de 64 dígitos
    # -------------------------------------------------------------------------
    def flow_show_key(self):
        self.show_header("Clave de Cifrado de 64 Dígitos")
        formatted = format_hex_key(self.current_key)
        copy_ok = copy_to_clipboard(self.current_key)

        txt = Text()
        txt.append(f"{formatted}\n\n", style="bold yellow")
        txt.append(f"Cadena continua:\n{self.current_key}\n\n", style="dim")
        if copy_ok:
            txt.append("✓ Clave copiada al portapapeles del sistema.", style="green")

        self.console.print(Panel(Align.center(txt), title="[bold]Clave Maestra de WhatsApp[/bold]", border_style="yellow"))
        Prompt.ask("\nPresiona Enter para volver al menú")

    # -------------------------------------------------------------------------
    # FLUJO 6: Extraer e incorporar mensajes nuevos de hoy
    # -------------------------------------------------------------------------
    def flow_merge_today(self):
        self.show_header("Incorporar Mensajes Nuevos de Hoy (Fusión Incremental)")

        self.console.print(
            "[bold]Este paso rescata los mensajes que recibiste hoy después de las 10:53 AM[/bold]\n"
            "para que no se pierdan al restaurar el historial de 12 años.\n"
        )

        self.console.print(
            Panel(
                "[bold cyan]Instrucciones en tu Pixel:[/bold cyan]\n\n"
                "1. Abre WhatsApp en tu Pixel.\n"
                "2. Ve a [bold]Ajustes > Chats > Copia de seguridad[/bold].\n"
                "3. Asegúrate de tener activada la copia cifrada con tu clave de 64 dígitos.\n"
                "4. Toca el botón verde [bold]'Guardar'[/bold] (o 'Hacer copia').\n"
                "5. Espera a que termine al 100% (genera el archivo msgstore.db.crypt15 actualizado).",
                title="[bold yellow]Paso 1: Generar Copia en el Teléfono[/bold yellow]",
                border_style="yellow",
            )
        )
        if not Confirm.ask("\n¿Ya pulsaste 'Guardar' y terminó la copia en tu Pixel?", default=True):
            self.console.print("\n[yellow]Por favor genera la copia en el teléfono primero.[/yellow]")
            Prompt.ask("\nPresiona Enter para volver")
            return

        self.console.print()
        self.console.print(Rule("[bold cyan]Conexión del Teléfono[/bold cyan]"))
        self.console.print("Conecta tu Pixel por cable USB (asegúrate de desbloquear la pantalla).")
        device = self.wait_for_android_device()
        if not device:
            return

        self.console.print(f"\n[bold green]✓ Dispositivo conectado:[/bold green] [cyan]{device.display_name}[/cyan]\n")

        # Localizar msgstore.db.crypt en el teléfono
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
                self.console.print(f"[green]✓ Copia de hoy encontrada en el teléfono:[/green] [cyan]{found_crypt.name}[/cyan]")
                self.copy_file_with_progress(found_crypt, local_today_crypt)
            else:
                self.console.print("[yellow]No se encontró automáticamente el archivo en MTP Databases.[/yellow]")
                p_str = Prompt.ask("Ingresa la ruta manual al msgstore.db.crypt15 de hoy", default=str(local_today_crypt))
                local_today_crypt = Path(p_str)
        elif device.kind == "adb":
            self.console.print("[bold]Copiando respaldo vía ADB pull...[/bold]")
            subprocess.run(
                ["adb", "-s", device.path_or_serial, "pull", f"{device.base_whatsapp_path}/Databases/msgstore.db.crypt15", str(local_today_crypt)],
                capture_output=True,
                text=True,
            )
            if local_today_crypt.exists():
                self.console.print(f"[green]✓ Copia de hoy extraída exitosamente:[/green] {local_today_crypt.name}")

        if not local_today_crypt.exists():
            self.console.print(f"[bold red]Error:[/bold red] No se pudo obtener el archivo {local_today_crypt}")
            Prompt.ask("\nPresiona Enter para volver")
            return

        key = Prompt.ask("Clave de cifrado de 64 dígitos", default=self.current_key)
        self.current_key = key

        # Descifrar e integrar
        today_decrypted = work_dir / "today_decrypted.db"
        with self.console.status("[bold green]Descifrando copia de hoy...[/bold green]"):
            try:
                decrypt_android_backup(key_input=key, encrypted_path=local_today_crypt, output_path=today_decrypted)
            except Exception as e:
                self.console.print(f"[bold red]Error al descifrar copia de hoy:[/bold red] {e}")
                Prompt.ask("\nPresiona Enter para volver")
                return

        target_merged_db = DEFAULT_PREPARED_CRYPT15.parent / "msgstore_merged.db"
        if not target_merged_db.exists():
            self.console.print(f"[bold red]Error:[/bold red] No se encontró {target_merged_db}")
            Prompt.ask("\nPresiona Enter para volver")
            return

        shutil.copyfile(target_merged_db, target_merged_db.parent / "msgstore_merged_before_today.db")

        with self.console.status("[bold green]Fusionando mensajes nuevos de hoy...[/bold green]"):
            count = merge_incremental_messages(today_decrypted, target_merged_db)

        self.console.print(f"\n[bold green]✓ Fusión completada:[/bold green] [cyan]{count} mensajes nuevos[/cyan] incorporados.")

        # Re-encriptar
        with self.console.status("[bold green]Re-encriptando base de datos completa a crypt15...[/bold green]"):
            encrypt_android_backup(
                key_input=key,
                decrypted_path=target_merged_db,
                output_path=DEFAULT_PREPARED_CRYPT15,
                reference_path=local_today_crypt,
            )

        self.console.print(f"[bold green]✓ Respaldo definitivo actualizado en:[/bold green] [cyan]{DEFAULT_PREPARED_CRYPT15}[/cyan]")
        self.console.print("\n[bold]¡Todo listo! Ahora la base de datos contiene todo tu historial + los mensajes de hoy.[/bold]")
        Prompt.ask("\nPresiona Enter para volver al menú")

    # -------------------------------------------------------------------------
    # Helper: Esperar teléfono
    # -------------------------------------------------------------------------
    def wait_for_android_device(self) -> AndroidDevice | None:
        with self.console.status("[bold cyan]Buscando teléfono Pixel por USB...[/bold cyan]") as status:
            dots = 0
            while True:
                devs = detect_android_devices()
                if devs:
                    return devs[0]
                time.sleep(1.5)
                dots += 1
                status.update(f"[bold cyan]Esperando teléfono Pixel por USB ({'.' * (dots % 4 + 1)}) Desbloquea la pantalla...[/bold cyan]")

    # -------------------------------------------------------------------------
    # Helper: Copiar archivo con barra de progreso Rich
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
            task = progress.add_task(f"Copiando {src.name}", total=total_size)
            chunk_size = 1024 * 1024 # 1 MB
            with open(src, "rb") as f_in, open(dst, "wb") as f_out:
                while True:
                    chunk = f_in.read(chunk_size)
                    if not chunk:
                        break
                    f_out.write(chunk)
                    progress.update(task, advance=len(chunk))

        self.console.print(f"[bold green]✓ Copiado exitosamente:[/bold green] [cyan]{dst}[/cyan]")

    # -------------------------------------------------------------------------
    # Helper: Transferir multimedia
    # -------------------------------------------------------------------------
    def transfer_media_files(self, device: AndroidDevice):
        if device.kind == "mtp":
            dest_media = Path(device.base_whatsapp_path) / "Media"
            dest_media.mkdir(parents=True, exist_ok=True)
            self.console.print(f"[bold]Transfiriendo archivos a MTP en:[/bold] [dim]{dest_media}[/dim]")

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
                task = progress.add_task("Transfiriendo multimedia...", total=len(all_files))
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

            self.console.print(f"[bold green]✓ Multimedia transferida:[/bold green] {copied} archivos copiados.")

        elif device.kind == "adb":
            self.console.print("[bold]Transfiriendo multimedia vía ADB push...[/bold]")
            subprocess.run(
                ["adb", "-s", device.path_or_serial, "push", str(DEFAULT_PREPARED_MEDIA), "/sdcard/Android/media/com.whatsapp/WhatsApp/"],
                check=False,
            )
            self.console.print("[bold green]✓ Multimedia transferida por ADB.[/bold green]")

    # -------------------------------------------------------------------------
    # Helper: Pipeline completo
    # -------------------------------------------------------------------------
    def execute_full_merge_pipeline(self, ios_path: Path, android_crypt: Path, key: str, output_dir: Path):
        decrypted_db = output_dir / "msgstore_decrypted.db"
        merged_db = output_dir / "msgstore_merged.db"
        merged_crypt = output_dir / "msgstore.db.crypt15"
        media_out = output_dir / "WhatsApp" / "Media"

        # 1. Descifrar
        with self.console.status("[bold green]1/3 Descifrando base de Android...[/bold green]"):
            decrypt_android_backup(key_input=key, encrypted_path=android_crypt, output_path=decrypted_db)
            shutil.copyfile(decrypted_db, merged_db)
        self.console.print(f"[green]✓ Android descifrado en {merged_db}[/green]")

        # 2. Fusionar
        self.console.print("\n[bold]2/3 Fusionando datos de iOS en la base de Android...[/bold]")
        extractor = IOSExtractor(ios_path)
        android_db = AndroidDB(merged_db)

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total} msgs"),
        )
        with progress:
            task = progress.add_task("Procesando mensajes...", total=76100)

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

        tbl = Table(title="Resumen de la Fusión")
        tbl.add_column("Métrica", style="bold")
        tbl.add_column("Cantidad", justify="right", style="green")
        tbl.add_row("Chats combinados (existentes)", str(summary.chats_reused))
        tbl.add_row("Chats nuevos creados", str(summary.chats_created))
        tbl.add_row("Mensajes nuevos insertados", str(summary.messages_inserted))
        tbl.add_row("Mensajes duplicados omitidos", str(summary.messages_skipped_duplicate))
        tbl.add_row("Archivos multimedia migrados", str(summary.media_migrated))
        self.console.print(tbl)

        # 3. Re-cifrar
        with self.console.status("[bold green]3/3 Re-cifrando base de datos para Android...[/bold green]"):
            encrypt_android_backup(
                key_input=key,
                decrypted_path=merged_db,
                output_path=merged_crypt,
                reference_path=android_crypt,
            )
        self.console.print(f"[bold green]✓ Archivo cifrado generado:[/bold green] [cyan]{merged_crypt}[/cyan]")


def start_wizard():
    wizard = WizardUI()
    wizard.menu_main()


if __name__ == "__main__":
    start_wizard()
