import os
import psycopg2
import requests
import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

# 1. CONFIGURACIÓN DE CRENDECIALES (Se leen de GitHub Secrets)
DATABASE_URL = os.getenv('DATABASE_URL')
API_KEY = os.getenv('API_KEY_FUTBOL')
LEAGUE_ID = 140  # Ejemplo: LaLiga. Cambia según necesites.
SEASON = 2025

def obtener_datos_api():
    print("Descargando resultados de la API...")
    url = f"https://v3.football.api-sports.io/fixtures?league={LEAGUE_ID}&season={SEASON}&status=FT"
    headers = {'x-apisports-key': API_KEY}
    response = requests.get(url, headers=headers).json()
    
    partidos = []
    for f in response['response']:
        local = f['teams']['home']['name']
        visita = f['teams']['away']['name']
        goles_l = f['goals']['home']
        goles_v = f['goals']['away']
        partidos.append([local, visita, goles_l, goles_v])
    return partidos

def funcion_objetivo(params, partidos, nombres_equipos):
    n = len(nombres_equipos)
    atk, dfn = params[:n], params[n:2*n]
    home_adv = params[-1]
    log_v = 0
    for loc, vis, g_l, g_v in partidos:
        if g_l is None or g_v is None: continue
        idx_l, idx_v = nombres_equipos.index(loc), nombres_equipos.index(vis)
        l_l = np.exp(atk[idx_l] - dfn[idx_v] + home_adv)
        l_v = np.exp(atk[idx_v] - dfn[idx_l])
        log_v += poisson.logpmf(g_l, l_l) + poisson.logpmf(g_v, l_v)
    return -log_v

def entrenar_y_subir():
    partidos = obtener_datos_api()
    if not partidos: 
        print("No hay partidos finalizados para entrenar.")
        return

    equipos = list(set([p[0] for p in partidos] + [p[1] for p in partidos]))
    n = len(equipos)
    
    print(f"Entrenando modelo para {n} equipos...")
    res = minimize(funcion_objetivo, np.zeros(2*n + 1), args=(partidos, equipos))
    atk_f, dfn_f, home_f = res.x[:n], res.x[n:2*n], res.x[-1]

    # CONEXIÓN A RAILWAY
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    # Crear tabla si no existe
    cur.execute("""
        CREATE TABLE IF NOT EXISTS modelo_futbol (
            equipo VARCHAR PRIMARY KEY,
            ataque FLOAT,
            defensa FLOAT,
            home_adv FLOAT,
            actualizado TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    for i, nombre in enumerate(equipos):
        cur.execute("""
            INSERT INTO modelo_futbol (equipo, ataque, defensa, home_adv)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (equipo) DO UPDATE SET 
            ataque=EXCLUDED.ataque, defensa=EXCLUDED.defensa, home_adv=EXCLUDED.home_adv, actualizado=now();
        """, (nombre, float(atk_f[i]), float(dfn_f[i]), float(home_f)))
    
    conn.commit()
    print("¡Base de datos en Railway actualizada con éxito!")
    cur.close()
    conn.close()

if __name__ == "__main__":
    entrenar_y_subir()
