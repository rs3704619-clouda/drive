import os
import psycopg2
import requests
import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

# 1. CONFIGURACIÓN (football-data.org usa X-Auth-Token)
API_KEY = os.getenv('API_KEY_FUTBOL')
DATABASE_URL = os.getenv('DATABASE_URL')
# Liga: PD = Primera División España, PL = Premier League, CL = Champions
LEAGUE_CODE = 'PD' 
SEASON = 2024

def obtener_datos_api():
    print(f"Descargando resultados de football-data.org para {LEAGUE_CODE}...")
    # La URL cambia a /v4/competitions/
    url = f"https://api.football-data.org/v4/competitions/{LEAGUE_CODE}/matches?season={SEASON}&status=FINISHED"
    headers = {'X-Auth-Token': API_KEY}
    
    response = requests.get(url, headers=headers).json()
    
    # Verificamos si hay error de permisos o de plan
    if 'matches' not in response:
        print(f"Error de la API: {response.get('message', 'No se encontraron partidos')}")
        return []

    print(f"Total de partidos encontrados: {len(response['matches'])}")
    
    partidos = []
    for m in response['matches']:
        local = m['homeTeam']['name']
        visita = m['awayTeam']['name']
        goles_l = m['score']['fullTime']['home']
        goles_v = m['score']['fullTime']['away']
        
        # Solo agregamos si tienen goles (partidos terminados)
        if goles_l is not None and goles_v is not None:
            partidos.append([local, visita, goles_l, goles_v])
            
    return partidos

# --- MATEMÁTICA DE POISSON ---

def funcion_objetivo(params, partidos, nombres_equipos):
    n = len(nombres_equipos)
    atk, dfn = params[:n], params[n:2*n]
    home_adv = params[-1]
    log_v = 0
    for loc, vis, g_l, g_v in partidos:
        idx_l, idx_v = nombres_equipos.index(loc), nombres_equipos.index(vis)
        l_l = np.exp(atk[idx_l] - dfn[idx_v] + home_adv)
        l_v = np.exp(atk[idx_v] - dfn[idx_l])
        log_v += poisson.logpmf(g_l, l_l) + poisson.logpmf(g_v, l_v)
    return -log_v

def entrenar_y_subir():
    partidos = obtener_datos_api()
    if not partidos:
        print("Cerrando: No hay datos para entrenar.")
        return

    equipos = list(set([p[0] for p in partidos] + [p[1] for p in partidos]))
    n = len(equipos)
    
    print(f"Calculando potencia de {n} equipos...")
    res = minimize(funcion_objetivo, np.zeros(2*n + 1), args=(partidos, equipos))
    atk_f, dfn_f, home_f = res.x[:n], res.x[n:2*n], res.x[-1]

    # GUARDAR EN RAILWAY
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
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
    print("¡Base de datos actualizada con datos de football-data.org!")
    cur.close()
    conn.close()

if __name__ == "__main__":
    entrenar_y_subir()
