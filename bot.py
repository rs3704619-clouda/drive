import os
import io
import json
import telebot
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# --- CONFIGURACIÓN ---
TOKEN = os.environ.get("TELEGRAM_TOKEN_NEWS") # Reutilizamos tu token o pon uno nuevo
FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID")
# Cargamos el JSON desde la variable de Railway
creds_dict = json.loads(os.environ.get("GOOGLE_CREDS_JSON"))

bot = telebot.TeleBot(TOKEN)

# Conexión con Google Drive
SCOPES = ['https://www.googleapis.com/auth/drive']
creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
drive_service = build('drive', 'v3', credentials=creds)

# ID del canal fuente (Cursos, libros, etc.)
CANAL_FUENTE = -100123456789 # <--- CAMBIA ESTO por el ID real
MI_CANAL = -100987654321    # <--- TU CANAL donde publicarás el link

@bot.channel_post_handler(content_types=['document', 'video', 'audio'])
def handle_mirror(message):
    try:
        # 1. Obtener info del archivo
        file_name = ""
        if message.document: file_name = message.document.file_name
        elif message.video: file_name = f"video_{message.video.file_id[:10]}.mp4"
        
        bot.send_message(MI_CANAL, f"📡 **Capturando:** `{file_name}`...")

        # 2. Descargar a la RAM (Railway)
        file_info = bot.get_file(message.document.file_id if message.document else message.video.file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        # 3. Subir a Google Drive
        file_metadata = {'name': file_name, 'parents': [FOLDER_ID]}
        fh = io.BytesIO(downloaded_file)
        media = MediaIoBaseUpload(fh, mimetype='application/octet-stream', resumable=True)
        
        uploaded_file = drive_service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        
        # 4. Hacer el link público
        drive_service.permissions().create(fileId=uploaded_file.get('id'), body={'type': 'anyone', 'role': 'viewer'}).execute()
        
        # 5. Mandar el link a tu canal
        link = uploaded_file.get('webViewLink')
        bot.send_message(MI_CANAL, f"✅ **Nuevo Recurso Subido**\n📂 `{file_name}`\n🔗 [Descargar de Drive]({link})", parse_mode="Markdown")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    print("Bot Espejo Hysterix operativo... 🔍")
    bot.infinity_polling()
