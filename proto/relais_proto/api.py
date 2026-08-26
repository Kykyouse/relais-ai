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
import pathlib

from fastapi import Cookie, Depends, FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import (HTMLResponse, JSONResponse, RedirectResponse,
                               StreamingResponse)
from pydantic import BaseModel, Field

import secrets

from . import (connexion, messages, pages, session, sonde_voix as _sonde, temps,
               vapi as _vapi)
from .calendar_stub import CalendarStub, libelle_creneau
from .confirmation import creer_jeton, empreinte, lien
from .depot import Introuvable
from .engine import Conversation
from .rdv import TransitionInterdite
from .registre import Artisan, Registre
from .scoring import build_lead
from .states import State

CONTRAT_LEAD_VERSION = 1

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
              voix_artisan_defaut: str | None = None) -> FastAPI:
    """Collaborateurs injectés explicitement plutôt que par variables globales : les tests
    passent un dépôt mémoire, un MockLLM et une horloge figée, la prod un dépôt Postgres.

    `envoyeur` est facultatif et ne sert qu'au **code de connexion**, qui doit partir tout
    de suite : un code qui arrive au prochain passage du cron n'est pas un code. Sans lui,
    tout continue de fonctionner — le message reste en file et le worker l'expédiera, avec
    la latence du cron.

    `sonde_voix` est le chemin du journal de la sonde de l'étape 0 (`sonde_voix.py`).
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
        return {"statut": "ok", "contrat_lead": CONTRAT_LEAD_VERSION,
                "cookie_secure": cookie_secure}

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
            convo = Conversation(artisan.config, fabrique_llm(),
                                 CalendarStub(artisan.config, now=t))
            texte = convo.open()
            if appel is None:
                depot.ouvrir_appel(artisan.id, t, appel_id=appel_id)
            depot.enregistrer_etat(appel_id, convo.to_dict())
            return _repondre_voix(texte, modele, t, corps)

        convo = Conversation.from_dict(appel.etat_conversation, artisan.config,
                                       fabrique_llm())
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

        textes = _vapi.messages_utilisateur(corps)
        texte = convo.process(textes[-1])
        depot.enregistrer_etat(appel_id, convo.to_dict())

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
                             CalendarStub(artisan.config, now=t))
        texte = convo.open()
        appel = depot.ouvrir_appel(artisan.id, t)
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

    @app.post("/connexion")
    def demander_code(telephone: str = Form(...)):
        """Envoie un code à 6 chiffres au mobile de l'artisan.

        **La réponse est la MÊME que le numéro soit connu ou non** : sinon cette page
        dirait à quiconque la sollicite si tel numéro est celui d'un de nos artisans.
        Un numéro mal tapé mène donc à l'écran de saisie, où le code sera simplement
        refusé — et le lien « recommencer » est là pour ça.
        """
        numero = connexion.normaliser_telephone(telephone)
        artisan = registre.par_telephone(numero)
        t = maintenant()
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

    @app.get("/app", response_class=HTMLResponse)
    def page_app(relais_session: str = Cookie(default="", alias=session.NOM_COOKIE),
                 authorization: str = Header(default="")) -> HTMLResponse:
        """La boîte de validation. Pas de 401 ici mais la page de connexion : un artisan
        dont la session a expiré doit voir un écran, pas un code d'erreur."""
        artisan = (registre.par_token(authorization.removeprefix("Bearer ").strip())
                   or _artisan_de_session(relais_session))
        if artisan is None:
            # Distinguer les deux causes change tout pour qui débogue : « aucun cookie
            # reçu » désigne le navigateur ou l'attribut Secure ; « cookie inconnu »
            # désigne une session expirée ou révoquée. Les confondre coûte un tour.
            if not relais_session:
                indice = ("Le navigateur n'a envoyé aucun cookie de session. En HTTP "
                          "non chiffré, un cookie Secure est refusé — sauf sur localhost, "
                          "pas sur une IP de réseau local. Vérifie /sante : si "
                          "cookie_secure vaut true, mets RELAIS_COOKIE_SECURE=false pour "
                          "tester en local.")
            else:
                indice = "Session expirée ou révoquée. Reconnecte-toi."
            return HTMLResponse(pages.connexion(NOM, indice), status_code=401)
        t = maintenant()
        cartes = []
        for r in depot.rdvs_en_attente(artisan.id):
            donnees = depot.lead(r.lead_id).donnees
            # `rdvs_en_attente` rend les RDV NON TERMINAUX, échus compris : le worker
            # d'expiration ne passe qu'à intervalles. Il faut donc distinguer ici ce qui
            # est encore décidable — sinon la page offre des boutons qui ne peuvent
            # qu'échouer (constaté en usage réel le 24/08 : 409 sur un tap).
            cartes.append({"id": r.id, "creneau": r.creneau["label"],
                           "urgence": r.urgence, "score": donnees.get("score", 0),
                           "raisons": donnees.get("raisons", []),
                           "echu": r.est_echu(t), "expire_a": r.expire_a})
        return HTMLResponse(pages.boite_validation(
            NOM, artisan.config["entreprise"]["prenom_patron"], cartes))

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

    return app
