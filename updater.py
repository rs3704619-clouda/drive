def actualizar_liga(league_id, season=2025):
    print(f"⚽ Actualizando liga {league_id}...")
    url = f"https://v3.football.api-sports.io/teams/statistics?league={league_id}&season={season}"
    headers = {"x-rapidapi-key": SPORTS_KEY}
    
    conn = get_db_connection()
    cur = conn.cursor()

    # 1. Obtener lista de equipos de esa liga
    teams_url = f"https://v3.football.api-sports.io/teams?league={league_id}&season={season}"
    teams_data = requests.get(teams_url, headers=headers).json()

    for item in teams_data.get('response', []):
        team_id = item['team']['id']
        team_name = item['team']['name']
        
        # 2. Pedir stats de cada equipo
        stats_url = f"{url}&team={team_id}"
        s = requests.get(stats_url, headers=headers).json()['response']
        
        if s:
            # Calculamos promedio: Goles Totales / Partidos Jugados
            jugados = s['fixtures']['played']['total'] or 1
            goles_f = s['goals']['for']['total']['total']
            goles_c = s['goals']['against']['total']['total']
            
            avg_f = round(goles_f / jugados, 2)
            avg_c = round(goles_c / jugados, 2)

            # 3. Guardar en Postgres
            cur.execute("""
                INSERT INTO stats_equipos (id_api, nombre, goles_favor_avg, goles_contra_avg, partidos_jugados)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (id_api) DO UPDATE SET 
                    goles_favor_avg = EXCLUDED.goles_favor_avg,
                    goles_contra_avg = EXCLUDED.goles_contra_avg,
                    partidos_jugados = EXCLUDED.partidos_jugados,
                    ultima_actualizacion = CURRENT_TIMESTAMP;
            """, (team_id, team_name, avg_f, avg_c, jugados))
            print(f"✅ {team_name} actualizado ({avg_f} / {avg_c})")

    conn.commit()
    cur.close()
    release_db_connection(conn)
