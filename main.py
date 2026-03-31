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
import unicodedata

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

# -----------------------------
# 🧹 LIMPIAR TEXTO
# -----------------------------
def limpiar_texto(texto):
    texto = texto.lower().strip()
    texto = unicodedata.normalize('NFD', texto)
    texto = texto.encode('ascii', 'ignore').decode('utf-8')
    return texto

# -----------------------------
# 🔎 BUSCAR EQUIPO EUROPA
# -----------------------------
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
        return "Error API"

# -----------------------------
# 🔎 BUSCAR EQUIPO LIGA MX
# -----------------------------
def buscar_team_id_mx(nombre):
    url = "https://api-football-v1.p.rapidapi.com/v3/teams"
    headers = {
        "X-RapidAPI-Key": SPORTS_KEY,
        "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
    }

    nombre = limpiar_texto(nombre)

    try:
        r = requests.get(
            url,
            headers=headers,
            params={"league": 262, "season": datetime.now().year},
            timeout=10
        )

        if r.status_code != 200:
            return None, None

        equipos = r.json().get("response", [])

        mejor_match = None
        mejor_score = 0

        for e in equipos:
            team_name_raw = e["team"]["name"]
            team_name = limpiar_texto(team_name_raw)

            palabras_input = set(nombre.split())
            palabras_team = set(team_name.split())

            # score por coincidencia de palabras
            score = len(palabras_input & palabras_team)

            if score > mejor_score:
                mejor_score = score
                mejor_match = (e["team"]["id"], team_name_raw)

        # mínimo 1 palabra en común
        if mejor_score >= 1:
            return mejor_match

    except:
        pass

    return None, None

# -----------------------------
# 📊 STATS EUROPA
# -----------------------------
def stats_europa(team_id):
    headers = {"X-Auth-Token": FOOTBALL_KEY}
    url = f"https://api.football-data.org/v4/teams/{team_id}/matches?limit=10"

    try:
        r = requests.get(url, headers=headers, timeout=10)
        matches = r.json().get("matches", [])

        gf = gc = 0
        peso_total = 0

        for i, m in enumerate(matches):
            score = m["score"]["fullTime"]
            if score["home"] is None:
                continue

            peso = 10 - i
            peso_total += peso

            if m["homeTeam"]["id"] == team_id:
                gf += score["home"] * peso
                gc += score["away"] * peso
            else:
                gf += score["away"] * peso
                gc += score["home"] * peso

        if peso_total == 0:
            return 1.2, 1.2

        return gf / peso_total, gc / peso_total

    except:
        return 1.2, 1.2

# -----------------------------
# 📊 STATS LIGA MX
# -----------------------------
def stats_mx(team_id):
    url = "https://api-football-v1.p.rapidapi.com/v3/fixtures"
    headers = {
        "X-RapidAPI-Key": SPORTS_KEY,
        "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
    }

    try:
        r = requests.get(
            url,
            headers=headers,
            params={"team": team_id, "last": 10},
            timeout=10
        )

        partidos = r.json().get("response", [])

        gf = gc = 0
        peso_total = 0

        for i, m in enumerate(partidos):
            g1 = m["goals"]["home"]
            g2 = m["goals"]["away"]

            if g1 is None:
                continue

            peso = 10 - i
            peso_total += peso

            if m["teams"]["home"]["id"] == team_id:
                gf += g1 * peso
                gc += g2 * peso
            else:
                gf += g2 * peso
                gc += g1 * peso

        if peso_total == 0:
            return 1.2, 1.2

        return gf / peso_total, gc / peso_total

    except:
        return 1.2, 1.2

# -----------------------------
# ⚙️ POISSON
# -----------------------------
def poisson(k, lamb):
    return (lamb**k * math.exp(-lamb)) / math.factorial(k)

def prob_poisson(l1, l2):
    p1 = p2 = px = 0

    for i in range(6):
        for j in range(6):
            p = poisson(i, l1) * poisson(j, l2)

            if i > j:
                p1 += p
            elif i < j:
                p2 += p
            else:
                px += p

    return round(p1*100, 2), round(px*100, 2), round(p2*100, 2)

# -----------------------------
# 🔍 SCAN
# -----------------------------
@bot.message_handler(commands=['scan'])
def scan(message):
    modelos = [m.name.replace('models/', '') for m in genai.list_models()
               if 'generateContent' in m.supported_generation_methods]

    nodos = []

    for m in modelos:
        try:
            t0 = time.time()
            genai.GenerativeModel(m).generate_content("hi")
            nodos.append((m, round(time.time()-t0, 2)))
        except:
            continue

    nodos.sort(key=lambda x: x[1])

    kb = InlineKeyboardMarkup()
    for n, t in nodos:
        kb.add(InlineKeyboardButton(f"{n} ({t}s)", callback_data=f"set_{n}"))

    bot.send_message(message.chat.id, "Selecciona nodo:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("set_"))
def setn(c):
    NODO_ACTIVO[c.message.chat.id] = c.data.replace("set_", "")
    bot.edit_message_text("Nodo activado", c.message.chat.id, c.message.message_id)

# -----------------------------
# ⚽ JUEGO
# -----------------------------
@bot.message_handler(commands=['juego'])
def juego(message):
    nodo = NODO_ACTIVO.get(message.chat.id)

    if not nodo:
        bot.reply_to(message, "Usa /scan primero")
        return

    txt = message.text.replace("/juego", "").strip()

    if " vs " not in txt:
        bot.reply_to(message, "Formato: equipo1 vs equipo2")
        return

    msg = bot.reply_to(message, "Analizando...")

    try:
        e1, e2 = txt.split(" vs ")

        id1, n1 = buscar_team_id(e1)
        id2, n2 = buscar_team_id(e2)

        es_mx1 = False
        es_mx2 = False

        if not id1:
            id1, n1 = buscar_team_id_mx(e1)
            es_mx1 = True

        if not id2:
            id2, n2 = buscar_team_id_mx(e2)
            es_mx2 = True

        if not id1 or not id2:
            bot.edit_message_text(
                "Equipos no encontrados. Usa nombres más claros.",
                message.chat.id,
                msg.message_id
            )
            return

        atk1, def1 = stats_mx(id1) if es_mx1 else stats_europa(id1)
        atk2, def2 = stats_mx(id2) if es_mx2 else stats_europa(id2)

        l1 = (atk1 + def2) / 2 + 0.15
        l2 = (atk2 + def1) / 2

        p1, px, p2 = prob_poisson(l1, l2)

        base = f"""
📊 MODELO PRO:
{n1}: {p1}%
EMPATE: {px}%
{n2}: {p2}%

xG:
{n1}: {round(l1,2)}
{n2}: {round(l2,2)}
"""

        prompt = f"""
Eres el Perro Loco.

{base}

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

# -----------------------------
# 🚀 SERVER
# -----------------------------
def run():
    app.run(host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    Thread(target=run).start()
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
