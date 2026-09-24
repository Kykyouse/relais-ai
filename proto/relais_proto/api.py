"""API HTTP : la façade du backend. Deux portes, deux authentifications.

**L'API ne décide jamais** — corollaire backend de la règle n°1. Elle transporte et
persiste : les transitions restent dans `engine.py` (conversation) et `rdv.py` (RDV), les
créneaux dans `calendar_stub.py`, les textes dans `messages.py`. Aucune règle métier ici.

**Un tour d'appel = une requête, sans aucune session en mémoire.** L'état conversationnel
est relu depuis le dépôt à chaque requête et réécrit après. C'est ce que la brique de
sérialisation (R14) a rendu possible, et c'est ce qui permettra de tenir plusieurs process
derrière un répartiteur sans coller les appels à une instance.
"""
from __future__ import annotations

import datetime as dt
import json as _json_mod
import pathlib
import re as _re_mod
from urllib.parse import quote

from fastapi import Cookie, Depends, FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import (HTMLResponse, JSONResponse, RedirectResponse,
                               StreamingResponse)
from pydantic import BaseModel, Field

import secrets

from . import (connexion, messages, pages, session, sonde_dispo as _sonde_dispo,
               sonde_voix as _sonde, temps,
               vapi as _vapi)
from .calendar_stub import JOURS_FR, MOIS_FR, CalendarStub, libelle_creneau
from .confirmation import creer_jeton, empreinte, lien
from . import admin as admin_mdp
from . import motdepasse
from .depot import Introuvable, LigneArtisan
from .engine import Conversation, formule_accueil
from .rdv import OCCUPENT, StatutRdv as _StatutRdv, TransitionInterdite
from .registre import (Artisan, Registre, empreinte as registre_empreinte,
                       valider_config)
from .scoring import build_lead, est_urgent as scoring_est_urgent
from .states import State

CONTRAT_LEAD_VERSION = 1

# Ce que dit une ligne du fil d'activité. Vocabulaire fermé, aligné sur
# `engine.py` : le fil RACONTE ce qui s'est passé, il ne l'interprète pas.
_CAT_TITRE = {
    "rdv_reserve": "RDV réservé par l'assistant",
    "prioritaire": "Lead prioritaire",
    "a_rappeler": "Client à rappeler",
    "injoignable": "Appel sans numéro",
    "hors_zone": "Hors zone",
    "hors_perimetre": "Hors prestations",
    "spam": "Appel indésirable",
    "appel_muet": "Appel muet",
}

# Le dossier des configs : modèles dont part un nouvel artisan (page d'admin), et
# repli pour les artisans dont la config n'a pas encore migré en base (migr. 011).
DOSSIER_CONFIG = pathlib.Path(__file__).parent.parent / "config"
DOSSIER_STATIQUE = pathlib.Path(__file__).parent / "static"

# L'identifiant technique d'un artisan : il voyage dans des URL et sert de clé
# étrangère. Minuscules, chiffres et tirets — rien qui demande d'être encodé, rien
# qu'on puisse retaper de travers.
_IDENTIFIANT_VALIDE = _re_mod.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

# Cookie de la connexion EN COURS : il ne porte que l'identifiant de l'artisan à qui un
# code vient d'être envoyé, le temps de le taper. Ce n'est pas un secret — la sécurité
# tient au code, à sa durée de vie et au nombre d'essais — mais il est `httponly` comme
# les autres, et il disparaît dès la session ouverte.
COOKIE_CONNEXION = "relais_connexion"


def _masquer(numero: str) -> str:
    """« +33612345678 » → « +33 6 •• •• •• 78 ». Assez pour que l'artisan reconnaisse son
    numéro, pas assez pour qu'un visiteur qui pose un cookie au hasard le recopie."""
    if len(numero) < 4:
        return numero or "votre mobile"
    return f"{numero[:4]} •• •• •• {numero[-2:]}"


# ------------------------------------------------------------------ schémas
class LeadOut(BaseModel):
    """Le contrat de la carte lead (spec produit §6). Versionné : l'app mobile et le site
    en dépendent, il évoluera plus vite que leurs cycles de publication."""
    contrat: int = CONTRAT_LEAD_VERSION
    horodatage: str
    source: str
    base_legale: str
    categorie: str
    zone: str | None = None
    score: int
    raisons: list[str] = Field(default_factory=list)
    slots: dict = Field(default_factory=dict)
    rdv: dict | None = None
    violations_gardes_fous: list[str] = Field(default_factory=list)
    degradations_llm: list[str] = Field(default_factory=list)
    alerte: dict | None = None
    transcript: list[list[str]] = Field(default_factory=list)


class RdvOut(BaseModel):
    """Ce que la boîte de validation affiche : le créneau à valider et la carte lead."""
    id: str
    statut: str
    creneau: dict
    duree_min: int
    urgence: bool
    expire_a: dt.datetime
    cree_a: dt.datetime
    notifie_a: dt.datetime | None = None
    lead: LeadOut | None = None


class OuvrirAppelIn(BaseModel):
    numero_appele: str          # le numéro Relais : c'est LUI qui désigne l'artisan
    numero_appelant: str | None = None


class TourIn(BaseModel):
    texte: str = ""             # vide = silence de l'appelant (répondeur, cf. S9)


class TourOut(BaseModel):
    appel_id: str
    texte: str
    termine: bool
    rdv_id: str | None = None


class ReproposerIn(BaseModel):
    date: str                   # AAAA-MM-JJ
    de: str                     # "14:00"
    a: str                      # "16:00"


# ------------------------------------------------------------------ fabrique
def creer_app(depot, registre: Registre, fabrique_llm, horloge=None,
              base_url: str = "https://relais.example",
              cookie_secure: bool = True, envoyeur=None,
              sonde_voix: "pathlib.Path | None" = None,
              sonde_dispo: "pathlib.Path | None" = None,
              voix_artisan_defaut: str | None = None,
              version: str = "inconnue",
              modeles: dict | None = None) -> FastAPI:
    """Collaborateurs injectés explicitement plutôt que par variables globales : les tests
    passent un dépôt mémoire, un MockLLM et une horloge figée, la prod un dépôt Postgres.

    `envoyeur` est facultatif et ne sert qu'au **code de connexion**, qui doit partir tout
    de suite : un code qui arrive au prochain passage du cron n'est pas un code. Sans lui,
    tout continue de fonctionner — le message reste en file et le worker l'expédiera, avec
    la latence du cron.

    `modeles` — {extracteur, formuleur} — est PUBLIÉ par `/sante`, pour la même raison que
    la révision (R65) : le 01/09, la question « ton appel tournait-il en Sonnet ou en
    Haiku ? » n'a pas pu être tranchée depuis le serveur, et il a fallu la déduire du
    fichier `.env`. Une déduction plausible et une mesure ne se disent pas de la même
    façon. Un nom de modèle n'est pas un secret ; l'ignorer coûte une enquête à chaque
    fois qu'une latence surprend.

    `sonde_voix` est le chemin du journal de la sonde de l'étape 0 (`sonde_voix.py`).
    `sonde_dispo` est celui de la sonde des tournures de temps (`sonde_dispo.py`). Les deux
    sont absentes par défaut : ce sont des outils de diagnostic, et la seule garantie qui
    tienne dans le temps est qu'il n'y ait rien à atteindre quand on ne les a pas allumées.
    `None` — le défaut — ne déclare même pas la route : un outil de diagnostic ne doit pas
    pouvoir se retrouver exposé en production par simple oubli de le désactiver.

    `voix_artisan_defaut` rattache à un artisan les appels vocaux SANS numéro appelé.
    Mesuré le 25/08 : un appel web n'en porte aucun (`call.type == "webCall"`), et c'est
    le mode du spike puisqu'il n'exige pas de numéro français. Sans lui, un tel appel est
    refusé explicitement plutôt que rattaché au hasard.
    """
    # l'un des DEUX seuls endroits où l'horloge système entre (l'autre est worker.py) :
    # elle rend un instant UTC, et tout ce qui suit en hérite (cf. temps.py)
    maintenant = horloge or temps.maintenant
    # Le nom VISIBLE du produit, résolu une fois. Exigé : une page ou un SMS signé de rien
    # est un défaut de câblage, pas une donnée d'exécution — mieux vaut refuser de
    # construire l'application. Même esprit que `_exige` dans serveur.py.
    if not (registre.produit or {}).get("nom"):
        raise RuntimeError(
            "config produit absente du registre : le nom visible du produit est "
            "obligatoire (proto/config/produit.json).")
    NOM = registre.produit["nom"]
    expediteur = None
    if envoyeur is not None:
        from .envoi import Expediteur
        expediteur = Expediteur(
            depot, envoyeur,
            lambda aid: (a.config if (a := registre.artisan(aid)) else None))
    app = FastAPI(title="Relais — API backend", version="0.1.0")

    # Les polices de l'espace artisan, SERVIES PAR NOUS. La maquette les chargeait
    # depuis `fonts.googleapis.com` ; chaque chargement transmet l'adresse IP du
    # visiteur — artisan ou client — à un tiers, sur un produit qui manipule des
    # données de particuliers. Les héberger donne le même rendu sans cette requête, et
    # sans dépendre d'un CDN joignable depuis un chantier. Licence SIL OFL, qui
    # l'autorise explicitement (cf. static/polices/LICENCE.txt).
    from fastapi.staticfiles import StaticFiles
    app.mount("/static", StaticFiles(directory=str(DOSSIER_STATIQUE)), name="static")

    @app.exception_handler(Introuvable)
    async def _introuvable(_: Request, exc: Introuvable) -> JSONResponse:
        return JSONResponse({"detail": "introuvable"}, status_code=404)

    # ---- authentification : deux portes distinctes ----
    def _artisan_de_session(jeton: str) -> Artisan | None:
        """Le cookie est la voie du NAVIGATEUR : un lien ouvert depuis un SMS ne peut pas
        porter d'en-tête `Authorization`. L'expiration est appliquée par le dépôt."""
        if not jeton:
            return None
        try:
            artisan_id = depot.artisan_de_session(session.empreinte(jeton), maintenant())
        except Introuvable:
            return None
        return registre.artisan(artisan_id)

    def artisan_authentifie(
            authorization: str = Header(default=""),
            relais_session: str = Cookie(default="", alias=session.NOM_COOKIE),
    ) -> Artisan:
        """Porte « app artisan », par deux voies : token porteur (API, future app mobile)
        ou cookie de session (navigateur). Une seule des deux suffit ; aucune ne remplace
        le secret webhook de la plateforme vocale."""
        token = authorization.removeprefix("Bearer ").strip()
        artisan = registre.par_token(token) if token else None
        artisan = artisan or _artisan_de_session(relais_session)
        if artisan is None:
            raise HTTPException(401, "authentification artisan requise")
        return artisan

    def _artisan_vu_par_admin(jeton_admin: str, vue: str):
        """L'artisan que l'admin REGARDE, ou `None`. Mode support, lecture seule.

        **Le cookie de vue ne vaut rien seul.** La session d'admin est revérifiée à
        chaque requête : sans elle, poser `nelyo_vue=art-x` à la main suffirait à devenir
        cet artisan. Le cookie ne porte donc aucune autorité — il désigne, il n'autorise
        pas.

        ET CETTE FONCTION N'EST PAS APPELÉE PAR `artisan_authentifie`, la dépendance des
        ACTIONS. C'est ainsi que la lecture seule est obtenue : non par une vérification
        qu'on peut oublier d'écrire, mais parce que l'identité d'emprunt n'existe pas sur
        le chemin qui valide, refuse ou repropose. Cacher les boutons est du confort ;
        ceci est la protection.
        """
        if not vue or not jeton_admin:
            return None
        if _admin_de_session(jeton_admin) is None:
            return None
        return registre.artisan(vue)

    def _secret_webhook_present(entetes: dict) -> bool:
        """Le secret webhook, par l'en-tête dédié OU par `Authorization`.

        La seconde voie n'est pas un confort : mesuré le 25/08, la plateforme vocale
        n'envoie AUCUN en-tête personnalisé vers un custom LLM — le contenu de son champ
        « API Key » part en `Authorization: Bearer`. Refuser cette voie reviendrait à
        exiger d'un tiers une convention qu'il n'a pas.

        ⚠️ Seul le SECRET WEBHOOK ouvre. Un jeton d'artisan présenté dans ce même format
        `Bearer` est refusé : c'est le format de l'AUTRE porte, et les deux ne se
        substituent jamais l'une à l'autre (R40, R41).
        """
        if registre.secret_webhook_valide(entetes.get("x-relais-secret", "")):
            return True
        return registre.secret_webhook_valide(
            entetes.get("authorization", "").removeprefix("Bearer ").strip())

    def webhook_authentifie(
            x_relais_secret: str = Header(default="")) -> None:
        """Porte « plateforme vocale » : secret partagé. N'identifie PAS un artisan —
        c'est le numéro appelé qui le fait. Un token d'artisan présenté ici est refusé,
        et réciproquement : les deux portes ne se substituent jamais l'une à l'autre."""
        if not registre.secret_webhook_valide(x_relais_secret):
            raise HTTPException(401, "secret webhook invalide")

    # ---- santé ----
    @app.get("/sante")
    def sante() -> dict:
        # `cookie_secure` y figure volontairement : ce n'est pas un secret, et c'est LE
        # réglage qui décide si une connexion par navigateur peut aboutir en HTTP. Le
        # vérifier depuis le téléphone doit prendre dix secondes, pas un aller-retour.
        # `version` : le commit qui tourne RÉELLEMENT. Le 27/08, un appel a montré une
        # réplique impossible sur l'arbre courant, et il a fallu remonter neuf commits par
        # déduction — trois fois dans la journée, la même enquête. **Dater ce qui tourne
        # doit être une donnée, pas un raisonnement.** Ce n'est pas un secret : c'est un
        # identifiant de révision, comme le numéro de version d'un logiciel.
        # `worker` : le dernier passage, et surtout son ANCIENNETÉ (R86). C'est elle
        # qu'on lit — « il y a 3 minutes » se comprend d'un coup d'œil, « 04:21:00Z »
        # demande une soustraction et un fuseau. `None` signifie JAMAIS, et se dit
        # explicitement : une base fraîche et un cron mort se ressemblent trop.
        passage = depot.dernier_passage_worker()
        age = None
        if passage is not None:
            age = int((maintenant() - passage).total_seconds() // 60)
        return {"statut": "ok", "contrat_lead": CONTRAT_LEAD_VERSION,
                "cookie_secure": cookie_secure, "version": version,
                "modeles": modeles or {},
                "worker": {"dernier_passage": passage.isoformat() if passage else None,
                           "il_y_a_min": age}}

    # ---- sonde de l'étape 0 (chantier voix), absente par défaut ----
    if sonde_voix is not None:
        chemin_sonde = pathlib.Path(sonde_voix)

        # Deux chemins pour une seule fonction : selon la façon dont l'URL est renseignée
        # côté plateforme, celle-ci appelle la racine telle quelle ou lui ajoute
        # `/chat/completions` (la convention OpenAI). Les deux mènent ici — une sonde qui
        # rendrait 404 parce qu'on a mal deviné le suffixe ne mesurerait rien.
        @app.post("/voix/sonde")
        @app.post("/voix/sonde/chat/completions")
        async def sonde_etape_zero(requete: Request):
            """Journalise la charge utile de la plateforme vocale et répond une phrase fixe.

            Aucun métier, aucune persistance dans le dépôt, aucune conversation : voir
            `sonde_voix.py` pour ce qu'on cherche à apprendre.
            """
            t = maintenant()
            entetes = dict(requete.headers)
            # DEUX voies pour le MÊME secret, appris du premier appel réel (25/08) : Vapi
            # n'envoie pas d'en-tête personnalisé vers un custom LLM, il envoie le contenu
            # de son champ « API Key » en `Authorization: Bearer`. La sonde accepte donc
            # les deux plutôt que d'imposer à la plateforme une convention qu'elle n'a pas.
            #
            # Le préfixe `Bearer ` est retiré s'il est là, et toléré absent : plusieurs
            # plateformes envoient la valeur nue. C'est une sonde — elle doit pouvoir se
            # brancher sur ce qu'on lui présente.
            #
            # ⚠️ Ce que cet élargissement ne fait PAS : ouvrir la porte de l'artisan. Le
            # secret webhook seul est accepté ici, et un jeton d'artisan présenté dans ce
            # même format `Bearer` est refusé (R40). Les deux portes ne se substituent
            # jamais l'une à l'autre — la sonde ne doit pas devenir le trou par lequel
            # elles communiquent. Et cet élargissement vaut pour la SONDE seule :
            # `webhook_authentifie`, la porte de production, n'y touche pas.
            voie_auth = None
            if registre.secret_webhook_valide(entetes.get("x-relais-secret", "")):
                voie_auth = "x-relais-secret"
            elif _secret_webhook_present(entetes):
                voie_auth = "authorization"
            if voie_auth is None:
                # On journalise l'échec, mais seulement les NOMS d'en-têtes (jamais leurs
                # valeurs : le secret en est une). C'est ce qu'il faut pour voir ce que la
                # plateforme a réellement envoyé et corriger sa configuration — sans faire
                # de la sonde un dépotoir où n'importe qui écrirait ce qu'il veut.
                # C'est CE journal-là qui a appris, le 25/08, quel canal Vapi utilise.
                _sonde.journaliser(
                    {"horodatage": t.isoformat(), "refuse": "secret webhook absent ou faux",
                     "entetes": sorted(entetes)}, chemin_sonde)
                raise HTTPException(401, "secret webhook invalide")
            try:
                corps = await requete.json()
            except Exception:
                corps = {"_corps_illisible": (await requete.body()).decode(
                    "utf-8", "replace")}
            _sonde.journaliser(_sonde.resume(corps, entetes, t, voie_auth), chemin_sonde)
            modele = corps.get("model") if isinstance(corps, dict) else None
            # Vapi envoie `stream: true` et ne prononce PAS une réponse d'un seul bloc :
            # 200 côté serveur, silence à l'oreille (mesuré le 25/08 à 21:02). D'où le
            # flux — un mode de TRANSPORT. La phrase, elle, part entière et d'un seul
            # morceau : voir `sonde_voix.evenements_sse`, où la raison est écrite.
            if isinstance(corps, dict) and corps.get("stream"):
                return StreamingResponse(
                    _vapi.evenements_sse(_sonde.PHRASE_SONDE, modele or "", t),
                    media_type="text/event-stream",
                    # la plateforme lit au fil de l'eau : un proxy qui met en tampon
                    # rendrait la mesure de latence fausse
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
            return JSONResponse(
                _vapi.reponse_openai(_sonde.PHRASE_SONDE, modele or "", t))

    # ---- capture du payload sur la route de PRODUCTION (hors produit) ----
    # La sonde de l'étape 0 ne capture que `/voix/sonde`. Or la question du 02/09 — la
    # plateforme nous transmet-elle le numéro APPELANT ? — ne se pose que sur un appel
    # téléphonique réel, qui passe par `/voix/vapi`. Faire basculer l'URL de l'assistant
    # vers la sonde le temps d'un appel répondrait, mais l'appel ne jouerait plus le
    # produit : on mesurerait la plateforme sans mesurer l'agent.
    #
    # Un seul appel doit donc faire les deux. Même journal, même variable
    # (`RELAIS_SONDE_VOIX`), donc éteinte par défaut comme le reste — et UNE SEULE fois
    # par appel, au premier tour : le payload est réémis à chaque tour, et le fichier
    # doit rester lisible.
    def _capturer_payload(corps: dict, entetes: dict, t, voie_auth: str | None) -> None:
        """Consigne la charge utile et ses identifiants candidats. Ne remonte JAMAIS rien.

        Même arbitrage que `_noter_dispo` : une exception dans un outil de diagnostic
        ferait raccrocher au nez d'un client.
        """
        if sonde_voix is None:
            return
        try:
            resume = _sonde.resume(corps, entetes, t, voie_auth)
            resume["identifiants_candidats"] = _sonde.identifiants_candidats(corps)
            resume["route"] = "/voix/vapi"
            _sonde.journaliser(resume, pathlib.Path(sonde_voix))
        except Exception:                                            # noqa: BLE001
            pass

    # ---- sonde des tournures de temps (hors produit, éteinte par défaut) ----
    _chemin_dispo = pathlib.Path(sonde_dispo) if sonde_dispo is not None else None

    def _noter_dispo(appel_id: str, convo) -> None:
        """Enregistre ce que l'appelant a dit du temps et ce qu'on en a tiré.

        Appelée depuis les DEUX transports, comme `_cloturer_appel` : une sonde qui
        n'observerait qu'une porte donnerait une image fausse de ce que les gens disent.

        Rien ne remonte d'ici. Une exception dans un outil de diagnostic ferait raccrocher
        au nez d'un client — c'est le seul arbitrage acceptable, et il vaut aussi pour
        l'écriture du fichier (disque plein, droits) autant que pour la lecture.
        """
        if _chemin_dispo is None:
            return
        try:
            entree = _sonde_dispo.lecture(convo)
            if entree is not None:
                entree["appel"] = appel_id
                _sonde_dispo.journaliser(entree, _chemin_dispo)
        except Exception:                                            # noqa: BLE001
            pass

    # ---- porte voix : adaptateur de la plateforme vocale ----
    def _cloturer_appel(appel_id: str, convo, artisan, t) -> str | None:
        """Fin d'appel : lead, puis RDV si un créneau a été réservé. Rend l'id du RDV.

        Partagé avec `/webhooks/appel/{id}/tour` : deux transports pour un seul métier.
        Le jour où l'un des deux oublierait de créer le RDV, c'est LA fonction produit qui
        disparaîtrait — sans la moindre erreur visible.
        """
        donnees = build_lead(convo)
        lead = depot.cloturer_appel(appel_id, donnees, t)
        if not donnees.get("rdv"):
            return None
        rdv = depot.creer_rdv(lead_id=lead.id, hold=donnees["rdv"],
                              lead_donnees=donnees, cfg=artisan.config, maintenant=t)
        # le push part ici ; l'échéance, elle, court depuis la réservation (rdv.py)
        rdv.notifier(t)
        depot.sauver_rdv(rdv)
        return rdv.id

    @app.post("/voix/vapi")
    @app.post("/voix/vapi/chat/completions")
    async def voix_vapi(requete: Request):
        """Un tour d'appel vocal. **Cette fonction ne décide rien** : elle traduit.

        Tout ce qu'elle sait de la plateforme est dans `vapi.py`, et vient de la récolte
        de l'étape 0 — pas d'une documentation.
        """
        entetes = dict(requete.headers)
        if not _secret_webhook_present(entetes):
            raise HTTPException(401, "secret webhook invalide")
        try:
            corps = await requete.json()
        except Exception:
            raise HTTPException(400, "charge utile illisible") from None
        if not isinstance(corps, dict):
            raise HTTPException(400, "charge utile illisible")

        appel_id = _vapi.identifiant_appel(corps)
        if not appel_id:
            # sans clé de conversation, chaque tour repartirait de zéro : mieux vaut un
            # refus lisible qu'un agent amnésique au téléphone
            raise HTTPException(400, "identifiant d'appel absent (call.id)")
        artisan, voie = _vapi.artisan_de_l_appel(corps, registre, voix_artisan_defaut)
        if artisan is None:
            # ON CAPTURE AVANT DE REFUSER. L'appel qu'on rejette est précisément celui
            # dont le payload nous manque le plus : un numéro composé absent du registre
            # ne se diagnostique pas autrement, et un appel réel se paie — parfois en
            # international. Capturer après le refus revenait à faire payer un appel pour
            # zéro information, ce qui est le contraire d'une sonde.
            _capturer_payload(corps, entetes, maintenant(), voie)
            raise HTTPException(
                404, "aucun artisan pour cet appel : ni numéro appelé reconnu, ni "
                     "artisan par défaut configuré (RELAIS_VOIX_ARTISAN)")

        t = maintenant()
        modele = corps.get("model") or ""
        try:
            appel = depot.appel(appel_id)
        except Introuvable:
            appel = None

        if appel is None or appel.etat_conversation is None:
            # OUVERTURE. L'annonce IA sort d'ICI, jamais d'un `firstMessage` configuré
            # côté plateforme : elle est non négociable (règle n°5) et ne doit pas pouvoir
            # diverger dans un tableau de bord. Configurer l'assistant Vapi SANS premier
            # message, pour que ce soit notre moteur qui parle en premier.
            #
            # Le calendrier est calé sur l'horloge de l'appel (cf. `/webhooks/appel`) :
            # son `now` voyage dans l'état sérialisé, donc « demain entre 08h et 10h »
            # garde le même sens jusqu'à la fin de l'appel, même passé minuit.
            # Le numéro D'OÙ l'on appelle, transmis par la plateforme (R81). Passé à
            # l'OUVERTURE seulement : il est une propriété de l'appel, pas du tour, et il
            # voyage ensuite dans l'état sérialisé comme le reste. Le contrôleur décide
            # s'il est exploitable — un appelant masqué ou un indicatif étranger ne doit
            # pas être prononcé.
            convo = Conversation(artisan.config, fabrique_llm(),
                                 CalendarStub(
                                     artisan.config, now=t,
                                     occupes=_creneaux_pris(artisan.id, t)),
                                 numero_appelant=_vapi.numero_appelant(corps))
            texte = convo.open()
            if appel is None:
                depot.ouvrir_appel(artisan.id, t, appel_id=appel_id,
                                   config=artisan.config)
                # premier tour de CET appel : le seul moment où l'on capture
                _capturer_payload(corps, entetes, t, voie)
            depot.enregistrer_etat(appel_id, convo.to_dict())
            return _repondre_voix(texte, modele, t, corps)

        # `__avant` : l'état tel qu'il était AVANT le dernier tour client. Rangé dans le
        # même blob que l'état courant plutôt que dans une colonne — le dépôt stocke un
        # JSON opaque, `Conversation.from_dict` ignore les clés qu'il ne connaît pas, et
        # les tests qui lisent `etat_conversation["transcript"]` continuent de marcher.
        # Il sert au REMBOBINAGE (R70) et à rien d'autre.
        brut = appel.etat_conversation
        instantane_avant = brut.get("__avant")
        convo = Conversation.from_dict(brut, artisan.config, fabrique_llm())
        # tours DÉJÀ traités = ce que notre transcript contient, pas ce que la plateforme
        # raconte. C'est notre état qui fait foi.
        traites = sum(1 for r, _ in convo.transcript if r == "client")
        # Le DERNIER texte réellement traité, en plus du compte : une transcription qui se
        # précise porte le même nombre de messages mais un texte plus long (R59). Le
        # comptage seul a coûté un client en zone le 26/08.
        dernier = next((txt for r, txt in reversed(convo.transcript) if r == "client"),
                       None)
        if _vapi.est_un_rejeu(corps, traites, dernier):
            # Retransmission (mesurée : 4 requêtes en 7 s pendant un barge-in). La traiter
            # ferait avancer le contrôleur sans que personne n'ait parlé. On redit la
            # dernière réplique — c'est aussi ce qu'il faut à l'oreille quand l'appelant a
            # coupé l'agent et n'a donc pas entendu la fin.
            dernier = next((txt for r, txt in reversed(convo.transcript) if r == "agent"),
                           None)
            return _repondre_voix(dernier or convo.open(), modele, t, corps)

        # REMBOBINAGE (R70). La transcription du tour en cours se précise : l'appelant n'a
        # parlé qu'une fois. On repart donc de l'état d'AVANT ce tour et on le rejoue avec
        # la meilleure version du texte, au lieu d'empiler un tour de plus. Sans cela,
        # celui qui dit tout d'un coup — problème, commune, numéro — voyait chaque
        # affinage compter pour un numéro incomplet, et se faisait raccrocher au nez.
        #
        # Faute d'instantané (état écrit avant R70, ou tout premier tour), on retombe sur
        # l'ancien comportement : mieux vaut un tour de trop qu'un appel perdu.
        textes = _vapi.messages_utilisateur(corps)
        if _vapi.est_un_affinage(corps, traites, dernier) and instantane_avant is not None:
            convo = Conversation.from_dict(instantane_avant, artisan.config,
                                           fabrique_llm())
            # le MÊME tour, dans sa meilleure version. Le point de rembobinage ne bouge
            # pas : l'affinage suivant devra repartir d'ici, pas d'ici plus un tour.
            a_traiter = textes[-1:]
        else:
            # tour NOUVEAU : c'est l'état courant qui devient le point de rembobinage.
            # Sans retirer `__avant`, l'instantané s'emboîterait en lui-même et le blob
            # enflerait à chaque tour.
            instantane_avant = {c: v for c, v in brut.items() if c != "__avant"}
            # RATTRAPAGE. La plateforme renvoie tout l'historique ; nous ne lisions que
            # le dernier message. Si une requête est perdue (réseau, 500, expiration), la
            # suivante arrive avec deux tours d'avance et le tour du milieu était
            # **définitivement perdu** — alors que son texte était dans la charge utile.
            # Mesuré le 26/08 : la commune, le code postal et le problème disparaissaient,
            # seul le numéro restait. Et l'appelant, lui, n'a aucune raison de redire ce
            # qu'il a déjà dit : c'est le « Déjà dit. » de R59, vu par un autre chemin.
            #
            # Le repli sur le dernier message couvre l'état écrit AVANT R70, où aucun
            # instantané n'existe et où l'on ne peut donc pas rembobiner.
            a_traiter = textes[traites:] or textes[-1:]
        # BORNE. Un retard de un ou deux vient d'une requête perdue, ce qui arrive. Un
        # retard de dix voudrait dire que plusieurs requêtes consécutives ont échoué, et
        # rejouer dix tours dans une seule requête HTTP ferait expirer l'appel — le client
        # entendrait le silence, ce qui est pire que de perdre un tour. On garde les plus
        # RÉCENTS : c'est le contexte utile.
        if len(a_traiter) > 3:
            a_traiter = a_traiter[-3:]
        texte = None
        for ligne in a_traiter:
            texte = convo.process(ligne)
            if convo.state in (State.S11_CLOTURE, State.FIN):
                break
        depot.enregistrer_etat(appel_id, {**convo.to_dict(),
                                          "__avant": instantane_avant})
        _noter_dispo(appel_id, convo)          # après la persistance : l'état d'abord

        if convo.state in (State.S11_CLOTURE, State.FIN) and appel.fin_a is None:
            _cloturer_appel(appel_id, convo, artisan, t)
        return _repondre_voix(texte, modele, t, corps)

    def _repondre_voix(texte: str, modele: str, t, corps: dict):
        """Une réplique, dans le transport que la plateforme attend.

        Le texte est déjà passé par les garde-fous (`_say` dans `engine.py`) AVANT
        d'arriver ici : c'est tout l'objet de la décision d'arbitrage n°4. Voir
        `vapi.evenements_sse` pour la raison écrite au long.
        """
        if corps.get("stream"):
            return StreamingResponse(
                _vapi.evenements_sse(texte, modele, t),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
        return JSONResponse(_vapi.reponse_openai(texte, modele, t))

    # ---- porte téléphonie ----
    @app.post("/webhooks/appel", response_model=TourOut,
              dependencies=[Depends(webhook_authentifie)])
    def ouvrir_appel(corps: OuvrirAppelIn) -> TourOut:
        artisan = registre.par_numero_relais(corps.numero_appele)
        if artisan is None:
            raise HTTPException(404, "numéro Relais inconnu")
        t = maintenant()
        # le calendrier est calé sur l'horloge de l'appel, PAS sur dt.datetime.now() :
        # son `now` voyage ensuite dans l'état sérialisé, donc les libellés déjà prononcés
        # (« demain entre 08h et 10h ») gardent le même sens jusqu'à la fin de l'appel,
        # même s'il franchit minuit.
        convo = Conversation(artisan.config, fabrique_llm(),
                             CalendarStub(artisan.config, now=t,
                                          occupes=_creneaux_pris(artisan.id, t)))
        texte = convo.open()
        # L'INSTANTANÉ de config (migration 011) : ce que l'agent sait est figé au
        # moment où l'appel s'ouvre. C'est ce qui remplace l'historique git du
        # fichier de config — et qui permet, un mois plus tard, de répondre
        # exactement à « qu'est-ce que l'agent savait pendant CET appel ? ».
        appel = depot.ouvrir_appel(artisan.id, t, config=artisan.config)
        depot.enregistrer_etat(appel.id, convo.to_dict())
        return TourOut(appel_id=appel.id, texte=texte, termine=False)

    @app.post("/webhooks/appel/{appel_id}/tour", response_model=TourOut,
              dependencies=[Depends(webhook_authentifie)])
    def tour(appel_id: str, corps: TourIn) -> TourOut:
        appel = depot.appel(appel_id)                    # 404 si inconnu
        if appel.fin_a is not None:
            raise HTTPException(409, "appel déjà clôturé")
        artisan = registre.artisan(appel.artisan_id)
        if artisan is None:                              # registre modifié en cours d'appel
            raise HTTPException(409, "artisan de cet appel introuvable au registre")

        if appel.etat_conversation is None:
            # incohérence : l'appel existe mais son état n'a jamais été écrit. 409 explicite
            # plutôt qu'une AttributeError remontée en 500 (défaut trouvé par mutation).
            raise HTTPException(409, "état de conversation absent pour cet appel")
        # tout l'état vient de la base, rien de la mémoire du process
        convo = Conversation.from_dict(appel.etat_conversation, artisan.config,
                                       fabrique_llm())
        texte = convo.process(corps.texte)
        depot.enregistrer_etat(appel_id, convo.to_dict())
        _noter_dispo(appel_id, convo)          # après la persistance : l'état d'abord

        if convo.state not in (State.S11_CLOTURE, State.FIN):
            return TourOut(appel_id=appel_id, texte=texte, termine=False)

        # fin d'appel : lead, puis RDV si un créneau a été réservé — même code que la
        # porte voix, pour que les deux transports ne puissent pas diverger
        t = maintenant()
        rdv_id = _cloturer_appel(appel_id, convo, artisan, t)
        return TourOut(appel_id=appel_id, texte=texte, termine=True, rdv_id=rdv_id)

    # ---- porte app artisan ----
    def _rdv_de_l_artisan(rdv_id: str, artisan: Artisan):
        rdv = depot.rdv(rdv_id)                          # 404 si inconnu
        if rdv.artisan_id != artisan.id:
            # 404 et non 403 : ne pas révéler qu'un RDV existe chez un autre artisan
            raise HTTPException(404, "introuvable")
        return rdv

    def _en_sortie(rdv, avec_lead: bool = True) -> RdvOut:
        lead = None
        if avec_lead:
            donnees = depot.lead(rdv.lead_id).donnees
            lead = LeadOut(**{k: v for k, v in donnees.items()
                              if k in LeadOut.model_fields})
        return RdvOut(id=rdv.id, statut=rdv.statut.value, creneau=rdv.creneau,
                      duree_min=rdv.duree_min, urgence=rdv.urgence,
                      expire_a=rdv.expire_a, cree_a=rdv.cree_a,
                      notifie_a=rdv.notifie_a, lead=lead)

    @app.get("/rdv", response_model=list[RdvOut])
    def boite_de_validation(artisan: Artisan = Depends(artisan_authentifie)
                            ) -> list[RdvOut]:
        """LA fonction produit : les RDV que l'artisan doit valider."""
        return [_en_sortie(r) for r in depot.rdvs_en_attente(artisan.id)]

    # Les deux issues décidées par l'artisan écrivent au client. Ce n'est pas une
    # politesse : l'agent lui a promis un SMS AU TÉLÉPHONE (« vous recevrez un SMS de
    # confirmation d'ici X heures »). Un refus silencieux le laisserait attendre un
    # rendez-vous qui n'aura pas lieu. R27 confronte la promesse aux envois réels.
    _SUITE_CLIENT = {"valider": messages.confirmation_client,
                     "refuser": messages.repli_client}

    def _decider(rdv_id: str, artisan: Artisan, action: str) -> RdvOut:
        rdv = _rdv_de_l_artisan(rdv_id, artisan)
        t = maintenant()
        try:
            # message construit AVANT la transition, comme pour la reproposition : si un
            # gabarit est refusé par les garde-fous, rien n'a bougé et l'artisan voit un
            # 409 franc plutôt qu'un RDV décidé dont le client n'est jamais prévenu.
            brouillon = _SUITE_CLIENT[action](rdv, depot.lead(rdv.lead_id).donnees,
                                              artisan.config)
            getattr(rdv, action)(t)
        except (TransitionInterdite, messages.MessageInterdit) as exc:
            # 409 : l'échéance est passée, ou le RDV est déjà décidé. Le message vient du
            # domaine — c'est lui qui sait pourquoi, pas l'API.
            raise HTTPException(409, str(exc)) from None
        depot.sauver_rdv(rdv)
        depot.enfiler_message(brouillon, t)
        return _en_sortie(rdv)

    @app.post("/rdv/{rdv_id}/valider", response_model=RdvOut)
    def valider(rdv_id: str, artisan: Artisan = Depends(artisan_authentifie)) -> RdvOut:
        return _decider(rdv_id, artisan, "valider")

    @app.post("/rdv/{rdv_id}/refuser", response_model=RdvOut)
    def refuser(rdv_id: str, artisan: Artisan = Depends(artisan_authentifie)) -> RdvOut:
        return _decider(rdv_id, artisan, "refuser")

    @app.post("/rdv/{rdv_id}/reproposer", response_model=RdvOut)
    def reproposer(rdv_id: str, corps: ReproposerIn,
                   artisan: Artisan = Depends(artisan_authentifie)) -> RdvOut:
        """L'artisan propose un autre créneau (spec §3.5bis). Le client reçoit un SMS avec
        un lien de validation à un tap — pas un « Répondez OUI » : un sender alphanumérique
        ne reçoit rien, et les numéros mobiles FR sont interdits à l'A2P."""
        rdv = _rdv_de_l_artisan(rdv_id, artisan)
        t = maintenant()
        try:
            jour = dt.date.fromisoformat(corps.date)
        except ValueError:
            raise HTTPException(422, "date attendue au format AAAA-MM-JJ") from None
        creneau = {"date": corps.date, "de": corps.de, "a": corps.a, "urgence": False,
                   # même fonction que le calendrier : le libellé lu par le client est
                   # celui qu'aurait prononcé l'agent. « aujourd'hui » se juge à la
                   # pendule de l'artisan — en UTC, un créneau reproposé à 00h30 le
                   # deviendrait « demain » pour tout le monde sauf pour lui.
                   "label": libelle_creneau(
                       jour, corps.de, corps.a,
                       temps.en_local(t, artisan.config).date())}
        jeton, empreinte_jeton = creer_jeton()
        try:
            rdv.reproposer(creneau, artisan.config, t, empreinte_jeton)
            # message construit AVANT l'écriture : si le gabarit refuse (pas de téléphone,
            # garde-fou), rien n'est persisté et l'artisan voit un 409 franc
            brouillon = messages.reproposition_client(
                rdv, depot.lead(rdv.lead_id).donnees, artisan.config,
                lien(base_url, jeton))
        except (TransitionInterdite, ValueError, messages.MessageInterdit) as exc:
            raise HTTPException(409, str(exc)) from None
        # écriture d'abord, mise en file ensuite : la validité du lien dépend de l'état
        # persisté. L'ordre inverse enverrait un lien mort si l'écriture échouait.
        depot.sauver_rdv(rdv)
        depot.enfiler_message(brouillon, t)
        return _en_sortie(rdv)

    # ---- porte client : le jeton EST l'authentification (le client n'a pas de compte) ----
    def _rdv_du_jeton(jeton: str):
        return depot.rdv_par_confirmation(empreinte(jeton))   # 404 si inconnu ou consommé

    # Ces deux routes rendent du HTML, pas du JSON : c'est une PAGE, ouverte depuis un SMS
    # sur un téléphone. Un client ne lit pas `{"statut":"repropose"}`.
    def _html(corps: str, code: int = 200) -> HTMLResponse:
        return HTMLResponse(corps, status_code=code)

    def _identite(rdv) -> tuple[str, str]:
        artisan = registre.artisan(rdv.artisan_id)
        if artisan is None:
            raise HTTPException(409, "artisan introuvable au registre")
        e = artisan.config["entreprise"]
        return e["nom"], e["prenom_patron"]

    @app.get("/c/{jeton}", response_class=HTMLResponse)
    def voir_proposition(jeton: str) -> HTMLResponse:
        """Page vue par le client. Volontairement pauvre : entreprise, prénom, créneau.
        **Ni son nom, ni son téléphone, ni le transcript** — l'URL vaut capacité, quiconque
        la possède ne doit rien apprendre de la personne."""
        try:
            rdv = _rdv_du_jeton(jeton)
        except Introuvable:
            # 404 avec une page lisible, et le MÊME texte qu'un lien déjà utilisé :
            # on ne renseigne pas un curieux, et on rassure celui qui a déjà validé
            return _html(pages.lien_invalide(NOM), 404)
        entreprise, prenom = _identite(rdv)
        if rdv.est_echu(maintenant()):
            return _html(pages.creneau_perime(NOM, prenom), 410)
        return _html(pages.proposition(NOM, entreprise, prenom,
                                       rdv.creneau["label"],
                                       action=f"/c/{jeton}"))

    @app.post("/c/{jeton}", response_class=HTMLResponse)
    def confirmer(jeton: str) -> HTMLResponse:
        try:
            rdv = _rdv_du_jeton(jeton)
        except Introuvable:
            return _html(pages.lien_invalide(NOM), 404)
        entreprise, prenom = _identite(rdv)
        t = maintenant()
        try:
            rdv.confirmer_par_client(jeton, t)
        except TransitionInterdite:
            # échéance passée, ou RDV déjà décidé : le domaine tranche, la page explique
            return _html(pages.creneau_perime(NOM, prenom), 409)
        depot.sauver_rdv(rdv)
        # Pas de SMS de confirmation au client ici, à la différence de `_decider` : il
        # vient de taper le lien et lit la page de confirmation à l'instant même. Le lui
        # réécrire serait un crédit payé pour lui apprendre ce qu'il a sous les yeux.
        # l'artisan doit l'apprendre sans avoir à ouvrir l'app
        try:
            depot.enfiler_message(
                messages.confirmation_artisan(rdv, depot.lead(rdv.lead_id).donnees,
                                              registre.artisan(rdv.artisan_id).config), t)
        except messages.MessageInterdit:
            pass          # la validation du client compte, la notification est secondaire
        return _html(pages.confirmee(NOM, entreprise, prenom, rdv.creneau["label"]))

    # ---- app artisan : pages HTML, sans JavaScript ----
    # Routes distinctes des routes JSON : celles-ci redirigent après action (303) pour que
    # le rechargement du navigateur ne rejoue pas le POST. Les routes JSON restent pour la
    # future app mobile.
    @app.get("/connexion", response_class=HTMLResponse)
    def page_connexion() -> HTMLResponse:
        return HTMLResponse(pages.connexion(NOM))

    def _ouvrir_session(artisan_id: str, t) -> RedirectResponse:
        """Session posée et cookie émis. Le seul endroit qui les crée."""
        clair, emp = session.creer_jeton()
        depot.creer_session(emp, artisan_id, session.expiration(t), t)
        reponse = RedirectResponse("/app", status_code=303)
        reponse.set_cookie(session.NOM_COOKIE, clair,
                           **session.attributs_cookie(secure=cookie_secure))
        reponse.delete_cookie(COOKIE_CONNEXION, path="/")
        return reponse

    @app.get("/connexion/lien/{artisan_id}/{jeton}")
    def connexion_par_lien(artisan_id: str, jeton: str):
        """Le lien à usage unique : il ouvre la session, puis il meurt.

        L'IDENTIFIANT DE L'ARTISAN EST DANS L'URL, et ce n'est pas une faiblesse : ce
        n'est pas un secret, et le port cherche un code PAR artisan. Le secret, c'est le
        jeton — 32 octets — et il est comparé à temps constant à l'empreinte stockée.

        CONSOMMÉ QUOI QU'IL ARRIVE en cas de succès : un lien qui ouvrirait deux sessions
        n'est plus à usage unique, et celui qui traîne dans un historique de navigateur ou
        une conversation redeviendrait une clé.
        """
        t = maintenant()
        pose = depot.code_connexion(artisan_id)
        if pose is None or pose.expire_a <= t \
                or not secrets.compare_digest(pose.empreinte,
                                              connexion.empreinte(jeton)):
            # Un lien périmé, déjà servi ou faux mène à la page de connexion ordinaire —
            # pas à une erreur : celui qui clique est probablement l'artisan, en retard.
            return HTMLResponse(
                pages.connexion(NOM, "Ce lien n'est plus valable. Demandez un code "
                                     "avec votre mobile, ou un nouveau lien."),
                status_code=401)
        if registre.artisan(artisan_id) is None:
            return HTMLResponse(pages.connexion(NOM), status_code=401)
        depot.supprimer_code_connexion(artisan_id)
        return _ouvrir_session(artisan_id, t)

    @app.post("/connexion")
    def demander_code(telephone: str = Form(...),
                      mot_de_passe: str = Form(default="")):
        """Le mobile ouvre la session — par MOT DE PASSE s'il en a un, par CODE sinon.

        Deux portes, un seul écran : l'artisan tape son numéro, et son mot de passe s'il
        en a défini un. C'est ce que demandait Geoffrey le 22/09 — « comme un site
        classique, qu'ils pourront enregistrer dans leurs appareils » : le gestionnaire
        du navigateur remplit les deux champs, et personne ne se reconnecte.

        Le CODE SMS ne disparaît pas et ne disparaîtra pas : c'est la seule voie pour qui
        a perdu son mot de passe, changé de téléphone, ou n'en a jamais défini.

        **La réponse est la MÊME que le numéro soit connu ou non** : sinon cette page
        dirait à quiconque la sollicite si tel numéro est celui d'un de nos artisans.
        Un numéro mal tapé mène donc à l'écran de saisie, où le code sera simplement
        refusé — et le lien « recommencer » est là pour ça.
        """
        numero = connexion.normaliser_telephone(telephone)
        artisan = registre.par_telephone(numero)
        t = maintenant()

        # PORTE 1 — LE MOT DE PASSE, quand l'artisan en a défini un et l'a saisi
        # (migration 014). « comme un site classique, qu'ils pourront enregistrer dans
        # leurs appareils » : le navigateur le propose, l'artisan ne se reconnecte plus.
        #
        # La vérification tourne MÊME quand le numéro est inconnu, contre une empreinte
        # factice : sinon le temps de réponse dirait quels mobiles sont enregistrés chez
        # nous — scrypt coûte assez cher pour que l'écart se mesure à distance.
        if mot_de_passe:
            ligne = depot.artisan_par_telephone(numero) if artisan else None
            if motdepasse.verifier(
                    mot_de_passe,
                    (ligne.mot_de_passe if ligne and ligne.mot_de_passe
                     else motdepasse.EMPREINTE_FACTICE)):
                return _ouvrir_session(artisan.id, t)
            # Un échec ne dit RIEN de plus : ni que le compte existe, ni qu'il a un mot
            # de passe. Le même écran que pour un numéro inconnu, avec un message.
            return HTMLResponse(
                pages.connexion(NOM, "Numéro ou mot de passe incorrect."),
                status_code=401)

        reponse = HTMLResponse(pages.saisie_code(NOM, _masquer(numero)))
        if artisan is None:
            return reponse

        # Frein au renvoi : chaque code est un SMS facturé et une notification chez
        # quelqu'un. Sans lui, un tiers fait sonner le téléphone d'un artisan en boucle à
        # nos frais. Le code précédent reste valable, donc rien n'est perdu pour l'artisan
        # qui insiste — et il n'apprend rien de plus qu'un inconnu, la page est la même.
        precedent = depot.code_connexion(artisan.id)
        if precedent and (t - precedent.cree_a).total_seconds() < \
                connexion.DELAI_RENVOI_SECONDES:
            return reponse

        code, emp = connexion.creer_code()
        depot.poser_code_connexion(artisan.id, emp, connexion.expiration(t), t,
                                   telephone=numero)
        try:
            brouillon = messages.code_connexion_artisan(
                artisan.id, numero, code, artisan.config,
                connexion.DUREE_MINUTES, empreinte_code=emp)
        except messages.MessageInterdit:
            return reponse           # gabarit refusé : on n'en dit pas plus au visiteur
        message, _ = depot.enfiler_message(brouillon, t)
        # Envoi IMMÉDIAT et ciblé : un code de connexion qui arrive au prochain passage du
        # cron n'est pas un code de connexion. La file reste la source de vérité (et le
        # worker rattrapera si l'envoi direct échoue), on ne fait que la doubler ici.
        if expediteur is not None:
            expediteur.passer(t, seulement={message.id})
        reponse.set_cookie(COOKIE_CONNEXION, artisan.id,
                           max_age=connexion.DUREE_MINUTES * 60, path="/",
                           httponly=True, samesite="lax", secure=cookie_secure)
        return reponse

    @app.post("/connexion/code")
    def verifier_code(code: str = Form(...),
                      relais_connexion: str = Cookie(default="",
                                                     alias=COOKIE_CONNEXION)):
        """Vérifie le code et ouvre la session.

        **Un seul message d'erreur pour toutes les causes** (pas de code en cours, périmé,
        essais épuisés, mauvais code) : les distinguer dirait à qui tâtonne s'il vise un
        numéro connu et combien d'essais il lui reste.
        """
        REFUS = "Code incorrect ou expiré. Demandez-en un nouveau."
        t = maintenant()
        pose = depot.code_connexion(relais_connexion) if relais_connexion else None
        if pose is None or t >= pose.expire_a:
            if pose is not None:
                depot.supprimer_code_connexion(pose.artisan_id)
            return HTMLResponse(pages.saisie_code(NOM, "", REFUS), status_code=401)

        # L'essai est consommé AVANT la comparaison : un processus tué au mauvais moment,
        # ou une comparaison qui lève, ne doit pas offrir une tentative gratuite. C'est
        # tout ce qui sépare 6 chiffres d'un secret devinable.
        essais = depot.consommer_essai_code(pose.artisan_id)
        if essais > connexion.ESSAIS_MAX:
            depot.supprimer_code_connexion(pose.artisan_id)
            return HTMLResponse(pages.saisie_code(NOM, "", REFUS), status_code=401)
        if not secrets.compare_digest(pose.empreinte,
                                      connexion.empreinte(code)):
            if essais >= connexion.ESSAIS_MAX:
                depot.supprimer_code_connexion(pose.artisan_id)
            return HTMLResponse(pages.saisie_code(NOM, _masquer(pose.telephone or ""), REFUS),
                                status_code=401)

        artisan = registre.artisan(pose.artisan_id)
        if artisan is None:          # retiré du registre entre la demande et la saisie
            depot.supprimer_code_connexion(pose.artisan_id)
            return HTMLResponse(pages.connexion(NOM, REFUS), status_code=401)
        # usage unique : le code ne resservira pas, même dans sa fenêtre de validité
        depot.supprimer_code_connexion(pose.artisan_id)
        return _ouvrir_session(artisan.id, t)

    @app.post("/deconnexion")
    def fermer_session(relais_session: str = Cookie(default="",
                                                   alias=session.NOM_COOKIE)):
        if relais_session:
            depot.supprimer_session(session.empreinte(relais_session))
        reponse = RedirectResponse("/connexion", status_code=303)
        reponse.delete_cookie(session.NOM_COOKIE, path="/")
        return reponse

    @app.post("/app/{rdv_id}/{action}")
    def agir(rdv_id: str, action: str,
             artisan: Artisan = Depends(artisan_authentifie),
             date: str = Form(default=""), de: str = Form(default=""),
             a: str = Form(default="")):
        """Une action, puis une redirection : le rechargement ne rejoue pas le POST."""
        if action not in ("valider", "refuser", "reproposer"):
            raise HTTPException(404, "action inconnue")
        try:
            if action == "reproposer":
                reproposer(rdv_id, ReproposerIn(date=date, de=de, a=a), artisan)
            else:
                _decider(rdv_id, artisan, action)
        except HTTPException as exc:
            if exc.status_code == 404:
                raise
            # Un refus du domaine (échéance passée, RDV déjà décidé) doit rendre une PAGE :
            # après un tap sur un téléphone, `{"detail": "..."}` est illisible.
            return HTMLResponse(pages.action_impossible(NOM, str(exc.detail)),
                                status_code=exc.status_code)
        return RedirectResponse("/app", status_code=303)

    # ------------------------------------------------------------------ ADMINISTRATION
    #
    # Sujet DISTINCT de l'artisan : sa table, sa session, son cookie (migration 012).
    # « je suis pas un artisan je suis le maitre du produit » — et le produit ne peut pas
    # être auto-servi : un plombier ne s'active pas seul (il faut lui provisionner un
    # numéro et lui faire configurer son renvoi conditionnel). Les premiers artisans sont
    # donc inscrits À LA MAIN, ici, pendant ou après l'appel de vente. Ce formulaire
    # deviendra la page d'inscription le jour où un numéro pourra être attribué tout seul.

    def _admin_de_session(jeton: str) -> str | None:
        if not jeton:
            return None
        try:
            return depot.admin_de_session(session.empreinte(jeton), maintenant())
        except Introuvable:
            return None

    def _exige_admin(jeton: str):
        """Le compte, ou `None`. L'appelant rend la page de connexion — jamais un 401 nu :
        un admin dont la session a expiré doit voir un écran utilisable."""
        aid = _admin_de_session(jeton)
        if aid is None:
            return None
        return next((a for a in depot.admins() if a.id == aid), None)

    def _modele_config() -> dict:
        """Le modèle dont part un nouvel artisan, et l'étalon de la validation.

        C'est `dupont.json` : le fichier que la suite de tests exerce à chaque exécution.
        S'en servir comme référence garantit que les exigences de validation suivent le
        moteur — une liste de clés écrite à la main aurait vieilli en silence.
        """
        return _json_mod.loads(
            (DOSSIER_CONFIG / "dupont.json").read_text(encoding="utf-8"))

    @app.get("/admin/connexion", response_class=HTMLResponse)
    def admin_page_connexion() -> HTMLResponse:
        return HTMLResponse(pages.admin_connexion(NOM))

    @app.post("/admin/connexion")
    def admin_ouvrir_session(identifiant: str = Form(default=""),
                             mot_de_passe: str = Form(default="")):
        compte = depot.admin_par_identifiant(identifiant.strip())
        # UN SEUL message pour les trois échecs — compte inconnu, compte désactivé, mot
        # de passe faux. La vérification est exécutée MÊME quand le compte est inconnu,
        # contre une empreinte factice : sinon le temps de réponse dirait quels
        # identifiants existent, et scrypt coûte assez cher pour que l'écart se mesure.
        empreinte_factice = "scrypt$32768$8$1$" + "00" * 16 + "$" + "00" * 32
        ok = admin_mdp.verifier(mot_de_passe,
                                compte.mot_de_passe if compte else empreinte_factice)
        if compte is None or not ok:
            return HTMLResponse(
                pages.admin_connexion(NOM, "Identifiant ou mot de passe incorrect."),
                status_code=401)
        jeton, emp = session.creer_jeton()
        t = maintenant()
        depot.creer_session_admin(
            emp, compte.id, t + dt.timedelta(days=admin_mdp.DUREE_JOURS), t)
        reponse = RedirectResponse("/admin", status_code=303)
        attributs = session.attributs_cookie(cookie_secure)
        attributs["max_age"] = admin_mdp.DUREE_JOURS * 24 * 3600
        reponse.set_cookie(admin_mdp.NOM_COOKIE, jeton, **attributs)
        return reponse

    @app.post("/admin/deconnexion")
    def admin_fermer_session(
            nelyo_admin: str = Cookie(default="", alias=admin_mdp.NOM_COOKIE)):
        if nelyo_admin:
            depot.supprimer_session_admin(session.empreinte(nelyo_admin))
        reponse = RedirectResponse("/admin/connexion", status_code=303)
        reponse.delete_cookie(admin_mdp.NOM_COOKIE, path="/")
        return reponse

    @app.get("/admin", response_class=HTMLResponse)
    def admin_liste(nelyo_admin: str = Cookie(default="", alias=admin_mdp.NOM_COOKIE)):
        compte = _exige_admin(nelyo_admin)
        if compte is None:
            return HTMLResponse(pages.admin_connexion(NOM), status_code=401)
        lignes = []
        for a in depot.artisans():
            lignes.append({
                "id": a.id, "nom": a.nom_affiche,
                "numero_relais": a.numero_relais, "telephone": a.telephone,
                "etat": a.etat_abonnement,
                # D'où vient sa config : « base » depuis la migration 011, « fichier »
                # pour les artisans antérieurs. Affiché parce que c'est exactement ce
                # qu'on veut voir disparaître, et qu'on ne le verra pas autrement.
                "source_config": ("base" if a.config is not None
                                  else (a.config_fichier or "AUCUNE")),
                "appels": depot.compter_appels(a.id),
                "utilisable": a.utilisable(),
            })
        return HTMLResponse(pages.admin_artisans(NOM, compte.nom or compte.identifiant,
                                                 lignes))

    @app.get("/admin/artisan/nouveau", response_class=HTMLResponse)
    def admin_nouveau(nelyo_admin: str = Cookie(default="", alias=admin_mdp.NOM_COOKIE)):
        if _exige_admin(nelyo_admin) is None:
            return HTMLResponse(pages.admin_connexion(NOM), status_code=401)
        # Pré-rempli avec le MODÈLE : un formulaire vide obligerait à connaître par cœur
        # onze sections, et la première config créée serait incomplète.
        return HTMLResponse(pages.admin_artisan(
            NOM, {}, _json_mod.dumps(_modele_config(), ensure_ascii=False, indent=2)))

    def _enregistrer_artisan(donnees: dict, existant, nelyo_admin: str,
                             nouveau: bool) -> HTMLResponse:
        """Le chemin d'écriture, partagé par la création et l'édition.

        Un seul endroit valide et écrit : deux chemins jumeaux finiraient par diverger
        sur une vérification, et ce serait celle qui manque qui casserait un appel.
        """
        erreurs: list[str] = []
        identifiant = (donnees.get("id") or "").strip()
        if not identifiant:
            erreurs.append("l'identifiant technique est obligatoire")
        elif not _IDENTIFIANT_VALIDE.fullmatch(identifiant):
            # R97 : l'identifiant voyage dans des URL (`/admin/artisan/<id>/voir`) et
            # sert de clé étrangère. Un espace ou une majuscule y passent — « Nexus
            # artisan » a été créé le 21/09, vingt minutes après l'ouverture de la page
            # — mais ils fabriquent des liens fragiles et des identifiants qu'on ne peut
            # pas retaper à l'identique. On les refuse À LA SAISIE : c'est le seul
            # moment où la correction ne coûte rien.
            erreurs.append(
                f"l'identifiant « {identifiant} » doit être en minuscules, sans espace "
                f"ni accent : lettres, chiffres et tirets (ex. « art-dupont »)")
        elif nouveau and depot.artisan_par_id(identifiant) is not None:
            erreurs.append(f"l'identifiant « {identifiant} » est déjà pris")

        mobile = (donnees.get("telephone") or "").strip()
        if mobile:
            # R96 : deux artisans qui partagent un mobile rendent la connexion par SMS
            # ambiguë, et le registre REFUSE désormais de trancher — donc aucun des deux
            # ne peut plus se connecter. Le refuser ici est la vraie correction : on
            # empêche l'ambiguïté d'exister plutôt que de la gérer après coup.
            autres = [l.id for l in depot.artisans_par_telephone(mobile)
                      if l.id != identifiant]
            if autres:
                erreurs.append(
                    f"le mobile {mobile} est déjà celui de « {autres[0]} » — deux "
                    f"artisans qui le partagent ne peuvent plus se connecter par SMS")

        try:
            brute = _json_mod.loads(donnees.get("config") or "")
        except ValueError as exc:
            brute = None
            erreurs.append(f"config illisible : {exc}")
        if brute is not None:
            erreurs += valider_config(brute, _modele_config())

        numero = (donnees.get("numero_relais") or "").strip()
        if numero:
            # Le numéro Relais DÉSIGNE l'artisan : deux artisans qui le partagent
            # rendraient le rattachement d'un appel arbitraire. La base porte déjà la
            # contrainte ; on la vérifie ici pour rendre un message plutôt qu'une 500.
            occupe = depot.artisan_par_numero_relais(numero)
            if occupe is not None and occupe.id != identifiant:
                erreurs.append(f"le numéro {numero} est déjà celui de « {occupe.id} »")

        if erreurs:
            vue = {"id": "" if nouveau else identifiant,
                   "nom": donnees.get("nom"),
                   "numero_relais": numero,
                   "telephone": donnees.get("telephone"),
                   "etat_abonnement": donnees.get("etat_abonnement")}
            return HTMLResponse(
                pages.admin_artisan(NOM, vue, donnees.get("config") or "",
                                    erreurs=erreurs),
                status_code=400)

        jeton = ""
        empreinte_jeton = existant.token_sha256 if existant is not None else None
        if nouveau:
            # Le jeton est GÉNÉRÉ, jamais repris du dépôt : les jetons de
            # `config/artisans.json` sont des jetons de dév publics.
            jeton = "nelyo_" + secrets.token_urlsafe(24)
            empreinte_jeton = registre_empreinte(jeton)
        depot.enregistrer_artisan(LigneArtisan(
            id=identifiant, nom_affiche=(donnees.get("nom") or "").strip() or None,
            numero_relais=numero or None,
            telephone=(donnees.get("telephone") or "").strip() or None,
            config_fichier=existant.config_fichier if existant is not None else None,
            token_sha256=empreinte_jeton,
            etat_abonnement=(donnees.get("etat_abonnement") or "actif"),
            config=brute))
        relu = depot.artisan_par_id(identifiant)
        return HTMLResponse(pages.admin_artisan(
            NOM,
            {"id": relu.id, "nom": relu.nom_affiche,
             "numero_relais": relu.numero_relais, "telephone": relu.telephone,
             "etat_abonnement": relu.etat_abonnement},
            _json_mod.dumps(relu.config, ensure_ascii=False, indent=2),
            jeton=jeton, cree=nouveau))

    @app.post("/admin/artisan", response_class=HTMLResponse)
    def admin_creer(nelyo_admin: str = Cookie(default="", alias=admin_mdp.NOM_COOKIE),
                    id: str = Form(default=""), nom: str = Form(default=""),
                    numero_relais: str = Form(default=""),
                    telephone: str = Form(default=""),
                    etat_abonnement: str = Form(default="actif"),
                    config: str = Form(default="")):
        if _exige_admin(nelyo_admin) is None:
            return HTMLResponse(pages.admin_connexion(NOM), status_code=401)
        return _enregistrer_artisan(
            {"id": id, "nom": nom, "numero_relais": numero_relais,
             "telephone": telephone, "etat_abonnement": etat_abonnement,
             "config": config}, None, nelyo_admin, nouveau=True)

    @app.get("/admin/artisan/{artisan_id}", response_class=HTMLResponse)
    def admin_editer(artisan_id: str,
                     nelyo_admin: str = Cookie(default="", alias=admin_mdp.NOM_COOKIE)):
        if _exige_admin(nelyo_admin) is None:
            return HTMLResponse(pages.admin_connexion(NOM), status_code=401)
        a = depot.artisan_par_id(artisan_id)
        if a is None:
            raise HTTPException(404, "artisan inconnu")
        # Un artisan dont la config est encore un FICHIER : on montre le contenu du
        # fichier, et l'enregistrer le fera passer en base. La migration se fait donc par
        # l'usage, sans script de conversion à écrire ni à se rappeler de lancer.
        brute = a.config
        if brute is None and a.config_fichier:
            chemin = DOSSIER_CONFIG / a.config_fichier
            brute = (_json_mod.loads(chemin.read_text(encoding="utf-8"))
                     if chemin.exists() else {})
        return HTMLResponse(pages.admin_artisan(
            NOM,
            {"id": a.id, "nom": a.nom_affiche, "numero_relais": a.numero_relais,
             "telephone": a.telephone, "etat_abonnement": a.etat_abonnement},
            _json_mod.dumps(brute or _modele_config(), ensure_ascii=False, indent=2)))

    @app.post("/admin/artisan/{artisan_id}", response_class=HTMLResponse)
    def admin_enregistrer(artisan_id: str,
                          nelyo_admin: str = Cookie(default="",
                                                    alias=admin_mdp.NOM_COOKIE),
                          nom: str = Form(default=""),
                          numero_relais: str = Form(default=""),
                          telephone: str = Form(default=""),
                          etat_abonnement: str = Form(default="actif"),
                          config: str = Form(default="")):
        if _exige_admin(nelyo_admin) is None:
            return HTMLResponse(pages.admin_connexion(NOM), status_code=401)
        existant = depot.artisan_par_id(artisan_id)
        if existant is None:
            raise HTTPException(404, "artisan inconnu")
        return _enregistrer_artisan(
            {"id": artisan_id, "nom": nom, "numero_relais": numero_relais,
             "telephone": telephone, "etat_abonnement": etat_abonnement,
             "config": config}, existant, nelyo_admin, nouveau=False)

    @app.post("/admin/artisan/{artisan_id}/voir")
    def admin_voir_comme(
            artisan_id: str,
            nelyo_admin: str = Cookie(default="", alias=admin_mdp.NOM_COOKIE)):
        """Entrer dans l'espace d'un artisan, en lecture seule.

        Le cookie posé ici ne porte QUE l'identifiant, et il est inerte sans la session
        d'admin — c'est elle l'autorité, revérifiée à chaque requête.
        """
        if _exige_admin(nelyo_admin) is None:
            return HTMLResponse(pages.admin_connexion(NOM), status_code=401)
        if depot.artisan_par_id(artisan_id) is None:
            raise HTTPException(404, "artisan inconnu")
        reponse = RedirectResponse("/app", status_code=303)
        attributs = session.attributs_cookie(cookie_secure)
        attributs["max_age"] = admin_mdp.DUREE_JOURS * 24 * 3600
        reponse.set_cookie(admin_mdp.NOM_COOKIE_VUE, artisan_id, **attributs)
        return reponse

    @app.post("/admin/vue/fin")
    def admin_quitter_vue():
        """Sortir du mode support.

        SOUS `/admin` ET NON `/app/vue/fin`, et c'est une leçon payée le jour même :
        `/app/{rdv_id}/{action}` est déclaré avant, et il capturait `/app/vue/fin` comme
        un RDV « vue » et une action « fin » — donc 401 par la dépendance artisan, sur
        une route censée n'en exiger aucune. Un chemin littéral derrière un chemin à
        paramètre se fait manger ; j'avais écrit ce commentaire quelques heures plus tôt
        au-dessus de `/app/appels`, et je suis quand même tombé dedans.

        Aucune authentification exigée : effacer un cookie qui ne donne aucun droit ne
        peut nuire à personne, et l'exiger empêcherait d'en sortir quand la session
        d'admin vient d'expirer."""
        reponse = RedirectResponse("/admin", status_code=303)
        reponse.delete_cookie(admin_mdp.NOM_COOKIE_VUE, path="/")
        return reponse

    def _fiche_artisan(a, **extra) -> HTMLResponse:
        """La fiche d'un artisan, rendue depuis la ligne relue. Un seul endroit : trois
        routes s'y terminent, et trois rendus jumeaux divergeraient sur un champ."""
        return HTMLResponse(pages.admin_artisan(
            NOM,
            {"id": a.id, "nom": a.nom_affiche, "numero_relais": a.numero_relais,
             "telephone": a.telephone, "etat_abonnement": a.etat_abonnement},
            _json_mod.dumps(a.config or {}, ensure_ascii=False, indent=2), **extra))

    @app.post("/admin/artisan/{artisan_id}/lien", response_class=HTMLResponse)
    def admin_lien_connexion(
            artisan_id: str,
            nelyo_admin: str = Cookie(default="", alias=admin_mdp.NOM_COOKIE)):
        """Engendre un lien de connexion à usage unique pour cet artisan.

        Il est rangé dans `code_connexion`, au même endroit que le code SMS : il hérite
        ainsi de « un seul vivant par artisan » — en engendrer un nouveau invalide le
        précédent, et un code demandé entre-temps l'invalide aussi. Empreinte seule en
        base ; le clair n'apparaît qu'ici, une fois.
        """
        if _exige_admin(nelyo_admin) is None:
            return HTMLResponse(pages.admin_connexion(NOM), status_code=401)
        a = depot.artisan_par_id(artisan_id)
        if a is None:
            raise HTTPException(404, "artisan inconnu")
        t = maintenant()
        clair, emp = connexion.creer_lien()
        depot.poser_code_connexion(artisan_id, emp,
                                   connexion.expiration_lien(t), t,
                                   telephone=a.telephone)
        return _fiche_artisan(
            a, lien=f"{base_url.rstrip('/')}/connexion/lien/{artisan_id}/{clair}")

    @app.post("/admin/artisan/{artisan_id}/motdepasse", response_class=HTMLResponse)
    def admin_mot_de_passe_artisan(
            artisan_id: str,
            nelyo_admin: str = Cookie(default="", alias=admin_mdp.NOM_COOKIE)):
        """Définit (ou remplace) le mot de passe de l'artisan, et l'affiche une fois.

        ENGENDRÉ, jamais choisi ici : un mot de passe tapé par l'admin dans un formulaire
        qu'il relit à l'écran finit dans son historique de navigateur et dans sa mémoire.
        L'artisan le changera pour le sien quand il aura son espace — d'ici là, celui-ci
        est solide et n'a été vu qu'une fois.
        """
        if _exige_admin(nelyo_admin) is None:
            return HTMLResponse(pages.admin_connexion(NOM), status_code=401)
        a = depot.artisan_par_id(artisan_id)
        if a is None:
            raise HTTPException(404, "artisan inconnu")
        clair = motdepasse.suggerer()
        a.mot_de_passe = motdepasse.chiffrer(clair)
        depot.enregistrer_artisan(a)
        return _fiche_artisan(depot.artisan_par_id(artisan_id), mot_de_passe=clair)

    @app.post("/admin/artisan/{artisan_id}/jeton", response_class=HTMLResponse)
    def admin_regenerer_jeton(
            artisan_id: str,
            nelyo_admin: str = Cookie(default="", alias=admin_mdp.NOM_COOKIE)):
        """Régénère le jeton porteur. L'ancien cesse de fonctionner IMMÉDIATEMENT —
        c'est le sens d'une révocation, et c'est pour ça que ce bouton existe."""
        if _exige_admin(nelyo_admin) is None:
            return HTMLResponse(pages.admin_connexion(NOM), status_code=401)
        a = depot.artisan_par_id(artisan_id)
        if a is None:
            raise HTTPException(404, "artisan inconnu")
        jeton = "nelyo_" + secrets.token_urlsafe(24)
        a.token_sha256 = registre_empreinte(jeton)
        depot.enregistrer_artisan(a)
        return HTMLResponse(pages.admin_artisan(
            NOM,
            {"id": a.id, "nom": a.nom_affiche, "numero_relais": a.numero_relais,
             "telephone": a.telephone, "etat_abonnement": a.etat_abonnement},
            _json_mod.dumps(a.config or {}, ensure_ascii=False, indent=2),
            jeton=jeton))


    # ═══════════════════════════════════════════════ L'ESPACE ARTISAN (six vues)
    #
    # La navigation de `docs/maquette/nelyo-maquette.html`, reprise telle quelle. La
    # maquette bascule entre six sections par JavaScript ; ici chaque vue est une URL —
    # même rendu, utilisable sans script, et le bouton « précédent » fonctionne.
    #
    # DEUX VUES SONT REMPLIES DE VRAIES DONNÉES (Aujourd'hui, Appels). Les quatre autres
    # affichent ce qui leur manque, précisément. La maquette les montre garnies de
    # chiffres — « 4 850 € récupérés », « ×32 votre abonnement », « 38 % de conversion » —
    # que le produit ne sait PAS calculer : il s'arrête au rendez-vous validé et
    # n'apprend jamais si le chantier a eu lieu ni ce qu'il a rapporté. Les afficher
    # demanderait de les inventer, et une interface qui affirme un chiffre le fait avec
    # son autorité (R79, R85).

    def _creneaux_pris(artisan_id: str, depuis: dt.datetime) -> list[dict]:
        """Les plages déjà vendues, sur la fenêtre que le calendrier peut proposer.

        R98 : `get_slots` fabriquait ses créneaux à partir des seules heures d'ouverture
        et ne regardait JAMAIS les rendez-vous existants. Deux appelants du même jour se
        voyaient proposer — et obtenaient — la même plage. C'est l'API qui va chercher
        l'information, pas le calendrier : `calendar_stub` ne connaît pas le dépôt, et
        c'est ce qui permettra de le remplacer par une lecture Google/Outlook sans rien
        changer ailleurs.

        VINGT-TROIS JOURS, parce que `get_slots` s'arrête à 21 jours et qu'une marge vaut
        mieux qu'une borne juste. `OCCUPENT` vient du domaine : un RDV VALIDÉ est
        terminal mais occupe la plage, un refusé ou un expiré la rend.
        """
        jour = temps.en_local(depuis, None).date()
        du, au = jour.isoformat(), (jour + dt.timedelta(days=23)).isoformat()
        pris = [r.creneau for r in depot.rdvs_entre(artisan_id, du, au)
                if r.statut in OCCUPENT]
        # ET l'agenda PROPRE de l'artisan (migration 013). Sans lui, Nelyo ne connaîtrait
        # que les rendez-vous passés par Nelyo : le chantier décroché de bouche à
        # oreille, le rendez-vous chez le comptable, la semaine de congés resteraient
        # invisibles — et l'agent continuerait de vendre ces plages. C'est la moitié
        # manquante de R98, et c'est ce qui permet de tenir son agenda ICI, sans Google
        # ni Outlook.
        pris += [e.creneau() for e in depot.evenements_entre(artisan_id, du, au)]
        return pris

    def _artisan_espace(authorization: str, relais_session: str,
                        nelyo_admin: str, nelyo_vue: str):
        """(artisan, vue_admin) ou (None, '') — la résolution commune aux six vues."""
        artisan = (registre.par_token(authorization.removeprefix("Bearer ").strip())
                   or _artisan_de_session(relais_session))
        if artisan is not None:
            return artisan, ""
        emprunt = _artisan_vu_par_admin(nelyo_admin, nelyo_vue)
        return emprunt, (emprunt.id if emprunt else "")

    def _contexte(artisan):
        """Ce que l'enveloppe affiche pour cet artisan, et le compteur de la navigation."""
        ent = artisan.config.get("entreprise", {})
        # La ville de l'ARTISAN, pas la première de sa zone : `adresse_base.ville` la
        # porte déjà correctement orthographiée (« Nogent-sur-Marne »), là où les clés
        # de la zone sont normalisées pour la recherche — les recapitaliser donnait
        # « Nogent-Sur-Marne », faux en français et visible dans la barre latérale.
        commune = (ent.get("adresse_base") or {}).get("ville") or ""
        t = maintenant()
        a_valider = sum(1 for r in depot.rdvs_en_attente(artisan.id)
                        if not r.est_echu(t))
        return {"entreprise": ent.get("nom") or "",
                "prenom": ent.get("prenom_patron") or "",
                "commune": commune, "a_valider": a_valider}

    def _duree(lead) -> str:
        """« 2:41 », ou « — » si l'appel n'a pas de fin enregistrée."""
        if not (lead.debut_a and lead.fin_a):
            return "—"
        s = max(0, int((lead.fin_a - lead.debut_a).total_seconds()))
        return f"{s // 60}:{s % 60:02d}"

    def _heure(instant, cfg) -> str:
        """« 14:32 » pour aujourd'hui, « Hier », sinon la date. L'artisan lit une
        chronologie, pas un horodatage : ce qui date d'aujourd'hui doit se distinguer
        d'un coup d'œil."""
        local = temps.en_local(instant, cfg)
        ajd = temps.en_local(maintenant(), cfg).date()
        if local.date() == ajd:
            return f"{local.hour:02d}:{local.minute:02d}"
        if (ajd - local.date()).days == 1:
            return "Hier"
        return f"{local.day:02d}/{local.month:02d}"

    def _tel_lisible(tel: str) -> str:
        return " ".join(tel[i:i + 2] for i in range(0, len(tel), 2)) \
            if tel.isdigit() else tel

    def _resume(d: dict) -> str:
        """Ce que le client voulait, en une ligne. Les RAISONS du scoring d'abord —
        elles disent déjà problème, commune et disponibilités — l'écho de la catégorie
        retiré, et les slots en repli quand il ne reste rien (cas `hors_zone`, où le
        scoring sort tôt)."""
        cat = d.get("categorie") or "autre"
        raisons = [r for r in (d.get("raisons") or []) if r != cat.replace("_", " ")]
        if not raisons:
            s = d.get("slots") or {}
            raisons = [x for x in (s.get("probleme"), s.get("commune")) if x]
        return " · ".join(raisons) or "Rien de noté"

    @app.get("/app", response_class=HTMLResponse)
    def page_app(relais_session: str = Cookie(default="", alias=session.NOM_COOKIE),
                 nelyo_admin: str = Cookie(default="", alias=admin_mdp.NOM_COOKIE),
                 nelyo_vue: str = Cookie(default="", alias=admin_mdp.NOM_COOKIE_VUE),
                 authorization: str = Header(default="")) -> HTMLResponse:
        """« Aujourd'hui » : ce qui attend une décision, puis ce qui s'est passé."""
        artisan, vue = _artisan_espace(authorization, relais_session,
                                       nelyo_admin, nelyo_vue)
        if artisan is None:
            # Distinguer les deux causes change tout pour qui débogue : « aucun cookie
            # reçu » désigne le navigateur ou l'attribut Secure ; « cookie inconnu »
            # désigne une session expirée. Les confondre coûte un tour.
            if not relais_session:
                indice = ("Le navigateur n'a envoyé aucun cookie de session. En HTTP "
                          "non chiffré, un cookie Secure est refusé — sauf sur "
                          "localhost, pas sur une IP de réseau local. Vérifie /sante : "
                          "si cookie_secure vaut true, mets RELAIS_COOKIE_SECURE=false "
                          "pour tester en local.")
            else:
                indice = "Session expirée ou révoquée. Reconnecte-toi."
            return HTMLResponse(pages.connexion(NOM, indice), status_code=401)

        ctx = _contexte(artisan)
        cfg = artisan.config
        t = maintenant()

        cartes = []
        for r in sorted(depot.rdvs_en_attente(artisan.id),
                        key=lambda x: (x.est_echu(t), x.expire_a)):
            d = depot.lead(r.lead_id).donnees
            s = d.get("slots") or {}
            reste = int((r.expire_a - t).total_seconds() // 60)
            cartes.append({
                "id": r.id, "score": d.get("score", 0),
                "client": s.get("nom") or "Client",
                "telephone": s.get("telephone_rappel") or "",
                "telephone_lisible": _tel_lisible(s.get("telephone_rappel") or ""),
                "motif": _resume(d),
                "creneau": r.creneau["label"],
                "echu": r.est_echu(t),
                "expire_minutes": max(reste, 0),
                "expire_dans": (f"{reste} min" if reste < 60
                                else f"{reste // 60} h {reste % 60:02d}"),
            })

        # LES TUILES SONT COMPTÉES SUR LES MÊMES LIGNES, toutes les quatre : mélanger un
        # total global et des sous-totaux d'un échantillon donnerait des chiffres qui ne
        # s'additionnent pas, et un tableau de bord qui ne tombe pas juste ne se
        # rattrape pas — on cesse de le croire en entier.
        tous = depot.leads(artisan.id, limite=500)
        def compte(*cats):
            return sum(1 for l in tous
                       if (l.donnees.get("categorie") or "autre") in cats)
        chiffres = [
            ("Appels traités", len(tous)),
            ("RDV pris par l'assistant", compte("rdv_reserve")),
            ("Clients à rappeler", compte("a_rappeler", "prioritaire")),
            ("Hors zone ou prestations", compte("hors_zone", "hors_perimetre")),
        ]

        ajd = temps.en_local(t, cfg).date()
        aujourdhui = sum(1 for l in tous
                         if l.debut_a and temps.en_local(l.debut_a, cfg).date() == ajd)
        jour = temps.en_local(t, cfg)
        salutation = (
            f"{JOURS_FR[jour.weekday()].capitalize()} {jour.day} "
            f"{MOIS_FR[jour.month - 1]}"
            + (f" · votre assistant a répondu à {aujourdhui} appel"
               f"{'s' if aujourdhui > 1 else ''} aujourd'hui."
               if aujourdhui else " · aucun appel aujourd'hui pour l'instant."))

        # Les points de couleur de la maquette : ils disent l'ISSUE d'un coup d'œil.
        teintes = {"rdv_reserve": "ok", "prioritaire": "crit", "a_rappeler": "cuivre"}
        activite = [{
            "heure": _heure(l.debut_a, cfg) if l.debut_a else "—",
            "couleur": teintes.get(l.donnees.get("categorie"), "faint"),
            "titre": _CAT_TITRE.get(l.donnees.get("categorie"), "Appel"),
            "detail": _resume(l.donnees),
        } for l in tous[:6]]

        return HTMLResponse(pages.accueil(
            NOM, ctx["prenom"], ctx["entreprise"], cartes, chiffres, activite,
            salutation=salutation, commune=ctx["commune"], vue_admin=vue))

    @app.get("/app/appels", response_class=HTMLResponse)
    def page_appels(categorie: str = "",
                    relais_session: str = Cookie(default="", alias=session.NOM_COOKIE),
                    nelyo_admin: str = Cookie(default="", alias=admin_mdp.NOM_COOKIE),
                    nelyo_vue: str = Cookie(default="",
                                            alias=admin_mdp.NOM_COOKIE_VUE),
                    authorization: str = Header(default="")) -> HTMLResponse:
        """« Appels » : tout ce que l'agent a pris, RDV ou pas.

        Le défaut fermé le 21/09 n'était pas une fonctionnalité manquante mais une
        moitié de promesse : `/app` ne montrait que les RDV à valider, et un appel qui
        n'aboutissait pas — hors zone, à rappeler, sans numéro — était capté, scoré,
        stocké avec son transcript, et vu par personne.
        """
        artisan, vue = _artisan_espace(authorization, relais_session,
                                       nelyo_admin, nelyo_vue)
        if artisan is None:
            return HTMLResponse(
                pages.connexion(NOM, "Session expirée ou révoquée. Reconnecte-toi."),
                status_code=401)
        ctx = _contexte(artisan)
        cfg = artisan.config

        tous = depot.leads(artisan.id, limite=500)
        # Les compteurs portent sur TOUT, pas sur la vue filtrée : un filtre doit dire
        # combien il y a derrière lui, sinon il ne sert qu'à confirmer ce qu'on voit.
        comptes: dict[str, int] = {}
        for l in tous:
            c = l.donnees.get("categorie") or "autre"
            comptes[c] = comptes.get(c, 0) + 1
        filtres = [(None, "Tous", len(tous))]
        filtres += [(c, pages._CATEGORIES.get(c, (c, ""))[0], n)
                    for c, n in sorted(comptes.items(), key=lambda kv: -kv[1])]

        cartes = []
        for l in tous:
            if categorie and (l.donnees.get("categorie") or "autre") != categorie:
                continue
            d = l.donnees
            s = d.get("slots") or {}
            tel = s.get("telephone_rappel") or ""
            cartes.append({
                "heure": _heure(l.debut_a, cfg) if l.debut_a else "—",
                "client": s.get("nom") or "Numéro masqué",
                "telephone": tel, "telephone_lisible": _tel_lisible(tel),
                "motif": s.get("prestation") or _resume(d),
                "commune": s.get("commune") or s.get("code_postal") or "—",
                "score": d.get("score", 0),
                "duree": _duree(l),
                "categorie": d.get("categorie") or "autre",
                "transcript": d.get("transcript") or [],
            })

        return HTMLResponse(pages.liste_appels(
            NOM, ctx["prenom"], cartes, filtres, vue_admin=vue,
            entreprise=ctx["entreprise"], a_valider=ctx["a_valider"],
            categorie=categorie, commune=ctx["commune"]))

    # Les quatre vues qui n'ont pas encore leurs données. Elles existent pour que la
    # navigation de la maquette soit entière — un onglet qui mène à une 404 est pire
    # qu'un onglet absent — et elles disent CE QUI MANQUE, précisément.
    _A_VENIR = {
        "stats": ["l'entonnoir (appels → qualifiés → RDV) est calculable dès "
                  "aujourd'hui et viendra en premier",
                  "le chiffre d'affaires et les chantiers signés ne le sont PAS : "
                  + NOM + " s'arrête au rendez-vous validé et n'apprend jamais si "
                  "le chantier a eu lieu ni ce qu'il a rapporté. Il faudra que "
                  "vous puissiez le saisir"],
        "factu": ["aucun paiement n'est branché",
                  "la consommation par artisan (appels, SMS) est mesurable et viendra "
                  "avec"],
    }

    def _vue_a_venir(cle: str, relais_session: str, nelyo_admin: str,
                     nelyo_vue: str, authorization: str) -> HTMLResponse:
        artisan, vue = _artisan_espace(authorization, relais_session,
                                       nelyo_admin, nelyo_vue)
        if artisan is None:
            return HTMLResponse(
                pages.connexion(NOM, "Session expirée ou révoquée. Reconnecte-toi."),
                status_code=401)
        ctx = _contexte(artisan)
        return HTMLResponse(pages.page_a_venir(
            NOM, cle, ctx["entreprise"], ctx["prenom"], _A_VENIR[cle],
            a_valider=ctx["a_valider"], commune=ctx["commune"], vue_admin=vue))

    @app.get("/app/stats", response_class=HTMLResponse)
    def page_stats(relais_session: str = Cookie(default="", alias=session.NOM_COOKIE),
                   nelyo_admin: str = Cookie(default="", alias=admin_mdp.NOM_COOKIE),
                   nelyo_vue: str = Cookie(default="", alias=admin_mdp.NOM_COOKIE_VUE),
                   authorization: str = Header(default="")) -> HTMLResponse:
        return _vue_a_venir("stats", relais_session, nelyo_admin, nelyo_vue,
                            authorization)

    @app.get("/app/facturation", response_class=HTMLResponse)
    def page_facturation(
            relais_session: str = Cookie(default="", alias=session.NOM_COOKIE),
            nelyo_admin: str = Cookie(default="", alias=admin_mdp.NOM_COOKIE),
            nelyo_vue: str = Cookie(default="", alias=admin_mdp.NOM_COOKIE_VUE),
            authorization: str = Header(default="")) -> HTMLResponse:
        return _vue_a_venir("factu", relais_session, nelyo_admin, nelyo_vue,
                            authorization)


    # ---------------------------------------------------------------- AGENDA
    #
    # L'agenda PROPRE de l'artisan (migration 013). Google et Outlook deviendront une
    # synchronisation optionnelle ; ils ne sont plus la condition d'avoir un agenda.

    def _lundi(iso: str, defaut) -> "dt.date":
        """Le lundi de la semaine demandée, ou celui de la semaine en cours.

        Une date invalide dans l'URL ramène à aujourd'hui plutôt que de lever : un lien
        recopié de travers doit montrer un agenda, pas une erreur.
        """
        try:
            d = dt.date.fromisoformat(iso) if iso else defaut
        except ValueError:
            d = defaut
        return d - dt.timedelta(days=d.weekday())

    @app.get("/app/agenda", response_class=HTMLResponse)
    def page_agenda(semaine: str = "",
                    relais_session: str = Cookie(default="", alias=session.NOM_COOKIE),
                    nelyo_admin: str = Cookie(default="", alias=admin_mdp.NOM_COOKIE),
                    nelyo_vue: str = Cookie(default="",
                                            alias=admin_mdp.NOM_COOKIE_VUE),
                    authorization: str = Header(default=""),
                    erreur: str = "") -> HTMLResponse:
        artisan, vue = _artisan_espace(authorization, relais_session,
                                       nelyo_admin, nelyo_vue)
        if artisan is None:
            return HTMLResponse(
                pages.connexion(NOM, "Session expirée ou révoquée. Reconnecte-toi."),
                status_code=401)
        ctx = _contexte(artisan)
        cfg = artisan.config
        ajd = temps.en_local(maintenant(), cfg).date()
        lundi = _lundi(semaine, ajd)
        # SIX JOURS, lundi→samedi, comme la maquette : le dimanche n'est pas un jour
        # ouvré pour un plombier, et lui garder une colonne vide sept fois sur sept
        # rétrécit les six autres pour rien.
        fin = lundi + dt.timedelta(days=5)

        rdvs = depot.rdvs_entre(artisan.id, lundi.isoformat(), fin.isoformat())
        evts = depot.evenements_entre(artisan.id, lundi.isoformat(), fin.isoformat())

        par_jour: dict[str, list] = {}
        for r in rdvs:
            # Un RDV refusé ou expiré ne figure PAS à l'agenda : sa plage est rendue, et
            # l'y laisser ferait croire à un engagement qui n'existe plus.
            if r.statut not in OCCUPENT:
                continue
            d = depot.lead(r.lead_id).donnees
            s = d.get("slots") or {}
            valide = r.statut is _StatutRdv.VALIDE
            par_jour.setdefault(r.creneau["date"], []).append({
                "id": r.id, "tri": r.creneau.get("de", ""),
                "heures": f"{r.creneau.get('de', '')} – {r.creneau.get('a', '')}",
                "titre": s.get("nom") or "Client",
                "detail": (s.get("prestation") or "") + (
                    f" · {s['commune']}" if s.get("commune") else ""),
                "classe": "e-ok" if valide else "e-wait",
                "de": r.creneau.get("de", ""), "a": r.creneau.get("a", ""),
                "type": "rdv",
                # Un RDV Nelyo ne se supprime ni ne se déplace d'ici : il porte un
                # engagement envers un client. On lui PROPOSE un autre créneau, et il
                # confirme — c'est `reproposer`, qui lui envoie un SMS.
                "supprimable": False,
            })
        for e in evts:
            par_jour.setdefault(e.jour, []).append({
                "id": e.id, "tri": e.de, "heures": f"{e.de} – {e.a}",
                "titre": e.titre, "detail": "",
                "classe": "e-off" if e.type == "indisponible" else "e-perso",
                "de": e.de, "a": e.a, "type": e.type,
                "supprimable": True,
            })

        jours = []
        for i in range(6):
            d = lundi + dt.timedelta(days=i)
            liste = sorted(par_jour.get(d.isoformat(), []), key=lambda x: x["tri"])
            jours.append({
                "iso": d.isoformat(),
                "nom": JOURS_FR[d.weekday()].capitalize(),
                "date": (f"{d.day} {MOIS_FR[d.month - 1][:4]}"
                         + (" · aujourd'hui" if d == ajd else "")),
                "aujourdhui": d == ajd, "evenements": liste,
            })

        libelle = (f"Semaine du {lundi.day} au {fin.day} {MOIS_FR[fin.month - 1]}"
                   if lundi.month == fin.month else
                   f"Semaine du {lundi.day} {MOIS_FR[lundi.month - 1]} au "
                   f"{fin.day} {MOIS_FR[fin.month - 1]}")
        return HTMLResponse(pages.agenda(
            NOM, ctx["prenom"], ctx["entreprise"], jours, libelle,
            (lundi - dt.timedelta(days=7)).isoformat(),
            (lundi + dt.timedelta(days=7)).isoformat(),
            a_valider=ctx["a_valider"], commune=ctx["commune"], vue_admin=vue,
            erreur=erreur))

    def _valider_evenement(artisan_id: str, titre: str, jour: str, de: str, a: str,
                           ignorer_rdv: str = "") -> tuple[str, str]:
        """(titre nettoyé, erreur). UNE seule définition, pour l'ajout ET le déplacement.

        Deux validations jumelles finiraient par diverger sur la vérification qui
        manque — et ce serait celle-là qui laisserait passer un conflit.
        """
        titre = (titre or "").strip()
        if not titre:
            return "", ("Il faut un intitulé : c'est ce que vous relirez dans "
                        "six semaines.")
        if not (jour and de and a):
            return titre, "Jour, heure de début et heure de fin sont obligatoires."
        if de >= a:
            return titre, "L'heure de fin doit venir après l'heure de début."
        try:
            dt.date.fromisoformat(jour)
        except ValueError:
            return titre, "Le jour n'est pas une date valide."
        # ON NE DOUBLE PAS L'ARTISAN NON PLUS. R98 empêche l'agent de revendre une plage ;
        # il serait incohérent de laisser l'artisan s'inscrire par-dessus un rendez-vous
        # que Nelyo lui a déjà obtenu — il découvrirait le conflit chez le client.
        occupe = [r for r in depot.rdvs_entre(artisan_id, jour, jour)
                  if r.statut in OCCUPENT and r.id != ignorer_rdv
                  and de < r.creneau.get("a", "") and r.creneau.get("de", "") < a]
        if occupe:
            return titre, (f"Vous avez déjà un rendez-vous Nelyo de "
                           f"{occupe[0].creneau.get('de')} à "
                           f"{occupe[0].creneau.get('a')} ce jour-là.")
        return titre, ""

    @app.post("/app/agenda/{ev_id}/modifier")
    def agenda_modifier(ev_id: str, titre: str = Form(default=""),
                        jour: str = Form(default=""), de: str = Form(default=""),
                        a: str = Form(default=""), type: str = Form(default="rdv"),
                        relais_session: str = Cookie(default="",
                                                     alias=session.NOM_COOKIE),
                        authorization: str = Header(default="")):
        """Déplacer ou renommer un événement que l'artisan a inscrit lui-même.

        Un rendez-vous NELYO ne passe pas par ici : le déplacer, c'est changer un
        engagement pris envers un client, et ça se fait par `reproposer` — qui lui
        envoie un SMS avec un lien de confirmation. Déplacer une plage vendue sans
        prévenir celui qui l'a achetée laisserait quelqu'un attendre chez lui.
        """
        artisan = artisan_authentifie(authorization, relais_session)
        titre, erreur = _valider_evenement(artisan.id, titre, jour, de, a)
        if erreur:
            return RedirectResponse(
                f"/app/agenda?semaine={jour}&erreur={quote(erreur)}", status_code=303)
        if not depot.modifier_evenement(artisan.id, ev_id, jour=jour, de=de, a=a,
                                        titre=titre,
                                        type=type if type in ("rdv", "indisponible")
                                        else "rdv"):
            raise HTTPException(404, "événement inconnu")
        return RedirectResponse(f"/app/agenda?semaine={jour}", status_code=303)

    @app.post("/app/agenda")
    def agenda_ajouter(titre: str = Form(default=""), jour: str = Form(default=""),
                       de: str = Form(default=""), a: str = Form(default=""),
                       type: str = Form(default="rdv"),
                       relais_session: str = Cookie(default="",
                                                    alias=session.NOM_COOKIE),
                       authorization: str = Header(default="")):
        """Inscrire un engagement pris HORS Nelyo.

        `artisan_authentifie` et NON `_artisan_espace` : écrire dans l'agenda est une
        ACTION, et le mode support est en lecture seule (T14). La lecture seule reste
        donc structurelle ici aussi — l'identité d'emprunt n'existe pas sur ce chemin.
        """
        artisan = artisan_authentifie(authorization, relais_session)
        from .depot import EvenementAgenda
        titre, erreur = _valider_evenement(artisan.id, titre, jour, de, a)
        if erreur:
            return RedirectResponse(f"/app/agenda?semaine={jour}&erreur={quote(erreur)}",
                                    status_code=303)
        depot.creer_evenement(EvenementAgenda(
            id="", artisan_id=artisan.id, jour=jour, de=de, a=a, titre=titre,
            type=type if type in ("rdv", "indisponible") else "rdv"))
        return RedirectResponse(f"/app/agenda?semaine={jour}", status_code=303)

    @app.post("/app/agenda/{ev_id}/supprimer")
    def agenda_supprimer(ev_id: str,
                         relais_session: str = Cookie(default="",
                                                      alias=session.NOM_COOKIE),
                         authorization: str = Header(default="")):
        artisan = artisan_authentifie(authorization, relais_session)
        depot.supprimer_evenement(artisan.id, ev_id)
        return RedirectResponse("/app/agenda", status_code=303)


    @app.get("/app/assistant", response_class=HTMLResponse)
    def page_assistant(
            relais_session: str = Cookie(default="", alias=session.NOM_COOKIE),
            nelyo_admin: str = Cookie(default="", alias=admin_mdp.NOM_COOKIE),
            nelyo_vue: str = Cookie(default="", alias=admin_mdp.NOM_COOKIE_VUE),
            authorization: str = Header(default="")) -> HTMLResponse:
        """« Assistant IA » : ce que la machine sait, et ce qu'elle dit.

        TOUT VIENT DE LA CONFIG RÉELLE — celle que le moteur lit à chaque appel. Rien
        n'est reformulé pour l'écran : `formule_accueil` est la fonction qu'appelle
        `Conversation.open()`, les consignes de sécurité et les phrases de tarif sont
        les chaînes que l'agent prononce. Une page qui paraphraserait finirait par
        décrire un assistant qui n'existe plus.
        """
        artisan, vue = _artisan_espace(authorization, relais_session,
                                       nelyo_admin, nelyo_vue)
        if artisan is None:
            return HTMLResponse(
                pages.connexion(NOM, "Session expirée ou révoquée. Reconnecte-toi."),
                status_code=401)
        ctx = _contexte(artisan)
        cfg = artisan.config
        ag = cfg.get("agenda", {})
        val = cfg.get("validation", {})

        def heures(jour, defaut="fermé"):
            f = (ag.get("horaires_rdv") or {}).get(jour) or []
            return " · ".join(f"{x['de']}–{x['a']}" for x in f) or defaut

        urg = ag.get("urgences", {})
        fenetre = (urg.get("fenetres_reservees") or [{}])[0]

        # Les communes sont indexées pour la RECHERCHE : « nogent » et
        # « nogent-sur-marne » désignent la même ville. On n'affiche donc pas les clés
        # brutes mais une entrée par CODE POSTAL, sous son libellé le plus long — sinon
        # l'artisan lirait sa zone en double et douterait de ce que l'agent comprend.
        par_cp: dict[str, str] = {}
        for nom_c, cp in (cfg.get("zone", {}).get("communes") or {}).items():
            if len(nom_c) > len(par_cp.get(cp, "")):
                par_cp[cp] = nom_c
        limitrophes = set(cfg.get("zone", {}).get("codes_postaux_limitrophes") or [])
        communes = sorted(v.title() for k, v in par_cp.items()
                          if k not in limitrophes)
        bordures = sorted(v.title() for k, v in par_cp.items() if k in limitrophes)

        promesse = (cfg.get("accueil", {}).get("promesse_rappel") or {})
        securite = cfg.get("securite", {})
        transfert = cfg.get("transfert", {})

        bloc = {
            "numero_relais": artisan.numero_relais or "—",
            "etat_abonnement": artisan.etat_abonnement,
            # LA VRAIE phrase d'accueil, par la fonction du moteur — pas une copie.
            # La CLÉ, pas le libellé : le français vit dans `pages.py` avec le reste
            # de la copie. L'artisan lisait « Quand il promet un rappel (ouvree) ».
            "dit": [("accueil", formule_accueil(cfg))]
                   + [(q, p) for q, p in promesse.items()],
            "couvertes": [p.replace("_", " ") for p in
                          (cfg.get("prestations", {}).get("couvertes") or [])],
            "refusees": [p.replace("_", " ") for p in
                         (cfg.get("prestations", {}).get("refusees") or [])],
            "communes": communes, "limitrophes": bordures,
            "agenda": [
                ("Lundi au vendredi", heures("lun-ven")),
                ("Samedi", heures("sam")),
                ("Dimanche", heures("dim")),
                ("Durée d'une intervention", f"{(ag.get('durees_min') or {}).get('defaut', '—')} min"),
                ("Trajet réservé entre deux", f"{ag.get('buffer_trajet_min', '—')} min"),
                ("RDV que l'assistant peut prendre par jour",
                 ag.get("max_rdv_agent_par_jour", "—")),
                ("Urgences", "acceptées" if urg.get("acceptees") else "refusées"),
                ("Créneau réservé aux urgences",
                 f"{fenetre.get('de', '—')}–{fenetre.get('a', '—')} "
                 f"({urg.get('max_par_jour', '—')} par jour)"),
            ],
            "validation": [
                ("Délai pour valider un RDV", f"{val.get('delai_max_heures', '—')} h"),
                ("Délai en urgence", f"{val.get('delai_max_urgence_heures', '—')} h"),
                ("Validation automatique",
                 "jamais" if val.get("auto_validation") == "jamais" else
                 str(val.get("auto_validation"))),
                ("Aucun SMS entre",
                 f"{(cfg.get('sms', {}).get('plage_silence') or {}).get('de', '—')} et "
                 f"{(cfg.get('sms', {}).get('plage_silence') or {}).get('a', '—')}"),
            ],
            "tarifs": [t.get("phrase") or t.get("libelle", "")
                       for t in (cfg.get("tarifs", {}).get("communicables") or [])],
            # DES DONNÉES, pas du HTML : `api.py` ne fabrique pas de balises — il n'y
            # importe même pas `escape`, et c'est voulu. Une route qui se met à écrire
            # du HTML finit par en écrire sans l'échapper.
            "consignes": list((securite.get("consignes_autorisees") or {}).values()),
            "securite": [
                ("Transfert si danger",
                 "oui" if securite.get("transfert_si_danger") else "non"),
                ("Transfert vers vous",
                 "actif" if transfert.get("actif") else "inactif"),
            ],
        }
        return HTMLResponse(pages.assistant(
            NOM, ctx["prenom"], ctx["entreprise"], bloc,
            a_valider=ctx["a_valider"], commune=ctx["commune"], vue_admin=vue))


    return app
