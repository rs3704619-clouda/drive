import os
import psycopg2
from psycopg2 import pool
import datetime as dt
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from flask import Flask
import threading

# -----------------------
# VARIABLES DE ENTORNO
# -----------------------
TOKEN = os.environ.get("TELEGRAM_TOKEN")
SPORTS_KEY = os.environ.get("SPORTS_KEY")  # Tu clave de v3.football.api-sports.io
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
DATABASE_URL = os.environ.get("DATABASE_URL")

# -----------------------
# CONFIGURACIÓN POSTGRESQL
# -----------------------
db_pool = None
try:
    if DATABASE_URL:
        db_pool = psycopg2.pool.SimpleConnectionPool(1, 10, DATABASE_URL)
        print("✅ Pool de PostgreSQL conectado")
except Exception as e:
    print(f"❌ Error DB Pool: {e}")

def get_db_connection():
    return db_pool.getconn() if db_pool else None

def release_db_connection(conn):
    if db_pool and conn: db_pool.putconn(conn)

def inicializar_db():
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS predicciones (
                    id SERIAL PRIMARY KEY,
                    deporte TEXT,
                    equipo_local TEXT,
                    equipo_visitante TEXT,
                    prediccion TEXT,
                    fecha DATE DEFAULT CURRENT_DATE
                );
            """)
            conn.commit()
            cur.close()
            print("✅ Tablas de PostgreSQL listas.")
        except Exception as e:
            print(f"❌ Error inicializando tablas: {e}")
        finally:
            release_db_connection(conn)

# -----------------------
# LÓGICA DE FÚTBOL (API-SPORTS)
# -----------------------
def obtener_fixture(eq1, eq2):
    url = "https://v3.football.api-sports.io/fixtures"
    headers = {"x-apisports-key": SPORTS_KEY}
    hoy = dt.datetime.now().strftime("%Y-%m-%d")
    try:
        r = requests.get(url, headers=headers, params={"date": hoy}, timeout=10)
        data = r.json().get("response", [])
        for f in data:
            home = f["teams"]["home"]["name"].lower()
            away = f["teams"]["away"]["name"].lower()
            if eq1.lower() in home and eq2.lower() in away: return f
            if eq1.lower() in away and eq2.lower() in home: return f
        return None
    except: return None

def consultar_h2h(eq1, eq2):
    url = "https://v3.football.api-sports.io/fixtures/headtohead"
    headers = {"x-apisports-key": SPORTS_KEY}
    try:
        # Nota: Aquí ideally necesitarías los IDs de los equipos para h2h exacto, 
        # pero mantenemos tu lógica de búsqueda por texto.
        r = requests.get(url, headers=headers, params={"h2h": f"{eq1}-{eq2}"}, timeout=10)
        data = r.json()
        fixtures = data.get('response', [])[:5]
        resumen = ""
        for f in fixtures:
            h, a = f['teams']['home']['name'], f['teams']['away']['name']
            gh, ga = f['goals']['home'], f['goals']['away']
            resumen += f"{h} {gh}-{ga} {a}\n"
        return resumen if resumen else "Sin historial cercano."
    except: return "Error en H2H"

# -----------------------
# COMANDO /SCAN (RECUPERADO)
# -----------------------
async def scan_models(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = f"https://generativelanguage.googleapis.com/v1/models?key={GEMINI_API_KEY}"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        models = [m["name"].replace("models/", "") for m in data.get("models", [])]
        txt = "🔍 *MODELOS GEMINI DETECTADOS:*\n\n" + "\n".join([f"✅ `{m}`" for m in models])
        await update.message.reply_text(txt, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error escaneando nodos: {e}")

# -----------------------
# COMANDO /JUEGO (CON BLINDAJE)
# -----------------------
async def juego(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = None
    try:
        texto = " ".join(context.args)
        if "vs" not in texto:
            await update.message.reply_text("Usa: /juego Local vs Visitante")
            return

        local, visit = [x.strip() for x in texto.split("vs")]
        await update.message.reply_text(f"🔮 El Oráculo Hysterix está analizando {local} vs {visit}...")

        fixture = obtener_fixture(local, visit)
        info_partido = f"PARTIDO: {local} vs {visit}\n"
        if fixture:
            info_partido += f"Fecha: {fixture['fixture']['date']}\nLiga: {fixture['league']['name']}"
        
        h2h = consultar_h2h(local, visit)

        prompt = f"""Eres el Oráculo Hysterix. Analiza este partido:
{info_partido}
HISTORIAL H2H:
{h2h}

Responde con:
1. Diagnóstico cínico y profesional.
2. Probabilidades (Local, Empate, Visitante).
3. PICK final con STAKE (1-10)."""

        url = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
        r = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=15)
        res_ia = r.json()

        # BLINDAJE CONTRA ERROR 'CANDIDATES'
        if "candidates" in res_ia and len(res_ia["candidates"]) > 0:
            pred = res_ia["candidates"][0]["content"]["parts"][0]["text"]
        else:
            pred = f"⚠️ Gemini no pudo generar el texto (Filtro de seguridad o error de nodo).\n\n📊 H2H detectado:\n{h2h}"

        # GUARDAR EN POSTGRESQL
        conn = get_db_connection()
        if conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO predicciones (deporte, equipo_local, equipo_visitante, prediccion) VALUES (%s, %s, %s, %s)",
                ("futbol", local, visit, pred)
            )
            conn.commit()
            cur.close()

        await update.message.reply_text(pred)

    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {e}")
    finally:
        if conn: release_db_connection(conn)

# -----------------------
# WEB SERVER Y ARRANQUE
# -----------------------
flask_app = Flask(__name__)
@flask_app.route("/")
def home(): return "Bot Hysterix Online"

def run_flask():
    flask_app.run(host="0.0.0.0", port=8080)

if __name__ == "__main__":
    inicializar_db()
    threading.Thread(target=run_flask, daemon=True).start()

    bot = Application.builder().token(TOKEN).build()
    bot.add_handler(CommandHandler("juego", juego))
    bot.add_handler(CommandHandler("scan", scan_models)) # Comando recuperado
    bot.add_handler(CommandHandler("help", lambda u, c: u.message.reply_text("/juego, /scan, /historial")))
    
    print("🚀 Bot Iniciado")
    bot.run_polling(drop_pending_updates=True)
