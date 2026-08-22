"""États de la machine et définition des slots — cf. docs/script-conversation-v1.md."""
from enum import Enum


class State(str, Enum):
    S0_OUVERTURE = "S0"
    S1_COMPRENDRE = "S1"
    S2_LOCALISER = "S2"
    S3_QUALIFIER = "S3"
    S4_IDENTITE = "S4"
    S5_CRENEAU = "S5"
    S6_SANS_RDV = "S6"
    S7_TRANSFERT = "S7"
    S8_HORS_PERIMETRE = "S8"
    S9_REPONDEUR = "S9"
    S10_SPAM = "S10"
    S11_CLOTURE = "S11"
    FIN = "FIN"


INTENTS = [
    "urgence", "depannage", "devis_travaux", "entretien", "suivi_dossier", "autre",
]

# intent générique -> prestations config qui le couvrent
INTENT_TO_PRESTATIONS = {
    "fuite": ["fuite"],
    "chaudiere_panne": ["chaudiere_panne"],
    "chauffe_eau": ["chauffe_eau"],
    "wc_evacuation": ["wc_evacuation"],
    "robinetterie": ["robinetterie"],
    "devis_chaudiere": ["devis_chaudiere"],
    "devis_pac": ["devis_pac"],
    "devis_sdb": ["devis_sdb"],
    "entretien_chaudiere": ["entretien_chaudiere"],
}

# Slots — None = pas encore rempli. Un slot peut se remplir à n'importe quel tour.
EMPTY_SLOTS = {
    "intent": None,            # enum INTENTS
    "prestation": None,        # clé prestation config (ex. "fuite")
    "probleme": None,          # texte court : équipement + symptôme
    "commune": None,
    "code_postal": None,
    "urgence_reelle": None,    # bool
    "statut_occupant": None,   # proprietaire | locataire | syndic | autre
    "nom": None,
    "telephone_rappel": None,  # normalisé 0XXXXXXXXX
    "tel_confirme": None,      # bool — répété et confirmé
    "disponibilites": None,    # texte libre
    "danger_gaz": None,        # bool
}

URGENT_PRESTATIONS = {"fuite", "chaudiere_panne", "chauffe_eau", "wc_evacuation"}
