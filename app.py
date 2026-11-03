# -*- coding: utf-8 -*-
"""Tableau de bord Streamlit - Candidatures aux 400 bourses UMG / MSHP 2026-2027
Source : API KoboToolbox (formulaire bourses_umg_mshp_2027)
"""
import pandas as pd
import plotly.express as px
import requests
import streamlit as st

st.set_page_config(page_title="Bourses UMG 2027 – Tableau de bord", page_icon="🎓", layout="wide")

# ------------------------------------------------------------------ Configuration
KOBO_SERVER = st.secrets.get("KOBO_SERVER", "https://kf.kobotoolbox.org")
KOBO_TOKEN = st.secrets["KOBO_TOKEN"]
ASSET_UID = st.secrets["KOBO_ASSET_UID"]
APP_PASSWORD = st.secrets.get("APP_PASSWORD", "")
# Sans mot de passe : mode public, aucune donnée nominative n'est affichée
PRIVATE = bool(APP_PASSWORD)

QUOTAS = {"Imagerie médicale / Radiologie": 150, "Anesthésie": 150,
          "Soins pédiatriques": 50, "Soins infirmiers": 50}

LABELS = {
    "programme": {"lim": "Imagerie médicale / Radiologie", "lsp": "Soins pédiatriques",
                  "lsi": "Soins infirmiers", "lan": "Anesthésie"},
    "region": {"boke": "Boké", "conakry": "Conakry", "faranah": "Faranah", "kankan": "Kankan",
               "kindia": "Kindia", "labe": "Labé", "mamou": "Mamou", "nzerekore": "N'Zérékoré"},
    "sexe": {"masculin": "Masculin", "feminin": "Féminin"},
    "statut": {"fonctionnaire": "Fonctionnaire", "contractuel": "Contractuel de l'État",
               "agent_structure": "Agent de la structure", "volontaire": "Volontaire / stagiaire"},
}


# ------------------------------------------------------------------ Accès protégé
def check_password() -> bool:
    if not APP_PASSWORD:
        return True
    if st.session_state.get("auth"):
        return True
    pwd = st.text_input("Mot de passe", type="password")
    if pwd:
        if pwd == APP_PASSWORD:
            st.session_state["auth"] = True
            st.rerun()
        else:
            st.error("Mot de passe incorrect.")
    return False


# ------------------------------------------------------------------ Données
@st.cache_data(ttl=300, show_spinner="Chargement des données Kobo…")
def load_data() -> pd.DataFrame:
    url = f"{KOBO_SERVER}/api/v2/assets/{ASSET_UID}/data/?format=json&limit=1000"
    headers = {"Authorization": f"Token {KOBO_TOKEN}"}
    rows = []
    while url:
        r = requests.get(url, headers=headers, timeout=60)
        r.raise_for_status()
        payload = r.json()
        rows.extend(payload.get("results", []))
        url = payload.get("next")
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # Retire les préfixes de groupes : "g_identite/nom" -> "nom"
    df.columns = [c.split("/")[-1] for c in df.columns]
    df["_submission_time"] = pd.to_datetime(df["_submission_time"], errors="coerce")
    df["date_depot"] = df["_submission_time"].dt.date
    for col in ("age", "anciennete"):
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    # Libellés lisibles
    for col, kind in [("programme_1", "programme"), ("programme_2", "programme"),
                      ("region_actuelle", "region"), ("region_pref_1", "region"),
                      ("sexe", "sexe"), ("statut", "statut")]:
        if col in df:
            df[col] = df[col].map(LABELS[kind]).fillna(df[col])
    if "parcours" in df:
        df["parcours"] = df["parcours"].replace({"CEC": "CEC (sans Bac)", "LPS": "LPS (avec Bac)"})
    # Doublons potentiels (même téléphone, même pièce ou même matricule)
    df["doublon"] = False
    for key in ("telephone", "num_piece", "matricule"):
        if key in df:
            s = df[key].astype(str).str.strip().str.upper()
            df["doublon"] |= s.duplicated(keep=False) & s.ne("") & s.ne("NAN")
    return df


if not check_password():
    st.stop()

st.title("🎓 Candidatures aux 400 bourses UMG – MSHP 2026-2027")

st.sidebar.header("Filtres")
if st.sidebar.button("🔄 Actualiser"):
    st.cache_data.clear()
    st.rerun()

try:
    df = load_data()
except Exception as e:  # noqa: BLE001
    st.error(f"Impossible de charger les données Kobo : {e}")
    st.stop()

if df.empty:
    st.info("Aucune candidature reçue pour le moment.")
    st.caption(f"Projet Kobo interrogé : {ASSET_UID} – serveur : {KOBO_SERVER}. "
               "Si des soumissions existent dans Kobo, vérifiez cet identifiant puis cliquez sur « Actualiser ».")
    st.stop()

# ------------------------------------------------------------------ Filtres
def multiselect(label, col):
    if col not in df:
        return None
    opts = sorted(df[col].dropna().unique())
    return st.sidebar.multiselect(label, opts)


f = df.copy()
for label, col in [("Programme (1er choix)", "programme_1"), ("Région d'affectation", "region_actuelle"),
                   ("Sexe", "sexe"), ("Cursus", "parcours")]:
    sel = multiselect(label, col)
    if sel:
        f = f[f[col].isin(sel)]
if PRIVATE and st.sidebar.checkbox("Afficher uniquement les doublons potentiels"):
    f = f[f["doublon"]]

# ------------------------------------------------------------------ Indicateurs
c1, c2, c3, c4 = st.columns(4)
c1.metric("Candidatures reçues", len(f), help="Quota total : 400 bourses")
if "sexe" in f:
    c2.metric("Femmes", f"{(f['sexe'] == 'Féminin').mean() * 100:.0f} %")
if "age" in f:
    c3.metric("Âge moyen", f"{f['age'].mean():.0f} ans")
c4.metric("Doublons potentiels", int(f["doublon"].sum()))

# ------------------------------------------------------------------ Quotas
st.subheader("Candidatures par rapport aux places disponibles")
q = f["programme_1"].value_counts().reindex(QUOTAS.keys(), fill_value=0).reset_index()
q.columns = ["Programme", "Candidatures"]
q["Places"] = q["Programme"].map(QUOTAS)
q["Taux"] = (q["Candidatures"] / q["Places"] * 100).round(0)
fig = px.bar(q, x="Programme", y=["Candidatures", "Places"], barmode="group",
             color_discrete_sequence=["#1F4E79", "#B0B7C3"])
st.plotly_chart(fig, use_container_width=True)
st.dataframe(q, hide_index=True, use_container_width=True)

# ------------------------------------------------------------------ Répartitions
left, right = st.columns(2)
with left:
    st.subheader("Par région d'affectation")
    if "region_actuelle" in f:
        d = f["region_actuelle"].value_counts().reset_index()
        d.columns = ["Région", "Candidatures"]
        st.plotly_chart(px.bar(d, x="Candidatures", y="Région", orientation="h",
                               color_discrete_sequence=["#1F4E79"]), use_container_width=True)
with right:
    st.subheader("Cursus (CEC / LPS)")
    if "parcours" in f:
        d = f["parcours"].value_counts().reset_index()
        d.columns = ["Cursus", "Candidatures"]
        st.plotly_chart(px.pie(d, names="Cursus", values="Candidatures", hole=0.5),
                        use_container_width=True)

left, right = st.columns(2)
with left:
    st.subheader("Hôpitaux les plus demandés (1er choix)")
    if "hopital_pref_1" in f:
        d = f["hopital_pref_1"].astype(str).str.replace("_", " ").str.title() \
            .value_counts().head(10).reset_index()
        d.columns = ["Hôpital", "Demandes"]
        st.plotly_chart(px.bar(d, x="Demandes", y="Hôpital", orientation="h",
                               color_discrete_sequence=["#2E8B57"]), use_container_width=True)
with right:
    st.subheader("Évolution des dépôts")
    d = f.groupby("date_depot").size().reset_index(name="Candidatures")
    st.plotly_chart(px.line(d, x="date_depot", y="Candidatures", markers=True),
                    use_container_width=True)

# ------------------------------------------------------------------ Tableau et export
if PRIVATE:
    st.subheader("Liste des candidatures")
    cols = [c for c in ["ref_candidature", "nom_complet", "sexe", "age", "telephone", "profession",
                        "structure_nom", "region_actuelle", "parcours", "programme_1", "programme_2",
                        "hopital_pref_1", "date_depot", "doublon"] if c in f]
    st.dataframe(f[cols], hide_index=True, use_container_width=True)
    st.download_button("⬇️ Exporter en CSV", f[cols].to_csv(index=False).encode("utf-8-sig"),
                       "candidatures_bourses.csv", "text/csv")
else:
    st.caption("🔒 Accès public : seules les statistiques sont affichées. "
               "La liste nominative des candidats n'est pas disponible.")
