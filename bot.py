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

# 1. CONFIGURACIÓN DE VARIABLES
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SPORTS_KEY = os.environ.get("SPORTS_KEY") 
DATABASE_URL = os.environ.get("DATABASE_URL")

# 2. CONEXIÓN A POSTGRESQL
try:
    db_pool = psycopg2.pool.SimpleConnectionPool(1, 10, DATABASE_URL)
except Exception as e:
    print(f"❌ Error DB: {e}")

def get_db_connection():
    return db_pool.getconn()

def release_db_connection(conn):
    db_pool.putconn(conn)

# --- FUNCIÓN MATEMÁTICA DE POISSON ---
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
    return round(prob_l * 100), round(prob_e * 100), round(prob_v * 100)

# 3. INICIALIZACIÓN DE TABLAS
def inicializar_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS predicciones(id SERIAL PRIMARY KEY, deporte TEXT, equipo_local TEXT, equipo_visitante TEXT, prediccion TEXT, fecha DATE)")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stats_equipos(
                id_api INTEGER PRIMARY KEY, 
                nombre TEXT, 
                goles_favor_avg DECIMAL(4,2) DEFAULT 1.5, 
                goles_contra_avg DECIMAL(4,2) DEFAULT 1.5, 
                partidos_jugados INTEGER DEFAULT 0,
                ultima_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        cursor.close()
        release_db_connection(conn)
        print("✅ Tablas listas en PostgreSQL.")
    except Exception as e:
        print(f"❌ Error inicializando DB: {e}")

# 4. FUNCIÓN PARA IMPORTAR EQUIPOS (Football-Data.org)
def actualizar_desde_api(league_code):
    url = f"https://api.football-data.org/v4/competitions/{league_code}/teams"
    headers = {"X-Auth-Token": SPORTS_KEY}
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
        release_db_connection(conn)
        return True
    except: return False

# 5. COMANDOS DEL BOT
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 *Guía del Oráculo Hysterix*\n\n"
        "🔮 *Predicciones:*\n"
        "/juego [Local] vs [Visitante] — Analiza un partido usando Poisson y Gemini.\n\n"
        "📊 *Gestión de Datos:*\n"
        "/stats [Nombre] — Muestra los goles promedio guardados de un equipo.\n"
        "/setstats [ID], [Nombre], [GF], [GC] — Actualiza manualmente los promedios.\n"
        "/actualizar — Sincroniza nombres de equipos desde la API (España e Inglaterra).\n\n"
        "📜 *Historial:*\n"
        "/historial — Muestra las últimas 5 predicciones realizadas.\n\n"
        "💡 *Consejo:* Si una predicción parece genérica, usa /stats para ver si el equipo tiene datos reales o usa el promedio base (1.5)."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def actualizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Sincronizando ligas con Football-Data.org...")
    s1 = actualizar_desde_api("PD") # España
    s2 = actualizar_desde_api("PL") # Inglaterra
    msg = "✅ Ligas sincronizadas." if s1 and s2 else "⚠️ Error al conectar con la API."
    await update.message.reply_text(msg)

async def setstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        datos = " ".join(context.args).split(",")
        id_api = int(datos[0].strip())
        nombre = datos[1].strip()
        gf = float(datos[2].strip())
        gc = float(datos[3].strip())
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("UPDATE stats_equipos SET goles_favor_avg=%s, goles_contra_avg=%s, ultima_actualizacion=CURRENT_TIMESTAMP WHERE id_api=%s", (gf, gc, id_api))
        conn.commit(); cur.close(); release_db_connection(conn)
        await update.message.reply_text(f"✅ Stats manuales aplicados para {nombre}.")
    except: await update.message.reply_text("Usa: /setstats ID, Nombre, GF, GC")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text("Usa: /stats Nombre del Equipo")
            return
        nombre_busqueda = " ".join(context.args)
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("SELECT nombre, goles_favor_avg, goles_contra_avg, id_api FROM stats_equipos WHERE nombre ILIKE %s", (f"%{nombre_busqueda}%",))
        equipo = cur.fetchone()
        cur.close(); release_db_connection(conn)
        if equipo:
            await update.message.reply_text(f"📊 *{equipo[0]}* (ID: {equipo[3]})\n⚽ GF Avg: {equipo[1]}\n🛡️ GC Avg: {equipo[2]}", parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Equipo no encontrado.")
    except Exception as e: await update.message.reply_text(f"Error: {e}")

async def historial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("SELECT equipo_local, equipo_visitante, fecha, id FROM predicciones ORDER BY id DESC LIMIT 5")
        rows = cur.fetchall()
        cur.close(); release_db_connection(conn)
        if not rows:
            await update.message.reply_text("Aún no hay predicciones en el historial.")
            return
        texto_historial = "📜 *Últimas 5 Predicciones:*\n\n"
        for row in rows:
            texto_historial += f"🔹 {row[2]} | *{row[0]} vs {row[1]}* (Ref: {row[3]})\n"
        await update.message.reply_text(texto_historial, parse_mode="Markdown")
    except Exception as e: await update.message.reply_text(f"⚠️ Error al leer historial: {e}")

async def juego(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        texto = " ".join(context.args)
        if "vs" not in texto:
            await update.message.reply_text("❌ Formato: /juego Equipo A vs Equipo B")
            return
        local, visit = [x.strip() for x in texto.split("vs")]
        await update.message.reply_text(f"🔮 El Oráculo Hysterix consultando datos para {local} vs {visit}...")
        
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("SELECT goles_favor_avg FROM stats_equipos WHERE nombre ILIKE %s", (local,))
        res_l = cur.fetchone()
        cur.execute("SELECT goles_favor_avg FROM stats_equipos WHERE nombre ILIKE %s", (visit,))
        res_v = cur.fetchone()
        
        m_l = float(res_l[0]) if res_l else 1.3
        m_v = float(res_v[0]) if res_v else 1.1
        
        p_l, p_e, p_v = calcular_poisson(m_l, m_v)
        max_prob = max(p_l, p_v)
        
        if max_prob > 70: sugerencia_stake = "ALTO (7-9)"
        elif max_prob > 55: sugerencia_stake = "MEDIO (4-6)"
        else: sugerencia_stake = "BAJO (1-3)"

        prompt = f"""
        Actúa como el Oráculo Hysterix. Analiza {local} vs {visit}.
        Probabilidades Poisson: L:{p_l}%, E:{p_e}%, V:{p_v}%.
        Tu nivel de confianza matemática es {sugerencia_stake}.
        Instrucciones: Da un PICK claro y un STAKE numérico basado en {sugerencia_stake}. Tono cínico y profesional.
        """
        
        url_gemini = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
        res_ia = requests.post(url_gemini, json={"contents": [{"parts": [{"text": prompt}]}]}).json()
        respuesta = res_ia["candidates"][0]["content"]["parts"][0]["text"]

        cur.execute("INSERT INTO predicciones (deporte, equipo_local, equipo_visitante, prediccion, fecha) VALUES (%s,%s,%s,%s,%s)",
                   ("Fútbol", local, visit, respuesta, dt.date.today()))
        conn.commit(); cur.close(); release_db_connection(conn)
        await update.message.reply_text(respuesta, parse_mode="Markdown")
    except Exception as e: await update.message.reply_text(f"⚠️ Error: {e}")

# 6. SERVIDOR FLASK
flask_app = Flask(__name__)
@flask_app.route("/")
def home(): return "Servidor Activo"

if __name__ == "__main__":
    inicializar_db()
    threading.Thread(target=lambda: flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080))), daemon=True).start()
    bot = Application.builder().token(TOKEN).build()
    bot.add_handler(CommandHandler("start", help_command))
    bot.add_handler(CommandHandler("help", help_command))
    bot.add_handler(CommandHandler("juego", juego))
    bot.add_handler(CommandHandler("actualizar", actualizar))
    bot.add_handler(CommandHandler("setstats", setstats))
    bot.add_handler(CommandHandler("stats", stats))
    bot.add_handler(CommandHandler("historial", historial))
    bot.run_polling()
