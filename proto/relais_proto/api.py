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

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import messages
from .calendar_stub import CalendarStub, libelle_creneau
from .confirmation import creer_jeton, empreinte, lien
from .depot import Introuvable
from .engine import Conversation
from .rdv import TransitionInterdite
from .registre import Artisan, Registre
from .scoring import build_lead
from .states import State

CONTRAT_LEAD_VERSION = 1


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


class PropositionOut(BaseModel):
    """Ce que voit le client au bout du lien. Aucune donnée le concernant : l'URL vaut
    capacité, elle ne doit rien révéler sur la personne."""
    entreprise: str
    prenom: str
    creneau: dict
    statut: str
    expire_a: dt.datetime


# ------------------------------------------------------------------ fabrique
def creer_app(depot, registre: Registre, fabrique_llm, horloge=None,
              base_url: str = "https://relais.example") -> FastAPI:
    """Collaborateurs injectés explicitement plutôt que par variables globales : les tests
    passent un dépôt mémoire, un MockLLM et une horloge figée, la prod un dépôt Postgres."""
    maintenant = horloge or (lambda: dt.datetime.now())
    app = FastAPI(title="Relais — API backend", version="0.1.0")

    @app.exception_handler(Introuvable)
    async def _introuvable(_: Request, exc: Introuvable) -> JSONResponse:
        return JSONResponse({"detail": "introuvable"}, status_code=404)

    # ---- authentification : deux portes distinctes ----
    def artisan_authentifie(
            authorization: str = Header(default="")) -> Artisan:
        """Porte « app artisan » : token porteur propre à l'artisan."""
        token = authorization.removeprefix("Bearer ").strip()
        artisan = registre.par_token(token) if token else None
        if artisan is None:
            raise HTTPException(401, "token artisan invalide")
        return artisan

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
        return {"statut": "ok", "contrat_lead": CONTRAT_LEAD_VERSION}

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

        # fin d'appel : lead, puis RDV si un créneau a été réservé
        t = maintenant()
        donnees = build_lead(convo)
        lead = depot.cloturer_appel(appel_id, donnees, t)
        rdv_id = None
        if donnees.get("rdv"):
            rdv = depot.creer_rdv(lead_id=lead.id, hold=donnees["rdv"],
                                  lead_donnees=donnees, cfg=artisan.config, maintenant=t)
            # le push part ici ; l'échéance, elle, court depuis la réservation (rdv.py)
            rdv.notifier(t)
            depot.sauver_rdv(rdv)
            rdv_id = rdv.id
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

    def _decider(rdv_id: str, artisan: Artisan, action: str) -> RdvOut:
        rdv = _rdv_de_l_artisan(rdv_id, artisan)
        try:
            getattr(rdv, action)(maintenant())
        except TransitionInterdite as exc:
            # 409 : l'échéance est passée, ou le RDV est déjà décidé. Le message vient du
            # domaine — c'est lui qui sait pourquoi, pas l'API.
            raise HTTPException(409, str(exc)) from None
        depot.sauver_rdv(rdv)
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
                   # celui qu'aurait prononcé l'agent
                   "label": libelle_creneau(jour, corps.de, corps.a, t.date())}
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

    def _proposition(rdv, artisan: Artisan) -> PropositionOut:
        return PropositionOut(entreprise=artisan.config["entreprise"]["nom"],
                              prenom=artisan.config["entreprise"]["prenom_patron"],
                              creneau=rdv.creneau, statut=rdv.statut.value,
                              expire_a=rdv.expire_a)

    @app.get("/c/{jeton}", response_model=PropositionOut)
    def voir_proposition(jeton: str) -> PropositionOut:
        """Page vue par le client. Volontairement pauvre : nom de l'entreprise, prénom de
        l'artisan, créneau. **Ni son nom, ni son téléphone, ni le transcript** — l'URL vaut
        capacité, quiconque la possède ne doit rien apprendre de la personne."""
        rdv = _rdv_du_jeton(jeton)
        artisan = registre.artisan(rdv.artisan_id)
        if artisan is None:
            raise HTTPException(409, "artisan introuvable au registre")
        return _proposition(rdv, artisan)

    @app.post("/c/{jeton}", response_model=PropositionOut)
    def confirmer(jeton: str) -> PropositionOut:
        rdv = _rdv_du_jeton(jeton)
        artisan = registre.artisan(rdv.artisan_id)
        if artisan is None:
            raise HTTPException(409, "artisan introuvable au registre")
        t = maintenant()
        try:
            rdv.confirmer_par_client(jeton, t)
        except TransitionInterdite as exc:
            raise HTTPException(409, str(exc)) from None
        depot.sauver_rdv(rdv)
        # l'artisan doit l'apprendre sans avoir à ouvrir l'app
        try:
            depot.enfiler_message(
                messages.confirmation_artisan(rdv, depot.lead(rdv.lead_id).donnees,
                                              artisan.config), t)
        except messages.MessageInterdit:
            pass          # la validation du client compte, la notification est secondaire
        return _proposition(rdv, artisan)

    return app
