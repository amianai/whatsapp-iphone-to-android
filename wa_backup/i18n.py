"""Internationalization (i18n) module for WhatsApp Backup Merger.

Supports English (en) and Spanish (es) with automatic system locale detection.
"""

import locale
import os
from typing import Any

_CURRENT_LANG = "en"


def detect_system_language() -> str:
    """Detects default language from environment or system locale."""
    for env_var in ("WA_LANG", "LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(env_var, "").lower()
        if val.startswith("es"):
            return "es"
        elif val.startswith("en"):
            return "en"
    try:
        loc = locale.getdefaultlocale()[0]
        if loc and loc.lower().startswith("es"):
            return "es"
    except Exception:
        pass
    return "en"


def set_language(lang: str):
    """Sets active language ('en' or 'es')."""
    global _CURRENT_LANG
    clean = lang.lower().strip()
    if clean in ("es", "spanish", "espanol", "español"):
        _CURRENT_LANG = "es"
    else:
        _CURRENT_LANG = "en"


def get_language() -> str:
    """Returns current active language code ('en' or 'es')."""
    return _CURRENT_LANG


# Initialize with detected language
_CURRENT_LANG = detect_system_language()

STRINGS = {
    "en": {
        # App Header
        "app_title": "📱 WHATSAPP MIGRATION WIZARD (iOS ➔ Android)",
        "app_subtitle": "Smart Backup Merger • Cryptography & Integrity Resolution",
        "menu_main": "Main Menu",
        # Status Box
        "status_title": "Current System Status",
        "status_backup": "Prepared merged backup",
        "status_backup_ready": "✓ Ready ({size:.1f} MB in output)",
        "status_backup_missing": "Not found (needs generating)",
        "status_device": "Connected Phone",
        "status_no_device": "None detected via USB",
        # Menu Options
        "select_option": "Select an option:",
        "opt_1": "🚀 [RECOMMENDED] Transfer and restore prepared backup on phone",
        "opt_6": "📥 Merge today's incremental messages (Extract from phone & merge)",
        "opt_2": "🔄 Full Step-by-Step Wizard (From scratch)",
        "opt_3": "⚙️ Re-merge databases (iOS ➔ Android ETL without transfer)",
        "opt_4": "🔍 Database integrity diagnostics & key test",
        "opt_5": "📋 View 64-digit encryption key & copy to clipboard",
        "opt_lang": "🌐 Switch language / Cambiar idioma (Current: English)",
        "opt_0": "Exit",
        "option_prompt": "Option",
        "goodbye": "Goodbye!",
        "operation_cancelled": "Operation cancelled by user.",
        "press_enter_continue": "Press Enter to continue",
        "press_enter_back": "Press Enter to return",
        "press_enter_menu": "Press Enter to return to main menu",
        "format_no_key": "(No key registered)",

        # Flow 1: Restore
        "flow_restore_title": "Final Step: Transfer and Restore Prepared Backup",
        "restore_not_found": "Error: Prepared file not found at:",
        "restore_run_opt_3": "Please run option 3 or option 2 to generate it first.",
        "restore_file_found": "✓ Prepared file found: {name} ({size:.1f} MB)",
        "restore_contains_desc": "Contains unified Android + iOS messages with 69% restore bug fix.",
        "ask_today_messages": "Did you activate WhatsApp today and receive new messages you want to preserve?",
        "redirecting_today": "Redirecting to incremental message merge tool...",
        "scoped_storage_warning_title": "⚠️ ATTENTION: CRITICAL PREREQUISITE ON PHONE",
        "scoped_storage_warning_body": (
            "In Android 13/14/15, clearing an app's storage completely WIPES its directory in /Android/media/.\n"
            "Therefore, you MUST clear WhatsApp storage FIRST, BEFORE transferring this file:\n\n"
            "1. On phone: Settings > Apps > WhatsApp > Storage & cache > Clear storage.\n"
            "2. Permissions: Enable Photos & videos, Contacts, Notifications.\n"
            "3. Leave WhatsApp on the welcome screen (DO NOT register yet)."
        ),
        "ask_cleared_storage": "Have you already cleared WhatsApp storage on the phone?",
        "clear_storage_first": "Please do this step on your phone first so the backup won't be erased.",
        "conn_rule_title": "Phone Connection",
        "conn_instructions": "Connect your Android phone to the PC via USB cable.\n(Ensure the screen is unlocked and select 'File transfer / MTP' or enable USB debugging).",
        "waiting_device": "Looking for Android phone via USB...",
        "waiting_device_dots": "Waiting for phone via USB ({dots}) Unlock screen...",
        "device_ready": "✓ Device connected and ready: {name}",
        "mtp_mkdir_error": "Error creating directory on MTP: {e}",
        "unlock_screen_hint": "Make sure your phone screen is unlocked.",
        "copying_to": "Copying backup to: {dest}",
        "copying_file_progress": "Copying {name}",
        "copy_success": "✓ Copied successfully: {dest}",
        "adb_pushing": "Transferring file via ADB push...",
        "adb_push_error": "Error in ADB push: {e}",
        "adb_push_success": "✓ ADB copy completed.",
        "ask_transfer_media": "Do you also want to transfer the {count} media files (photos/videos/audios) to the phone?",
        "skipping_media": "Skipping media for now. All chats and messages will restore to 100% anyway.",
        "key_title": "Your 64-Digit Encryption Key",
        "key_copied": "✓ Key automatically copied to system clipboard.",
        "key_ready": "64-digit key ready to enter.",
        "restore_guide_title": "PHONE RESTORATION GUIDE",
        "restore_guide_body": (
            "[bold cyan]1.[/bold cyan] On your phone, open [bold]WhatsApp[/bold].\n"
            "[bold cyan]2.[/bold cyan] Select language, accept terms, and verify your phone number via SMS/call.\n"
            "[bold cyan]3.[/bold cyan] [bold yellow]CRITICAL![/bold yellow] When WhatsApp prompts for storage & contacts permissions, tap [bold green]CONTINUE[/bold green] and [bold green]ALLOW[/bold green].\n"
            "[bold cyan]4.[/bold cyan] [bold yellow]CRITICAL![/bold yellow] If prompted to check Google Drive for backups, tap [bold red]SKIP[/bold red].\n"
            "[bold cyan]5.[/bold cyan] WhatsApp will show: [bold white]'Backup found'[/bold white] with today's date and size.\n"
            "[bold cyan]6.[/bold cyan] Tap [bold green]Restore[/bold green] and enter the [bold yellow]64-digit key[/bold yellow] shown above.\n"
            "[bold cyan]7.[/bold cyan] The progress bar will advance smoothly past 69% and reach [bold green]100%[/bold green].\n"
            "[bold cyan]8.[/bold cyan] Enter your profile name and enjoy all your unified chats!"
        ),
        "press_enter_finished_restore": "Press Enter once restoration on phone has completed",

        # Flow 2: Full wizard
        "full_wizard_title": "Full Step-by-Step Wizard",
        "full_wizard_desc": "Guides you through the steps to perform a complete migration from scratch:",
        "wizard_step1": "Step 1: Locate or extract iPhone backup",
        "wizard_step2": "Step 2: Locate Android original backup",
        "wizard_step3": "Step 3: 64-digit encryption key",
        "wizard_step4": "Step 4: Smart merge, database sanitation, and re-encryption",
        "wizard_step5": "Step 5: Phone transfer and restoration",
        "ask_start_wizard": "Do you want to start the wizard?",
        "rule_step1_ios": "Step 1: iPhone Backup",
        "ios_detected": "✓ iPhone backup detected: {path}",
        "ask_use_ios": "Use this iPhone backup?",
        "prompt_ios_path": "Enter path to ChatStorage.sqlite or iTunes backup folder",
        "rule_step2_andr": "Step 2: Android Backup",
        "andr_detected": "✓ Original Android backup detected: {path}",
        "ask_use_andr": "Use this Android backup file?",
        "prompt_andr_path": "Enter path to msgstore.db.crypt14/15",
        "rule_step3_key": "Step 3: 64-Digit Encryption Key",
        "prompt_hex_key": "Encryption key (64 hex characters)",
        "rule_step4_merge": "Step 4: Merge and Sanitation",
        "ask_proceed_transfer": "Do you want to proceed immediately to transfer to phone?",

        # Flow 3: Remerge
        "remerge_title": "Re-run Database Merge",
        "prompt_ios_path_short": "iPhone backup path",
        "prompt_andr_path_short": "Original Android backup path (.crypt14/15)",
        "prompt_key_short": "64-digit encryption key",
        "prompt_out_dir": "Output directory",

        # Flow 4: Diagnostics
        "diagnostics_title": "Database Diagnostics & Integrity Tools",
        "prompt_db_path": "Path to SQLite database to examine",
        "diag_file_not_found": "File not found: {path}",
        "diag_running": "Running SQLite verification checks...",
        "diag_table_title": "Diagnostics for {name}",
        "diag_test_col": "Test",
        "diag_res_col": "Result",
        "diag_btree": "B-Tree Integrity (quick_check)",
        "diag_fks": "Foreign Keys (foreign_key_check)",
        "diag_errors": "{count} errors",
        "diag_total_msgs": "Total Messages",
        "diag_total_chats": "Total Chats",
        "diag_bad_jids": "Invalid JIDs (@status)",

        # Flow 5: View Key
        "show_key_title": "64-Digit Encryption Key",
        "continuous_string": "Continuous hex string:",
        "key_panel_header": "WhatsApp Master Key",

        # Flow 6: Merge Today
        "merge_today_title": "Merge Today's New Messages (Incremental)",
        "merge_today_desc": "Rescues messages received today on your phone before restoring, ensuring ZERO message loss.",
        "today_step1_title": "Step 1: Create Backup on Phone",
        "today_step1_body": (
            "Instructions on phone:\n\n"
            "1. Open WhatsApp.\n"
            "2. Settings > Chats > Chat backup.\n"
            "3. Verify End-to-End Encrypted Backup is ON with your 64-digit key.\n"
            "4. Tap BACK UP and wait for it to reach 100%."
        ),
        "ask_backup_finished": "Did you tap Back Up and did it reach 100%?",
        "backup_first": "Please create the backup on the phone first.",
        "today_conn_title": "Phone Connection",
        "today_conn_instructions": "Connect your phone via USB cable (ensure screen is unlocked).",
        "today_found_phone": "✓ Today's backup found on phone: {name}",
        "today_mtp_not_found": "Could not automatically locate file in MTP Databases.",
        "prompt_today_path": "Manual path to today's msgstore.db.crypt15",
        "pulling_adb": "Pulling backup via ADB...",
        "adb_pull_success": "✓ Today's backup extracted via ADB: {name}",
        "today_file_not_found": "Error: Could not retrieve file {path}",
        "prompt_key": "64-digit encryption key",
        "decrypting_today": "Decrypting today's backup...",
        "decrypt_error": "Failed to decrypt today's backup: {e}",
        "target_merged_missing": "Error: Could not find {path}",
        "merging_today": "Merging today's new messages...",
        "merge_today_success": "✓ Incremental merge complete: {count} new messages added.",
        "reencrypting": "Re-encrypting full database to crypt15...",
        "merged_crypt_ready": "✓ Final backup updated at: {path}",
        "merge_today_all_done": "All set! The database now contains your full history + today's new messages.",

        # Helpers
        "transferring_mtp_to": "Transferring files to MTP at: {dest}",
        "transferring_media_task": "Transferring media...",
        "media_transferred_count": "✓ Media transferred: {count} files copied.",
        "transferring_adb_task": "Transferring media via ADB push...",
        "adb_media_success": "✓ Media transferred via ADB.",
        "pipeline_decrypting": "1/3 Decrypting Android database...",
        "pipeline_decrypted_success": "✓ Android decrypted at {path}",
        "pipeline_merging": "2/3 Merging iOS data into Android database...",
        "pipeline_processing_msgs": "Processing messages...",
        "pipeline_summary_title": "Merge Summary",
        "pipeline_summary_metric": "Metric",
        "pipeline_summary_count": "Count",
        "pipeline_summary_reused": "Chats merged (reused existing)",
        "pipeline_summary_created": "New chats created",
        "pipeline_summary_inserted": "New messages inserted",
        "pipeline_summary_skipped": "Duplicate messages skipped",
        "pipeline_summary_media": "Media files migrated",
        "pipeline_encrypting": "3/3 Re-encrypting database for Android...",
        "pipeline_encrypt_success": "✓ Encrypted backup generated: {path}",

        "wa_standard": "Standard WhatsApp",
        "wa_business": "WhatsApp Business",
        "cli_desc": "WhatsApp iOS to Android Backup Merger",
        "cli_wizard_help": "Launch interactive step-by-step TUI wizard",
        "cli_decrypt_help": "Decrypt Android msgstore.db.crypt14/15",
        "cli_encrypt_help": "Re-encrypt msgstore.db to crypt15 format",
        "cli_inspect_ios_help": "Inspect iOS backup",
        "cli_merge_help": "Merge iOS backup into decrypted Android database",
        "cli_pipeline_help": "Full pipeline: decrypt, merge, and re-encrypt",
        "cli_decrypt_panel": "Decrypting Android Backup",
        "cli_decrypt_success": "✓ Decrypted database saved at: {path}",
        "cli_decrypt_error": "Decryption failed: {e}",
        "cli_encrypt_panel": "Re-encrypting Database for Android",
        "cli_encrypt_success": "✓ Encrypted backup generated at: {path}",
        "cli_encrypt_error": "Encryption failed: {e}",
        "cli_inspect_ios": "Inspecting iOS Backup ({type})",
        "cli_inspect_ios_title": "Chats found ({count} total)",
        "cli_inspect_ios_col_pk": "PK",
        "cli_inspect_ios_col_jid": "JID",
        "cli_inspect_ios_col_name": "Name / Contact",
        "cli_inspect_ios_col_msgs": "Messages",
        "cli_inspect_ios_no_name": "(No name)",
        "cli_inspect_ios_more": "... and {count} more chats.",
        "cli_inspect_ios_total_msgs": "Total messages in iOS: {count}",
        "cli_inspect_ios_media_dir": "Media directory: {path}",
        "cli_inspect_ios_error": "Error inspecting iOS: {e}",
        "cli_merge_panel": "Merging iOS Backup into Android Database",
        "cli_merge_progress": "Progress: {processed} messages processed ({inserted} inserted)...",
        "cli_merge_success": "✓ Merge completed successfully.",
        "cli_merge_error": "Error during merge: {e}",
        "cli_pipeline_panel": "WhatsApp Backup Merger: Full Pipeline",
        "cli_pipeline_step1": "1. Decrypting Android database...",
        "cli_pipeline_step2": "2. Merging iOS data into Android database...",
        "cli_pipeline_step3": "3. Re-encrypting combined database for Android...",
        "cli_pipeline_restore_note": (
            "\n[cyan]To restore on Android:\n"
            "1. Copy '{crypt_path}' to your phone at 'Android/media/com.whatsapp/WhatsApp/Databases/msgstore.db.crypt15'\n"
            "2. Copy the media folder '{media_path}' to 'Android/media/com.whatsapp/WhatsApp/Media'\n"
            "3. Log into WhatsApp to detect and restore the local backup.[/cyan]"
        ),
    },
    "es": {
        # App Header
        "app_title": "📱 ASISTENTE DE MIGRACIÓN WHATSAPP (iOS ➔ Android)",
        "app_subtitle": "Fusión Inteligente de Respaldos • Resolución de Integridad y Criptografía",
        "menu_main": "Menú Principal",
        # Status Box
        "status_title": "Estado Actual del Sistema",
        "status_backup": "Respaldo corregido",
        "status_backup_ready": "✓ Disponible ({size:.1f} MB en salida)",
        "status_backup_missing": "No detectado (requiere generar)",
        "status_device": "Teléfono conectado",
        "status_no_device": "Ninguno detectado por USB",
        # Menu Options
        "select_option": "Selecciona una opción:",
        "opt_1": "🚀 [RECOMENDADO] Transferir y restaurar en el teléfono el respaldo ya corregido",
        "opt_6": "📥 Incorporar mensajes nuevos de hoy (Extraer del teléfono y fusionar)",
        "opt_2": "🔄 Asistente Completo Paso a Paso (Flujo completo desde cero)",
        "opt_3": "⚙️ Re-fusionar bases de datos (iOS ➔ Android ETL sin transferir)",
        "opt_4": "🔍 Verificador de integridad de bases de datos y prueba de clave",
        "opt_5": "📋 Ver clave de 64 dígitos y copiar al portapapeles",
        "opt_lang": "🌐 Cambiar idioma / Switch language (Actual: Español)",
        "opt_0": "Salir",
        "option_prompt": "Opción",
        "goodbye": "¡Hasta luego!",
        "operation_cancelled": "Operación cancelada por el usuario.",
        "press_enter_continue": "Presiona Enter para continuar",
        "press_enter_back": "Presiona Enter para volver",
        "press_enter_menu": "Presiona Enter para volver al menú principal",
        "format_no_key": "(Sin clave registrada)",

        # Flow 1: Restore
        "flow_restore_title": "Paso Final: Transferir y Restaurar Respaldo Corregido",
        "restore_not_found": "Error: No se encontró el archivo corregido en:",
        "restore_run_opt_3": "Ejecuta la opción 3 o 2 para generarlo primero.",
        "restore_file_found": "✓ Archivo corregido localizado: {name} ({size:.1f} MB)",
        "restore_contains_desc": "Contiene mensajes de Android + iOS unificados y sin el error del 69%.",
        "ask_today_messages": "¿Activaste WhatsApp hoy y recibiste mensajes nuevos que quieras conservar?",
        "redirecting_today": "Redirigiendo a la herramienta de incorporación de mensajes de hoy...",
        "scoped_storage_warning_title": "⚠️ ATENCIÓN: PASO CRÍTICO PREVIO EN TU TELÉFONO",
        "scoped_storage_warning_body": (
            "En Android 13/14/15, borrar el almacenamiento de una app ELIMINA por completo su carpeta en /Android/media/.\n"
            "Por lo tanto, DEBES borrar almacenamiento PRIMERO, ANTES de copiar este archivo:\n\n"
            "1. En el teléfono: Ajustes > Aplicaciones > WhatsApp > Almacenamiento y caché > Borrar almacenamiento.\n"
            "2. Permisos: Activa Fotos y videos, Contactos, Notificaciones.\n"
            "3. Deja WhatsApp en la pantalla de bienvenida (NO entres a registrar todavía)."
        ),
        "ask_cleared_storage": "¿Ya borraste el almacenamiento de WhatsApp en el teléfono?",
        "clear_storage_first": "Por favor realiza este paso primero para que no se borre el respaldo.",
        "conn_rule_title": "Conexión del Teléfono",
        "conn_instructions": "Conecta tu teléfono a la computadora mediante cable USB.\n(Asegúrate de desbloquear la pantalla y seleccionar 'Transferencia de archivos (MTP)' o habilitar depuración USB).",
        "waiting_device": "Buscando teléfono por USB...",
        "waiting_device_dots": "Esperando teléfono por USB ({dots}) Desbloquea la pantalla...",
        "device_ready": "✓ Dispositivo conectado y listo: {name}",
        "mtp_mkdir_error": "Error al crear carpeta en MTP: {e}",
        "unlock_screen_hint": "Asegúrate de desbloquear la pantalla del teléfono.",
        "copying_to": "Copiando respaldo a: {dest}",
        "copying_file_progress": "Copiando {name}",
        "copy_success": "✓ Copiado exitosamente: {dest}",
        "adb_pushing": "Transfiriendo archivo vía ADB push...",
        "adb_push_error": "Error en ADB push: {e}",
        "adb_push_success": "✓ Copia por ADB completada.",
        "ask_transfer_media": "¿Deseas transferir también los {count} archivos multimedia (fotos/audios/videos) al teléfono?",
        "skipping_media": "Omitiendo multimedia por ahora. Los mensajes se restaurarán al 100% de todos modos.",
        "key_title": "Tu Clave de Cifrado (64 dígitos)",
        "key_copied": "✓ Clave copiada automáticamente al portapapeles del sistema.",
        "key_ready": "Clave de 64 dígitos lista para ingresar.",
        "restore_guide_title": "GUÍA DE RESTAURACIÓN EN EL TELÉFONO",
        "restore_guide_body": (
            "[bold cyan]1.[/bold cyan] En tu teléfono, abre [bold]WhatsApp[/bold].\n"
            "[bold cyan]2.[/bold cyan] Selecciona idioma, acepta términos e ingresa tu número para verificar por SMS/llamada.\n"
            "[bold cyan]3.[/bold cyan] [bold yellow]¡IMPORTANTE![/bold yellow] Cuando WhatsApp solicite permisos de almacenamiento y contactos, toca [bold green]CONTINUAR[/bold green] y [bold green]PERMITIR[/bold green].\n"
            "[bold cyan]4.[/bold cyan] [bold yellow]¡IMPORTANTE![/bold yellow] Si pide buscar copias en Google Drive, toca [bold red]OMITIR[/bold red].\n"
            "[bold cyan]5.[/bold cyan] WhatsApp mostrará la pantalla: [bold white]'Copia de seguridad encontrada'[/bold white] con fecha de hoy y tamaño.\n"
            "[bold cyan]6.[/bold cyan] Toca [bold green]Restaurar[/bold green] e introduce la [bold yellow]clave de 64 dígitos[/bold yellow] mostrada arriba.\n"
            "[bold cyan]7.[/bold cyan] La barra de progreso avanzará limpiamente a través del 69% hasta llegar al [bold green]100%[/bold green].\n"
            "[bold cyan]8.[/bold cyan] Ingresa tu nombre de perfil y ¡disfruta de todos tus chats combinados!"
        ),
        "press_enter_finished_restore": "Presiona Enter cuando hayas finalizado la restauración en tu teléfono",

        # Flow 2: Full wizard
        "full_wizard_title": "Asistente Completo Paso a Paso",
        "full_wizard_desc": "Te guiará en los pasos para realizar la migración completa desde cero:",
        "wizard_step1": "Paso 1: Localización del respaldo de iPhone",
        "wizard_step2": "Paso 2: Localización del respaldo de Android",
        "wizard_step3": "Paso 3: Clave de cifrado de 64 dígitos",
        "wizard_step4": "Paso 4: Fusión inteligente, saneamiento y re-cifrado",
        "wizard_step5": "Paso 5: Transferencia y restauración en el teléfono",
        "ask_start_wizard": "¿Deseas iniciar el proceso?",
        "rule_step1_ios": "Paso 1: Respaldo de iPhone",
        "ios_detected": "✓ Respaldo de iPhone detectado: {path}",
        "ask_use_ios": "¿Usar este respaldo de iPhone?",
        "prompt_ios_path": "Ingresa la ruta a ChatStorage.sqlite o carpeta de respaldo iTunes",
        "rule_step2_andr": "Paso 2: Respaldo de Android",
        "andr_detected": "✓ Respaldo original de Android detectado: {path}",
        "ask_use_andr": "¿Usar este archivo de Android?",
        "prompt_andr_path": "Ingresa la ruta a msgstore.db.crypt14/15",
        "rule_step3_key": "Paso 3: Clave de 64 dígitos",
        "prompt_hex_key": "Clave de cifrado (64 caracteres hex)",
        "rule_step4_merge": "Paso 4: Fusión y Saneamiento",
        "ask_proceed_transfer": "¿Deseas proceder inmediatamente a transferir y restaurar en el teléfono?",

        # Flow 3: Remerge
        "remerge_title": "Re-procesar Fusión de Bases de Datos",
        "prompt_ios_path_short": "Ruta del respaldo de iPhone",
        "prompt_andr_path_short": "Ruta del respaldo Android original (.crypt14/15)",
        "prompt_key_short": "Clave de 64 dígitos",
        "prompt_out_dir": "Directorio de salida",

        # Flow 4: Diagnostics
        "diagnostics_title": "Herramientas de Diagnóstico e Integridad",
        "prompt_db_path": "Ruta de la base SQLite a examinar",
        "diag_file_not_found": "Archivo no encontrado: {path}",
        "diag_running": "Ejecutando verificaciones de SQLite...",
        "diag_table_title": "Diagnóstico de {name}",
        "diag_test_col": "Prueba",
        "diag_res_col": "Resultado",
        "diag_btree": "Integridad B-Tree (quick_check)",
        "diag_fks": "Claves Foráneas (foreign_key_check)",
        "diag_errors": "{count} errores",
        "diag_total_msgs": "Total de Mensajes",
        "diag_total_chats": "Total de Chats",
        "diag_bad_jids": "JIDs inválidos (@status)",

        # Flow 5: View Key
        "show_key_title": "Clave de Cifrado de 64 Dígitos",
        "continuous_string": "Cadena continua:",
        "key_panel_header": "Clave Maestra de WhatsApp",

        # Flow 6: Merge Today
        "merge_today_title": "Incorporar Mensajes Nuevos de Hoy (Fusión Incremental)",
        "merge_today_desc": "Rescata los mensajes recibidos hoy en tu teléfono antes de restaurar, garantizando CERO pérdida de datos.",
        "today_step1_title": "Paso 1: Generar Copia en el Teléfono",
        "today_step1_body": (
            "Instrucciones en tu teléfono:\n\n"
            "1. Abre WhatsApp.\n"
            "2. Ajustes > Chats > Copia de seguridad.\n"
            "3. Asegúrate de tener activa la copia cifrada con tu clave de 64 dígitos.\n"
            "4. Toca GUARDAR y espera que llegue al 100%."
        ),
        "ask_backup_finished": "¿Ya pulsaste 'Guardar' y terminó la copia en tu teléfono?",
        "backup_first": "Por favor genera la copia en el teléfono primero.",
        "today_conn_title": "Conexión del Teléfono",
        "today_conn_instructions": "Conecta tu teléfono por cable USB (asegúrate de desbloquear la pantalla).",
        "today_found_phone": "✓ Copia de hoy encontrada en el teléfono: {name}",
        "today_mtp_not_found": "No se encontró automáticamente el archivo en MTP Databases.",
        "prompt_today_path": "Ruta manual al msgstore.db.crypt15 de hoy",
        "pulling_adb": "Copiando respaldo vía ADB pull...",
        "adb_pull_success": "✓ Copia de hoy extraída exitosamente: {name}",
        "today_file_not_found": "Error: No se pudo obtener el archivo {path}",
        "prompt_key": "Clave de cifrado de 64 dígitos",
        "decrypting_today": "Descifrando copia de hoy...",
        "decrypt_error": "Error al descifrar copia de hoy: {e}",
        "target_merged_missing": "Error: No se encontró {path}",
        "merging_today": "Fusionando mensajes nuevos de hoy...",
        "merge_today_success": "✓ Fusión completada: {count} mensajes nuevos incorporados.",
        "reencrypting": "Re-encriptando base de datos completa a crypt15...",
        "merged_crypt_ready": "✓ Respaldo definitivo actualizado en: {path}",
        "merge_today_all_done": "¡Todo listo! Ahora la base de datos contiene todo tu historial + los mensajes de hoy.",

        # Helpers
        "transferring_mtp_to": "Transfiriendo archivos a MTP en: {dest}",
        "transferring_media_task": "Transfiriendo multimedia...",
        "media_transferred_count": "✓ Multimedia transferida: {count} archivos copiados.",
        "transferring_adb_task": "Transfiriendo multimedia vía ADB push...",
        "adb_media_success": "✓ Multimedia transferida por ADB.",
        "pipeline_decrypting": "1/3 Descifrando base de Android...",
        "pipeline_decrypted_success": "✓ Android descifrado en {path}",
        "pipeline_merging": "2/3 Fusionando datos de iOS en la base de Android...",
        "pipeline_processing_msgs": "Procesando mensajes...",
        "pipeline_summary_title": "Resumen de la Fusión",
        "pipeline_summary_metric": "Métrica",
        "pipeline_summary_count": "Cantidad",
        "pipeline_summary_reused": "Chats combinados (existentes)",
        "pipeline_summary_created": "Chats nuevos creados",
        "pipeline_summary_inserted": "Mensajes nuevos insertados",
        "pipeline_summary_skipped": "Mensajes duplicados omitidos",
        "pipeline_summary_media": "Archivos multimedia migrados",
        "pipeline_encrypting": "3/3 Re-cifrando base de datos para Android...",
        "pipeline_encrypt_success": "✓ Archivo cifrado generado: {path}",

        "wa_standard": "WhatsApp Estándar",
        "wa_business": "WhatsApp Business",
        "cli_desc": "Fusionador de respaldos de WhatsApp iOS a Android",
        "cli_wizard_help": "Inicia el asistente interactivo paso a paso (TUI)",
        "cli_decrypt_help": "Descifra msgstore.db.crypt14/15 de Android",
        "cli_encrypt_help": "Re-cifra msgstore.db a formato crypt15",
        "cli_inspect_ios_help": "Inspecciona respaldo de iOS",
        "cli_merge_help": "Fusiona respaldo iOS dentro de base Android descifrada",
        "cli_pipeline_help": "Flujo completo: descifra, fusiona y re-cifra",
        "cli_decrypt_panel": "Descifrando respaldo de Android",
        "cli_decrypt_success": "✓ Base de datos descifrada guardada en: {path}",
        "cli_decrypt_error": "Error al descifrar: {e}",
        "cli_encrypt_panel": "Re-cifrando base de datos para Android",
        "cli_encrypt_success": "✓ Archivo cifrado generado en: {path}",
        "cli_encrypt_error": "Error al cifrar: {e}",
        "cli_inspect_ios": "Inspeccionando respaldo de iOS ({type})",
        "cli_inspect_ios_title": "Chats encontrados ({count} total)",
        "cli_inspect_ios_col_pk": "PK",
        "cli_inspect_ios_col_jid": "JID",
        "cli_inspect_ios_col_name": "Nombre / Contacto",
        "cli_inspect_ios_col_msgs": "Mensajes",
        "cli_inspect_ios_no_name": "(Sin nombre)",
        "cli_inspect_ios_more": "... y {count} chats adicionales.",
        "cli_inspect_ios_total_msgs": "Total de mensajes en iOS: {count}",
        "cli_inspect_ios_media_dir": "Directorio multimedia: {path}",
        "cli_inspect_ios_error": "Error al inspeccionar iOS: {e}",
        "cli_merge_panel": "Fusionando respaldo de iOS dentro de la base de Android",
        "cli_merge_progress": "Progreso: {processed} mensajes procesados ({inserted} insertados)...",
        "cli_merge_success": "✓ Fusión completada con éxito.",
        "cli_merge_error": "Error durante la fusión: {e}",
        "cli_pipeline_panel": "WhatsApp Backup Merger: Pipeline Completo",
        "cli_pipeline_step1": "1. Descifrando base de Android...",
        "cli_pipeline_step2": "2. Uniendo datos de iOS en la base de Android...",
        "cli_pipeline_step3": "3. Re-cifrando base combinada para Android...",
        "cli_pipeline_restore_note": (
            "\n[cyan]Para restaurar en Android:\n"
            "1. Copia '{crypt_path}' a tu teléfono en 'Android/media/com.whatsapp/WhatsApp/Databases/msgstore.db.crypt15'\n"
            "2. Copia la carpeta de multimedia '{media_path}' a 'Android/media/com.whatsapp/WhatsApp/Media'\n"
            "3. Inicia sesión en WhatsApp para que detecte y restaure la copia local.[/cyan]"
        ),
    },
}


def t(key: str, **kwargs: Any) -> str:
    """Translates a message key to the current language."""
    lang_dict = STRINGS.get(_CURRENT_LANG, STRINGS["en"])
    template = lang_dict.get(key) or STRINGS["en"].get(key, key)
    if kwargs:
        try:
            return template.format(**kwargs)
        except Exception:
            return template
    return template
