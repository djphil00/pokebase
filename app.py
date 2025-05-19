# --- Imports principaux ---
import streamlit as st
import requests
import json
import datetime
from pathlib import Path
from json.decoder import JSONDecodeError
from PIL import Image
from io import BytesIO
import pandas as pd
import altair as alt
from natsort import natsorted
import unicodedata  # (Ajoutez cet import tout en haut de votre fichier si pas encore fait)

# --- Configuration de l'application ---
st.set_page_config(page_title="Ma Collection Pokémon", layout="wide")

# --- Constantes Globales ---
API_BASE = "https://api.pokemontcg.io/v2"
API_KEY = "d573b52b-894a-4046-960a-406e8360e24e"  # À remplacer par votre propre clé

USD_TO_EUR = 0.92
PER_PAGE = 12  # Nombre de cartes par page

# Fichiers locaux
PRICES_HISTORY_FILE = Path("prices_history.json")
COLL_FILE = Path('collection.json')
INDEX_FILE = Path('cards_index.json')

# Types principaux
TYPES = ["", "Fire", "Water", "Grass", "Lightning", "Psychic", "Fighting", "Darkness", "Metal", "Fairy"]

# Mappages variantes
VARIANT_ORDER = {
    "normal": 0,
    "reverse": 1,
    "holo": 2,
    "reverse_classic": 3,
    "reverse_pokeball": 4,
    "reverse_masterball": 5
}
VARIANT_ICONS = {
    "normal": "✅",
    "reverse": "↩️",
    "holo": "🌟",
    "reverse_classic": "🌀",
    "reverse_pokeball": "⚪",
    "reverse_masterball": "🟣"
}
VARIANT_TO_API_FIELD = {
    "normal": "normal",
    "reverse": "reverse",
    "reverse_classic": "reverse",
    "reverse_pokeball": "reverse",
    "reverse_masterball": "reverse",
    "holo": "holo"
}

# Sets gérés
SETS = {"ssp": "sv08", "pre": "sv08.5", "jtg": "sv09"}
SET_NAMES = {
    "ssp": "Surging Sparks",
    "pre": "Prismatic Evolution",
    "jtg": "Journey Together"
}
SET_VARIANTS = {
    "ssp": ["normal", "reverse", "holo"],
    "pre": ["normal", "reverse_classic", "reverse_pokeball", "reverse_masterball"],
    "jtg": ["normal", "reverse"]
}

# --- Chargement des données locales ---

# Chargement de l'index des cartes
if INDEX_FILE.exists():
    with INDEX_FILE.open("r", encoding="utf-8") as f:
        index = json.load(f)
else:
    index = {}

# Chargement de la collection de cartes
if not COLL_FILE.exists():
    COLL_FILE.write_text('{}')  # Initialiser si absent

try:
    collection = json.loads(COLL_FILE.read_text())
    if not isinstance(collection, dict):
        collection = {}
except JSONDecodeError:
    collection = {}
    

# Créer un fichier sales.json si absent
SALES_FILE = Path("sales.json")
if not SALES_FILE.exists():
    SALES_FILE.write_text('{}')

try:
    sales = json.loads(SALES_FILE.read_text())
    if not isinstance(sales, dict):
        sales = {}
except JSONDecodeError:
    sales = {}

# --- Fonctions Utilitaires ---

    # --- Mapping centralisé pour les variantes disponibles ---
AVAILABLE_VARIANTS = {
    "ssp": ["normal", "reverse"],
    "pre": ["normal", "reverse_classic", "reverse_pokeball", "reverse_masterball"],
    "jtg": ["normal", "reverse"]
}
    # --- Suite Fontions : ---

def load_json(path: Path, fallback: dict = {}) -> dict:
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else fallback.copy()
    except Exception:
        pass
    return fallback.copy()

def get_available_variants(set_alias: str) -> list:
    """
    Retourne la liste des variantes possibles pour un set donné.
    """
    return AVAILABLE_VARIANTS.get(set_alias, ["normal"])

def correct_card_id(card_id: str) -> str:
    """
    Corrige l'ID d'une carte pour correspondre aux attentes de l'API officielle.
    Exemple : "sv08-219" devient "sv8-219"
    """
    if card_id.startswith("sv08-"):
        return card_id.replace("sv08-", "sv8-")
    if card_id.startswith("sv08.5-"):
        return card_id.replace("sv08.5-", "sv8pt5-")
    if card_id.startswith("sv09-"):
        return card_id.replace("sv09-", "sv9-")
    return card_id

def restore_old_cid(new_cid: str) -> str:
    """
    Effectue l'opération inverse de correct_card_id pour la compatibilité ancienne.
    """
    if new_cid.startswith("sv8pt5-"):
        return new_cid.replace("sv8pt5-", "sv08.5-")
    if new_cid.startswith("sv8-"):
        return new_cid.replace("sv8-", "sv08-")
    return new_cid  # sv9 reste identique

@st.cache_data(show_spinner=False)
def get_price(card_id: str) -> float:
    """
    Récupère le prix en USD d'une carte depuis l'API Pokémon TCG.
    Utilise le cache Streamlit pour limiter les appels réseau.
    """
    url = f"{API_BASE}/cards/{card_id}"
    headers = {"X-Api-Key": API_KEY}
    try:
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        prices = data['data'].get('tcgplayer', {}).get('prices', {})
        price_info = prices.get('normal') or prices.get('holofoil') or {}
        return price_info.get('market')
    except Exception as e:
        print(f"[Erreur API] Récupération du prix échouée pour {card_id}: {e}")
        return None

@st.cache_data(show_spinner=False)
def get_gray_image(url: str) -> Image:
    """
    Télécharge une image et la convertit en niveaux de gris (pour affichage 'non possédé').
    """
    try:
        resp = requests.get(url)
        resp.raise_for_status()
        return Image.open(BytesIO(resp.content)).convert("L")
    except Exception as e:
        print(f"[Erreur Image] Impossible de charger l'image: {e}")
        return None

@st.cache_data(show_spinner=False)
def get_detail(card_id: str) -> dict:
    """
    Récupère les détails d'une carte depuis l'index local.
    """
    return index.get(card_id, {})

def infer_set_alias(card_id: str) -> str:
    """
    Déduit l'alias de set ('ssp', 'pre', 'jtg') à partir de l'ID de la carte.
    """
    if card_id.startswith("sv8pt5-"):
        return "pre"
    if card_id.startswith("sv8-"):
        return "ssp"
    if card_id.startswith("sv9-"):
        return "jtg"
    return ""

# --- Fonctions Avancées ---
#---Save Dayly prices---
import time
updated_keys = []
skipped_keys = []

import time

def fetch_price_with_retry(cid, api_field):
    url = f"{API_BASE}/cards/{cid}"
    headers = {"X-Api-Key": API_KEY}
    for attempt in range(2):
        try:
            r = requests.get(url, headers=headers)
            r.raise_for_status()
            data = r.json()["data"]
            prices = data.get("tcgplayer", {}).get("prices", {})
            variant_data = prices.get(api_field)
            if isinstance(variant_data, dict):
                return variant_data.get("market")
            return variant_data
        except Exception as e:
            if attempt == 1:
                print(f"[❌] {cid} ({api_field}) erreur API après 2 tentatives : {e}")
    return None

def save_daily_prices_from_sets():
    today = datetime.date.today().isoformat()

    try:
        history = json.loads(PRICES_HISTORY_FILE.read_text())
    except Exception:
        history = {}

    VARIANT_TO_API_FIELD = {
        "normal": "normal",
        "reverse": "reverseHolofoil",
        "holo": "holofoil",
        "reverse_classic": "reverseHolofoil",
        "reverse_pokeball": "reversePokeballHolofoil",
        "reverse_masterball": "reverseMasterballHolofoil"
    }

    sets = ["sv8", "sv8pt5", "sv9"]
    count = 0
    for set_id in sets:
        page = 1
        while True:
            params = {"q": f"set.id:{set_id}", "pageSize": 250, "page": page}
            r = requests.get(f"{API_BASE}/cards", headers={"X-Api-Key": API_KEY}, params=params)
            r.raise_for_status()
            cards = r.json().get("data", [])
            if not cards:
                break
            for card in cards:
                cid = card.get("id", "")
                prices = card.get("tcgplayer", {}).get("prices", {})
                for var, field in VARIANT_TO_API_FIELD.items():
                    p = prices.get(field)
                    market = p.get("market") if isinstance(p, dict) else None
                    if isinstance(market, (int, float)):
                        price_eur = round(market * USD_TO_EUR, 4)
                        key = f"{cid}_{var}"
                        history.setdefault(key, {})[today] = price_eur
                        count += 1
            page += 1

    PRICES_HISTORY_FILE.write_text(json.dumps(history, indent=2))
    st.success(f"✅ {count} prix mis à jour via requêtes groupées (sets complets)")

price_history = load_json(PRICES_HISTORY_FILE)

def plot_price_history(card_id: str):
    """
    Affiche l'historique de prix d'une carte sous forme de graphique.
    """
    if not PRICES_HISTORY_FILE.exists():
        st.info("Pas encore d'historique enregistré.")
        return

    try:
        history = json.loads(PRICES_HISTORY_FILE.read_text())
    except JSONDecodeError:
        st.error("Erreur de lecture de l'historique de prix.")
        return

    data = history.get(card_id, {})
    if not data:
        st.info("Pas encore d'historique pour cette carte.")
        return

    df = pd.DataFrame(list(data.items()), columns=["Date", "Prix (€)"])
    df["Date"] = pd.to_datetime(df["Date"])

    # Construction du graphique Altair
    chart = alt.Chart(df).mark_line(point=True).encode(
        x="Date:T",
        y="Prix (€):Q",
        tooltip=["Date:T", "Prix (€):Q"]
    ).properties(width=500, height=300)

    st.altair_chart(chart)

def normalize_text(text: str) -> str:
    """
    Supprime les accents et met en minuscules pour comparaison tolérante.
    """
    return unicodedata.normalize('NFKD', text) \
                     .encode('ASCII', 'ignore') \
                     .decode('utf-8') \
                     .lower()

def animated_progress(label: str, percent: float, color="#4CAF50"):
    """
    Barre de progression animée personnalisée pour les statistiques.
    """
    st.markdown(
        f"""
        <div style="margin-bottom: 1rem;">
            <div style="font-weight: bold;">{label}</div>
            <div style="background-color: #ddd; border-radius: 10px; overflow: hidden;">
                <div style="height: 20px; width: {percent:.2f}%; background-color: {color}; transition: width 1.5s;"></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

# --- Interface Utilisateur : Barre latérale (Sidebar) ---

# Chargement du CSS personnalisé pour l'affichage (animations, boutons, etc.)
st.markdown("""
<style>
/* Limite largeur globale */
.reportview-container .main .block-container {
    max-width: 90%;
}

/* Animation légère au survol des images */
img {
    transition: all 0.3s ease;
    border-radius: 10px;
}
img:hover {
    transform: scale(1.05);
    box-shadow: 0 4px 20px rgba(0,0,0,0.25);
}

/* Style boutons */
button[kind="primary"] {
    border-radius: 10px;
    background-color: #4CAF50;
    transition: all 0.3s ease;
    font-weight: bold;
}
button[kind="primary"]:hover {
    background-color: #45A049;
    transform: scale(1.03);
    box-shadow: 0 4px 15px rgba(0,0,0,0.3);
}
</style>
""", unsafe_allow_html=True)

# --- Navigation principale ---
st.sidebar.title("Navigation")
mode = st.sidebar.radio("Menu", ["Recherche", "Mes Binders", "Statistiques", "Mes Ventes"])

# --- Mode : Recherche de cartes ---

if mode == "Recherche":
    st.title("Recherche de cartes 🔍")

    # 1) Saisie utilisateur
    q = st.text_input("Rechercher nom, numéro, set…").strip()
    type_filter = st.selectbox("Type (optionnel)", TYPES)

    if not q and not type_filter:
        st.info("Tapez un mot-clé ou choisissez un type pour lancer la recherche.")
    else:
        # 2) Tokenisation & détection set / termes
        tokens = normalize_text(q).split()
        set_alias = None
        search_terms = []

        for t in tokens:
            if t.upper() in ["SSP", "PRE", "JTG"]:
                set_alias = t.lower()
            else:
                search_terms.append(t)

        # 3) On part de toutes les cartes
        cards_list = list(index.values())

        # 4) Filtre Type
        if type_filter:
            cards_list = [
                c for c in cards_list
                if type_filter in (c.get("types") or [])
            ]

        # 5) Filtre Set
        if set_alias:
            prefix_map = {"ssp": "sv8-", "pre": "sv8pt5-", "jtg": "sv9-"}
            pref = prefix_map[set_alias]
            cards_list = [
                c for c in cards_list
                if c.get("id", "").lower().startswith(pref)
            ]

        # 6) Filtrage par termes (mots / numéros)
        brief = []
        special = {
            "double rare","ultra rare","illustration rare",
            "special illustration rare","hyper rare","gold rare",
            "ace spec","shining rare"
        }

        for card in cards_list:
            name_norm = normalize_text(card.get("name", ""))
            card_id = card.get("id", "").lower()
            # on prend la partie après le tiret comme numéro
            suffix = card_id.split("-", 1)[-1]

            # vérifier chaque terme
            ok = True
            for term in search_terms:
                if term.isdigit():
                    if term != suffix:
                        ok = False
                        break
                else:
                    if term not in name_norm:
                        ok = False
                        break
            if not ok:
                continue

            # 7) Préparation des variantes pour les cases à cocher
            rarity = card.get("rarity", "").lower()
            alias = infer_set_alias(card_id)
            types = card.get("types") or []

            if any(r in rarity for r in special):
                vars_list = ["holo"]
            elif "Trainer" in types and alias in ["pre", "jtg"]:
                vars_list = get_available_variants(alias)
            else:
                vars_list = get_available_variants(alias)

            card["available_variants"] = vars_list
            brief.append(card)
            brief.sort(key=lambda c: int(c.get("localId") or c["id"].split("-")[-1]))

        # 8) Affichage & pagination
        total = len(brief)
        if total == 0:
            st.markdown(
                '<div style="text-align:center;margin-top:2em;">'
                '<h3>😢 Aucun résultat trouvé</h3>'
                '<p>Essayez d’autres termes ou ajustez vos filtres.</p>'
                '</div>',
                unsafe_allow_html=True
            )
        else:
            pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
            if "recherche_page" not in st.session_state:
                st.session_state["recherche_page"] = 1

            key_q = q + (type_filter or "")
            if st.session_state.get("last_query") != key_q:
                st.session_state["recherche_page"] = 1
                st.session_state["last_query"] = key_q

            page = st.session_state["recherche_page"]
            start = (page - 1) * PER_PAGE
            paginated = brief[start : start + PER_PAGE]

            # Calcul de pagination (sécurité)
            if "brief" in locals():
                total = len(brief)
            else:
                total = 0
            pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)

            # Affichage en grille
            for i in range(0, len(paginated), 4):
                cols = st.columns(4)
                for j, detail in enumerate(paginated[i : i + 4]):
                    with cols[j]:
                        img = detail.get("images", {}).get("large", "")
                        if img:
                            st.image(img, width=200)
                        suffix = detail.get("localId") or detail.get("id", "").split("-", 1)[1]
                        st.write(f"**{detail.get('name','')} #{suffix}**")

                        if "price_history" not in globals():
                            price_history = load_json(PRICES_HISTORY_FILE)

                        for var in detail["available_variants"]:
                            icon = VARIANT_ICONS.get(var, "")
                            data_key = f"{detail['id']}_{var}"
                            have = collection.get(data_key, False)

                            # Récupération du prix
                            hist = price_history.get(data_key, {})
                            latest = sorted(hist)[-1] if hist else None
                            price_eur = f"{hist[latest]:.2f} €" if latest else "Prix indisponible"

                            # Checkbox avec prix intégré
                            label = f"{icon} {var.capitalize()} : 💶 {price_eur}"
                            chk = st.checkbox(label, value=have, key=f"{data_key}_{i}_{j}")
                            collection[data_key] = chk

                            # Gestion ventes
                            if chk:
                                qty_key = f"sale_qty_{data_key}"
                                if qty_key not in st.session_state:
                                    st.session_state[qty_key] = sales.get(data_key, {}).get("qty", 0)

                                col_sale = st.columns([1, 2, 1])

                                with col_sale[0]:
                                    if st.button("➖", key=f"minus_{data_key}_{i}_{j}"):
                                        st.session_state[qty_key] = max(0, st.session_state[qty_key] - 1)

                                with col_sale[1]:
                                    st.markdown(
                                        f"<div style='text-align:center; font-size:0.9em; padding-top:6px;'>"
                                        f"{st.session_state[qty_key]} à vendre"
                                        f"</div>", unsafe_allow_html=True
                                    )

                                with col_sale[2]:
                                    if st.button("➕", key=f"plus_{data_key}_{i}_{j}"):
                                        st.session_state[qty_key] += 1

            # Sécurisation de page
            page = st.session_state.get("recherche_page", 1)

            # Pagination visuelle
            cols_pag = st.columns([1, 2, 1])
            with cols_pag[1]:
                st.number_input("Page", 1, pages, page, key="recherche_page")

            if st.button("✅ Mettre à jour la collection ET ventes"):
                # 1) Met à jour les qty dans sales depuis st.session_state  
                for key, val in st.session_state.items():
                    if key.startswith("sale_qty_"):
                        data_key = key[len("sale_qty_"):]
                        sales.setdefault(data_key, {})
                        sales[data_key]["qty"] = val
                # 2) Écrit enfin vos fichiers
                COLL_FILE.write_text(json.dumps(collection, indent=2))
                SALES_FILE.write_text(json.dumps(sales, indent=2))
                st.success("✅ Collection et Ventes mises à jour !")  
                
                st.experimental_rerun()

# --- Mode : Mes Binders ---
elif mode == "Mes Binders":
    st.title("📁 Mes Binders")

    # Emojis pour chaque set
    EMOJIS = {"ssp": "⚡", "pre": "🧬", "jtg": "🤝"}

    special_rarities = [
        "double rare", "ultra rare", "illustration rare",
        "special illustration rare", "hyper rare", "gold rare",
        "ace spec", "shining rare"
    ]

    # --- Affichage des Binders ---
    for alias, prefix in [("ssp", "sv8"), ("pre", "sv8pt5"), ("jtg", "sv9")]:
        slot_list = []
        owned_cards = 0

        for card in index.values():
            cid = card.get("id", "")
            if not cid.startswith(prefix + "-"):
                continue  # Ignore les cartes d'un autre set

            rarity = card.get("rarity", "").lower()

            # --- Déterminer variantes attendues ---
            if rarity in special_rarities:
                variants = ["holo"]
            else:
                variants = get_available_variants(alias)

            # --- Gestion de la possession ---
            for var in variants:
                new_key = f"{cid}_{var}"
                old_key = f"{restore_old_cid(cid)}_{var}"

                is_owned = collection.get(new_key, False) or collection.get(old_key, False)

                if is_owned:
                    owned_cards += 1

                try:
                    num = int(card.get("localId", "") or cid.split("-", 1)[1])
                except (ValueError, IndexError):
                    num = 0

                order = VARIANT_ORDER.get(var, 0)
                slot_list.append((num, order, cid, card, var, is_owned))

        # --- Tri naturel ---
        slot_list.sort(key=lambda x: (x[0], x[1]))

        # --- Affichage du classeur ---
        emoji = EMOJIS.get(alias, "📁")
        with st.expander(f"{emoji} Classeur {SET_NAMES.get(alias, alias)}", expanded=False):
            PER_PAGE_BINDER = 12
            pages = max(1, (len(slot_list) + PER_PAGE_BINDER - 1) // PER_PAGE_BINDER)

            page = st.number_input(
                f"Page {SET_NAMES[alias]} (1-{pages})",
                min_value=1, max_value=pages, value=1, key=f"binder_{alias}"
            )

            page_cards = slot_list[(page - 1) * PER_PAGE_BINDER : page * PER_PAGE_BINDER]

            for i in range(0, len(page_cards), 4):
                cols = st.columns(4)
                for j, (_, _, cid, card, var, is_owned) in enumerate(page_cards[i:i+4]):
                    with cols[j]:
                        img_url = card.get("images", {}).get("large", "")

                        if img_url:
                            if is_owned:
                                st.image(img_url, width=200)
                            else:
                                st.markdown(
                                    f"""
                                    <div style="position:relative;width:200px;">
                                        <img src="{img_url}" style="width:100%;filter:grayscale(100%);border-radius:10px;">
                                    </div>
                                    """,
                                    unsafe_allow_html=True
                                )
                        else:
                            st.markdown("""
                                <div style="width:200px;height:280px;background-color:#f0f0f0;
                                            display:flex;align-items:center;justify-content:center;
                                            border-radius:10px;">
                                    <span style="color:#999;">Image<br>non dispo</span>
                                </div>
                            """, unsafe_allow_html=True)

                        name = card.get("name", "Nom inconnu").strip()
                        num  = card.get("localId") or cid.split("-", 1)[1]
                        icon = VARIANT_ICONS.get(var, "")
                        label = var.replace('_', ' ').capitalize()

                        st.markdown(
                            f"<strong>{icon} {name} #{num} — {label}</strong>",
                            unsafe_allow_html=True
                        )
                        # 🔥 Sécurité absolue : on ignore toute trace de .get("prices")
                        if "prices" in card:
                            card = dict(card)
                            card.pop("prices", None)

                        # --- Affichage du prix ---
                        full_key = f"{cid}_{var}"
                        hist = price_history.get(full_key, {})
                        if hist:
                            latest = sorted(hist)[-1]
                            st.markdown(f"<div style='font-size:0.9em;'>💶 {hist[latest]:.2f} €</div>", unsafe_allow_html=True)
                        else:
                            st.markdown("<div style='font-size:0.9em;'>💶 Prix indisponible</div>", unsafe_allow_html=True)
                    
# --- Mode : Statistiques ---

elif mode == "Statistiques":
    st.title("📈 Statistiques sur toutes les cartes + variantes attendues")

    # --- Configuration des variantes et visuels ---
    STATS_VARIANTS = ["normal", "reverse", "reverse_classic", "reverse_pokeball", "reverse_masterball", "holo"]
    ICONS  = {"ssp": "⚡", "pre": "🧬", "jtg": "🤝"}
    COLORS = {"ssp": "#FFD700", "pre": "#87CEFA", "jtg": "#90EE90"}

    special_rarities = {
        "double rare", "ultra rare", "illustration rare",
        "special illustration rare", "hyper rare", "gold rare",
        "ace spec", "shining rare"
    }

    def get_expected_variants(set_alias, rarity):
        """
        Déduit les variantes attendues selon l'alias du set et la rareté.
        """
        if rarity in special_rarities:
            return ["holo"]
        if set_alias == "pre":
            return ["normal", "reverse_classic", "reverse_pokeball", "reverse_masterball"]
        if set_alias == "jtg":
            return ["normal", "reverse"]
        return ["normal", "reverse"]

    # --- Construction des statistiques ---
    stats_by_set = {
        alias: {
            "name": SET_NAMES[alias],
            "variants": {v: {"possible": 0, "possessed": 0} for v in STATS_VARIANTS},
            "picked": []  # Cartes possédées pour évaluer la valeur
        }
        for alias in ["ssp", "pre", "jtg"]
    }

    total_collection_value = 0.0

    for cid, detail in index.items():
        # Inférer l'alias du set
        prefix = cid.split("-", 1)[0]
        alias = infer_set_alias(cid)
        if alias not in stats_by_set:
            continue

        rarity = detail.get("rarity", "").lower()
        expected_variants = get_expected_variants(alias, rarity)

        for var in expected_variants:
            # +1 variante possible
            stats_by_set[alias]["variants"][var]["possible"] += 1

            # Vérifier possession
            key_new = f"{cid}_{var}"
            key_old = f"{restore_old_cid(cid)}_{var}"

            if collection.get(key_new, False) or collection.get(key_old, False):
                stats_by_set[alias]["variants"][var]["possessed"] += 1

                # Calcul valeur
                full_key = f"{cid}_{var}"
                hist = price_history.get(full_key, {})
                price_eur = 0.0
                if hist:
                    latest = sorted(hist)[-1]
                    price_eur = hist[latest]

                stats_by_set[alias]["picked"].append((cid, var, price_eur))

                total_collection_value += price_eur

    # --- Affichage des statistiques par set ---
    for alias, data in stats_by_set.items():
        st.markdown(f"<h2 style='color:{COLORS[alias]}'>{ICONS[alias]} {data['name']}</h2>", unsafe_allow_html=True)

        total_possible = sum(d["possible"] for d in data["variants"].values())
        total_possessed = sum(d["possessed"] for d in data["variants"].values())
        percent = (total_possessed / total_possible * 100) if total_possible else 0

        st.write(f"**{total_possessed} / {total_possible} variantes possédées ({percent:.2f} %)**")
        set_value = sum(p for _, _, p in data["picked"])
        st.write(f"**💶 Valeur estimée du set : {set_value:.2f} €**")
        animated_progress(f"{total_possessed} / {total_possible}", percent)

        with st.expander(f"📚 Détail par variante pour {data['name']}"):
            for var, stats in data["variants"].items():
                if stats["possible"] == 0:
                    continue
                p = (stats["possessed"] / stats["possible"]) * 100
                st.write(f"**{var.replace('_', ' ').capitalize()}** : {stats['possessed']} / {stats['possible']} ({p:.2f} %)")
                animated_progress(f"{stats['possessed']} / {stats['possible']}", p)

        # Top 5 cartes > 2 €
        top_cards = sorted([c for c in data["picked"] if c[2] > 2], key=lambda x: x[2], reverse=True)[:5]
        if top_cards:
            st.markdown("### 🏆 Top 5 cartes > 2 €")
            for cid, var, eur in top_cards:
                detail = index.get(cid, {})
                img_url = detail.get("images", {}).get("small", "")
                name = detail.get("name", "")
                num  = detail.get("localId", "")

                c1, c2 = st.columns([1, 4])
                with c1:
                    if img_url:
                        st.image(img_url, width=60)
                with c2:
                    st.markdown(
                        f"**{name} #{num}** – <span style='color:green'>{eur:.2f} €</span>",
                        unsafe_allow_html=True
                    )
        else:
            st.info("Pas de cartes > 2 € pour ce set.")

        st.markdown("---")

    # --- Résumé global ---
    st.success(f"🎯 Valeur totale de votre collection : {total_collection_value:.2f} €")

# --- Mes Ventes : ---
if mode == "Mes Ventes":
        st.title("💸 Mes Ventes")

        # Sélecteur de vue
        vue = st.radio("Mode d'affichage", ["🖼️ Vue images", "📋 Vue tableau"], horizontal=True, key="view_mode")
        show_sold = st.checkbox("Afficher uniquement les cartes vendues (avec historique)", value=False)

        # Construction des données
        vente_rows = []
        for cid_var, info in sales.items():
            qty = info.get("qty", 0)
            if (qty > 0 and not show_sold) or (show_sold and info.get("sales")):
                cid, var = cid_var.rsplit("_", 1)
                detail = index.get(cid, {})
                name = detail.get("name", "Inconnu")
                num = detail.get("localId") or cid.split("-", 1)[1]
                image = detail.get("images", {}).get("large")
                key_price = f"{correct_card_id(cid)}_{var}"
                hist = price_history.get(key_price, {})
                if hist:
                    latest = sorted(hist)[-1]
                    price_eur = round(hist[latest], 2)
                else:
                    price_eur = "?"
                sale_price = info.get("sale_price", 0.0)
                ventes = info.get("sales", [])
                ventes_cumulees = sum(v.get("sold_price", 0) for v in ventes)
                vente_rows.append({
                    "cid": cid,
                    "cid_var": cid_var,
                    "Variante": var,
                    "Nom": name,
                    "#": num,
                    "Quantité": info.get("qty", 0) if not show_sold else sum(1 for v in info.get("sales", [])),
                    "Prix marché (€)": price_eur,
                    "Prix souhaité (€)": sale_price,
                    "Ventes (€ cumulées)": f"{ventes_cumulees:.2f} € ({len(ventes)} ventes)" if ventes else "—",
                    "Image": image
                })

        if not vente_rows:
            st.info("Aucune carte marquée à vendre.")

        elif vue == "📋 Vue tableau":
            st.write("✏️ Double-cliquez pour éditer les prix souhaités. Les modifications seront enregistrées. Vous pouvez trier par colonne et filtrer via les en-têtes.")
            df = pd.DataFrame(vente_rows).drop(columns=["cid", "cid_var", "Image"])
            edited_df = st.data_editor(
                df,
                num_rows="dynamic",
                use_container_width=True,
                column_order=["Nom", "#", "Variante", "Quantité", "Prix marché (€)", "Prix souhaité (€)", "Ventes (€ cumulées)"],
                column_config={"Quantité": st.column_config.NumberColumn(disabled=True)},
                hide_index=True,
                key="vente_table"
            )

            # Mettre à jour les données modifiées + sauvegarde
            for idx, row in edited_df.iterrows():
                cid = vente_rows[idx]["cid"]
                variant = vente_rows[idx]["Variante"]
                key = f"{cid}_{variant}"
                sales.setdefault(key, {})["sale_price"] = float(row["Prix souhaité (€)"])
           
            # Avant SALES_FILE.write_text(...)
            for key, val in st.session_state.items():
                if key.startswith("sale_qty_"):
                    data_key = key[len("sale_qty_"):]
                    sales[data_key] = {
                        "qty": val,
                        "sale_price": sales.get(data_key, {}).get("sale_price", None)
                    }

            SALES_FILE.write_text(json.dumps(sales, indent=2))

            # Ajouter un résumé total des ventes
            total_ventes = 0.0
            total_cartes_vendues = 0
            for r in vente_rows:
                cid = r["cid"]
                variant = r["Variante"]
                key = f"{cid}_{variant}"
                ventes = sales.get(key, {}).get("sales", [])
                total_ventes += sum(v.get("sold_price", 0) for v in ventes)
                total_cartes_vendues += len(ventes)

            st.markdown(f"**🧾 Total ventes réalisées : {total_ventes:.2f} € ({total_cartes_vendues} cartes vendues)**")

        else:
            if show_sold:
                export_data = []
                for i in range(0, len(vente_rows), 4):
                    cols = st.columns(4)
                    for j, r in enumerate(vente_rows[i:i+4]):
                        with cols[j]:
                            if r["Image"]:
                                st.image(r["Image"], width=200)
                            st.markdown(f"**{r['Nom']} #{r['#']} — {r['Variante']}**")
                            st.markdown(f"💶 Marché : {r['Prix marché (€)']} €")
                            st.markdown(f"🏷️ Prix de vente : {r['Prix souhaité (€)']} €")
                            export_data.append({
                                "Nom": r["Nom"],
                                "#": r["#"],
                                "Variante": r["Variante"],
                                "Prix marché (€)": r["Prix marché (€)"],
                                "Prix souhaité (€)": r["Prix souhaité (€)"]
                            })

                # Export CSV
                df_export = pd.DataFrame(export_data)
                csv = df_export.to_csv(index=False).encode("utf-8")
                st.download_button("📥 Exporter les cartes vendues en CSV", csv, "ventes.csv", "text/csv")

            else:
                for i in range(0, len(vente_rows), 4):
                    cols = st.columns(4)
                    for j, r in enumerate(vente_rows[i:i+4]):
                        with cols[j]:
                            if r["Image"]:
                                st.image(r["Image"], width=200)
                            st.markdown(f"**{r['Nom']} #{r['#']} — {r['Variante']}**")
                            st.markdown(f"🛒 Quantité : {r['Quantité']}")
                            st.markdown(f"💶 Marché : {r['Prix marché (€)']} €")
                            current = sales.get(f"{r['cid']}_{r['Variante']}", {}).get("sale_price", 0.0)
                            new_price = st.number_input(
                                "Prix souhaité (€)",
                                min_value=0.0,
                                value=float(current),
                                step=0.1,
                                key=f"sale_input_{r['cid']}_{r['Variante']}"
                            )
                            sales[f"{r['cid']}_{r['Variante']}"]["sale_price"] = new_price
                            if st.button(f"✅ Vendu ({r['Variante']})", key=f"vendu_btn_{r['cid']}_{r['Variante']}"):
                                sales[f"{r['cid']}_{r['Variante']}"].setdefault("sales", []).append({
                                    "sold_price": new_price,
                                    "sold_date": datetime.date.today().isoformat()
                                })
                                sales[f"{r['cid']}_{r['Variante']}"]["qty"] = max(0, sales[f"{r['cid']}_{r['Variante']}"]["qty"] - 1)
                                SALES_FILE.write_text(json.dumps(sales, indent=2))
                                st.success("✅ Vente enregistrée")

            # Sauvegarde automatique à la fin de la vue image
            SALES_FILE.write_text(json.dumps(sales, indent=2))

        # Export CSV
        if st.button("🔗 Exporter ventes en CSV"):
            rows = []
            for key, info in sales.items():
                if info.get("sales"):
                    cid, var = key.split("_", 1)
                    detail = index.get(cid, {})
                    for sale in info["sales"]:
                        rows.append({
                            "ID": cid,
                            "Nom": detail.get("name", "?"),
                            "Set": detail.get("set_name", "?"),
                            "Variante": var,
                            "Prix vendu (€)": sale.get("sold_price", 0),
                            "Date de vente": sale.get("sold_date", "?")
                        })
            df_export = pd.DataFrame(rows)
            df_export.to_csv("sales_export.csv", index=False)
            st.success("✅ Fichier sales_export.csv généré !")
        
        # Bouton pour sauvegarder
        if st.button("💾 Sauvegarder les prix de vente actuels"):
            SALES_FILE.write_text(json.dumps(sales, indent=2))
            st.success("✅ Prix de vente sauvegardés !")

# --- Espace réservé en bas de la sidebar ---
bottom_placeholder = st.sidebar.empty()

with bottom_placeholder.container():
    st.markdown("---")
    if st.sidebar.button("💾 Mettre à jour les prix"):
     save_daily_prices_from_sets()