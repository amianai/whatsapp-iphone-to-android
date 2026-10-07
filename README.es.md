# 📱 WhatsApp Backup Merger (iOS ➔ Android)

<p align="center">
  <a href="README.md"><b>🇺🇸 English</b></a> • <a href="README.es.md"><b>🇪🇸 Español</b></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12+-blue.svg?style=flat-square&logo=python" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/WhatsApp-Crypt14%20%2F%20Crypt15-25D366.svg?style=flat-square&logo=whatsapp" alt="Crypt14 / Crypt15">
  <img src="https://img.shields.io/badge/Licencia-MIT-green.svg?style=flat-square&logo=open-source-initiative" alt="Licencia MIT">
  <img src="https://img.shields.io/badge/Pruebas-Pasando-brightgreen.svg?style=flat-square" alt="Pruebas Pasando">
</p>

Una herramienta libre y de código abierto diseñada para **fusionar el historial de WhatsApp de un iPhone (iOS) dentro de una copia existente de Android**, uniendo historiales de chat de varios años en una única base de datos limpia y lista para ser restaurada en Android — **sin sobrescribir tus chats existentes y resolviendo el infame error del 69% al restaurar.**

---

## 💡 ¿Por qué existe este proyecto?

1. **La herramienta oficial sobrescribe los datos:** La migración oficial de WhatsApp de iPhone a Android solo funciona si el teléfono Android está recién formateado o de fábrica. Si ya llevabas semanas o meses usando Android y quieres traer tus 10 años de chats de iPhone, la herramienta oficial te borra todo lo que tengas en Android.
2. **Las aplicaciones de pago son caras e invasivas:** Los programas comerciales privativos cobran entre $30 y $50 USD anuales, piden permisos root o controladores sospechosos y procesan tus conversaciones privadas descifradas en servidores cerrados.
3. **El infame "Error del 69%":** La gran mayoría de scripts antiguos de la comunidad fallan en versiones modernas de WhatsApp. Durante la restauración en Android, el progreso se congela o la app crashea al llegar exactamente al **69%**, arruinando la restauración.

---

## 🛠️ Cómo se resolvió el "Error del 69%"

Al llegar aproximadamente al ~69% del progreso, WhatsApp para Android concluye la inserción secuencial de mensajes y ejecuta tres tareas internas críticas:
1. Validación de contactos y JIDs para construir la lista de hilos de chat (`JidFactory`).
2. Reconstrucción e indexación de metadatos multimedia (`message_media`).
3. Detección de colisiones de hilos y migración de cuentas múltiples (`local_chat_db_lid_migration`).

Esta herramienta elimina de raíz todas las causas técnicas que provocan el cierre en el 69%:

| Causa de Falla | Qué Ocurría | Cómo lo Solucionamos |
| :--- | :--- | :--- |
| **JIDs `@status` Inválidos** | iOS guarda las historias de contactos en `ZWACHATSESSION` (`ZSESSIONTYPE = 3`). Android crashea con `InvalidJidException: Invalid server status`. | Se filtran por completo las sesiones de estado y se fuerzan servidores de JID válidos para Android (`s.whatsapp.net`, `g.us`, `status@broadcast`). |
| **Colisiones de Hilos LID vs Teléfono** | En iOS moderno, los chats 1 a 1 usan identificadores opacos `@lid` en vez de números telefónicos. Android crea hilos duplicados para contactos ya existentes y colapsa. | Se resuelven automáticamente los chats `@lid` a su número telefónico real canónico (`ZCONTACTIDENTIFIER`) y se unifican en los chats existentes de Android. |
| **Filas Faltantes en `message_media`** | Si una foto/video de iPhone ya no existía en disco, los scripts antiguos no creaban fila en `message_media`. Android lanza `NullPointerException` al indexar la multimedia. | Se asegura el 100% de cobertura en `message_media` para cada mensaje multimedia con flags de transferencia seguros y hashes de respaldo. |
| **Prefijo de Rutas Relativas** | Android requiere que las rutas de multimedia sean relativas a su carpeta raíz (ej. `Media/WhatsApp Images/...`). | Se sanitizan y anteponen automáticamente los prefijos `Media/` en todas las rutas. |
| **Columnas de Cuentas Múltiples y Control** | Las versiones modernas de WhatsApp requieren `account_jid_row_id = jid_row_id` y valores no nulos en flags de control (`broadcast`, `origin`, `sort_id`). | Se pueblan todos los campos según el esquema esperado por las vistas nativas `available_message_view` y `chat_view`. |

---

## ✨ Características Principales

* **🔄 Fusión Bidireccional de Historial:** Une chats individuales y grupales de iPhone (`ChatStorage.sqlite`) en Android (`msgstore.db`).
* **⏱️ Conversión de Epochs y Fechas:** Convierte marcas de tiempo Apple Core Data Cocoa (desde 2001) a marcas Unix en milisegundos (desde 1970).
* **🧹 Deduplicación Inteligente:** Detecta mensajes repetidos mediante `stanza_id` (`key_id`), emisor, fecha y contenido para evitar duplicados.
* **🔐 Cifrado Nativo Crypt14 y Crypt15:** Descifra y vuelve a cifrar respaldos de Android con claves raíz hex de 64 dígitos, clonando los encabezados Protobuf varint oficiales.
* **📥 Fusión Incremental (Cero Pérdida de Datos):** Permite extraer e incorporar los mensajes que recibiste en el teléfono *hoy* antes de restaurar, garantizando que no se pierda ni un mensaje reciente.
* **📸 Migración de Archivos Multimedia:** Copia fotos, videos, notas de voz, audios, GIFs y documentos en la estructura de carpetas de Android (`Android/media/com.whatsapp/WhatsApp/Media/`).
* **🧙 Asistente Interactivo en Terminal (TUI):** Asistente visual paso a paso (`wizard.py`) con detección automática de dispositivos USB (MTP o ADB) y herramientas de diagnóstico.

---

## 📋 Requisitos Previos

Necesitarás:

1. **El Respaldo de iPhone:**
   * Una carpeta de copia de seguridad local de iTunes/Finder (que contenga `Manifest.db`), **O BIEN**
   * El archivo extraído `ChatStorage.sqlite` (y opcionalmente la carpeta `Media/`).
2. **El Respaldo de Android:**
   * Tu archivo `msgstore.db.crypt14` o `msgstore.db.crypt15` (ubicado en tu teléfono en `Android/media/com.whatsapp/WhatsApp/Databases/`).
3. **Clave de Cifrado Hexadecimal de 64 Dígitos:**
   * Se obtiene al activar "Copia de seguridad cifrada de extremo a extremo" en WhatsApp (**Ajustes > Chats > Copia de seguridad > Copia de seguridad cifrada de extremo a extremo**).
4. **Python 3.12+** (se recomienda usar [uv](https://github.com/astral-sh/uv)).

---

## 🚀 Inicio Rápido

### 1. Instalación

Clona este repositorio e instala las dependencias usando `uv` (o con `pip` estándar):

```bash
git clone https://github.com/yourusername/wa-backup.git
cd wa-backup

# Usando uv (más rápido y recomendado)
uv sync

# O usando pip tradicional
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Ejecutar el Asistente Interactivo (Recomendado)

Lanza el asistente interactivo en la terminal:

```bash
./wizard.py
# o bien: uv run wa-wizard

# Especificar idioma explícitamente (Español / Inglés):
./wizard.py --lang es
./wizard.py --lang en
```

> **Consejo:** También puedes presionar `L` en el menú principal del asistente en cualquier momento para alternar instantáneamente entre español e inglés.

El asistente te guiará en:
1. Detectar o seleccionar tu respaldo de iPhone y el `.crypt15` de Android.
2. Descifrar, sanear, fusionar y re-cifrar la base de datos combinada.
3. Detectar automáticamente tu teléfono Android conectado por USB (MTP o ADB).
4. Transferir la base de datos y la multimedia al teléfono.
5. Verificar la integridad de la base de datos y copiar tu clave de 64 dígitos al portapapeles.

---

## 💻 Uso por Línea de Comandos (CLI / Modo Avanzado)

Si prefieres automatizar por terminal:

### Pipeline Completo en un solo Comando
```bash
uv run wa-backup pipeline \
  --ios /ruta/al/ChatStorage.sqlite \
  --android-crypt /ruta/a/msgstore.db.crypt15 \
  --key "TU_CLAVE_DE_64_CARACTERES_HEX" \
  --output-dir ./output
```

### Comandos Paso a Paso

1. **Descifrar respaldo de Android:**
   ```bash
   uv run wa-backup decrypt \
     --key "TU_CLAVE_DE_64_CARACTERES_HEX" \
     --input msgstore.db.crypt15 \
     --output msgstore_decrypted.db
   ```

2. **Fusionar iPhone en la base SQLite de Android:**
   ```bash
   uv run wa-backup merge \
     --ios /ruta/al/ChatStorage.sqlite \
     --android-db msgstore_decrypted.db \
     --android-media ./output/WhatsApp/Media
   ```

3. **Re-cifrar base combinada a crypt15:**
   ```bash
   uv run wa-backup encrypt \
     --key "TU_CLAVE_DE_64_CARACTERES_HEX" \
     --input msgstore_decrypted.db \
     --output ./output/msgstore.db.crypt15 \
     --reference msgstore.db.crypt15
   ```

---

## 📲 Cómo Restaurar en el Teléfono Android

Sigue esta secuencia cuidadosamente para que Android 14/15 y WhatsApp lean el respaldo local sin conflictos de almacenamiento:

1. **Borrar Almacenamiento de WhatsApp en el Teléfono:**
   * En tu teléfono ve a: **Ajustes > Aplicaciones > WhatsApp > Almacenamiento y caché > Borrar almacenamiento**.
   * *(⚠️ Nota: En Android 13+, borrar el almacenamiento de una app borra su carpeta `com.whatsapp`. Por eso, el archivo de respaldo SIEMPRE debe copiarse DESPUÉS de este paso).*

2. **Conceder Permisos por Anticipado:**
   * Ve a: **Ajustes > Aplicaciones > WhatsApp > Permisos**.
   * Concede manualmente: **Fotos y videos**, **Contactos**, y **Notificaciones**.
   *(Esto asegura que WhatsApp tenga acceso al almacenamiento desde el primer segundo en que arranque).*

3. **Transferir el Archivo de Respaldo:**
   * Copia el archivo `msgstore.db.crypt15` generado en:
     ```
     Almacenamiento interno/Android/media/com.whatsapp/WhatsApp/Databases/msgstore.db.crypt15
     ```
   * *(Opcional: Copia la carpeta `WhatsApp/Media/` en `Almacenamiento interno/Android/media/com.whatsapp/WhatsApp/Media/`)*.

4. **Abrir WhatsApp y Restaurar:**
   * Abre WhatsApp, elige idioma, acepta términos y verifica tu número con el código SMS.
   * **⚠️ Muy Importante:** Si WhatsApp muestra una pantalla para buscar copias en Google Drive, toca **OMITIR** (Skip).
   * WhatsApp escaneará de inmediato la memoria interna y mostrará:
     **"Copia de seguridad local encontrada"** (Fecha: Hoy, Tamaño: ~100–300 MB).
   * Toca **Restaurar** e introduce tu **clave de 64 dígitos**.
   * Verás cómo la barra de progreso avanza fluidamente a través del 69% hasta llegar al **100%**.

---

## 🧪 Pruebas Unitarias

La suite de pruebas valida la compatibilidad del esquema, sanitización de JIDs, pruebas de ida y vuelta de cifrado y deduplicación:

```bash
uv run pytest tests/
```

---

## 📄 Licencia

Distribuido bajo la [Licencia MIT](LICENSE). Libre para uso personal y comercial.

---

## 🤝 Contribuciones

¡Las contribuciones, reportes de bugs y sugerencias son bienvenidas! Siéntete libre de abrir un issue o pull request en GitHub.
