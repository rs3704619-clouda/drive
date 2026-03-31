import requests
import json
import os

SPORTS_KEY = os.environ.get("SPORTS_KEY")

def fetch_league_stats(league_id, season=2025):
    url = "https://v3.football.api-sports.io/standings"
    headers = {"x-apisports-key": SPORTS_KEY}
    params = {"league": league_id, "season": season}
    
    try:
        r = requests.get(url, headers=headers, params=params)
        data = r.json()['response'][0]['league']['standings'][0]
        
        stats = {}
        for team in data:
            name = team['team']['name'].lower()
            # Calculamos promedios simples para Poisson
            played = team['all']['played']
            goals_for = team['all']['goals']['for']
            goals_against = team['all']['goals']['against']
            
            stats[name] = {
                "attack": goals_for / played if played > 0 else 0,
                "defense": goals_against / played if played > 0 else 0,
                "points": team['points']
            }
        
        with open("stats_model.json", "w") as f:
            json.dump(stats, f)
        print("Modelo actualizado correctamente.")
        
    except Exception as e:
        print(f"Error entrenando: {e}")

if __name__ == "__main__":
    # Ejemplo: 140 es La Liga, 39 Premier League, etc.
    fetch_league_stats(league_id=39)
