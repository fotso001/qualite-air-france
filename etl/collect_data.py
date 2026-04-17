"""
ETL - Collecte des donnees de qualite de l'air via l'API OpenAQ v3
Doc : https://docs.openaq.org/

IMPORTANT : il faut une cle API gratuite.
1. S'inscrire sur https://explore.openaq.org/register
2. Recuperer la cle dans "Account settings"
3. La mettre dans un fichier .env a la racine du projet :
       OPENAQ_API_KEY=ta_cle_ici
"""

import os
import time
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import pandas as pd
from dotenv import load_dotenv

# ─── CONFIG ───────────────────────────────────────────────────────────────────
load_dotenv()

API_KEY = os.getenv("OPENAQ_API_KEY")

# Fallback pour Streamlit Cloud (qui utilise st.secrets au lieu de .env)
if not API_KEY:
    try:
        import streamlit as st
        API_KEY = st.secrets.get("OPENAQ_API_KEY")
    except Exception:
        pass

if not API_KEY:
    raise RuntimeError(
        "OPENAQ_API_KEY manquante. "
        "En local : cree un fichier .env avec OPENAQ_API_KEY=ta_cle. "
        "Sur Streamlit Cloud : ajoute-la dans Settings > Secrets."
    )

BASE_URL = "https://api.openaq.org/v3"
HEADERS = {"X-API-Key": API_KEY}

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "air_quality.db"

# On cible des villes francaises via bounding box (lat_min, lon_min, lat_max, lon_max)
# Plutot que filtrer par nom (peu fiable), on cible par coordonnees.
VILLES = {
    "Paris":       (48.815, 2.224, 48.902, 2.470),
    "Lyon":        (45.707, 4.771, 45.808, 4.898),
    "Marseille":   (43.213, 5.228, 43.396, 5.532),
    "Bordeaux":    (44.810, -0.635, 44.913, -0.525),
    "Lille":       (50.600, 2.964, 50.660, 3.127),
    "Nantes":      (47.180, -1.625, 47.290, -1.470),
    "Toulouse":    (43.548, 1.350, 43.668, 1.507),
}

# Polluants qu'on suit (noms OpenAQ v3)
POLLUANTS = ["pm25", "pm10", "no2", "o3", "co"]

# Seuils OMS 2021 (moyenne journaliere, µg/m³ sauf co en mg/m³)
SEUILS_OMS = {
    "pm25": 15,
    "pm10": 45,
    "no2": 25,
    "o3": 100,
    "co": 4,        # mg/m³ — attention unite differente
}

# Rate limit : OpenAQ v3 = 60 req/min en anonyme, on dort un peu entre appels
SLEEP_BETWEEN_CALLS = 1.1


# ─── APPELS API ───────────────────────────────────────────────────────────────

def api_get(endpoint: str, params: dict = None) -> dict:
    """Appel API generique avec gestion d'erreurs et rate limit."""
    url = f"{BASE_URL}{endpoint}"
    try:
        r = requests.get(url, headers=HEADERS, params=params or {}, timeout=20)
        time.sleep(SLEEP_BETWEEN_CALLS)
        if r.status_code == 401:
            raise RuntimeError("Cle API invalide. Verifie ton fichier .env")
        if r.status_code == 429:
            print("  Rate limit atteint, pause 30s...")
            time.sleep(30)
            return api_get(endpoint, params)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        print(f"  Erreur API {endpoint} : {e}")
        return {"results": []}


def get_locations_in_bbox(lat_min, lon_min, lat_max, lon_max) -> list:
    """
    Recupere les stations dans une bounding box.
    Doc : https://docs.openaq.org/using-the-api/geospatial
    """
    # Format bbox OpenAQ : minx,miny,maxx,maxy = lon_min,lat_min,lon_max,lat_max
    bbox = f"{lon_min},{lat_min},{lon_max},{lat_max}"
    data = api_get("/locations", {"bbox": bbox, "limit": 100})
    return data.get("results", [])


def get_measurements_for_sensor(sensor_id: int, days: int = 7) -> list:
    """
    Recupere les mesures horaires d'un capteur sur les N derniers jours.
    Endpoint v3 : /sensors/{id}/hours
    """
    date_to = datetime.now(timezone.utc)
    date_from = date_to - timedelta(days=days)

    params = {
        "datetime_from": date_from.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "datetime_to":   date_to.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "limit": 1000,
    }
    data = api_get(f"/sensors/{sensor_id}/hours", params)
    return data.get("results", [])


# ─── TRANSFORMATION ───────────────────────────────────────────────────────────

def extraire_stations(locations: list, ville: str) -> list:
    """Extrait les infos utiles des stations."""
    stations = []
    for loc in locations:
        coords = loc.get("coordinates") or {}
        stations.append({
            "id": loc["id"],
            "nom": loc.get("name") or f"Station {loc['id']}",
            "ville": ville,
            "latitude": coords.get("latitude"),
            "longitude": coords.get("longitude"),
        })
    return stations


def extraire_sensors(locations: list) -> list:
    """Extrait les capteurs (un capteur = un polluant mesure sur une station)."""
    sensors = []
    for loc in locations:
        for s in loc.get("sensors", []):
            param = s.get("parameter", {})
            polluant = param.get("name")
            if polluant in POLLUANTS:
                sensors.append({
                    "sensor_id": s["id"],
                    "location_id": loc["id"],
                    "polluant": polluant,
                    "unite": param.get("units"),
                })
    return sensors


def mesures_vers_df(mesures: list, sensor_id: int, location_id: int,
                    polluant: str, unite: str) -> pd.DataFrame:
    """Convertit les mesures JSON en DataFrame."""
    if not mesures:
        return pd.DataFrame()

    rows = []
    for m in mesures:
        periode = m.get("period") or {}
        datetime_from = periode.get("datetimeFrom") or {}
        rows.append({
            "sensor_id": sensor_id,
            "location_id": location_id,
            "polluant": polluant,
            "valeur": m.get("value"),
            "unite": unite,
            "date_heure": datetime_from.get("utc"),
            "collecte_le": datetime.now(timezone.utc).isoformat(),
        })
    return pd.DataFrame(rows)


def nettoyer(df: pd.DataFrame) -> pd.DataFrame:
    """Nettoyage : doublons, valeurs negatives, aberrations."""
    if df.empty:
        return df

    df = df.dropna(subset=["valeur", "date_heure"])
    df = df.drop_duplicates(subset=["sensor_id", "date_heure"])
    df = df[df["valeur"] >= 0]

    # Filtre aberrations : > 10x le seuil OMS
    def valide(row):
        seuil = SEUILS_OMS.get(row["polluant"])
        return seuil is None or row["valeur"] <= seuil * 10

    df = df[df.apply(valide, axis=1)].copy()
    df["date_heure"] = pd.to_datetime(df["date_heure"], errors="coerce")
    df = df.dropna(subset=["date_heure"])

    # Flag anomalie = valeur > seuil OMS
    df["anomalie"] = df.apply(
        lambda r: 1 if SEUILS_OMS.get(r["polluant"]) and r["valeur"] > SEUILS_OMS[r["polluant"]] else 0,
        axis=1
    )
    return df


# ─── STOCKAGE SQLITE ──────────────────────────────────────────────────────────

def init_db():
    """Cree les tables si elles n'existent pas."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS stations (
            id          INTEGER PRIMARY KEY,
            nom         TEXT,
            ville       TEXT,
            latitude    REAL,
            longitude   REAL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sensors (
            sensor_id   INTEGER PRIMARY KEY,
            location_id INTEGER,
            polluant    TEXT,
            unite       TEXT,
            FOREIGN KEY (location_id) REFERENCES stations(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS mesures (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            sensor_id    INTEGER,
            location_id  INTEGER,
            polluant     TEXT,
            valeur       REAL,
            unite        TEXT,
            date_heure   TEXT,
            collecte_le  TEXT,
            anomalie     INTEGER DEFAULT 0,
            UNIQUE(sensor_id, date_heure),
            FOREIGN KEY (sensor_id) REFERENCES sensors(sensor_id)
        )
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_mesures_date ON mesures(date_heure)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_mesures_polluant ON mesures(polluant)")

    conn.commit()
    conn.close()
    print(f"BDD initialisee : {DB_PATH}")


def sauvegarder_stations(stations: list):
    conn = sqlite3.connect(DB_PATH)
    for s in stations:
        conn.execute("""
            INSERT OR REPLACE INTO stations (id, nom, ville, latitude, longitude)
            VALUES (?, ?, ?, ?, ?)
        """, (s["id"], s["nom"], s["ville"], s["latitude"], s["longitude"]))
    conn.commit()
    conn.close()


def sauvegarder_sensors(sensors: list):
    conn = sqlite3.connect(DB_PATH)
    for s in sensors:
        conn.execute("""
            INSERT OR REPLACE INTO sensors (sensor_id, location_id, polluant, unite)
            VALUES (?, ?, ?, ?)
        """, (s["sensor_id"], s["location_id"], s["polluant"], s["unite"]))
    conn.commit()
    conn.close()


def sauvegarder_mesures(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    conn = sqlite3.connect(DB_PATH)
    df_out = df.copy()
    df_out["date_heure"] = df_out["date_heure"].astype(str)
    # INSERT OR IGNORE pour gerer les doublons sans planter
    inserted = 0
    for _, row in df_out.iterrows():
        try:
            conn.execute("""
                INSERT OR IGNORE INTO mesures
                (sensor_id, location_id, polluant, valeur, unite, date_heure, collecte_le, anomalie)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (row["sensor_id"], row["location_id"], row["polluant"],
                  row["valeur"], row["unite"], row["date_heure"],
                  row["collecte_le"], row["anomalie"]))
            if conn.total_changes > inserted:
                inserted = conn.total_changes
        except Exception as e:
            print(f"    Erreur insert : {e}")
    conn.commit()
    conn.close()
    return inserted


# ─── PIPELINE ─────────────────────────────────────────────────────────────────

def run_pipeline(days: int = 7):
    print("=" * 60)
    print(f"PIPELINE QUALITE DE L'AIR - {datetime.now():%Y-%m-%d %H:%M}")
    print("=" * 60)

    init_db()

    total_stations = 0
    total_sensors = 0
    total_mesures = 0

    for ville, bbox in VILLES.items():
        print(f"\n[{ville}]")
        locations = get_locations_in_bbox(*bbox)
        if not locations:
            print(f"  Aucune station trouvee")
            continue

        stations = extraire_stations(locations, ville)
        sensors = extraire_sensors(locations)

        sauvegarder_stations(stations)
        sauvegarder_sensors(sensors)
        total_stations += len(stations)
        total_sensors += len(sensors)
        print(f"  {len(stations)} stations, {len(sensors)} capteurs")

        # Recuperer les mesures pour chaque capteur
        for s in sensors:
            mesures_raw = get_measurements_for_sensor(s["sensor_id"], days=days)
            df = mesures_vers_df(
                mesures_raw, s["sensor_id"], s["location_id"],
                s["polluant"], s["unite"]
            )
            df = nettoyer(df)
            n = sauvegarder_mesures(df)
            total_mesures += n
            if n > 0:
                print(f"    sensor {s['sensor_id']} ({s['polluant']}) : {n} mesures")

    print("\n" + "=" * 60)
    print(f"TERMINE - {total_stations} stations | {total_sensors} capteurs | {total_mesures} mesures")
    print(f"BDD : {DB_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    run_pipeline(days=7)