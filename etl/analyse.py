"""
Analyse - KPIs et detection d'anomalies sur la qualite de l'air.
Sert a la fois pour le dashboard Streamlit ET pour exporter vers Power BI.
"""

import sqlite3
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "air_quality.db"

SEUILS_OMS = {
    "pm25": 15,
    "pm10": 45,
    "no2": 25,
    "o3": 100,
    "co": 4,
}


# ─── LECTURE BDD ──────────────────────────────────────────────────────────────

def charger_mesures() -> pd.DataFrame:
    """Charge toutes les mesures + infos station depuis la BDD."""
    conn = sqlite3.connect(DB_PATH)
    query = """
        SELECT
            m.date_heure,
            m.polluant,
            m.valeur,
            m.unite,
            m.anomalie,
            s.id AS station_id,
            s.nom AS station_nom,
            s.ville,
            s.latitude,
            s.longitude
        FROM mesures m
        JOIN stations s ON s.id = m.location_id
        ORDER BY m.date_heure
    """
    df = pd.read_sql_query(query, conn, parse_dates=["date_heure"])
    conn.close()
    return df


# ─── KPIs ─────────────────────────────────────────────────────────────────────

def kpi_global(df: pd.DataFrame) -> dict:
    """KPIs d'ensemble pour la page d'accueil du dashboard."""
    if df.empty:
        return {
            "total_mesures": 0, "villes": 0, "stations": 0,
            "anomalies": 0, "taux_anomalie": 0.0
        }
    return {
        "total_mesures": len(df),
        "villes":        df["ville"].nunique(),
        "stations":      df["station_id"].nunique(),
        "anomalies":     int(df["anomalie"].sum()),
        "taux_anomalie": round(df["anomalie"].mean() * 100, 2),
    }


def moyennes_par_ville_polluant(df: pd.DataFrame) -> pd.DataFrame:
    """Moyenne de chaque polluant par ville + taux de depassement du seuil OMS."""
    if df.empty:
        return pd.DataFrame()
    agg = df.groupby(["ville", "polluant"]).agg(
        valeur_moyenne=("valeur", "mean"),
        valeur_max=("valeur", "max"),
        nb_mesures=("valeur", "count"),
        nb_depassements=("anomalie", "sum"),
    ).reset_index()
    agg["taux_depassement_pct"] = round(agg["nb_depassements"] / agg["nb_mesures"] * 100, 2)
    agg["seuil_oms"] = agg["polluant"].map(SEUILS_OMS)
    agg["valeur_moyenne"] = agg["valeur_moyenne"].round(2)
    agg["valeur_max"] = agg["valeur_max"].round(2)
    return agg


def tendance_journaliere(df: pd.DataFrame, ville: str = None,
                         polluant: str = None) -> pd.DataFrame:
    """Moyenne journaliere pour la courbe temporelle."""
    if df.empty:
        return pd.DataFrame()
    tmp = df.copy()
    if ville:
        tmp = tmp[tmp["ville"] == ville]
    if polluant:
        tmp = tmp[tmp["polluant"] == polluant]
    if tmp.empty:
        return pd.DataFrame()

    tmp["date"] = tmp["date_heure"].dt.date
    return (tmp.groupby(["date", "ville", "polluant"])["valeur"]
               .mean()
               .round(2)
               .reset_index())


# ─── DETECTION D'ANOMALIES ────────────────────────────────────────────────────

def anomalies_recentes(df: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    """Top N des depassements les plus recents avec le ratio vs seuil OMS."""
    if df.empty:
        return pd.DataFrame()
    anom = df[df["anomalie"] == 1].copy()
    if anom.empty:
        return pd.DataFrame()
    anom["seuil_oms"] = anom["polluant"].map(SEUILS_OMS)
    anom["ratio_seuil"] = (anom["valeur"] / anom["seuil_oms"]).round(2)
    anom = anom.sort_values("date_heure", ascending=False).head(top_n)
    return anom[["date_heure", "ville", "station_nom", "polluant",
                 "valeur", "unite", "seuil_oms", "ratio_seuil"]]


def pics_par_ville(df: pd.DataFrame) -> pd.DataFrame:
    """Pour chaque ville+polluant, la valeur max observee."""
    if df.empty:
        return pd.DataFrame()
    idx = df.groupby(["ville", "polluant"])["valeur"].idxmax()
    pics = df.loc[idx, ["ville", "polluant", "valeur", "unite",
                        "date_heure", "station_nom"]].copy()
    pics["seuil_oms"] = pics["polluant"].map(SEUILS_OMS)
    pics["ratio_seuil"] = (pics["valeur"] / pics["seuil_oms"]).round(2)
    return pics.sort_values(["ville", "polluant"]).reset_index(drop=True)


# ─── EXPORT CSV POUR POWER BI ─────────────────────────────────────────────────

def exporter_pour_powerbi(dossier: str = None):
    """
    Exporte 3 CSV pretes a etre importees dans Power BI :
      - mesures.csv         : table de faits
      - stations.csv        : dimension stations
      - kpis_ville.csv      : KPIs agreges
    """
    if dossier is None:
        dossier = Path(__file__).resolve().parent.parent / "data" / "powerbi"
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)

    df = charger_mesures()

    # Table de faits : mesures
    faits = df[["date_heure", "station_id", "polluant", "valeur",
                "unite", "anomalie"]].copy()
    faits["seuil_oms"] = faits["polluant"].map(SEUILS_OMS)
    faits.to_csv(dossier / "mesures.csv", index=False, encoding="utf-8-sig")

    # Dimension stations (unique)
    dim_stations = df[["station_id", "station_nom", "ville",
                       "latitude", "longitude"]].drop_duplicates()
    dim_stations.to_csv(dossier / "stations.csv", index=False, encoding="utf-8-sig")

    # KPIs agreges
    kpis = moyennes_par_ville_polluant(df)
    kpis.to_csv(dossier / "kpis_ville.csv", index=False, encoding="utf-8-sig")

    print(f"Export Power BI termine dans : {dossier}")
    print(f"  - mesures.csv       ({len(faits)} lignes)")
    print(f"  - stations.csv      ({len(dim_stations)} lignes)")
    print(f"  - kpis_ville.csv    ({len(kpis)} lignes)")


if __name__ == "__main__":
    df = charger_mesures()
    print("\n=== KPIs globaux ===")
    print(kpi_global(df))

    print("\n=== Moyennes par ville x polluant ===")
    print(moyennes_par_ville_polluant(df))

    print("\n=== Top 10 anomalies recentes ===")
    print(anomalies_recentes(df, top_n=10))

    print("\n=== Export Power BI ===")
    exporter_pour_powerbi()
