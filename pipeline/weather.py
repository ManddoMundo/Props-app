"""Kickoff weather for this week's outdoor NFL games: wind and temperature from the Open-Meteo forecast (free, no key),
averaged over the three hours from kickoff. Writes out/weather.json {game_id: {wind, temp, asof}}. Only outdoor stadiums
at their own home field are asked for; domes, retractable roofs and neutral sites get nothing. Display and tracking only.
A failure leaves the last file in place and the Games tab simply shows no wind note."""
import json, os, datetime, urllib.request, urllib.parse
import pandas as pd

D = "/home/claude/props/data/"
O = "/home/claude/props/out/"
# outdoor stadiums by home club: latitude, longitude
ST = {"BUF": (42.774, -78.787), "MIA": (25.958, -80.239), "NE": (42.091, -71.264), "NYJ": (40.813, -74.074), "NYG": (40.813, -74.074),
      "BAL": (39.278, -76.623), "CIN": (39.095, -84.516), "CLE": (41.506, -81.699), "PIT": (40.447, -80.016), "JAX": (30.324, -81.637),
      "TEN": (36.166, -86.771), "DEN": (39.744, -105.020), "KC": (39.049, -94.484), "PHI": (39.901, -75.168), "WAS": (38.908, -76.864),
      "CHI": (41.862, -87.617), "GB": (44.501, -88.062), "CAR": (35.226, -80.853), "TB": (27.976, -82.503), "SF": (37.403, -121.970),
      "SEA": (47.595, -122.332)}


def forecast(lat, lon, day, hour):
    q = urllib.parse.urlencode(dict(latitude=lat, longitude=lon, hourly="wind_speed_10m,temperature_2m", wind_speed_unit="mph",
                                    temperature_unit="fahrenheit", timezone="America/New_York", start_date=day, end_date=day))
    with urllib.request.urlopen("https://api.open-meteo.com/v1/forecast?" + q, timeout=30) as r:
        h = json.load(r)["hourly"]
    idx = [i for i, t in enumerate(h["time"]) if hour <= int(t[11:13]) <= hour + 2]
    w = [h["wind_speed_10m"][i] for i in idx if h["wind_speed_10m"][i] is not None]
    t = [h["temperature_2m"][i] for i in idx if h["temperature_2m"][i] is not None]
    if not w:
        return None
    return dict(wind=round(sum(w) / len(w), 1), temp=round(sum(t) / len(t)) if t else None)


def main():
    g = pd.read_csv(D + "nfl_games.csv", low_memory=False)
    up = g[(g.season == g.season.max()) & g.result.isna()]
    if up.empty:
        print("weather: no games ahead"); return
    up = up[up.week == up.week.min()]
    today = datetime.date.today()
    out, n, bad = {}, 0, 0
    for r in up.itertuples():
        if r.roof != "outdoors" or r.location != "Home" or r.home_team not in ST:
            continue
        try:
            day = datetime.date.fromisoformat(str(r.gameday))
            if not (0 <= (day - today).days <= 14):
                continue
            f = forecast(*ST[r.home_team], str(r.gameday), int(str(r.gametime)[:2]))
            if f:
                f["asof"] = today.isoformat(); out[r.game_id] = f; n += 1
        except Exception as e:
            bad += 1; err = str(e)[:80]
    if n:
        json.dump(out, open(O + "weather.json", "w"), separators=(",", ":"))
    print(f"weather: {n} outdoor games with a forecast" + (f", {bad} failed ({err})" if bad else ""))


if __name__ == "__main__":
    main()
