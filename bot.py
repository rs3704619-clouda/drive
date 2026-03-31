import os
import telebot
import requests
import google.generativeai as genai
from flask import Flask
from threading import Thread
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import time
import sqlite3
from datetime import datetime
import math

# --- CONFIG ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_KEY")
SPORTS_KEY = os.environ.get("SPORTS_API_KEY")
FOOTBALL_KEY = os.environ.get("FOOTBALL_DATA_KEY")
PORT = int(os.environ.get("PORT", 7860))

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
NODO_ACTIVO = {}

# --- DB ---
conn = sqlite3.connect("historial.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS predicciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT,
    partido TEXT,
    ganador TEXT,
    pick TEXT,
    confianza TEXT,
    nodo TEXT
)
""")
conn.commit()

# --- GEMINI ---
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

bot.remove_webhook()

# --- RAPIDAPI H2H ---
def consultar_rapidsport(eq1, eq2):
    url = "https://api-football-v1.p.rapidapi.com/v3/fixtures/headtohead"
    headers = {
        "X-RapidAPI-Key": SPORTS_KEY,
        "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
    }
    try:
        r = requests.get(url, headers=headers, params={"h2h": f"{eq1}-{eq2}"}, timeout=10)
        data = r.json()
        fixtures = data.get('response', [])[:5]

        if not fixtures:
            return "Sin historial reciente."

        resumen = ""
        for f in fixtures:
            resumen += f"{f['teams']['home']['name']} {f['goals']['home']}-{f['goals']['away']} {f['teams']['away']['name']}\n"

        return resumen
    except:
        return "Error API H2H"

# --- FOOTBALL DATA (REAL) ---
def buscar_team_id(nombre):
    url = "https://api.football-data.org/v4/teams"
    headers = {"X-Auth-Token": FOOTBALL_KEY}

    try:
        r = requests.get(url, headers=headers, timeout=10)
        teams = r.json().get("teams", [])

        nombre = nombre.lower()

        for t in teams:
            if nombre in t["name"].lower():
                return t["id"], t["name"]

        return None, None
    except:
        return None, None

def obtener_stats_equipo(team_id):
    url = f"https://api.football-data.org/v4/teams/{team_id}/matches?limit=10"
    headers = {"X-Auth-Token": FOOTBALL_KEY}

    try:
        r = requests.get(url, headers=headers, timeout=10)
        matches = r.json().get("matches", [])

        gf = gc = partidos = 0

        for m in matches:
            score = m["score"]["fullTime"]
            if score["home"] is None:
                continue

            if m["homeTeam"]["id"] == team_id:
                gf += score["home"]
                gc += score["away"]
            else:
                gf += score["away"]
                gc += score["home"]

            partidos += 1

        if partidos == 0:
            return 1.2, 1.2

        return gf / partidos, gc / partidos
    except:
        return 1.2, 1.2

# --- POISSON ---
def poisson(k, lamb):
    return (lamb**k * math.exp(-lamb)) / math.factorial(k)

def probabilidades_poisson(l1, l2):
    max_goles = 6
    p1 = p2 = px = 0

    for i in range(max_goles):
        for j in range(max_goles):
            p = poisson(i, l1) * poisson(j, l2)

            if i > j:
                p1 += p
            elif i < j:
                p2 += p
            else:
                px += p

    return round(p1*100,2), round(px*100,2), round(p2*100,2)

# --- STATUS ---
@bot.message_handler(commands=['status'])
def status_api(message):
    texto = (
        f"Gemini: {'OK' if GEMINI_KEY else 'FALTA'}\n"
        f"RapidAPI: {'OK' if SPORTS_KEY else 'FALTA'}\n"
        f"FootballData: {'OK' if FOOTBALL_KEY else 'FALTA'}"
    )
    bot.reply_to(message, texto)

# --- SCAN ---
@bot.message_handler(commands=['scan'])
def scan_nodos(message):
    modelos = [m.name.replace('models/', '') for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]

    nodos_activos = []
    bot.send_message(message.chat.id, "Probando nodos...")

    for nodo in modelos:
        try:
            t0 = time.time()
            genai.GenerativeModel(nodo).generate_content("hi")
            t = round(time.time() - t0, 2)
            nodos_activos.append((nodo, t))
        except:
            continue

    nodos_activos.sort(key=lambda x: x[1])

    markup = InlineKeyboardMarkup()
    for nodo, t in nodos_activos:
        markup.add(InlineKeyboardButton(f"{nodo} ({t}s)", callback_data=f"set_{nodo}"))

    bot.send_message(message.chat.id, "Selecciona nodo:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("set_"))
def set_nodo(call):
    NODO_ACTIVO[call.message.chat.id] = call.data.replace("set_", "")
    bot.edit_message_text("Nodo activado", call.message.chat.id, call.message.message_id)

# --- JUEGO ---
@bot.message_handler(commands=['juego'])
def juego(message):
    nodo = NODO_ACTIVO.get(message.chat.id)

    if not nodo:
        bot.reply_to(message, "Usa /scan primero")
        return

    query = message.text.replace("/juego", "").strip()

    if " vs " not in query:
        bot.reply_to(message, "Formato: equipo1 vs equipo2")
        return

    msg = bot.reply_to(message, "Analizando...")

    try:
        e1, e2 = query.split(" vs ")

        # H2H
        h2h = consultar_rapidsport(e1, e2)

        # IDs reales
        id1, name1 = buscar_team_id(e1)
        id2, name2 = buscar_team_id(e2)

        if not id1 or not id2:
            bot.edit_message_text("Equipos no encontrados en API real", message.chat.id, msg.message_id)
            return

        # stats reales
        atk1, def1 = obtener_stats_equipo(id1)
        atk2, def2 = obtener_stats_equipo(id2)

        l1 = (atk1 + def2) / 2
        l2 = (atk2 + def1) / 2

        p1, px, p2 = probabilidades_poisson(l1, l2)

        prob_text = f"""
📊 MODELO REAL:
{name1}: {p1}%
EMPATE: {px}%
{name2}: {p2}%

Goles esperados:
{name1}: {round(l1,2)}
{name2}: {round(l2,2)}
"""

        prompt = f"""
Eres el Oráculo Hysterix.

{prob_text}

DATOS H2H:
{h2h}

⚠️ REGLA:
No inventes probabilidades, usa las matemáticas.

⚽ DIAGNÓSTICO:

📊 PROBABILIDADES:

🎯 PICK:

GANADOR:
PICK:
CONFIANZA:
"""

        res = genai.GenerativeModel(nodo).generate_content(prompt).text

        bot.edit_message_text(res, message.chat.id, msg.message_id)

    except Exception as e:
        bot.edit_message_text(str(e), message.chat.id, msg.message_id)

# --- SERVER ---
def run():
    app.run(host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    Thread(target=run).start()
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
