# 🌫️ Dashboard Qualité de l'Air — France

Pipeline **ETL Python → SQLite → Power BI / Streamlit** pour analyser la qualité de l'air dans 7 villes françaises en temps réel, avec détection automatique des dépassements des seuils OMS.

> **Objectif :** démontrer une maîtrise de bout en bout d'un projet Data Analyst / BI : ingestion d'API REST, modélisation SQL, analyse statistique, visualisation interactive.

---

## 📊 Aperçu

- **7 villes** : Paris, Lyon, Marseille, Bordeaux, Lille, Nantes, Toulouse
- **5 polluants** suivis : PM2.5, PM10, NO₂, O₃, CO
- **Seuils OMS 2021** pour la détection d'anomalies
- **Deux interfaces** : Power BI (rapport téléchargeable) + Streamlit (démo en ligne)

## 🏗️ Architecture

```
API OpenAQ v3  ──►  Pipeline ETL  ──►  SQLite  ──┬──►  Streamlit (démo web)
  (REST)           (Python/pandas)    (3 tables) │
                                                 └──►  CSV ──►  Power BI
```

### Modèle de données

```
stations (id, nom, ville, lat, lon)
    │
    └── sensors (sensor_id, location_id, polluant, unité)
              │
              └── mesures (sensor_id, date_heure, valeur, anomalie)
```

---

## ✨ Fonctionnalités

| Couche | Ce que fait le code |
|---|---|
| **Extract** | Appels à l'API OpenAQ v3 (bounding box par ville, authentification par clé API, gestion du rate limit 429) |
| **Transform** | Nettoyage (doublons, valeurs négatives, aberrations > 10× seuil OMS), typage, flag d'anomalie |
| **Load** | Écriture idempotente en SQLite (contrainte UNIQUE sur `sensor_id + date_heure`) |
| **Analyse** | KPIs par ville/polluant, tendances journalières, top anomalies, pics de pollution |
| **Dashboard** | Streamlit interactif (filtres ville/polluant/période, carte géographique, seuils OMS affichés) |
| **Export BI** | 3 CSV (faits + dimensions + KPIs) prêts pour Power BI |

---

## 🚀 Installation

```bash
# 1. Cloner le repo
git clone https://github.com/TON_USER/qualite-air-france.git
cd qualite-air-france

# 2. Créer un environnement virtuel
python -m venv .venv
source .venv/bin/activate   # Windows : .venv\Scripts\activate

# 3. Installer les dépendances
pip install -r requirements.txt

# 4. Créer une clé API OpenAQ (gratuite, 2 min)
#    → https://explore.openaq.org/register
#    → Copier .env.example en .env et y coller la clé
cp .env.example .env
```

## ▶️ Utilisation

```bash
# Lancer le pipeline ETL (collecte les 7 derniers jours)
python etl/collect_data.py

# Générer les KPIs + exporter les CSV pour Power BI
python etl/analyse.py

# Lancer le dashboard Streamlit
streamlit run dashboard/app.py
```

---

## 📈 Dashboard Power BI

Les CSV générés dans `data/powerbi/` s'importent directement dans Power BI Desktop :

1. **Obtenir les données** → Texte/CSV → sélectionner `mesures.csv`, `stations.csv`, `kpis_ville.csv`
2. Créer les relations : `mesures[station_id]` ↔ `stations[station_id]`
3. Pages suggérées :
   - **Vue d'ensemble** : cartes KPIs (total mesures, anomalies, villes)
   - **Évolution** : courbe temporelle par polluant avec ligne de seuil OMS
   - **Comparatif** : barres empilées par ville × polluant
   - **Carte** : stations géolocalisées, taille = nb mesures, couleur = taux anomalie

---

## 🧰 Stack technique

- **Python 3.10+** — `pandas`, `requests`, `python-dotenv`
- **SQLite** — base locale, pas de serveur à gérer
- **Streamlit + Plotly** — dashboard interactif déployable gratuitement
- **Power BI** — rapport BI pour recruteurs
- **OpenAQ v3 API** — données ouvertes, clé gratuite

---

## 📁 Structure du projet

```
qualite-air-france/
├── etl/
│   ├── collect_data.py      # Pipeline ETL (API → SQLite)
│   └── analyse.py           # KPIs + export Power BI
├── dashboard/
│   └── app.py               # Dashboard Streamlit
├── data/
│   ├── air_quality.db       # BDD SQLite (générée)
│   └── powerbi/             # CSV pour Power BI (générés)
├── .env.example             # Template config (clé API)
├── .gitignore
├── requirements.txt
└── README.md
```

---

## 🎯 Compétences démontrées

- Intégration d'API REST avec authentification et gestion d'erreurs
- Modélisation relationnelle (tables de faits / dimensions)
- Nettoyage et validation de données (detect & handle outliers)
- Analyse exploratoire avec pandas (groupby, agrégations, pivots)
- Visualisation interactive (Streamlit, Plotly)
- Export structuré pour outils BI (Power BI)
- Bonnes pratiques : `.env` pour secrets, `.gitignore`, code modulaire, README documenté

---

## 📚 Sources

- [OpenAQ API v3 documentation](https://docs.openaq.org/)
- [WHO global air quality guidelines 2021](https://www.who.int/publications/i/item/9789240034228)
