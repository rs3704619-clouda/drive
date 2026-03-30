import os
import json
import asyncio
from pyrogram import Client, filters
from googleapiclient.discovery import build
from google.oauth2 import service_account
from googleapiclient.http import MediaFileUpload

# --- CONFIGURACIÓN DESDE RAILWAY (VARIABLES) ---
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
SESSION_STRING = os.environ.get("SESSION_STRING")
CANAL_FUENTE = int(os.environ.get("CANAL_FUENTE"))
MI_CANAL = int(os.environ.get("MI_CANAL"))
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID")
GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_CREDS_JSON")

# --- PARCHE PARA EL ERROR DE JSON ---
# Esto limpia el JSON si se pegó con comillas extra en Railway
limpio_json = GOOGLE_CREDS_JSON.strip()
if limpio_json.startswith('"') and limpio_json.endswith('"'):
    limpio_json = limpio_json[1:-1].replace('\\"', '"')

with open('creds.json', 'w') as f:
    f.write(limpio_json)

# --- CONFIGURACIÓN DE CLIENTES ---
app = Client("hysterix_bot", session_string=SESSION_STRING, api_id=API_ID, api_hash=API_HASH)

# Configuración de Google Drive
creds = service_account.Credentials.from_service_account_file('creds.json')
drive_service = build('drive', 'v3', credentials=creds)

# --- LÓGICA DEL BOT ---

# Extensiones de libros permitidas
EXT_LIBROS = (".pdf", ".epub", ".mobi", ".azw3")

@app.on_message(filters.chat(CANAL_FUENTE) & filters.document)
async def procesar_documento(client, message):
    file_name = message.document.file_name
    
    # FILTRO: ¿Es un formato de libro permitido?
    if file_name and file_name.lower().endswith(EXT_LIBROS):
        aviso = await client.send_message(MI_CANAL, f"📥 **Detectado:** `{file_name}`\nDescargando y subiendo a Drive...")
        
        try:
            # 1. Descargar archivo de Telegram
            path = await message.download()
            
            # 2. Preparar subida a Google Drive
            file_metadata = {
                'name': file_name,
                'parents': [DRIVE_FOLDER_ID]
            }
            media = MediaFileUpload(path, resumable=True)
            
            # 3. Subir a Drive
            drive_file = drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webViewLink'
            ).execute()
            
            # 4. Avisar en TU CANAL con el link
            drive_link = drive_file.get('webViewLink')
            await aviso.edit(
                f"✅ **Subido con éxito:**\n"
                f"📂 `{file_name}`\n"
                f"🔗 [Ver en Google Drive]({drive_link})",
                disable_web_page_preview=True
            )
            
            # Limpiar archivo temporal de Railway
            if os.path.exists(path):
                os.remove(path)
            
        except Exception as e:
            await client.send_message(MI_CANAL, f"❌ **Error con:** `{file_name}`\n`{str(e)}`")

print("🕵️ UserBot Espejo Hysterix en marcha...")
app.run()
