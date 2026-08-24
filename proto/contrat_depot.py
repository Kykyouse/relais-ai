#!/usr/bin/env python3
"""Suite de CONTRAT du port `Depot` — écrite une fois, jouée contre chaque implémentation.

`DepotMemoire` la joue dans `run_scenario.py` (rapide, sans infra) ; `DepotPostgres` la
joue dans `run_depot_pg.py` (quand une base est joignable). Si l'une passe et l'autre pas,
c'est l'adaptateur qui a tort — et non le test qu'il faut assouplir.

Les fixtures sont locales et minimales : ce module ne dépend pas de `run_scenario`, pour
que la dépendance aille dans un seul sens.
"""
from __future__ import annotations

import datetime as dt
import json
from zoneinfo import ZoneInfo

from relais_proto.calendar_stub import CalendarStub
from relais_proto.depot import Introuvable
from relais_proto.engine import Conversation
from relais_proto.llm import MockLLM
from relais_proto.messages import Brouillon, Canal, Destinataire, StatutMessage
from relais_proto.rdv import StatutRdv
from relais_proto.scoring import build_lead

# Un INSTANT, pas une heure de pendule (cf. relais_proto/temps.py) : c'est ce que les deux
# implémentations doivent rendre à l'identique. Contre Postgres, le contrat vérifie donc
# aussi que `timestamptz` n'a pas décalé l'aller-retour.
LUNDI_9H = dt.datetime(2026, 8, 24, 9, 0,
                       tzinfo=ZoneInfo("Europe/Paris")).astimezone(dt.UTC)

# Identifiant absent des deux implémentations, mais de forme UUID VALIDE : contre Postgres,
# comparer une chaîne quelconque à une colonne uuid lève une erreur de cast au lieu de
# rendre zéro ligne. Le contrat ne doit pas présumer du format d'id de l'implémentation.
ID_ABSENT = "00000000-0000-0000-0000-000000000000"

# Deux conversations suffisent : une urgence (échéance courte) et un entretien (échéance
# longue). Lignes en dur ici pour que le contrat ne dépende pas du fichier de scénarios.
LIGNES_URGENCE = ["J'ai une fuite, c'est urgent, ça coule", "94130",
                  "Garcia, 06 12 34 56 78", "Oui c'est bien ça", "Le premier"]
LIGNES_ENTRETIEN = ["Je veux un entretien de chaudière", "Nogent 94130",
                    "Diallo, 07 88 11 22 33", "Oui", "Le premier"]


def _lead_donnees(cfg: dict, lignes: list[str], maintenant: dt.datetime) -> dict:
    convo = Conversation(cfg, MockLLM(), CalendarStub(cfg, now=maintenant))
    convo.open()
    for ligne in lignes:
        if convo.state.value in ("S11", "FIN"):
            break
        convo.process(ligne)
    return build_lead(convo), convo.to_dict()


def _json_natif(valeur):
    """Ramène une valeur à ses types JSON. Une colonne jsonb restitue un DOCUMENT, pas des
    objets Python : le transcript, tuples en mémoire, revient en listes. Ce n'est pas un
    défaut de l'adaptateur, c'est la nature du stockage — on compare donc les deux côtés
    sous forme normalisée, sinon le contrat exigerait de Postgres qu'il rende des tuples.
    """
    return json.loads(json.dumps(valeur, ensure_ascii=False))


def _brouillon(cle: str, texte: str = "message de test") -> Brouillon:
    return Brouillon(cle_idempotence=cle, destinataire=Destinataire.CLIENT,
                     canal=Canal.SMS, cible="0612345678", texte=texte,
                     artisan_id="art-dupont")


def verifier(fabrique, cfg: dict) -> list[str]:
    """Joue le contrat contre le dépôt rendu par `fabrique()`. Rend la liste des écarts."""
    ecarts: list[str] = []

    def exiger(condition: bool, message: str) -> None:
        if not condition:
            ecarts.append(message)

    def exiger_leve(exc, action, message: str) -> None:
        try:
            action()
        except exc:
            return
        except Exception as autre:  # noqa: BLE001 — on veut savoir CE qui a été levé
            ecarts.append(f"{message} (levé : {type(autre).__name__})")
            return
        ecarts.append(f"{message} (rien levé)")

    depot = fabrique()

    # ---- appels ----
    donnees, etat = _lead_donnees(cfg, LIGNES_URGENCE, LUNDI_9H)
    appel = depot.ouvrir_appel("art-dupont", LUNDI_9H)
    exiger(bool(appel.id), "ouvrir_appel : id vide")
    exiger(depot.appel(appel.id).debut_a == LUNDI_9H,
           "appel : debut_a ne fait pas l'aller-retour")
    exiger(depot.appel(appel.id).fin_a is None, "appel neuf : fin_a devrait être vide")

    depot.enregistrer_etat(appel.id, etat)
    relu = depot.appel(appel.id).etat_conversation
    exiger(_json_natif(relu) == _json_natif(etat),
           "enregistrer_etat : l'état sérialisé ne fait pas l'aller-retour")
    exiger_leve(Introuvable, lambda: depot.appel(ID_ABSENT),
                "appel(id inconnu) doit lever Introuvable")

    lead = depot.cloturer_appel(appel.id, donnees, LUNDI_9H)
    exiger(depot.appel(appel.id).fin_a == LUNDI_9H, "cloturer_appel : fin_a non écrit")
    exiger(depot.appel(appel.id).lead_id == lead.id,
           "cloturer_appel : l'appel ne pointe pas sur son lead")
    exiger(_json_natif(depot.lead(lead.id).donnees) == _json_natif(donnees),
           "lead : les données ne font pas l'aller-retour")
    exiger_leve(ValueError, lambda: depot.cloturer_appel(appel.id, donnees, LUNDI_9H),
                "clôturer deux fois le même appel doit lever")

    # ---- alerte lead ----
    depot.marquer_lead_alerte(lead.id, "rdv_expire_sans_reponse", LUNDI_9H)
    alerte = depot.lead(lead.id).donnees.get("alerte", {})
    exiger(alerte.get("motif") == "rdv_expire_sans_reponse",
           f"marquer_lead_alerte : alerte absente ou incomplète ({alerte})")
    exiger(depot.lead(lead.id).donnees.get("score") == donnees["score"],
           "marquer_lead_alerte a écrasé les données du lead au lieu de les compléter")
    exiger_leve(Introuvable,
                lambda: depot.marquer_lead_alerte(ID_ABSENT, "x", LUNDI_9H),
                "marquer_lead_alerte(id inconnu) doit lever Introuvable")

    # ---- RDV : aller-retour exact ----
    rdv = depot.creer_rdv(lead_id=lead.id, hold=donnees["rdv"], lead_donnees=donnees,
                          cfg=cfg, maintenant=LUNDI_9H)
    relu = depot.rdv(rdv.id)
    for champ in ("lead_id", "artisan_id", "creneau", "duree_min", "urgence", "statut",
                  "expire_a", "cree_a", "notifie_a", "decide_a", "historique"):
        exiger(getattr(relu, champ) == getattr(rdv, champ),
               f"rdv.{champ} ne fait pas l'aller-retour : "
               f"{getattr(relu, champ)!r} != {getattr(rdv, champ)!r}")
    exiger_leve(Introuvable, lambda: depot.rdv(ID_ABSENT),
                "rdv(id inconnu) doit lever Introuvable")

    # le dépôt ne rend jamais l'instance vivante : muter sans sauver ne persiste rien
    fantome = depot.rdv(rdv.id)
    fantome.notifier(LUNDI_9H)
    exiger(depot.rdv(rdv.id).statut is StatutRdv.TAMPON,
           "le dépôt rend l'instance vivante : muter sans sauver_rdv() a persisté")

    rdv.notifier(LUNDI_9H)
    depot.sauver_rdv(rdv)
    relu = depot.rdv(rdv.id)
    exiger(relu.statut is StatutRdv.EN_ATTENTE_VALIDATION and relu.notifie_a == LUNDI_9H,
           "sauver_rdv : statut ou notifie_a non persisté")
    exiger(len(relu.historique) == len(rdv.historique),
           "sauver_rdv : l'historique d'audit n'est pas persisté")

    # ---- files : boîte de validation et file du worker ----
    exiger({r.id for r in depot.rdvs_en_attente("art-dupont")} == {rdv.id},
           "rdvs_en_attente ne rend pas le RDV en attente")
    exiger(depot.rdvs_en_attente("art-autre") == [],
           "rdvs_en_attente fuit sur un autre artisan")
    exiger(depot.rdvs_echus(rdv.expire_a - dt.timedelta(minutes=1)) == [],
           "rdvs_echus rend un RDV encore dans les temps")
    exiger({r.id for r in depot.rdvs_echus(rdv.expire_a)} == {rdv.id},
           "rdvs_echus ne rend pas le RDV échu")

    # un RDV terminal disparaît des deux files
    rdv.valider(rdv.expire_a - dt.timedelta(minutes=1))
    depot.sauver_rdv(rdv)
    exiger(depot.rdvs_en_attente("art-dupont") == [],
           "un RDV validé reste dans la boîte de validation")
    exiger(depot.rdvs_echus(rdv.expire_a + dt.timedelta(days=7)) == [],
           "un RDV validé reste dans la file du worker")

    # un second RDV, non urgent : échéance plus lointaine, files indépendantes
    donnees2, _ = _lead_donnees(cfg, LIGNES_ENTRETIEN, LUNDI_9H)
    appel2 = depot.ouvrir_appel("art-dupont", LUNDI_9H)
    lead2 = depot.cloturer_appel(appel2.id, donnees2, LUNDI_9H)
    rdv2 = depot.creer_rdv(lead_id=lead2.id, hold=donnees2["rdv"],
                           lead_donnees=donnees2, cfg=cfg, maintenant=LUNDI_9H)
    exiger(rdv2.expire_a > rdv.expire_a,
           "l'échéance non urgente devrait être plus lointaine que l'urgente")
    exiger({r.id for r in depot.rdvs_en_attente("art-dupont")} == {rdv2.id},
           "rdvs_en_attente : le RDV en tampon devrait y être, et lui seul")

    # ---- recherche par jeton de confirmation (la seule entrée dont dispose le client) ----
    from relais_proto.confirmation import creer_jeton
    jeton, emp = creer_jeton()
    # on ne repropose que ce qui a été notifié : tampon → repropose est interdit par le
    # graphe, et c'est voulu (l'artisan ne peut pas contre-proposer avant d'être prévenu)
    rdv2.notifier(LUNDI_9H)
    rdv2.reproposer({**rdv2.creneau, "date": "2026-09-01",
                     "label": "mardi 01/09 entre 08h et 10h"}, cfg, LUNDI_9H, emp)
    depot.sauver_rdv(rdv2)
    exiger(depot.rdv(rdv2.id).confirmation_sha256 == emp,
           "l'empreinte du jeton de confirmation ne fait pas l'aller-retour")
    trouve = depot.rdv_par_confirmation(emp)
    exiger(trouve.id == rdv2.id,
           f"rdv_par_confirmation rend {trouve.id} au lieu de {rdv2.id}")
    exiger(trouve.statut is StatutRdv.REPROPOSE,
           f"le statut reproposé ne survit pas ({trouve.statut})")
    exiger_leve(Introuvable, lambda: depot.rdv_par_confirmation("empreinte-inexistante"),
                "rdv_par_confirmation(jeton inconnu) doit lever Introuvable")
    exiger_leve(Introuvable, lambda: depot.rdv_par_confirmation(""),
                "rdv_par_confirmation('') doit lever Introuvable, pas rendre un RDV")
    # le jeton en clair ne doit JAMAIS être en base
    exiger(jeton not in str(depot.rdv(rdv2.id).to_dict()),
           "le jeton de confirmation est stocké en clair")

    # ---- file sortante : idempotence portée par le dépôt ----
    msg, nouveau = depot.enfiler_message(_brouillon("contrat:1"), LUNDI_9H)
    exiger(nouveau, "enfiler_message : premier appel devrait être neuf")
    exiger(msg.statut is StatutMessage.A_ENVOYER,
           f"message neuf : statut {msg.statut} au lieu de a_envoyer")
    exiger(msg.cree_a == LUNDI_9H, "enfiler_message : cree_a ne fait pas l'aller-retour")
    exiger(msg.artisan_id == "art-dupont",
           f"artisan_id du message ne fait pas l'aller-retour ({msg.artisan_id!r}) — "
           f"sans lui l'expéditeur applique la plage de silence d'un autre artisan")

    encore, nouveau2 = depot.enfiler_message(
        _brouillon("contrat:1", "texte DIFFÉRENT"), LUNDI_9H + dt.timedelta(hours=1))
    exiger(not nouveau2, "enfiler_message : la clé d'idempotence n'a pas joué")
    exiger(encore.id == msg.id, "enfiler_message : un doublon a créé un second message")
    exiger(encore.texte == msg.texte,
           "enfiler_message : un doublon a écrasé le texte du message existant")
    exiger(len(depot.messages()) == 1,
           f"file sortante : {len(depot.messages())} messages au lieu de 1")

    depot.enfiler_message(_brouillon("contrat:2"), LUNDI_9H)
    exiger(len(depot.messages(StatutMessage.A_ENVOYER)) == 2,
           "messages(statut) ne filtre pas correctement")
    depot.marquer_message_envoye(msg.id, LUNDI_9H + dt.timedelta(minutes=1))
    envoyes = depot.messages(StatutMessage.ENVOYE)
    exiger([m.id for m in envoyes] == [msg.id],
           "marquer_message_envoye : le message n'a pas changé de statut")
    exiger(envoyes and envoyes[0].envoye_a == LUNDI_9H + dt.timedelta(minutes=1),
           "marquer_message_envoye : envoye_a non persisté")
    exiger(len(depot.messages(StatutMessage.A_ENVOYER)) == 1,
           "le message envoyé reste dans la file à envoyer")
    exiger_leve(Introuvable,
                lambda: depot.marquer_message_envoye(ID_ABSENT, LUNDI_9H),
                "marquer_message_envoye(id inconnu) doit lever Introuvable")
    envoye = depot.messages(StatutMessage.ENVOYE)[0]
    exiger(envoye.reference is None, "reference devrait être vide sans accusé fournisseur")

    # ---- envoi : différé, réessais, échec définitif ----
    m3, _ = depot.enfiler_message(_brouillon("contrat:3"), LUNDI_9H)
    plus_tard = LUNDI_9H + dt.timedelta(hours=5)
    depot.differer_message(m3.id, plus_tard)
    relu3 = next(m for m in depot.messages() if m.id == m3.id)
    exiger(relu3.envoyer_apres == plus_tard,
           f"differer_message : envoyer_apres = {relu3.envoyer_apres}, attendu {plus_tard}")
    exiger(relu3.statut is StatutMessage.A_ENVOYER,
           "un message différé doit rester à envoyer, pas changer de statut")

    depot.marquer_message_echec(m3.id, "TimeoutError: fournisseur muet", LUNDI_9H)
    relu3 = next(m for m in depot.messages() if m.id == m3.id)
    exiger(relu3.essais == 1, f"marquer_message_echec : essais = {relu3.essais}, attendu 1")
    exiger(relu3.derniere_erreur and "Timeout" in relu3.derniere_erreur,
           "marquer_message_echec : l'erreur n'est pas conservée")
    exiger(relu3.statut is StatutMessage.A_ENVOYER,
           "un échec transitoire doit laisser le message en file pour réessai")

    depot.marquer_message_echec(m3.id, "définitif", LUNDI_9H, definitif=True)
    relu3 = next(m for m in depot.messages() if m.id == m3.id)
    exiger(relu3.essais == 2, f"le compteur d'essais n'est pas cumulatif ({relu3.essais})")
    exiger(relu3.statut is StatutMessage.ECHEC,
           "un échec définitif doit sortir le message de la file")

    m4, _ = depot.enfiler_message(_brouillon("contrat:4"), LUNDI_9H)
    depot.marquer_message_envoye(m4.id, LUNDI_9H, reference="ref-fournisseur-42", cout=2)
    relu4 = next(m for m in depot.messages() if m.id == m4.id)
    exiger(relu4.reference == "ref-fournisseur-42",
           f"l'accusé du fournisseur n'est pas conservé ({relu4.reference})")
    # le coût par message est la donnée qui dira si changer de fournisseur se rentabilise.
    # Elle ne repasse jamais : si l'aller-retour la perd, elle est perdue pour toujours.
    exiger(relu4.cout == 2, f"le coût du message n'est pas conservé ({relu4.cout!r})")

    for nom, action in (("marquer_message_echec",
                         lambda: depot.marquer_message_echec(ID_ABSENT, "x", LUNDI_9H)),
                        ("differer_message",
                         lambda: depot.differer_message(ID_ABSENT, LUNDI_9H))):
        exiger_leve(Introuvable, action, f"{nom}(id inconnu) doit lever Introuvable")

    # ---- sessions artisan ----
    # Toute méthode du port doit passer par ici, sinon son SQL n'est jamais exercé.
    emp_s = "a" * 64
    fin = LUNDI_9H + dt.timedelta(days=90)
    depot.creer_session(emp_s, "art-dupont", fin, LUNDI_9H, appareil="test")
    exiger(depot.artisan_de_session(emp_s, LUNDI_9H) == "art-dupont",
           "artisan_de_session ne retrouve pas la session")
    # l'expiration est appliquée par le DÉPÔT, pas par l'appelant : sinon il suffirait
    # d'oublier de la vérifier une seule fois quelque part
    exiger_leve(Introuvable, lambda: depot.artisan_de_session(emp_s, fin),
                "une session périmée doit être traitée comme absente")
    exiger_leve(Introuvable,
                lambda: depot.artisan_de_session("b" * 64, LUNDI_9H),
                "artisan_de_session(empreinte inconnue) doit lever Introuvable")
    # reconnexion sur le même appareil : on prolonge, on n'empile pas
    depot.creer_session(emp_s, "art-dupont", fin + dt.timedelta(days=1), LUNDI_9H)
    exiger(depot.artisan_de_session(emp_s, fin) == "art-dupont",
           "une reconnexion doit prolonger la session existante")
    depot.supprimer_session(emp_s)
    exiger_leve(Introuvable, lambda: depot.artisan_de_session(emp_s, LUNDI_9H),
                "supprimer_session doit révoquer la session côté serveur")
    depot.supprimer_session(emp_s)      # déconnexion deux fois : sans effet, sans erreur

    return ecarts
