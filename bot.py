import os
import psycopg2
from psycopg2 import pool
import datetime as dt
import requests
import math
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from flask import Flask
import threading

# --- CONFIGURACIÓN ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SPORTS_KEY = os.environ.get("SPORTS_KEY")
DATABASE_URL = os.environ.get("DATABASE_URL")

db_pool = None
try:
    if DATABASE_URL:
        db_pool = psycopg2.pool.SimpleConnectionPool(1, 10, DATABASE_URL)
        print("✅ Pool de conexiones DB establecido")
except Exception as e:
    print(f"❌ Error DB Pool: {e}")

def get_db_connection():
    return db_pool.getconn() if db_pool else None

def release_db_connection(conn):
    if db_pool and conn: db_pool.putconn(conn)

# --- INICIALIZACIÓN DE TABLAS (Evita el error de 'relation does not exist') ---
def inicializar_db():
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS stats_equipos (
                    id_api INTEGER PRIMARY KEY,
                    nombre TEXT,
                    goles_favor_avg DECIMAL(4,2) DEFAULT 1.3,
                    goles_contra_avg DECIMAL(4,2) DEFAULT 1.1,
                    partidos_jugados INTEGER DEFAULT 0,
                    ultima_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS predicciones (
                    id SERIAL PRIMARY KEY,
                    equipo_local TEXT,
                    equipo_visitante TEXT,
                    prediccion TEXT,
                    fecha DATE DEFAULT CURRENT_DATE
                );
            """)
            conn.commit()
            cur.close()
            print("✅ Tablas verificadas/creadas correctamente")
        except Exception as e:
            print(f"❌ Error inicializando tablas: {e}")
        finally:
            release_db_connection(conn)

# --- MATEMÁTICAS DE POISSON ---
def calcular_poisson(goles_local, goles_visitante):
    def poisson_prob(k, lamb):
        return (math.exp(-lamb) * (lamb**k)) / math.factorial(k)
    prob_l, prob_e, prob_v = 0, 0, 0
    for x in range(6): 
        for y in range(6):
            p = poisson_prob(x, goles_local) * poisson_prob(y, goles_visitante)
            if x > y: prob_l += p
            elif x < y: prob_v += p
            else: prob_e += p
    return round(prob_l * 100, 2), round(prob_e * 100, 2), round(prob_v * 100, 2)

# --- LÓGICA DE API DEPORTIVA ---
def actualizar_desde_api(league_code):
    url = f"https://api.football-data.org/v4/competitions/{league_code}/teams"
    headers = {"X-Auth-Token": SPORTS_KEY}
    conn = None
    try:
        r = requests.get(url, headers=headers)
        data = r.json()
        conn = get_db_connection()
        cur = conn.cursor()
        for team in data.get('teams', []):
            cur.execute("""
                INSERT INTO stats_equipos (id_api, nombre) VALUES (%s, %s)
                ON CONFLICT (id_api) DO UPDATE SET nombre = EXCLUDED.nombre
            """, (team['id'], team['shortName'] or team['name']))
        conn.commit()
        cur.close()
        return True
    except: return False
    finally: release_db_connection(conn)

# --- COMANDOS DEL BOT ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 *GUÍA DEL ORÁCULO HYSTERIX*\n\n"
        "🔮 *PREDICCIONES:*\n"
        "/juego [Local] vs [Visitante] — Análisis del Perro Loco.\n"
        "/historial — Últimas 5 predicciones guardadas.\n\n"
        "📊 *DATOS:*\n"
        "/stats [Equipo] — Ver promedios de goles.\n"
        "/actualizar — Sincronizar ligas (España/Inglaterra).\n"
        "/testdb — Diagnóstico de conexión.\n"
        "/reset — Recrear tablas si hay errores."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def juego(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = None
    try:
        texto = " ".join(context.args)
        if "vs" not in texto:
            await update.message.reply_text("❌ Formato: /juego Local vs Visitante")
            return
        
        local, visit = [x.strip() for x in texto.split("vs")]
        await update.message.reply_text(f"🔮 El Perro Loco está olfateando el {local} vs {visit}...")

        conn = get_db_connection()
        m_l, m_v = 1.3, 1.1 
        if conn:
            cur = conn.cursor()
            cur.execute("SELECT goles_favor_avg FROM stats_equipos WHERE nombre ILIKE %s", (f"%{local}%",))
            res_l = cur.fetchone()
            cur.execute("SELECT goles_favor_avg FROM stats_equipos WHERE nombre ILIKE %s", (f"%{visit}%",))
            res_v = cur.fetchone()
            if res_l: m_l = float(res_l[0])
            if res_v: m_v = float(res_v[0])
            cur.close()
        
        p_l, p_e, p_v = calcular_poisson(m_l, m_v)
        max_p = max(p_l, p_v)
        stk = "ALTO (7-9)" if max_p > 70 else "MEDIO (4-6)" if max_p > 55 else "BAJO (1-3)"

        prompt = (
            f"Actúa como el Oráculo Hysterix (apodado 'El Perro Loco'). "
            f"Partido: {local} vs {visit}. Probabilidades Poisson: Local {p_l}%, Empate {p_e}%, Visitante {p_v}%. "
            f"Confianza: {stk}. Usa un lenguaje agresivo, callejero y experto. "
            f"Estructura: 1. Diagnóstico cínico. 2. Porcentajes. 3. PICK final con STAKE numérico."
        )

        url = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
        res_ia = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}).json()
        resp = res_ia["candidates"][0]["content"]["parts"][0]["text"]

        if conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO predicciones (equipo_local, equipo_visitante, prediccion) VALUES (%s,%s,%s)", (local, visit, resp))
            conn.commit()
            cur.close()

        await update.message.reply_text(resp)
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {e}")
    finally: release_db_connection(conn)

async def historial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT equipo_local, equipo_visitante, fecha FROM predicciones ORDER BY id DESC LIMIT 5")
        rows = cur.fetchall()
        if not rows:
            await update.message.reply_text("Aún no hay nada en el historial, jefe.")
            return
        msg = "📜 *ÚLTIMAS PREDICCIONES:*\n\n"
        for r in rows:
            msg += f"🔹 {r[2]}: *{r[0]} vs {r[1]}*\n"
        await update.message.reply_text(msg, parse_mode="Markdown")
    except: await update.message.reply_text("Error al leer historial.")
    finally: release_db_connection(conn)

async def actualizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Sincronizando ligas con la API...")
    s1 = actualizar_desde_api("PD") 
    s2 = actualizar_desde_api("PL") 
    await update.message.reply_text("✅ Ligas listas." if s1 or s2 else "❌ Fallo total de API.")

async def testdb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    if conn:
        await update.message.reply_text("✅ Base de Datos Conectada.")
        release_db_connection(conn)
    else: await update.message.reply_text("❌ Sin conexión a DB.")

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    inicializar_db()
    await update.message.reply_text("🔄 Intento de recreación de tablas finalizado.")

# --- SERVIDOR Y ARRANQUE ---
app = Flask(__name__)
@app.route("/")
def home(): return "Hysterix Online"

if __name__ == "__main__":
    inicializar_db() # Crea las tablas al arrancar
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=8080), daemon=True).start()
    bot = Application.builder().token(TOKEN).build()
    bot.add_handler(CommandHandler("help", help_command))
    bot.add_handler(CommandHandler("start", help_command))
    bot.add_handler(CommandHandler("juego", juego))
    bot.add_handler(CommandHandler("historial", historial))
    bot.add_handler(CommandHandler("actualizar", actualizar))
    bot.add_handler(CommandHandler("testdb", testdb))
    bot.add_handler(CommandHandler("reset", reset_command))
    bot.run_polling()
