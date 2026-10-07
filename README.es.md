# ⚡ wa-fuse: Fusión de Respaldos de WhatsApp (iOS ➔ Android)

<p align="center">
  <a href="README.md"><b>🇺🇸 English</b></a> • <a href="README.es.md"><b>🇪🇸 Español</b></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12+-blue.svg?style=flat-square&logo=python" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/WhatsApp-Crypt14%20%2F%20Crypt15-25D366.svg?style=flat-square&logo=whatsapp" alt="Crypt14 / Crypt15">
  <img src="https://img.shields.io/badge/Licencia-MIT-green.svg?style=flat-square&logo=open-source-initiative" alt="Licencia MIT">
  <img src="https://img.shields.io/badge/Pruebas-Aprobadas-brightgreen.svg?style=flat-square" alt="Pruebas Aprobadas">
</p>

Herramienta de código abierto diseñada para **fusionar el historial de chats de WhatsApp de un iPhone (iOS) dentro de una copia de seguridad de Android existente**, consolidando más de una década de mensajes en una base de datos única y limpia lista para restaurarse en Android — **sin sobreescribir tus chats actuales y resolviendo definitivamente el famoso error de congelamiento en el 69%.**

---

## 💡 ¿Por qué existe este proyecto?

1. **La transferencia oficial sobreescribe tus datos:** La herramienta oficial "Trasladar a Android" sólo funciona en dispositivos recién formateados de fábrica. Si llevas días o semanas usando tu Android y quieres traer el historial de tu iPhone anterior, la herramienta oficial te borra todo lo que tengas en Android.
2. **Las herramientas de pago son costosas y riesgosas:** Cobran entre 30$ y 50$ USD anuales, exigen root o drivers invasivos, y procesan tus conversaciones privadas y descifradas en servidores cerrados.
3. **El infame "Error del 69%":** La gran mayoría de scripts antiguos de la comunidad fallan con las versiones modernas de WhatsApp. Al restaurar la copia en Android, la barra de progreso se congela o truena al **69%**, arruinando la restauración.

---

## 🛠️ Cómo resolvemos el "Error del 69%"

Al llegar aproximadamente al 69% del proceso de restauración, WhatsApp para Android termina la inserción secuencial de mensajes e inicia tres tareas internas críticas de mantenimiento:
1. Validación de JIDs y contactos para generar el listado de hilos (`JidFactory`).
2. Reindexación de metadatos multimedia (`message_media`).
3. Detección de colisiones e identidades multi-cuenta (`local_chat_db_lid_migration`).

**wa-fuse** elimina de raíz las causas de este fallo:

| Causa del Fallo | Qué sucedía internamente | Cómo lo solucionamos |
| :--- | :--- | :--- |
| **JIDs `@status` inválidos** | iOS guarda los estados de contactos en `ZWACHATSESSION` (`ZSESSIONTYPE = 3`). Android lanza `InvalidJidException: Invalid server status`. | Filtra y descarta sesiones de estado, garantizando únicamente servidores válidos en Android (`s.whatsapp.net`, `g.us`, `status@broadcast`). |
| **Colisiones LID vs. Teléfono** | Las versiones modernas de iOS indexan chats 1 a 1 usando identificadores opacos `@lid`. Android genera hilos duplicados y truena en la migración LID. | Resuelve de forma automática las sesiones `@lid` al número telefónico canónico (`ZCONTACTIDENTIFIER`) y las une en los chats existentes. |
| **Registros faltantes en `message_media`** | Si faltaba el archivo físico de una foto o audio de iPhone, scripts viejos no insertaban su fila en `message_media`. Android lanzaba `NullPointerException`. | Garantiza cobertura al 100% en `message_media` para cada mensaje multimedia con flags de transferencia válidos y hashes seguros. |
| **Prefijos de ruta relativa** | Android espera rutas de archivo relativas a su carpeta raíz (ej. `Media/WhatsApp Images/...`). | Sanea y antepone `Media/` a todas las rutas relativas. |
| **Flags de control y multi-cuenta** | WhatsApp moderno en Android requiere `account_jid_row_id = jid_row_id` y valores obligatorios en `broadcast`, `origin` y `sort_id`. | Pobla los esquemas conforme a las vistas nativas `available_message_view` y `chat_view`. |

---

## ✨ Características Principales

* **🔄 Fusión Bidireccional:** Une chats individuales y grupales de iPhone (`ChatStorage.sqlite`) en la base de Android (`msgstore.db`).
* **⏱️ Conversión de Épocas:** Convierte marcas de tiempo Cocoa de Apple Core Data (segundos desde 2001) a marcas de tiempo Unix en milisegundos (desde 1970).
* **🧹 Desduplicación Inteligente:** Compara mensajes por `stanza_id` (`key_id`), remitente, timestamp y contenido para evitar mensajes repetidos.
* **🔐 Criptografía Crypt14 y Crypt15:** Descifra y re-cifra copias de seguridad de Android usando la clave raíz hex de 64 caracteres, replicando las cabeceras varint Protobuf oficiales.
* **📥 Fusión Incremental de Hoy:** Permite extraer y sumar los mensajes recibidos en el teléfono *el día de hoy* antes de restaurar, garantizando **cero pérdida de datos**.
* **📸 Migración Multimedia:** Copia fotos, videos, audios, notas de voz, GIFs y documentos a la estructura nativa de carpetas de Android (`Android/media/com.whatsapp/WhatsApp/Media/`).
* **🧙 Asistente Interactivo en Terminal (TUI):** Asistente paso a paso con detección automática de teléfonos por USB (MTP y ADB), copia automática de clave al portapapeles y herramientas de diagnóstico de SQLite.
* **🌐 Soporte Bilingüe:** Interfaz y documentación completa en español e inglés con autodetección de idioma.

---

## 📋 Requisitos Previos

Necesitarás:

1. **Copia de seguridad de WhatsApp de iPhone:**
   * Respaldo local sin cifrar que contenga `ChatStorage.sqlite` y la carpeta `Message` con multimedia, O bien el archivo `ChatStorage.sqlite` suelto.
2. **Copia de seguridad original de Android:**
   * Tu archivo `msgstore.db.crypt14` o `msgstore.db.crypt15` (ubicado en `Android/media/com.whatsapp/WhatsApp/Databases/`).
3. **Clave de cifrado de 64 caracteres hexadecimales:**
   * La clave generada al activar la copia cifrada de extremo a extremo en WhatsApp (**Ajustes > Chats > Copia de seguridad > Copia de seguridad cifrada de extremo a extremo**).
4. **Python 3.12+** (recomendado gestionar con [uv](https://github.com/astral-sh/uv)).

---

## 🚀 Inicio Rápido

### 1. Instalación

Clona este repositorio e instala las dependencias:

```bash
git clone https://github.com/tu-usuario/wa-fuse.git
cd wa-fuse

# Usando uv (el más rápido y recomendado)
uv sync

# O usando pip tradicional
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Ejecutar el Asistente Interactivo (Recomendado)

Inicia el asistente interactivo en la terminal:

```bash
./wa-fuse
# o bien: uv run wa-fuse

# Especificar idioma explícitamente (Español / Inglés):
./wa-fuse --lang es
./wa-fuse --lang en
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
uv run wa-fuse pipeline \
  --ios /ruta/a/ChatStorage.sqlite \
  --android-crypt /ruta/a/msgstore.db.crypt15 \
  --key "TU_CLAVE_DE_64_CARACTERES_HEX" \
  --output-dir ./output
```

### Comandos Paso a Paso

1. **Descifrar respaldo de Android:**
   ```bash
   uv run wa-fuse decrypt \
     --key "TU_CLAVE_DE_64_CARACTERES_HEX" \
     --input msgstore.db.crypt15 \
     --output msgstore_decrypted.db
   ```

2. **Fusionar base de datos de iPhone en la de Android:**
   ```bash
   uv run wa-fuse merge \
     --ios /ruta/a/ChatStorage.sqlite \
     --android-db msgstore_decrypted.db \
     --android-media ./output/WhatsApp/Media
   ```

3. **Re-cifrar base de datos combinada a crypt15:**
   ```bash
   uv run wa-fuse encrypt \
     --key "TU_CLAVE_DE_64_CARACTERES_HEX" \
     --input msgstore_decrypted.db \
     --output ./output/msgstore.db.crypt15 \
     --reference msgstore.db.crypt15
   ```

---

## 📲 Cómo Restaurar en tu Teléfono Android

Sigue estos pasos con atención para que Android 14/15 y WhatsApp detecten la copia local correctamente:

1. **Borrar Almacenamiento de WhatsApp en el Teléfono:**
   * Entra a: **Ajustes > Aplicaciones > WhatsApp > Almacenamiento y caché > Borrar almacenamiento**.
   * *(⚠️ Importante: En Android 13 en adelante, borrar el almacenamiento de una app elimina su carpeta `com.whatsapp`. Por eso, siempre debes copiar el archivo DESPUÉS de haber borrado datos).*

2. **Otorgar Permisos por Adelantado:**
   * Entra a: **Ajustes > Aplicaciones > WhatsApp > Permisos**.
   * Habilita manualmente: **Fotos y videos**, **Contactos** y **Notificaciones**.
   *(Esto asegura que WhatsApp tenga acceso al almacenamiento interno desde el primer arranque).*

3. **Copiar el Respaldo Generado:**
   * Copia el archivo `msgstore.db.crypt15` resultante a:
     ```
     Almacenamiento interno/Android/media/com.whatsapp/WhatsApp/Databases/msgstore.db.crypt15
     ```
   * *(Opcional: Copia la carpeta `WhatsApp/Media/` a `Almacenamiento interno/Android/media/com.whatsapp/WhatsApp/Media/`)*.

4. **Abrir WhatsApp y Restaurar:**
   * Abre WhatsApp, elige idioma, acepta términos e introduce tu número para verificar por SMS.
   * **⚠️ Crucial:** Si WhatsApp pregunta por buscar copias en Google Drive, pulsa **OMITIR**.
   * WhatsApp escaneará el almacenamiento local e indicará:
     **"Copia de seguridad local encontrada"** (Fecha: Hoy, Tamaño: ~100–300 MB).
   * Pulsa **Restaurar** e introduce tu **clave de 64 dígitos**.
   * La barra de progreso avanzará de forma fluida a través del 69% hasta alcanzar el **100%**.

---

## 🧪 Pruebas Unitarias

La suite de pruebas valida compatibilidad de esquemas, saneamiento de JIDs, cifrado de ida y vuelta y prevención de duplicados:

```bash
uv run pytest tests/
```

---

## 📄 Licencia

Distribuido bajo la [Licencia MIT](LICENSE). Libre para uso personal y comercial.

---

## 🤝 Contribuciones

¡Las contribuciones, reportes de problemas y sugerencias son bienvenidas! Visita la [sección de issues](https://github.com/tu-usuario/wa-fuse/issues).
