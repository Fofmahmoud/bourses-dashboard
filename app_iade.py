# -*- coding: utf-8 -*-
"""Tableau de bord Streamlit - Candidatures à la bourse de formation IADE
(Anesthésie-Réanimation, Université Gamal Abdel Nasser de Conakry)
Source : API KoboToolbox (formulaire bourse_uganc_iade)
"""
import re
import unicodedata

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

st.set_page_config(page_title="Bourse IADE – Tableau de bord", page_icon="🩺", layout="wide")

# ------------------------------------------------------------------ Configuration
KOBO_SERVER = st.secrets.get("KOBO_SERVER", "https://kf.kobotoolbox.org")
KOBO_TOKEN = st.secrets["KOBO_TOKEN"]
ASSET_UID = st.secrets["KOBO_ASSET_UID"]
APP_PASSWORD = st.secrets.get("APP_PASSWORD", "")
# Sans mot de passe : mode public, aucune donnée nominative n'est affichée
PRIVATE = bool(APP_PASSWORD)

MAX_PAR_STRUCTURE = 2  # « 1 à 2 agents par structure »

LABELS = {
    "region": {"boke": "Boké", "conakry": "Conakry", "faranah": "Faranah", "kankan": "Kankan",
               "kindia": "Kindia", "labe": "Labé", "mamou": "Mamou", "nzerekore": "N'Zérékoré"},
    "sexe": {"masculin": "Masculin", "feminin": "Féminin"},
    "statut": {"fonctionnaire": "Fonctionnaire de l'État", "contractuel": "Contractuel de l'État"},
    "service": {"bloc": "Bloc opératoire", "reanimation": "Réanimation",
                "soins_intensifs": "Soins intensifs", "autre": "Autre service"},
    "type_structure": {"cmc": "CMC", "csa": "CSA", "hop_prefectoral": "Hôpital préfectoral",
                       "hop_regional": "Hôpital régional", "hop_national": "Hôpital national",
                       "autre": "Autre structure"},
}


def norm(s) -> str:
    """Normalise un nom de structure pour regrouper les variantes d'écriture."""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


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
    df.columns = [c.split("/")[-1] for c in df.columns]
    df["_submission_time"] = pd.to_datetime(df["_submission_time"], errors="coerce")
    df["date_depot"] = df["_submission_time"].dt.date
    for col in ("age", "anciennete", "anciennete_service"):
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col, kind in [("region_actuelle", "region"), ("sexe", "sexe"), ("statut", "statut"),
                      ("service", "service"), ("type_structure", "type_structure")]:
        if col in df:
            df[col] = df[col].map(LABELS[kind]).fillna(df[col])
    if "structure_nom" in df:
        df["structure_cle"] = df["structure_nom"].map(norm)
    # Doublons potentiels (même téléphone, même pièce ou même matricule)
    df["doublon"] = False
    for key in ("telephone", "num_piece", "matricule"):
        if key in df:
            s = df[key].astype(str).str.strip().str.upper()
            df["doublon"] |= s.duplicated(keep=False) & s.ne("") & s.ne("NAN")
    return df


if not check_password():
    st.stop()

st.title("🩺 Candidatures – Bourse de formation IADE (Anesthésie-Réanimation)")
st.caption("Université Gamal Abdel Nasser de Conakry · MSHP")

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
    return st.sidebar.multiselect(label, sorted(df[col].dropna().unique()))


f = df.copy()
for label, col in [("Région d'affectation", "region_actuelle"), ("Type de structure", "type_structure"),
                   ("Service", "service"), ("Statut", "statut"), ("Sexe", "sexe")]:
    sel = multiselect(label, col)
    if sel:
        f = f[f[col].isin(sel)]
if PRIVATE and st.sidebar.checkbox("Afficher uniquement les doublons potentiels"):
    f = f[f["doublon"]]

# ------------------------------------------------------------------ Structures (quota 1 à 2)
if "structure_cle" in f:
    par_struct = (f.groupby("structure_cle")
                  .agg(Structure=("structure_nom", "first"),
                       Région=("region_actuelle", "first"),
                       Candidatures=("structure_nom", "size"))
                  .reset_index(drop=True)
                  .sort_values("Candidatures", ascending=False))
    depassent = par_struct[par_struct["Candidatures"] > MAX_PAR_STRUCTURE]
else:
    par_struct, depassent = pd.DataFrame(), pd.DataFrame()

# ------------------------------------------------------------------ Indicateurs
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Candidatures reçues", len(f))
c2.metric("Structures représentées", len(par_struct))
if "sexe" in f:
    c3.metric("Femmes", f"{(f['sexe'] == 'Féminin').mean() * 100:.0f} %")
if "age" in f:
    c4.metric("Âge moyen", f"{f['age'].mean():.0f} ans")
if "anciennete_service" in f:
    c5.metric("Exp. bloc/réa (moy.)", f"{f['anciennete_service'].mean():.1f} ans")

# ------------------------------------------------------------------ Alerte quota par structure
st.subheader(f"Quota : {MAX_PAR_STRUCTURE} candidats maximum par structure")
if len(depassent):
    st.warning(f"{len(depassent)} structure(s) dépassent {MAX_PAR_STRUCTURE} candidatures. "
               "Un arbitrage est nécessaire.")
    st.dataframe(depassent, hide_index=True, use_container_width=True)
else:
    st.success(f"Aucune structure ne dépasse {MAX_PAR_STRUCTURE} candidatures.")
with st.expander("Voir toutes les structures"):
    st.dataframe(par_struct, hide_index=True, use_container_width=True)

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
    st.subheader("Par type de structure")
    if "type_structure" in f:
        d = f["type_structure"].value_counts().reset_index()
        d.columns = ["Type", "Candidatures"]
        st.plotly_chart(px.pie(d, names="Type", values="Candidatures", hole=0.5),
                        use_container_width=True)

left, right = st.columns(2)
with left:
    st.subheader("Service d'exercice")
    if "service" in f:
        d = f["service"].value_counts().reset_index()
        d.columns = ["Service", "Candidatures"]
        st.plotly_chart(px.bar(d, x="Service", y="Candidatures",
                               color_discrete_sequence=["#2E8B57"]), use_container_width=True)
with right:
    st.subheader("Répartition par âge (35 ans maximum)")
    if "age" in f:
        st.plotly_chart(px.histogram(f.dropna(subset=["age"]), x="age", nbins=16,
                                     labels={"age": "Âge"}, color_discrete_sequence=["#1F4E79"]),
                        use_container_width=True)

st.subheader("Évolution des dépôts")
d = f.groupby("date_depot").size().reset_index(name="Candidatures")
st.plotly_chart(px.line(d, x="date_depot", y="Candidatures", markers=True), use_container_width=True)

# ------------------------------------------------------------------ Liste et export
if PRIVATE:
    st.subheader("Liste des candidatures")
    cols = [c for c in ["ref_candidature", "nom_complet", "sexe", "age", "telephone", "statut",
                        "service", "structure_nom", "type_structure", "region_actuelle",
                        "anciennete", "anciennete_service", "date_depot", "doublon"] if c in f]
    st.dataframe(f[cols], hide_index=True, use_container_width=True)
    st.download_button("⬇️ Exporter en CSV", f[cols].to_csv(index=False).encode("utf-8-sig"),
                       "candidatures_iade.csv", "text/csv")
else:
    st.caption("🔒 Accès public : seules les statistiques sont affichées. "
               "La liste nominative des candidats n'est pas disponible.")
