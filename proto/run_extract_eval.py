"""Tests unitaires d'EXTRACTION : (ce que l'appelant dit + contexte) → action attendue.

**Pourquoi ce fichier existe.** Trois défauts d'affilée (R68, R70, R71) ont été corrigés en
ajoutant une liste de mots-clés dans `engine.py`. Geoffrey a arrêté ça le 01/09, et il avait
raison : une liste de mots-clés ne couvrira jamais le français. « Le plus vite possible »,
« dès que vous pouvez », « peu importe, le premier », « avant ma pause déjeuner » — c'est
sans fin, et chaque ajout est une occasion de refaire l'inversion qu'on vient de corriger.

Interpréter le SENS est désormais le travail du modèle, contre un menu d'actions FERMÉ que
le contrôleur possède (`actions.py`). La contrepartie de cette latitude, c'est de la
MESURER — sinon on remplace des mots-clés vérifiables par une confiance non vérifiée, ce
qui serait un recul. **C'est ici qu'on encode les mille formulations : dans les cas de
test, plus jamais dans le code.**

Chaque tournure ratée en appel réel devient une ligne de ce fichier. Jamais une ligne de
contrôleur.

Différence avec les deux autres évals, qui ne se recouvrent pas :

- `run_scenario.py` — la machine à états, en mock, sans réseau. Rapide, déterministe. Elle
  ne dit RIEN de la compréhension : le mock décide par mots-clés.
- `run_llm_eval.py` — des conversations entières avec un appelant simulé. Elle dit si
  l'appel aboutit, pas POURQUOI une tournure a été mal lue.
- celui-ci — un appel LLM par cas, une phrase, une attente. Quand il échoue, on sait
  exactement quelle tournure et quelle action. Quelques centimes le passage.

    python run_extract_eval.py                # tous les cas (exige ANTHROPIC_API_KEY)
    python run_extract_eval.py --mock         # la plomberie, sans clé ni réseau
    python run_extract_eval.py --only plus_tot

`--mock` ne mesure PAS la compréhension : il vérifie que le harnais tient (contexte bien
formé, actions valides, comptage juste). Un run vert en mock ne dit rien du modèle.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from relais_proto import actions                                     # noqa: E402
from relais_proto.llm import AnthropicLLM, MockLLM                   # noqa: E402

RACINE = pathlib.Path(__file__).resolve().parents[1]

# Le contexte d'un tour de créneaux, tel que le contrôleur le donne réellement à
# l'extracteur (`Conversation._ctx`). Deux propositions le même jour : c'est la forme la
# plus fréquente, et celle où le rang compte le plus.
CTX_S5 = {
    "metier": "plombier chauffagiste",
    "nom_entreprise": "Dupont Chauffage",
    "prestations": ["fuite", "wc_evacuation", "chaudiere_panne", "devis_sdb"],
    "etat": "S5_CRENEAU",
    "dernier_agent": ("Je peux vous proposer demain entre 8 heures et 10 heures, "
                      "ou demain entre 14 heures et 16 heures. Lequel vous arrange ?"),
    "propositions": ["demain entre 8 heures et 10 heures",
                     "demain entre 14 heures et 16 heures"],
    "dernier_tour": "",
    # R73 : le jour courant, en heure de pendule. Sans lui, « pas le vendredi » est
    # ininterprétable — le modèle ne peut pas savoir si « demain » EST un vendredi.
    # Mardi 1er septembre 2026 : « demain » est donc un mercredi.
    "aujourdhui": "mardi 1 septembre 2026, 9 h",
}

# (phrase, action attendue, rang attendu ou None, étiquette)
#
# Les tournures marquées « RÉEL » viennent d'appels vraiment passés — ce sont elles qui
# comptent. Les autres sont là pour border : un modèle qui répond juste sur les cas propres
# et se trompe sur la bouillie de transcription serait dangereux, pas utile.
CAS: list[tuple[str, str, int | None, str]] = [
    # ---- ce qui a coûté l'appel du 01/09 ----
    ("Le plus vite possible.", actions.PLUS_TOT, None, "plus_tot/reel-0109"),
    ("Le plus vite possible", actions.PLUS_TOT, None, "plus_tot/reel-0109-bis"),
    ("J'ai besoin de quelqu'un le plus vite possible.", actions.PLUS_TOT, None,
     "plus_tot/reel-0109-phrase"),

    # ---- la même intention, autrement dite ----
    ("Dès que vous pouvez.", actions.PLUS_TOT, None, "plus_tot/des-que"),
    ("Au plus vite s'il vous plaît.", actions.PLUS_TOT, None, "plus_tot/au-plus-vite"),
    # AMBIGU, et les deux lectures donnent le bon comportement : `choisir/1` réserve le
    # premier créneau, `plus_tot` l'annonce et demande confirmation. Haiku ET Sonnet
    # répondent `plus_tot` — c'est le plus prudent des deux, et on ne va pas le leur
    # reprocher.
    ("Peu importe, le premier libre.", ("choisir/1", "plus_tot"), None,
     "plus_tot/premier-libre"),
    ("Vous n'avez rien avant ?", actions.PLUS_TOT, None, "plus_tot/rien-avant"),
    ("C'est vraiment urgent, l'eau coule.", actions.PLUS_TOT, None, "plus_tot/urgent"),
    ("Franchement le plus tôt possible, je suis inondé.", actions.PLUS_TOT, None,
     "plus_tot/inonde"),

    # ---- choisir, par rang, par heure, par acceptation ----
    ("Le premier.", actions.CHOISIR, 1, "choisir/rang-1"),
    ("Le deuxième ira très bien.", actions.CHOISIR, 2, "choisir/rang-2"),
    ("Le matin, plutôt.", actions.CHOISIR, 1, "choisir/par-moment"),
    ("Celui de 14 heures.", actions.CHOISIR, 2, "choisir/par-heure"),
    ("L'après-midi m'arrange mieux.", actions.CHOISIR, 2, "choisir/apres-midi"),
    ("Oui, c'est parfait.", actions.CHOISIR, 1, "choisir/acceptation"),
    ("Ça me va.", actions.CHOISIR, 1, "choisir/ca-me-va"),
    ("Huit heures c'est bon pour moi.", actions.CHOISIR, 1, "choisir/heure-nue"),
    ("Le second créneau.", actions.CHOISIR, 2, "choisir/second"),

    # ---- contraintes : tout ce que le contrôleur lisait par mots-clés (R68) ----
    ("Plutôt jeudi si c'est possible.", actions.CONTRAINTE, None, "contrainte/jour"),
    ("Seulement le matin, je travaille l'après-midi.", actions.CONTRAINTE, None,
     "contrainte/moment"),
    ("Pas le samedi, je ne suis pas là.", actions.CONTRAINTE, None,
     "contrainte/negation-jour"),
    ("Surtout pas le matin.", actions.CONTRAINTE, None, "contrainte/negation-moment"),
    ("Pas avant jeudi, je suis en déplacement.", actions.CONTRAINTE, None,
     "contrainte/plancher"),
    ("Après 18 heures uniquement.", actions.CONTRAINTE, None, "contrainte/apres-18h"),
    # AMBIGU aussi : la première proposition (8 h – 10 h) EST avant le déjeuner. La lire
    # comme le choix du créneau du matin est juste ; la lire comme une contrainte de
    # moment l'est également. Sonnet choisit la première, Haiku la seconde.
    ("Avant ma pause déjeuner si vous pouvez.", ("contrainte", "choisir/1"), None,
     "contrainte/avant-dejeuner"),
    ("La semaine prochaine plutôt, cette semaine je suis pris.", actions.CONTRAINTE, None,
     "contrainte/semaine-prochaine"),
    ("Il faudrait que ce soit un jour où ma femme est là, le mercredi.",
     actions.CONTRAINTE, None, "contrainte/detour"),

    # ---- ce que le jour courant rend possible (R73) : sans lui, ces trois-la sont
    # indecidables. « Demain » est un mercredi ; « pas le vendredi » ne l'exclut donc pas.
    ("En tout cas, pas le vendredi.", actions.CONTRAINTE, None, "jour/pas-vendredi"),
    ("Il me faudrait quelque chose avant vendredi.", actions.CONTRAINTE, None,
     "jour/avant-vendredi"),
    ("Demain c'est mercredi ? Alors va pour le matin.", actions.CHOISIR, 1,
     "jour/demain-est-mercredi"),

    # ---- refus sec ----
    ("Non, ça ne me convient pas.", actions.REFUSER, None, "refuser/non"),
    ("Aucun des deux ne m'arrange.", actions.REFUSER, None, "refuser/aucun"),
    ("Ni l'un ni l'autre.", actions.REFUSER, None, "refuser/ni-lun"),

    # ---- pas clair : la bouillie de transcription, mesurée en vrai le 01/09 ----
    ("agençum", actions.PAS_CLAIR, None, "pas_clair/reel-agencum"),
    ("Nos gens sur Marne.", actions.PAS_CLAIR, None, "pas_clair/reel-nos-gens"),
    ("Euh attendez, je regarde mon agenda.", actions.PAS_CLAIR, None,
     "pas_clair/attendez"),
    ("Allô ? Vous m'entendez ?", actions.PAS_CLAIR, None, "pas_clair/allo"),
    ("Le chien a renversé la gamelle, une seconde.", actions.PAS_CLAIR, None,
     "pas_clair/hors-sujet"),
    ("Il est bien le", actions.PAS_CLAIR, None, "pas_clair/coupee"),
]


# Le contexte du tour d'IDENTITÉ. Les cas de FAITS s'y jouent : un numéro fabriqué et une
# demande de contact humain n'ont rien à voir avec le menu de S5, et les mesurer dans le
# contexte des créneaux aurait été mesurer autre chose.
CTX_S4 = {
    "metier": "plombier chauffagiste",
    "nom_entreprise": "Dupont Chauffage",
    "prestations": ["fuite", "wc_evacuation", "chaudiere_panne", "devis_sdb"],
    "etat": "S4_IDENTITE",
    "aujourdhui": "mercredi 2 septembre 2026, 11 h",
    "dernier_agent": ("À quel nom, et sur quel numéro Julien peut vous confirmer le "
                      "rendez-vous ?"),
    "propositions": [],
    "dernier_tour": "",
}

# Sentinelle : la clé ne doit PAS être renvoyée. « Absent » est une réponse à part entière
# et souvent la BONNE — un numéro à peu près juste est pire qu'un numéro absent.
ABSENT = "«absent»"

# (phrase, contexte, clé attendue, valeur attendue, étiquette)
CAS_FAITS: list[tuple[str, dict, str, object, str]] = [
    # ---- CE QUI A COÛTÉ L'APPEL DU 01/09, 15 h 16 ----
    # L'appelant, en urgence, demandait qu'on joigne l'artisan. `veut_humain` ne s'est pas
    # armé, l'agent a répondu « pardon, je n'ai pas bien saisi », puis a raccroché — alors
    # que l'escalade humaine était la bonne réponse et qu'elle existe dans le moteur.
    ("Il faut trouver une solution, essayer de le joindre, de l'appeler, je ne sais pas.",
     CTX_S4, "veut_humain", True, "humain/reel-0109"),
    ("Vous ne pouvez pas le prévenir ?", CTX_S4, "veut_humain", True, "humain/prevenir"),
    ("Je préfère lui parler directement.", CTX_S4, "veut_humain", True, "humain/parler"),
    ("Passez-moi quelqu'un s'il vous plaît.", CTX_S4, "veut_humain", True,
     "humain/passez-moi"),
    # ET LA FRONTIÈRE : demander une INTERVENTION n'est pas demander une conversation.
    # « Quelqu'un » tout seul est la façon la plus banale de demander un plombier — les
    # confondre coûterait un transfert à chaque appel (défaut trouvé le 25/08).
    ("Il faudrait que quelqu'un vienne réparer ça.", CTX_S4, "veut_humain", ABSENT,
     "humain/frontiere-intervention"),
    ("J'aimerais qu'on envoie quelqu'un demain.", CTX_S4, "veut_humain", ABSENT,
     "humain/frontiere-envoyer"),

    # ---- CE QUI A COÛTÉ L'APPEL DU 02/09 : le numéro FABRIQUÉ ----
    # Huit chiffres dictés, dix rendus. Le prompt l'interdit en toutes lettres ; le
    # contrôleur l'écarte désormais aussi (R75), mais on veut savoir si le modèle obéit.
    ("Le numéro c'est le 0 6. 30. 30 11.", CTX_S4, "telephone_rappel", ABSENT,
     "tel/fabrication-0209"),
    ("Mon numéro est 06 10 15 47 68 79.", CTX_S4, "telephone_rappel", ABSENT,
     "tel/onze-chiffres"),
    ("C'est le 06 30 30 11 11.", CTX_S4, "telephone_rappel", "0630301111",
     "tel/dix-chiffres"),
    ("Alors, 0 6, 30, 30, 11, 11.", CTX_S4, "telephone_rappel", "0630301111",
     "tel/dicte-par-morceaux"),
]


def _verdict_fait(ex: dict, cle: str, attendu) -> tuple[bool, str]:
    """Un FAIT extrait, comparé à ce qu'il devrait valoir — `ABSENT` compris.

    Absent est une réponse, et souvent la bonne : le prompt interdit de compléter un
    numéro incomplet, et un modèle qui invente deux chiffres est plus dangereux qu'un
    modèle qui ne rend rien.
    """
    obtenu = ex.get(cle, ABSENT)
    # ABSENT et False disent la MÊME CHOSE pour un booléen : « non, ce n'est pas le cas ».
    # Le prompt demande d'omettre les clés absentes, mais répondre `false` explicitement
    # est aussi juste — et plus bavard, pas plus faux. Compter cela comme un échec
    # apprendrait à « corriger » un modèle qui a raison : même leçon que les actions
    # ambiguës du 01/09.
    if attendu is ABSENT and obtenu is False:
        return True, "False (= absent)"
    return obtenu == attendu, str(obtenu)


def _verdict(ex: dict, attendu, rang_attendu: int | None) -> tuple[bool, str]:
    """La validation du CONTRÔLEUR, pas la sortie brute du modèle.

    On mesure ce que le produit va exécuter. Un modèle qui renvoie une action inventée est
    aussi faux qu'un modèle qui se trompe d'action, et c'est `actions.valider` qui tranche
    — donc c'est elle qu'on interroge, jamais le JSON directement.

    `attendu` accepte un TUPLE de réponses légitimes, et ce n'est pas une commodité : au
    premier passage réel, les deux seuls « échecs » de Haiku et Sonnet étaient des cas où
    MON attente était discutable. « Peu importe, le premier libre » lu comme `plus_tot`
    déclenche « le plus tôt que je peux, c'est demain 8 h – 10 h, je vous le réserve ? » —
    exactement la bonne réplique. Un banc de test qui compte ça comme une faute apprend à
    « réparer » des modèles qui ont raison, et c'est pire qu'un banc absent : il donne du
    travail faux avec l'autorité d'un chiffre.

    Là où plusieurs lectures mènent à un comportement correct, on les accepte toutes.
    Là où une seule est correcte, on n'en accepte qu'une.
    """
    action, rang = actions.valider(ex, CTX_S5["etat"], len(CTX_S5["propositions"]))
    obtenu = f"{action}" + (f"/{rang}" if rang else "")
    if isinstance(attendu, tuple):
        return obtenu in attendu, obtenu
    if action != attendu:
        return False, obtenu
    if rang_attendu is not None and rang != rang_attendu:
        return False, f"{action}/rang={rang}"
    return True, obtenu


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true",
                    help="plomberie seule, sans clé ni réseau (ne mesure PAS le modèle)")
    ap.add_argument("--only", default=None, help="filtre sur l'étiquette")
    ap.add_argument("--modele", default=None,
                    help="modèle à mesurer (défaut : RELAIS_MODEL_EXTRACTEUR, puis "
                         "RELAIS_MODEL). Sert à comparer deux modèles sur les MÊMES cas.")
    args = ap.parse_args()

    cas = [c for c in CAS if not args.only or args.only in c[3]]
    faits = [c for c in CAS_FAITS if not args.only or args.only in c[4]]
    if not cas and not faits:
        print(f"aucun cas ne correspond à --only {args.only!r}")
        return 2

    if args.mock:
        llm, modele = MockLLM(), "mock"
    else:
        try:
            from dotenv import load_dotenv
            load_dotenv(RACINE / ".env")
        except ImportError:
            pass
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("ANTHROPIC_API_KEY absente : `--mock` pour la plomberie seule.")
            return 2
        modele = (args.modele or os.environ.get("RELAIS_MODEL_EXTRACTEUR")
                  or os.environ.get("RELAIS_MODEL") or "claude-haiku-4-5")
        # passé en ARGUMENT : l'environnement ne doit pas pouvoir écraser en silence le
        # modèle qu'on croit mesurer
        llm = AnthropicLLM(model=modele)

    print(f"extraction · {len(cas)} actions + {len(faits)} faits · modèle {modele}\n")
    resultats, reussis = [], 0
    for phrase, attendu, rang_attendu, etiquette in cas:
        debut = time.monotonic()
        try:
            ex = llm.extract(phrase, CTX_S5)
        except Exception as exc:                                      # noqa: BLE001
            ex = {"_erreur": repr(exc)}
        ms = int((time.monotonic() - debut) * 1000)
        ok, obtenu = _verdict(ex, attendu, rang_attendu)
        reussis += ok
        marque = "✅" if ok else "❌"
        attendu_lu = (" ou ".join(attendu) if isinstance(attendu, tuple)
                      else attendu + (f"/{rang_attendu}" if rang_attendu else ""))
        print(f"{marque} {etiquette:34} {phrase[:44]:46} "
              f"{obtenu:16} (attendu {attendu_lu}) {ms:>5} ms")
        resultats.append({"etiquette": etiquette, "phrase": phrase,
                          "attendu": attendu_lu, "obtenu": obtenu, "ok": ok,
                          "brut": ex, "ms": ms})

    # UN APPEL QUI N'A PAS ABOUTI N'EST PAS UNE INCOMPRÉHENSION. Le premier passage réel
    # de cet outil, le 01/09, a rendu « 6/36 compris » sur une clé API invalide : trente
    # 401 avaient dégradé en `pas_clair`, et le tableau se lisait comme un verdict sur le
    # modèle. C'est la panne silencieuse contre laquelle tout ce projet est écrit, et je
    # venais de la fabriquer dans l'outil censé la débusquer.
    #
    # Sortie 2, comme `run_depot_pg.py` quand il n'a rien testé : « ça n'a pas marché » et
    # « ça a marché et c'est mauvais » ne doivent pas se ressembler.
    casses = [r for r in resultats if r["brut"].get("_erreur")]
    if casses:
        print(f"\n⚠️  {len(casses)}/{len(cas)} appels ont ÉCHOUÉ — ce passage ne mesure "
              f"RIEN.")
        print(f"    première erreur : {casses[0]['brut']['_erreur'][:160]}")
        print("    (clé dans .env à la racine ; RELAIS_MODEL pour le modèle)")
        return 2

    for phrase, ctx, cle, attendu, etiquette in faits:
        debut = time.monotonic()
        try:
            ex = llm.extract(phrase, ctx)
        except Exception as exc:                                      # noqa: BLE001
            ex = {"_erreur": repr(exc)}
        ms = int((time.monotonic() - debut) * 1000)
        ok, obtenu = _verdict_fait(ex, cle, attendu)
        reussis += ok
        print(f"{'✅' if ok else '❌'} {etiquette:34} {phrase[:44]:46} "
              f"{cle}={obtenu:14} (attendu {attendu}) {ms:>5} ms")
        resultats.append({"etiquette": etiquette, "phrase": phrase,
                          "attendu": str(attendu), "obtenu": f"{cle}={obtenu}",
                          "ok": ok, "brut": ex, "ms": ms})

    # p50 ET p95, pas une moyenne : au téléphone c'est la QUEUE qui s'entend. Un modèle
    # à 200 ms de médiane et 2 s de p95 fait attendre un appelant sur vingt, et c'est
    # précisément celui-là qui raccroche.
    lat = sorted(r["ms"] for r in resultats)
    def _q(part):
        return lat[min(len(lat) - 1, int(part * len(lat)))]
    print(f"\nlatence : p50 {_q(0.50)} ms · p95 {_q(0.95)} ms · max {lat[-1]} ms")

    print(f"{reussis}/{len(cas) + len(faits)} compris")
    if args.mock:
        # EN MOCK, LE CRITÈRE N'EST PAS LA COMPRÉHENSION. Le harnais par mots-clés se
        # trompe forcément — il rend « choisir/2 » sur « le chien a renversé la gamelle,
        # une SECONDE », ce qui illustre assez bien pourquoi ces listes ont quitté le
        # contrôleur. Ce qu'on vérifie ici, c'est que la plomberie tient : contexte bien
        # formé, aucune exception, et toute sortie validée en une action du menu.
        #
        # Faire échouer `--mock` sur le score de compréhension apprendrait à ignorer un
        # rouge — le plus sûr moyen de ne plus rien voir le jour où il compte.
        # les cas de FAITS ne rendent pas une action : on les reconnaît au « = » de
        # leur libellé, et pour eux la plomberie se limite à « aucune exception ».
        casse = [r for r in resultats
                 if r["brut"].get("_erreur")
                 or ("=" not in r["obtenu"]
                     and r["obtenu"].split("/")[0] not in actions.menu(CTX_S5["etat"]))]
        if casse:
            for r in casse:
                print(f"   PLOMBERIE : {r['etiquette']} → {r['obtenu']} "
                      f"{r['brut'].get('_erreur', '')}")
            return 1
        print(f"plomberie OK sur {len(cas) + len(faits)} cas — le score ci-dessus ne mesure PAS le "
              f"modèle (lancer sans --mock pour cela)")
        return 0
    if not args.mock:
        # Les résultats se comparent d'un modèle à l'autre : un fichier par passage, comme
        # `run_llm_eval.py`. C'est ainsi qu'on répondra pour de bon à « Haiku suffit-il ? »
        # — en mesurant, pas en devinant.
        dossier = RACINE / "evals"
        dossier.mkdir(exist_ok=True)
        chemin = dossier / f"extract-{time.strftime('%Y%m%d-%H%M%S')}.json"
        chemin.write_text(json.dumps(
            {"modele": modele, "reussis": reussis,
             "total": len(cas) + len(faits),
             "latence_p50_ms": _q(0.50), "latence_p95_ms": _q(0.95),
             "latence_max_ms": lat[-1], "cas": resultats},
            ensure_ascii=False, indent=2, default=str),
            encoding="utf-8")
        print(f"→ {chemin}")
    return 0 if reussis == len(cas) + len(faits) else 1


if __name__ == "__main__":
    sys.exit(main())
