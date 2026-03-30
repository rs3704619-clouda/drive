import os
import io
import json
from pyrogram import Client, filters
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# --- CONFIGURACIÓN USERBOT ---
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")

# --- CONFIGURACIÓN GOOGLE DRIVE ---
FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID")
creds_dict = json.loads(os.environ.get("GOOGLE_CREDS_JSON"))
SCOPES = ['https://www.googleapis.com/auth/drive']
creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
drive_service = build('drive', 'v3', credentials=creds)

# Iniciamos la sesión de tu cuenta
app = Client("hysterix_session", api_id=API_ID, api_hash=API_HASH)

# ID del canal de donde vas a sacar los archivos (El canal ajeno)
CANAL_FUENTE = -100123456789 

@app.on_message(filters.chat(CANAL_FUENTE) & (filters.document | filters.video))
async def handle_mirror(client, message):
    file_name = message.document.file_name if message.document else "video_descargado.mp4"
    print(f"📥 Detectado: {file_name}")

    # 1. Descargamos el archivo directamente a la memoria
    file_data = await client.download_media(message, in_memory=True)
    
    # 2. Subimos a Google Drive
    file_metadata = {'name': file_name, 'parents': [FOLDER_ID]}
    media = MediaIoBaseUpload(io.BytesIO(file_data.getbuffer()), mimetype='application/octet-stream', resumable=True)
    
    uploaded_file = drive_service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
    
    print(f"✅ Subido a Drive: {uploaded_file.get('webViewLink')}")

app.run()
