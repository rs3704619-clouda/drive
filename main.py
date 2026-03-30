import os
import io
import json
import asyncio
from pyrogram import Client, filters
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# --- VARIABLES DESDE RAILWAY ---
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
SESSION_STRING = os.environ.get("SESSION_STRING") # Aquí irá tu sesión activa
FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID")
CANAL_FUENTE = int(os.environ.get("CANAL_FUENTE")) # ID del canal a "espejear"
MI_CANAL = int(os.environ.get("MI_CANAL")) # Tu canal de avisos

# --- GOOGLE DRIVE SETUP ---
creds_dict = json.loads(os.environ.get("GOOGLE_CREDS_JSON"))
creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=['https://www.googleapis.com/auth/drive'])
drive_service = build('drive', 'v3', credentials=creds)

# --- USERBOT SETUP ---
app = Client("hysterix_userbot", session_string=SESSION_STRING, api_id=API_ID, api_hash=API_HASH)

@app.on_message(filters.chat(CANAL_FUENTE) & (filters.document | filters.video | filters.audio))
async def mirror_to_drive(client, message):
    try:
        # 1. Definir nombre del archivo
        file_name = message.document.file_name if message.document else f"archivo_{message.id}"
        await app.send_message(MI_CANAL, f"📡 **Capturando de canal ajeno:** `{file_name}`...")

        # 2. Descargar a la RAM
        file_data = await client.download_media(message, in_memory=True)
        
        # 3. Subir a Drive
        file_metadata = {'name': file_name, 'parents': [FOLDER_ID]}
        media = MediaIoBaseUpload(io.BytesIO(file_data.getbuffer()), mimetype='application/octet-stream', resumable=True)
        
        uploaded = drive_service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        
        # 4. Hacerlo público y avisar
        drive_service.permissions().create(fileId=uploaded.get('id'), body={'type': 'anyone', 'role': 'viewer'}).execute()
        
        link = uploaded.get('webViewLink')
        await app.send_message(MI_CANAL, f"✅ **Subido a Drive:**\n📂 `{file_name}`\n🔗 [Link de Descarga]({link})")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    print("UserBot Espejo Hysterix en marcha... 🕵️")
    app.run()
