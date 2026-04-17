"""
Dashboard Streamlit - Qualite de l'air en France
Version cloud-ready : la BDD est generee a la volee au premier lancement,
puis mise en cache 1h pour ne pas surcharger l'API OpenAQ.

Lancement local : streamlit run dashboard/app.py
Deploy cloud    : https://share.streamlit.io
"""

import sys
from pathlib import Path

import streamlit as st
import pandas as pd
import plotly.express as px

# Permettre l'import des modules etl depuis dashboard/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from etl.collect_data import run_pipeline, DB_PATH
from etl.analyse import (
    charger_mesures,
    kpi_global,
    moyennes_par_ville_polluant,
    tendance_journaliere,
    anomalies_recentes,
    SEUILS_OMS,
)

# ─── CONFIG PAGE ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Qualite de l'air - France",
    page_icon="🌫️",
    layout="wide",
)

st.title("🌫️ Qualite de l'air en France")
st.caption("Pipeline ETL Python → SQLite → Streamlit · Donnees OpenAQ v3 · Seuils OMS 2021")


# ─── CHARGEMENT DES DONNEES (avec collecte auto + cache) ──────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def collecter_et_charger(jours: int = 2):
    """
    Lance le pipeline ETL si la BDD n'existe pas ou est vide,
    puis charge les mesures. Cache 1h pour ne pas spammer l'API.
    """
    db_exists = DB_PATH.exists() and DB_PATH.stat().st_size > 10_000

    if not db_exists:
        with st.status("⚙️ Collecte des donnees en cours (1-3 min)...", expanded=True) as status:
            st.write("→ Appel de l'API OpenAQ v3")
            st.write("→ Recuperation des stations sur 7 villes")
            st.write("→ Telechargement des mesures sur 48h")
            st.write("→ Nettoyage et stockage en SQLite")
            run_pipeline(days=jours)
            status.update(label="✅ Collecte terminee", state="complete")

    return charger_mesures()


# Bouton pour forcer le rafraichissement
with st.sidebar:
    st.header("⚙️ Donnees")
    if st.button("🔄 Rafraichir les donnees", use_container_width=True):
        collecter_et_charger.clear()
        if DB_PATH.exists():
            DB_PATH.unlink()
        st.rerun()
    st.caption("Cache : 1h. Click pour forcer une nouvelle collecte.")


try:
    df = collecter_et_charger(jours=2)
except Exception as e:
    st.error(f"Impossible de charger les donnees : {e}")
    st.info(
        "En local : verifie ton fichier `.env` avec OPENAQ_API_KEY. "
        "Sur Streamlit Cloud : verifie les Secrets dans les settings."
    )
    st.stop()

if df.empty:
    st.warning(
        "Aucune donnee recuperee. L'API OpenAQ peut etre temporairement indisponible. "
        "Essaie de rafraichir dans quelques minutes."
    )
    st.stop()


# ─── SIDEBAR : FILTRES ────────────────────────────────────────────────────────

st.sidebar.header("🔍 Filtres")

villes_dispo = sorted(df["ville"].unique())
villes_selec = st.sidebar.multiselect(
    "Villes", villes_dispo, default=villes_dispo
)

polluants_dispo = sorted(df["polluant"].unique())
polluants_selec = st.sidebar.multiselect(
    "Polluants", polluants_dispo, default=polluants_dispo
)

date_min = df["date_heure"].min().date()
date_max = df["date_heure"].max().date()
plage_dates = st.sidebar.date_input(
    "Periode", value=(date_min, date_max),
    min_value=date_min, max_value=date_max
)

# Filtrage du DataFrame
df_f = df[
    (df["ville"].isin(villes_selec)) &
    (df["polluant"].isin(polluants_selec))
]
if isinstance(plage_dates, tuple) and len(plage_dates) == 2:
    d0, d1 = plage_dates
    df_f = df_f[(df_f["date_heure"].dt.date >= d0) &
                (df_f["date_heure"].dt.date <= d1)]


# ─── KPIs GLOBAUX ─────────────────────────────────────────────────────────────

st.subheader("📊 Indicateurs cles")
k = kpi_global(df_f)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Mesures", f"{k['total_mesures']:,}".replace(",", " "))
c2.metric("Villes", k["villes"])
c3.metric("Stations", k["stations"])
c4.metric("Depassements OMS", f"{k['anomalies']:,}".replace(",", " "))
c5.metric("Taux d'anomalies", f"{k['taux_anomalie']}%")


# ─── TENDANCE TEMPORELLE ──────────────────────────────────────────────────────

st.subheader("📈 Evolution dans le temps")

if polluants_selec:
    polluant_graph = st.selectbox("Polluant a afficher", polluants_selec)

    tendance = tendance_journaliere(df_f, polluant=polluant_graph)
    if not tendance.empty:
        seuil = SEUILS_OMS.get(polluant_graph)
        fig = px.line(
            tendance, x="date", y="valeur", color="ville",
            markers=True,
            labels={"valeur": f"{polluant_graph} (moyenne journaliere)", "date": "Date"},
            title=f"{polluant_graph.upper()} - moyenne journaliere par ville"
        )
        if seuil:
            fig.add_hline(y=seuil, line_dash="dash", line_color="red",
                          annotation_text=f"Seuil OMS ({seuil})",
                          annotation_position="top right")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Pas de donnees pour ce polluant sur la periode selectionnee.")


# ─── COMPARATIF PAR VILLE ─────────────────────────────────────────────────────

st.subheader("🏙️ Comparatif par ville")

moyennes = moyennes_par_ville_polluant(df_f)
if not moyennes.empty:
    fig_bar = px.bar(
        moyennes, x="ville", y="valeur_moyenne", color="polluant",
        barmode="group",
        labels={"valeur_moyenne": "Valeur moyenne", "ville": "Ville"},
        title="Moyenne par ville et polluant"
    )
    st.plotly_chart(fig_bar, use_container_width=True)

    st.dataframe(
        moyennes[["ville", "polluant", "valeur_moyenne", "valeur_max",
                  "seuil_oms", "nb_mesures", "nb_depassements",
                  "taux_depassement_pct"]]
        .rename(columns={
            "valeur_moyenne": "Moyenne",
            "valeur_max": "Max",
            "seuil_oms": "Seuil OMS",
            "nb_mesures": "Nb mesures",
            "nb_depassements": "Depassements",
            "taux_depassement_pct": "% depassement",
        }),
        use_container_width=True,
    )


# ─── CARTE DES STATIONS ───────────────────────────────────────────────────────

st.subheader("🗺️ Carte des stations")

carte_df = (df_f.groupby(["station_id", "station_nom", "ville",
                          "latitude", "longitude"])
            .agg(mesures=("valeur", "count"),
                 anomalies=("anomalie", "sum"))
            .reset_index())
carte_df = carte_df.dropna(subset=["latitude", "longitude"])

if not carte_df.empty:
    fig_map = px.scatter_mapbox(
        carte_df, lat="latitude", lon="longitude",
        hover_name="station_nom",
        hover_data={"ville": True, "mesures": True, "anomalies": True,
                    "latitude": False, "longitude": False},
        color="anomalies", size="mesures",
        color_continuous_scale="Reds",
        zoom=4.5, height=500,
    )
    fig_map.update_layout(mapbox_style="open-street-map",
                          margin={"r": 0, "t": 0, "l": 0, "b": 0})
    st.plotly_chart(fig_map, use_container_width=True)


# ─── ANOMALIES RECENTES ───────────────────────────────────────────────────────

st.subheader("⚠️ Anomalies recentes")
st.caption("Mesures depassant les seuils OMS 2021")

anom = anomalies_recentes(df_f, top_n=30)
if anom.empty:
    st.success("Aucun depassement sur la periode selectionnee")
else:
    st.dataframe(anom, use_container_width=True)


# ─── FOOTER ───────────────────────────────────────────────────────────────────

st.markdown("---")
st.caption(
    "Projet personnel · Pipeline ETL Python + SQLite + Streamlit · "
    "Donnees : [OpenAQ](https://openaq.org) · Seuils : [OMS 2021]"
    "(https://www.who.int/publications/i/item/9789240034228)"
)