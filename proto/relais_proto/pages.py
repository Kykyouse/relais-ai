"""Pages HTML rendues côté serveur. Aucun framework, aucune étape de build, aucun JS.

Pourquoi ce choix pour la page client : elle est ouverte **une fois**, depuis un SMS, sur un
téléphone dont on ne sait rien — réseau de chantier, vieil Android, navigateur intégré à
l'application de messagerie. Deux kilo-octets de HTML autonome battent n'importe quel bundle.
Aucune ressource externe non plus : pas de police distante, pas de script tiers, donc rien
qui puisse échouer ou pister l'appelant d'un artisan.

Toutes les valeurs interpolées passent par `html.escape` : elles viennent de la config
artisan et du calendrier, pas du visiteur, mais échapper est le comportement par défaut
correct — pas une réaction à une menace identifiée.
"""
from __future__ import annotations

from html import escape

# Mobile-first et sobre. Cible de frappe généreuse (48 px minimum) : l'artisan comme son
# client tapent parfois avec les doigts mouillés, sur un écran fissuré.
_STYLE = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { margin: 0; padding: 24px 20px; font: 17px/1.5 -apple-system, BlinkMacSystemFont,
  "Segoe UI", Roboto, sans-serif; background: #f6f7f9; color: #14181f; }
main { max-width: 30rem; margin: 0 auto; background: #fff; border-radius: 14px;
  padding: 28px 22px; box-shadow: 0 1px 3px rgba(0,0,0,.09); }
h1 { font-size: 1.3rem; margin: 0 0 6px; }
.entreprise { color: #5b6472; font-size: .95rem; margin: 0 0 22px; }
.creneau { font-size: 1.35rem; font-weight: 650; margin: 0 0 4px; }
.jour { color: #5b6472; margin: 0 0 26px; }
button { width: 100%; min-height: 52px; font-size: 1.05rem; font-weight: 600;
  border: 0; border-radius: 10px; background: #1a6b3c; color: #fff; cursor: pointer; }
button:active { background: #14512e; }
.apres { font-size: .92rem; color: #5b6472; margin: 20px 0 0; }
.ok { font-size: 2.4rem; line-height: 1; margin: 0 0 10px; }
.marque { margin: 26px 0 0; text-align: center; font-size: .8rem; color: #9aa4b2;
  letter-spacing: .08em; text-transform: uppercase; }
@media (prefers-color-scheme: dark) {
  body { background: #14181f; color: #e8eaed; }
  main { background: #1d232c; box-shadow: none; }
  .entreprise, .jour, .apres { color: #9aa4b2; }
}
"""


def _page(produit: str, titre: str, corps: str) -> str:
    """Le nom du produit est un PARAMÈTRE, jamais une constante.

    Il apparaît dans le `<title>` (l'onglet, et ce que le téléphone affiche en aperçu de
    lien) et en signature de bas de page. Le client, lui, ne connaît que son artisan :
    la signature dit qui organise, elle ne prend pas sa place.
    """
    return (
        "<!DOCTYPE html>\n"
        '<html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        # une page de confirmation n'a rien à faire dans un index de moteur de recherche
        '<meta name="robots" content="noindex, nofollow">'
        f"<title>{escape(titre)} · {escape(produit)}</title>"
        f"<style>{_STYLE}</style></head>"
        f'<body><main>{corps}<p class="marque">{escape(produit)}</p></main></body></html>'
    )


def proposition(produit: str, entreprise: str, prenom: str, creneau_label: str,
                action: str) -> str:
    """Page vue par le client au bout du lien SMS : un créneau, un bouton.

    Volontairement pauvre en informations : ni son nom, ni son téléphone, ni le motif de
    l'intervention. L'URL vaut capacité — quiconque la possède ne doit rien apprendre sur
    la personne. Le formulaire poste sur la MÊME URL : pas de JS, donc ça marche partout.
    """
    return _page(
        produit,
        f"Valider votre rendez-vous — {entreprise}",
        f"<h1>Votre rendez-vous</h1>"
        f'<p class="entreprise">{escape(entreprise)}</p>'
        f'<p class="creneau">{escape(creneau_label)}</p>'
        f'<p class="jour">Proposé par {escape(prenom)}</p>'
        f'<form method="post" action="{escape(action)}">'
        f"<button type=\"submit\">Ça me convient</button></form>"
        f'<p class="apres">En validant, {escape(prenom)} est prévenu immédiatement.</p>')


def confirmee(produit: str, entreprise: str, prenom: str, creneau_label: str) -> str:
    return _page(
        produit,
        f"Rendez-vous confirmé — {entreprise}",
        f'<p class="ok">✅</p><h1>C\'est confirmé</h1>'
        f'<p class="entreprise">{escape(entreprise)}</p>'
        f'<p class="creneau">{escape(creneau_label)}</p>'
        f'<p class="apres">{escape(prenom)} a été prévenu. Vous n\'avez plus rien à '
        f"faire.</p>")


def lien_invalide(produit: str) -> str:
    """404 ET 410 : le même texte pour un lien inconnu, déjà utilisé ou périmé.

    Ne pas distinguer les cas est délibéré côté sécurité — mais surtout, ce message doit
    rassurer le client qui a déjà validé et recharge sa page. Il ne doit pas croire que sa
    validation a échoué.
    """
    return _page(
        produit,
        "Lien expiré",
        "<h1>Ce lien n'est plus valide</h1>"
        '<p class="apres">Il a peut-être déjà été utilisé, ou le créneau n\'est plus '
        "proposé. <strong>Si vous venez de valider, c\'est bien pris en compte</strong> "
        "et l'artisan a été prévenu. Sinon, il vous recontacte pour convenir d'un autre "
        "horaire.</p>")


def creneau_perime(produit: str, prenom: str) -> str:
    return _page(
        produit,
        "Créneau expiré",
        "<h1>Ce créneau n'est plus disponible</h1>"
        f'<p class="apres">Le délai de validation est passé. {escape(prenom)} vous '
        f"recontacte pour vous en proposer un autre.</p>")


# --------------------------------------------------------------- côté artisan
_STYLE_APP = _STYLE + """
main { max-width: 34rem; }
.rdv { border: 1px solid #e2e5ea; border-radius: 12px; padding: 16px; margin: 0 0 14px; }
.score { display: inline-block; font-weight: 700; font-size: .85rem; padding: 3px 9px;
  border-radius: 999px; background: #eef1f5; color: #3c454a; margin-bottom: 8px; }
.urgent { background: #fde8e4; color: #98261a; }
.raisons { color: #5b6472; font-size: .92rem; margin: 0 0 12px; }
.actions { display: flex; gap: 10px; }
.actions form { flex: 1; }
button.refus { background: #fff; color: #98261a; border: 1px solid #e2b5ae; }
details { margin-top: 12px; }
summary { cursor: pointer; color: #5b6472; font-size: .92rem; min-height: 32px; }
label { display: block; font-size: .88rem; color: #5b6472; margin: 10px 0 4px; }
input { width: 100%; min-height: 46px; font-size: 1rem; padding: 0 10px;
  border: 1px solid #cfd5de; border-radius: 8px; background: #fff; color: #14181f; }
.vide { color: #5b6472; }
.support { background: #e7eefb; color: #1c3f7a; border-radius: 8px;
  padding: 12px 14px; margin: 0 0 18px; font-size: .94rem; line-height: 1.6; }
.support form { display: inline; }
.support button { width: auto; min-height: 34px; font-size: .88rem; padding: 0 12px;
  background: #fff; color: #1c3f7a; border: 1px solid #b6c8e8; margin-left: 6px; }
.rdv.perime { opacity: .72; border-style: dashed; }
.perdu { color: #98261a; font-size: .92rem; margin: 0; }
a { color: #1a6b3c; }
/* --- page « Mes appels » --- */
.quand { color: #5b6472; font-size: .85rem; margin: 0 0 6px; }
.cat { display: inline-block; font-size: .85rem; font-weight: 600; padding: 3px 9px;
  border-radius: 999px; background: #eef1f5; color: #3c454a; margin-bottom: 8px; }
.cat.ok { background: #e3f2e8; color: #1a6b3c; }
.cat.action { background: #fdf3df; color: #7a5510; }
.cat.urgent { background: #fde8e4; color: #98261a; }
.filtres { font-size: .92rem; margin: 0 0 16px; line-height: 1.9; }
/* Le lien de rappel est la seule ACTION de la page : taille de cible tactile pleine. */
.rappel a { display: inline-block; min-height: 44px; line-height: 44px; font-weight: 600; }
.dit-agent, .dit-client { margin: 6px 0; font-size: .92rem; }
.dit-agent { color: #5b6472; }
.dit-client { color: #14181f; }
@media (prefers-color-scheme: dark) {
  .support { background: #1c2a40; color: #a8c4ee; }
  .support button { background: #1d232c; color: #a8c4ee; border-color: #35496b; }
  .rdv { border-color: #2c3542; } .score { background: #2c3542; color: #c8d0da; }
  input { background: #14181f; color: #e8eaed; border-color: #2c3542; }
  button.refus { background: #1d232c; border-color: #5a3a34; color: #f0a99f; }
  .cat { background: #2c3542; color: #c8d0da; }
  .cat.ok { background: #1c3a28; color: #8fd0a8; }
  .cat.action { background: #3a3322; color: #e0c07a; }
  .cat.urgent { background: #3d2320; color: #f0a99f; }
  .dit-client { color: #e8eaed; }
}
"""


def _page_app(produit: str, titre: str, corps: str) -> str:
    return (
        "<!DOCTYPE html>\n"
        '<html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex, nofollow">'
        f"<title>{escape(titre)} · {escape(produit)}</title>"
        f"<style>{_STYLE_APP}</style></head>"
        f'<body><main>{corps}<p class="marque">{escape(produit)}</p></main></body></html>')


def action_impossible(produit: str, raison: str) -> str:
    """Une action refusée par le domaine doit rendre une PAGE, pas du JSON.

    Après un tap sur un téléphone, `{"detail":"RDV ... échu depuis ..."}` est illisible.
    Le motif vient du domaine — c'est lui qui sait pourquoi — la page ne fait que
    l'habiller et proposer le retour.
    """
    return _page_app(
        produit,
        "Action impossible",
        "<h1>Action impossible</h1>"
        f'<p class="raisons">{escape(raison)}</p>'
        '<p class="apres"><a href="/app">Revenir à mes rendez-vous</a></p>')


def connexion(produit: str, erreur: str = "") -> str:
    """Premier écran : l'artisan donne son numéro de mobile.

    `type="tel"` fait sortir le pavé numérique du téléphone, et `autocomplete="tel"`
    laisse le navigateur proposer le numéro déjà connu — sur un chantier, une main libre
    et un écran sale, chaque frappe évitée compte.
    """
    alerte = f'<p class="raisons">{escape(erreur)}</p>' if erreur else ""
    return _page_app(
        produit,
        "Connexion",
        "<h1>Connexion</h1>"
        '<p class="raisons">Entrez votre numéro de mobile : vous recevrez un code '
        "par SMS.</p>"
        + alerte
        + '<form method="post" action="/connexion">'
          "<label>Mobile</label>"
          '<input type="tel" name="telephone" autocomplete="tel" '
          'inputmode="numeric" placeholder="06 12 34 56 78" required>'
          '<label></label><button type="submit">Recevoir un code</button></form>')


def saisie_code(produit: str, telephone: str, erreur: str = "") -> str:
    """Second écran : la saisie du code à 6 chiffres.

    `inputmode="numeric"` et `autocomplete="one-time-code"` : sur iOS comme sur Android,
    le clavier propose alors le code reçu par SMS d'un seul appui. Le numéro est réaffiché
    parce qu'un artisan qui s'est trompé de chiffre doit le voir sans revenir en arrière.
    """
    alerte = f'<p class="raisons">{escape(erreur)}</p>' if erreur else ""
    return _page_app(
        produit,
        "Code reçu par SMS",
        "<h1>Votre code</h1>"
        f'<p class="raisons">Envoyé au {escape(telephone)}, valable quelques minutes.</p>'
        + alerte
        + '<form method="post" action="/connexion/code">'
          "<label>Code</label>"
          '<input type="text" name="code" inputmode="numeric" '
          'autocomplete="one-time-code" pattern="[0-9]*" maxlength="6" '
          'autofocus required>'
          '<label></label><button type="submit">Entrer</button></form>'
          '<p class="apres"><a href="/connexion">Recommencer avec un autre numéro</a></p>')


# ------------------------------------------------------------------ côté admin
_STYLE_ADMIN = _STYLE_APP + """
main { max-width: 52rem; }
table { width: 100%; border-collapse: collapse; margin: 0 0 18px; }
th, td { text-align: left; padding: 9px 8px; border-bottom: 1px solid #e2e5ea;
  font-size: .94rem; vertical-align: top; }
th { color: #5b6472; font-weight: 600; font-size: .85rem; }
td.num { font-variant-numeric: tabular-nums; white-space: nowrap; }
textarea { width: 100%; min-height: 24rem; font-family: ui-monospace, Menlo, Consolas,
  monospace; font-size: .86rem; line-height: 1.45; padding: 10px;
  border: 1px solid #cfd5de; border-radius: 8px; background: #fff; color: #14181f; }
select { width: 100%; min-height: 46px; font-size: 1rem; padding: 0 10px;
  border: 1px solid #cfd5de; border-radius: 8px; background: #fff; color: #14181f; }
.erreurs { background: #fde8e4; color: #98261a; border-radius: 8px; padding: 12px 14px;
  margin: 0 0 16px; }
.erreurs ul { margin: 6px 0 0; padding-left: 20px; }
.secret { background: #fdf3df; color: #7a5510; border-radius: 8px; padding: 12px 14px;
  margin: 0 0 16px; font-family: ui-monospace, Menlo, Consolas, monospace;
  word-break: break-all; }
.inactif { opacity: .55; }
.barre { display: flex; gap: 14px; align-items: baseline; margin: 0 0 18px; }
.barre h1 { margin: 0; }
.barre .pousse { margin-left: auto; }
form.enligne { display: inline; }
button.discret { background: #fff; color: #3c454a; border: 1px solid #cfd5de;
  min-height: 36px; font-size: .9rem; padding: 0 12px; width: auto; }
@media (prefers-color-scheme: dark) {
  th, td { border-color: #2c3542; }
  textarea, select { background: #14181f; color: #e8eaed; border-color: #2c3542; }
  .erreurs { background: #3d2320; color: #f0a99f; }
  .secret { background: #3a3322; color: #e0c07a; }
  button.discret { background: #1d232c; color: #c8d0da; border-color: #2c3542; }
}
"""


def _page_admin(produit: str, titre: str, corps: str) -> str:
    return (
        "<!DOCTYPE html>\n"
        '<html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex, nofollow">'
        f"<title>{escape(titre)} · admin {escape(produit)}</title>"
        f"<style>{_STYLE_ADMIN}</style></head>"
        f'<body><main>{corps}<p class="marque">{escape(produit)} · administration'
        "</p></main></body></html>")


def admin_connexion(produit: str, erreur: str = "") -> str:
    """Le formulaire d'entrée de l'exploitant.

    UN SEUL MESSAGE pour tous les échecs — identifiant inconnu, compte désactivé, mot de
    passe faux. Distinguer serait aimable et renseignerait un inconnu sur l'existence
    d'un compte. Contrairement à la page de connexion artisan, où le visiteur est un
    client qu'on aide à se dépanner, celui qui échoue ici n'a rien à y faire.
    """
    alerte = f'<p class="erreurs">{escape(erreur)}</p>' if erreur else ""
    return _page_admin(
        produit, "Connexion",
        "<h1>Administration</h1>" + alerte +
        '<form method="post" action="/admin/connexion">'
        '<label for="i">Identifiant</label>'
        '<input id="i" name="identifiant" autocomplete="username" required autofocus>'
        '<label for="m">Mot de passe</label>'
        '<input id="m" name="mot_de_passe" type="password" '
        'autocomplete="current-password" required>'
        '<label></label><button type="submit">Entrer</button></form>')


def admin_artisans(produit: str, nom: str, artisans: list[dict]) -> str:
    """La liste. Première page après connexion : elle dit qui est servi et qui ne l'est
    pas — un artisan inutilisable doit se voir ICI, pas au premier appel de son client.
    """
    if artisans:
        lignes = "".join(
            '<tr class="{}">'.format("" if a["utilisable"] else "inactif")
            + '<td><a href="/admin/artisan/{}">{}</a><br>'.format(
                escape(a["id"]), escape(a["id"]))
            + '<span class="raisons">{}</span></td>'.format(escape(a["nom"] or "—"))
            + '<td class="num">{}</td>'.format(escape(a["numero_relais"] or "—"))
            + '<td class="num">{}</td>'.format(escape(a["telephone"] or "—"))
            + "<td>{}</td>".format(escape(a["etat"]))
            + "<td>{}</td>".format(escape(a["source_config"]))
            + '<td class="num">{}</td>'.format(a["appels"])
            + ('<td><form class="enligne" method="post" '
               'action="/admin/artisan/{}/voir">'
               '<button class="discret" type="submit">Voir son espace</button>'
               "</form></td></tr>").format(escape(a["id"]))
            for a in artisans)
        corps = ("<table><tr><th>Artisan</th><th>Numéro Relais</th><th>Mobile</th>"
                 "<th>Abonnement</th><th>Config</th><th>Appels</th><th></th></tr>"
                 + lignes + "</table>")
    else:
        corps = ('<p class="vide">Aucun artisan. Le produit ne peut servir personne '
                 "tant que cette liste est vide.</p>")
    return _page_admin(
        produit, "Artisans",
        '<div class="barre"><h1>Artisans</h1>'
        + '<span class="pousse raisons">{}</span>'.format(escape(nom))
        + '<form class="enligne" method="post" action="/admin/deconnexion">'
          '<button class="discret" type="submit">Quitter</button></form></div>'
        + corps
        + '<p class="apres"><a href="/admin/artisan/nouveau">+ Nouvel artisan</a></p>')


def admin_artisan(produit: str, artisan: dict, config_json: str,
                  erreurs: list = (), jeton: str = "", cree: bool = False) -> str:
    """Création et édition. UN SEUL gabarit pour les deux : les champs sont les mêmes, et
    deux pages jumelles finiraient par diverger sur le détail qui compte.

    LA CONFIG EST ÉDITÉE EN JSON, et c'est un choix assumé pour cette première version.
    Elle compte onze sections et dix-huit chemins que le moteur lit sans filet ; un
    formulaire structuré est un vrai travail de conception, qui mérite d'être fait APRÈS
    avoir vu trois configs réelles. En attendant, le JSON donne accès à TOUT
    immédiatement — et la validation côté serveur est la même quelle que soit la forme
    du champ. C'est elle qui protège l'appel, pas le formulaire.
    """
    neuf = not artisan.get("id")
    action = "/admin/artisan" if neuf else "/admin/artisan/" + escape(artisan["id"])
    alerte = ""
    if erreurs:
        alerte = ('<div class="erreurs"><b>Rien n a été enregistré.</b><ul>'
                  .replace("n a", "n&#x27;a")
                  + "".join("<li>{}</li>".format(escape(str(e))) for e in erreurs)
                  + "</ul></div>")
    secret = ""
    if jeton:
        secret = ('<div class="secret"><b>Jeton porteur — affiché une seule fois.</b>'
                  "<br>" + escape(jeton) + "<br>"
                  "La base n en garde que l empreinte : il ne sera pas relisible.</div>"
                  ).replace("n en", "n&#x27;en").replace("l empreinte", "l&#x27;empreinte")
    bandeau = '<p class="raisons">Artisan créé.</p>' if cree else ""
    verrou = " required autofocus" if neuf else " readonly"
    etat = artisan.get("etat_abonnement") or "actif"
    options = "".join(
        '<option value="{0}"{1}>{0}</option>'.format(
            e, " selected" if e == etat else "")
        for e in ("actif", "essai", "suspendu", "resilie"))
    titre = artisan.get("id") or "Nouvel artisan"
    regenerer = ""
    if not neuf:
        regenerer = (
            '<form method="post" action="/admin/artisan/'
            + escape(artisan["id"]) + '/jeton" style="margin-top:18px">'
            '<button class="discret" type="submit">Régénérer le jeton porteur</button>'
            "</form>")
    return _page_admin(
        produit, titre,
        '<div class="barre"><h1>' + escape(titre) + "</h1>"
        '<span class="pousse"><a href="/admin">Tous les artisans</a></span></div>'
        + bandeau + alerte + secret
        + '<form method="post" action="' + action + '">'
        + '<label for="id">Identifiant technique</label>'
        + '<input id="id" name="id" value="{}"{}>'.format(
            escape(artisan.get("id") or ""), verrou)
        + '<label for="nom">Nom affiché</label>'
        + '<input id="nom" name="nom" value="{}">'.format(
            escape(artisan.get("nom") or ""))
        + '<label for="rel">Numéro Relais (celui que le client compose)</label>'
        + '<input id="rel" name="numero_relais" value="{}">'.format(
            escape(artisan.get("numero_relais") or ""))
        + '<label for="tel">Mobile du patron (reçoit le code de connexion)</label>'
        + '<input id="tel" name="telephone" value="{}">'.format(
            escape(artisan.get("telephone") or ""))
        + '<label for="ab">Abonnement</label>'
        + '<select id="ab" name="etat_abonnement">' + options + "</select>"
        + '<label for="cfg">Config — ce que l&#x27;agent saura pendant les appels</label>'
        + '<textarea id="cfg" name="config" spellcheck="false">'
        + escape(config_json) + "</textarea>"
        + '<label></label><button type="submit">Enregistrer</button></form>'
        + regenerer)


# ══════════════════════════════════════════ L'ESPACE ARTISAN — système de design
#
# LA RÉFÉRENCE EST `docs/maquette/nelyo-maquette.html`, et c'est une CIBLE, pas une
# inspiration : jetons (`:root`), typographie, composants (cards, pills, scores,
# boutons, filtres, table d'appels, bulles de transcript) et structure de navigation
# en sont repris tels quels. Toute divergence ci-dessous est délibérée et commentée.
#
# DEUX ÉCARTS ASSUMÉS, et deux seulement :
#
# 1. **Les polices sont AUTO-HÉBERGÉES** (`/static/polices`). La maquette les charge
#    depuis `fonts.googleapis.com` ; chaque chargement transmet l'IP du visiteur —
#    artisan ou client — à un tiers, sur un produit qui manipule des données de
#    particuliers, et fait dépendre l'affichage d'un CDN joignable depuis un chantier.
#    Même rendu, même familles (SIL OFL, l'auto-hébergement est explicitement permis).
#
# 2. **Pas de JavaScript.** La maquette bascule entre ses six vues par `go(v)` ; ici
#    chaque vue est une URL et la navigation est faite de liens. Le rendu est
#    identique, la page reste utilisable sans script, et le bouton « précédent »
#    fonctionne. Les `<button data-v>` deviennent donc des `<a href>`.
_STYLE_NELYO = """
@font-face{font-family:'Instrument Sans';font-style:normal;font-weight:400 600;
  font-display:swap;src:url(/static/polices/instrument-sans.woff2) format('woff2')}
@font-face{font-family:'Bricolage Grotesque';font-style:normal;font-weight:500 700;
  font-display:swap;src:url(/static/polices/bricolage-grotesque.woff2) format('woff2')}
:root{
  --marine:#1E3D5C; --marine-deep:#16304A; --marine-soft:#E8EFF5;
  --cuivre:#C06B45; --cuivre-deep:#A85837; --cuivre-soft:#F7E9E1;
  --paper:#F3F5F6; --surface:#FFFFFF; --surface-2:#F8FAFB;
  --ink:#1E2A33; --muted:#5C6B77; --faint:#8B99A4; --line:#DFE6EA;
  --ok:#2E7D4F; --ok-bg:#E3F0E8; --warn:#A66A12; --warn-bg:#F8EEDC;
  --crit:#C24A3F; --crit-bg:#F8E6E3;
  --sidebar:#16304A; --sidebar-ink:#C7D6E4; --sidebar-active:#FFFFFF;
  --shadow:0 1px 2px rgba(22,48,74,.06),0 4px 16px rgba(22,48,74,.07);
  --r:10px;
}
@media (prefers-color-scheme: dark){
  :root{
    --marine:#7FA8CC; --marine-deep:#0F2438; --marine-soft:#1D2E3F;
    --cuivre:#D07E55; --cuivre-deep:#E08B60; --cuivre-soft:#3A2A21;
    --paper:#10161C; --surface:#18212A; --surface-2:#1D2833;
    --ink:#E8EDF1; --muted:#9AAAB6; --faint:#6E7E8A; --line:#2A3641;
    --ok:#5CB483; --ok-bg:#1C3227; --warn:#D9A24A; --warn-bg:#372B16;
    --crit:#E07A6E; --crit-bg:#3A211E;
    --sidebar:#0F1B28; --sidebar-ink:#8FA5B8; --sidebar-active:#FFFFFF;
    --shadow:0 1px 2px rgba(0,0,0,.3),0 4px 16px rgba(0,0,0,.25);
  }
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
  font:400 14.5px/1.5 "Instrument Sans",system-ui,-apple-system,sans-serif}
h1,h2,h3,.num{font-family:"Bricolage Grotesque","Instrument Sans",system-ui,sans-serif}
.num{font-variant-numeric:tabular-nums}
a{color:var(--marine)}
.app{display:flex;min-height:100vh}
/* ---------- barre latérale ---------- */
.side{width:228px;flex:0 0 228px;background:var(--sidebar);color:var(--sidebar-ink);
  display:flex;flex-direction:column;position:sticky;top:0;height:100vh}
.logo{display:flex;align-items:center;gap:10px;padding:22px 20px 18px;color:#fff;
  text-decoration:none}
.logo-mark{width:32px;height:32px;border-radius:9px;background:var(--cuivre);
  display:grid;place-items:center;flex:0 0 32px}
.logo-mark svg{width:18px;height:18px}
.logo b{font-family:"Bricolage Grotesque";font-size:19px;font-weight:700;
  letter-spacing:.2px}
.logo small{display:block;font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;
  opacity:.65;font-weight:500}
nav{padding:6px 12px;display:flex;flex-direction:column;gap:2px}
.nav-item{display:flex;align-items:center;gap:11px;padding:9px 12px;border-radius:8px;
  color:inherit;text-decoration:none;font:500 14px/1 "Instrument Sans",sans-serif}
.nav-item svg{width:17px;height:17px;flex:0 0 17px;opacity:.8}
.nav-item:hover{background:rgba(255,255,255,.07);color:#fff}
.nav-item.on{background:rgba(255,255,255,.12);color:var(--sidebar-active)}
.nav-item.on svg{opacity:1}
.nav-item .cnt{margin-left:auto;background:var(--cuivre);color:#fff;font-size:11px;
  font-weight:600;border-radius:99px;padding:1px 7px}
.side-foot{margin-top:auto;padding:14px 16px;border-top:1px solid rgba(255,255,255,.09)}
.artisan{display:flex;gap:10px;align-items:center}
.avatar{width:34px;height:34px;border-radius:50%;background:var(--cuivre-soft);
  color:var(--cuivre);display:grid;place-items:center;font-weight:600;font-size:13px;
  flex:0 0 34px}
.side .avatar{background:rgba(255,255,255,.12);color:#fff}
.artisan b{color:#fff;font-size:13.5px;display:block}
.artisan span{font-size:11.5px;opacity:.65}
.side-foot form{margin-top:10px}
.side-foot button{width:100%;background:none;border:1px solid rgba(255,255,255,.16);
  color:var(--sidebar-ink);border-radius:8px;padding:6px;font:500 12px "Instrument Sans";
  cursor:pointer}
/* ---------- zone principale ---------- */
.main{flex:1;min-width:0;display:flex;flex-direction:column}
.topbar{display:flex;align-items:center;gap:14px;padding:14px 28px;
  background:var(--surface);border-bottom:1px solid var(--line);position:sticky;top:0;
  z-index:5}
.topbar h1{font-size:19px;font-weight:600;margin:0}
.topbar .droite{margin-left:auto;display:flex;align-items:center;gap:10px}
.content{padding:24px 28px 48px;display:flex;flex-direction:column;gap:20px;
  max-width:1180px;width:100%;margin:0 auto}
/* ---------- briques communes ---------- */
.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);
  box-shadow:var(--shadow)}
.card-h{display:flex;align-items:center;gap:10px;padding:15px 18px;
  border-bottom:1px solid var(--line);flex-wrap:wrap}
.card-h h3{margin:0;font-size:15px;font-weight:600}
.card-h .sub{color:var(--muted);font-size:12.5px}
.card-b{padding:18px}
.pill{display:inline-flex;align-items:center;gap:5px;border-radius:99px;padding:2px 9px;
  font-size:11.5px;font-weight:600;white-space:nowrap}
.p-ok{background:var(--ok-bg);color:var(--ok)}
.p-warn{background:var(--warn-bg);color:var(--warn)}
.p-crit{background:var(--crit-bg);color:var(--crit)}
.p-mut{background:var(--surface-2);color:var(--muted);border:1px solid var(--line)}
.p-marine{background:var(--marine-soft);color:var(--marine)}
.btn{border:1px solid var(--line);background:var(--surface);color:var(--ink);
  border-radius:8px;padding:8px 14px;font:600 13px "Instrument Sans",sans-serif;
  cursor:pointer;text-decoration:none;display:inline-block}
.btn:hover{background:var(--surface-2)}
.btn-cu{background:var(--cuivre);border-color:var(--cuivre);color:#fff}
.btn-cu:hover{background:var(--cuivre-deep);border-color:var(--cuivre-deep)}
.btn-ghost-crit{color:var(--crit)}
.chip{display:inline-flex;align-items:center;border:1px solid var(--line);
  background:var(--surface-2);border-radius:99px;padding:4px 11px;font-size:12.5px;
  font-weight:500}
.chip.x{border-style:dashed;color:var(--muted)}
.grid{display:grid;gap:16px}
.g4{grid-template-columns:repeat(4,1fr)}
.g3{grid-template-columns:repeat(3,1fr)}
.g2{grid-template-columns:repeat(2,1fr)}
.eyebrow{font-size:11px;letter-spacing:.08em;text-transform:uppercase;
  color:var(--faint);font-weight:600}
/* ---------- accueil ---------- */
.hello h1{font-size:24px;margin:0 0 2px;text-wrap:balance}
.hello p{margin:0;color:var(--muted)}
.stat .card-b{display:flex;flex-direction:column;gap:2px;padding:15px 18px}
.stat .num{font-size:26px;font-weight:700}
.stat .lbl{color:var(--muted);font-size:12.5px}
.valid-item{display:flex;gap:14px;padding:14px 18px;border-bottom:1px solid var(--line);
  align-items:center;flex-wrap:wrap}
.valid-item:last-child{border-bottom:0}
.score{width:38px;height:38px;border-radius:9px;display:grid;place-items:center;
  font:700 14px "Bricolage Grotesque";flex:0 0 38px}
.s5{background:var(--crit-bg);color:var(--crit)}
.s4{background:var(--cuivre-soft);color:var(--cuivre)}
.s3{background:var(--marine-soft);color:var(--marine)}
.s1{background:var(--surface-2);color:var(--faint)}
.valid-info{min-width:190px;flex:1}
.valid-info b{font-size:14.5px}
.valid-info .d{color:var(--muted);font-size:12.5px}
.valid-slot{font-weight:600;font-size:13.5px}
.valid-slot .d{color:var(--muted);font-weight:400;font-size:12px}
.valid-act{display:flex;gap:8px;margin-left:auto;flex-wrap:wrap}
.valid-act form{display:inline}
.feed{list-style:none;margin:0;padding:0}
.feed li{display:flex;gap:12px;padding:10px 18px;border-bottom:1px solid var(--line);
  font-size:13.5px;align-items:baseline}
.feed li:last-child{border-bottom:0}
.feed time{color:var(--faint);font-size:12px;font-variant-numeric:tabular-nums;
  flex:0 0 46px}
.feed .dot{width:7px;height:7px;border-radius:50%;flex:0 0 7px;align-self:center}
/* ---------- appels ---------- */
.filters{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.fbtn{border:1px solid var(--line);background:var(--surface);border-radius:99px;
  padding:6px 14px;font:500 13px "Instrument Sans";color:var(--muted);cursor:pointer;
  text-decoration:none;display:inline-block}
.fbtn.on{background:var(--marine);border-color:var(--marine);color:#fff}
table.calls{width:100%;border-collapse:collapse;font-size:13.5px}
.calls th{font-size:11px;letter-spacing:.07em;text-transform:uppercase;
  color:var(--faint);text-align:left;padding:11px 14px;
  border-bottom:1px solid var(--line);font-weight:600}
.calls td{padding:12px 14px;border-bottom:1px solid var(--line);vertical-align:middle}
.calls tr:last-child td{border-bottom:0}
.caller b{display:block}
.caller span{color:var(--faint);font-size:12px}
.transcript{background:var(--surface-2);border-top:1px dashed var(--line);
  padding:16px 18px;display:flex;flex-direction:column;gap:10px}
.bulle{max-width:520px;padding:8px 13px;border-radius:12px;font-size:13px;
  line-height:1.45}
.b-ia{background:var(--marine-soft);color:var(--ink);border-top-left-radius:3px;
  align-self:flex-start}
.b-cl{background:var(--surface);border:1px solid var(--line);
  border-top-right-radius:3px;align-self:flex-end}
.bulle .who{display:block;font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;
  color:var(--faint);margin-bottom:2px;font-weight:600}
details.appel summary{list-style:none;cursor:pointer}
details.appel summary::-webkit-details-marker{display:none}
details.horaire summary{list-style:none;cursor:pointer;display:inline-block}
details.horaire summary::-webkit-details-marker{display:none}
details.horaire[open]{flex:1 0 100%;order:9}
details.horaire form{margin-top:10px;max-width:260px}
details.horaire label{display:block;font-size:12px;color:var(--muted);margin:8px 0 3px}
details.horaire input{width:100%;min-height:38px;border:1px solid var(--line);
  border-radius:8px;padding:0 10px;background:var(--surface);color:var(--ink);
  font:400 13.5px "Instrument Sans",sans-serif}
/* ---------- états vides et pages à venir ---------- */
.vide{padding:40px 24px;text-align:center;color:var(--muted)}
.vide .gros{font-size:16px;color:var(--ink);font-weight:600;margin:0 0 6px;
  font-family:"Bricolage Grotesque"}
.vide p{margin:0;font-size:13.5px}
.aveu{border-left:3px solid var(--warn)}
.aveu ul{margin:10px 0 0;padding-left:20px;color:var(--muted);font-size:13.5px}
.aveu li{margin:4px 0}
/* ---------- bandeau support ---------- */
.support{background:var(--marine-soft);color:var(--marine);
  border-bottom:1px solid var(--line);padding:10px 28px;font-size:13px;display:flex;
  gap:12px;align-items:center;flex-wrap:wrap}
.support form{margin-left:auto}
.week{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}
.day{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);
  min-height:260px;display:flex;flex-direction:column}
.day.today{border-color:var(--cuivre)}
.day-h{padding:10px 12px;border-bottom:1px solid var(--line);font-weight:600;
  font-size:13px}
.day-h span{color:var(--faint);font-weight:400;display:block;font-size:11.5px}
.day-b{padding:8px;display:flex;flex-direction:column;gap:7px}
.evt{border-radius:8px;padding:8px 10px;font-size:12.5px;line-height:1.35;
  border:1px solid transparent;position:relative}
.evt time{display:block;font-size:11px;font-weight:600;opacity:.75;
  font-variant-numeric:tabular-nums}
.evt b{font-size:12.5px}
.e-ok{background:var(--marine-soft);color:var(--ink)}
.e-wait{background:var(--cuivre-soft);border:1px dashed var(--cuivre);color:var(--ink)}
.e-perso{background:var(--surface-2);border:1px solid var(--line);color:var(--ink)}
.e-off{background:repeating-linear-gradient(45deg,var(--surface-2),
  var(--surface-2) 6px,var(--line) 6px,var(--line) 7px);color:var(--muted)}
.evt details{margin-top:7px}
.evt details summary{list-style:none;cursor:pointer;color:var(--faint);font-size:11px;
  letter-spacing:.04em;text-transform:uppercase;font-weight:600}
.evt details summary::-webkit-details-marker{display:none}
.evt details summary:hover{color:var(--ink)}
.evt form{margin-top:7px;display:flex;flex-direction:column;gap:5px}
.evt form label{margin:0;font-size:10.5px}
.evt form input,.evt form select{min-height:32px;font-size:12.5px;padding:0 7px}
.evt form .btns{display:flex;gap:6px;margin-top:4px}
.evt form button{min-height:30px;font-size:11.5px;padding:0 9px;width:auto}
.evt .avis{color:var(--muted);font-size:11px;line-height:1.35;margin:5px 0 0}
.legend{display:flex;gap:18px;flex-wrap:wrap;font-size:12.5px;color:var(--muted);
  align-items:center}
.sw{width:12px;height:12px;border-radius:4px;display:inline-block;vertical-align:-2px;
  margin-right:6px}
.ajout{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;
  align-items:end}
.ajout label{margin:0 0 3px}
.ajout .large{grid-column:span 2}
@media (max-width:940px){.week{grid-template-columns:repeat(2,1fr)}}
@media (max-width:520px){.week{grid-template-columns:1fr}}
/* ---------- responsive ---------- */
.mobilebar{display:none}
@media (max-width:940px){
  .side{display:none}
  .topbar{padding:12px 16px}
  .content{padding:16px 16px 90px}
  .support{padding:10px 16px}
  .g4,.g3{grid-template-columns:repeat(2,1fr)}
  .g2{grid-template-columns:1fr}
  .valid-act{margin-left:0;width:100%}
  .calls th:nth-child(4),.calls td:nth-child(4){display:none}
  .mobilebar{display:flex;position:fixed;bottom:0;left:0;right:0;
    background:var(--surface);border-top:1px solid var(--line);z-index:20;
    justify-content:space-around;
    padding:6px 4px calc(6px + env(safe-area-inset-bottom,0px))}
  .mobilebar a{border:0;background:none;color:var(--faint);
    font:500 10px "Instrument Sans";display:flex;flex-direction:column;
    align-items:center;gap:3px;padding:4px 8px;text-decoration:none}
  .mobilebar a.on{color:var(--cuivre)}
  .mobilebar svg{width:19px;height:19px}
}
@media (max-width:520px){.g4,.g3{grid-template-columns:1fr}}
"""

# Les icônes de la navigation, reprises de la maquette. En SVG INLINE : ce n'est pas une
# ressource externe, donc rien à charger et rien à fuiter.
_ICONES = {
    "accueil": '<path d="M3 11 12 4l9 7"/><path d="M5 10v10h14V10"/>',
    "appels": ('<path d="M5 4h4l2 5-2.5 1.5a12 12 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16'
               ' 16 0 0 1 3 6a2 2 0 0 1 2-2z"/>'),
    "agenda": ('<rect x="3" y="5" width="18" height="16" rx="2"/>'
               '<path d="M8 3v4M16 3v4M3 10h18"/>'),
    "stats": '<path d="M4 20V10M10 20V4M16 20v-7M21 20H3"/>',
    "ia": ('<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3'
           'M4.9 4.9l2.1 2.1M17 17l2.1 2.1M19.1 4.9 17 7M7 17l-2.1 2.1"/>'),
    "factu": ('<rect x="3" y="6" width="18" height="13" rx="2"/>'
              '<path d="M3 10h18M7 15h4"/>'),
}

# La navigation de la maquette, telle quelle : six entrées, dans le même ordre.
# `/app` est l'accueil ; les autres ont leur propre URL, puisqu'il n'y a pas de JS pour
# basculer entre des sections cachées.
_NAV = [
    ("accueil", "Aujourd'hui", "/app"),
    ("appels", "Appels", "/app/appels"),
    ("agenda", "Agenda", "/app/agenda"),
    ("stats", "Statistiques", "/app/stats"),
    ("ia", "Assistant IA", "/app/assistant"),
    ("factu", "Facturation", "/app/facturation"),
]
_TITRES = {c: t for c, t, _ in _NAV}


def _svg(cle: str, taille: int = 17) -> str:
    return (f'<svg viewBox="0 0 24 24" width="{taille}" height="{taille}" fill="none" '
            f'stroke="currentColor" stroke-width="2" stroke-linecap="round">'
            f'{_ICONES[cle]}</svg>')


def _initiales(nom: str) -> str:
    """« Dupont Chauffage » → « DC ». Deux lettres, jamais plus."""
    mots = [m for m in (nom or "").replace("-", " ").split() if m]
    return ("".join(m[0] for m in mots[:2]) or "?").upper()


def _page_nelyo(produit: str, vue: str, corps: str, *, entreprise: str = "",
                prenom: str = "", commune: str = "", a_valider: int = 0,
                vue_admin: str = "", titre: str = "") -> str:
    """L'enveloppe de l'espace artisan : barre latérale, barre du haut, contenu.

    Reprend la structure de la maquette — `.app > .side + .main > .topbar + .content` —
    avec la barre du bas sur mobile. La VUE ACTIVE est un paramètre : la page sait où
    elle est, l'enveloppe n'a pas à le redeviner en lisant une URL.

    Le compteur « à valider » vit dans la navigation et pas seulement sur l'accueil :
    c'est le seul chiffre qui appelle une action, et il doit se voir depuis n'importe
    quel écran — sinon il faut y aller pour savoir s'il faut y aller.
    """
    bandeau = ""
    if vue_admin:
        bandeau = (
            '<div class="support">'
            "<span><b>Mode support — lecture seule.</b> Vous regardez l&#x27;espace de "
            + escape(vue_admin) + " ; aucune action n&#x27;est possible d&#x27;ici."
            "</span>"
            '<form method="post" action="/admin/vue/fin">'
            '<button class="btn" type="submit">Revenir à l&#x27;administration</button>'
            "</form></div>")

    liens = "".join(
        '<a class="nav-item{}" href="{}">{}{}{}</a>'.format(
            " on" if cle == vue else "", href, _svg(cle), escape(libelle),
            f'<span class="cnt">{a_valider}</span>'
            if (cle == "accueil" and a_valider) else "")
        for cle, libelle, href in _NAV)
    barre_mobile = "".join(
        '<a class="{}" href="{}">{}{}</a>'.format(
            "on" if cle == vue else "", href, _svg(cle, 19),
            escape("Accueil" if cle == "accueil" else libelle.split()[0]))
        for cle, libelle, href in _NAV)

    ini = _initiales(entreprise or prenom)
    pied_lateral = (
        '<div class="side-foot"><div class="artisan">'
        f'<span class="avatar">{escape(ini)}</span>'
        f"<div><b>{escape(entreprise or '—')}</b>"
        f"<span>{escape(prenom)}{' · ' + escape(commune) if commune else ''}</span>"
        "</div></div>"
        + ("" if vue_admin else
           '<form method="post" action="/deconnexion">'
           '<button type="submit">Se déconnecter</button></form>')
        + "</div>")

    return (
        "<!DOCTYPE html>\n"
        '<html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex, nofollow">'
        f"<title>{escape(titre or _TITRES.get(vue, ''))} · {escape(produit)}</title>"
        f"<style>{_STYLE_NELYO}</style></head><body>"
        + bandeau
        + '<div class="app"><aside class="side">'
        + '<a class="logo" href="/app"><span class="logo-mark">'
          '<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" '
          'stroke-linecap="round"><path d="M5 4v6a7 7 0 0 0 14 0V4"/>'
          '<path d="M12 17v3"/></svg></span>'
        + f"<div><b>{escape(produit)}</b><small>Ne ratez plus rien</small></div></a>"
        + f"<nav>{liens}</nav>{pied_lateral}</aside>"
        + '<div class="main"><header class="topbar">'
        + f"<h1>{escape(titre or _TITRES.get(vue, ''))}</h1>"
        + f'<div class="droite"><span class="avatar" style="width:32px;height:32px;'
          f'font-size:12px">{escape(ini)}</span></div></header>'
        + f'<div class="content">{corps}</div></div></div>'
        + f'<nav class="mobilebar">{barre_mobile}</nav>'
        + "</body></html>")


# Le SCORE a sa classe de couleur dans la maquette (`.s5` rouge, `.s4` cuivre,
# `.s3` marine, `.s1` gris). Elle porte du sens : plus c'est chaud, plus ça presse.
def _classe_score(score: int) -> str:
    return {5: "s5", 4: "s4", 3: "s3"}.get(int(score or 0), "s1")


# Ce que chaque catégorie VEUT DIRE, et la pastille de la maquette qui lui va.
# Vocabulaire fermé, aligné sur `engine.py` — une catégorie inconnue s'affiche telle
# quelle plutôt que d'être masquée : mieux vaut un libellé brut qu'un appel escamoté.
#
# R79 appliqué à l'écran : « une catégorie doit dire à l'artisan ce qu'il peut FAIRE ».
# La teinte sépare ce sur quoi il peut agir de ce qui est clos.
_CATEGORIES = {
    "rdv_reserve":    ("RDV réservé", "p-ok"),
    "prioritaire":    ("Prioritaire", "p-crit"),
    "a_rappeler":     ("À rappeler", "p-marine"),
    "injoignable":    ("Sans numéro", "p-mut"),
    "hors_zone":      ("Hors zone", "p-mut"),
    "hors_perimetre": ("Hors prestations", "p-mut"),
    "spam":           ("Indésirable", "p-mut"),
    "appel_muet":     ("Appel muet", "p-mut"),
    "autre":          ("Autre", "p-mut"),
}


def accueil(produit: str, prenom: str, entreprise: str, rdvs: list[dict],
            chiffres: list[tuple], activite: list[dict], salutation: str = "",
            commune: str = "", vue_admin: str = "") -> str:
    """« Aujourd'hui » : ce qui attend une décision, puis ce qui s'est passé.

    LA MAQUETTE PORTE DEUX BLOCS QUE JE N'AI PAS REPRIS, et c'est délibéré : le bandeau
    « CA récupéré ce mois — 4 850 € × 32 votre abonnement », et les deltas des tuiles
    (« +18 % vs août », « 38 % de conversion »). Le produit ne sait NI ce qu'un chantier
    a rapporté, NI s'il a été signé : il s'arrête au rendez-vous validé. Les afficher
    demanderait de les inventer, et une interface qui affirme un chiffre le fait avec
    son autorité (R79/R85). Ils reviendront le jour où l'artisan pourra saisir le
    montant d'un chantier — c'est une fonctionnalité, pas un calcul.

    Les tuiles affichées, elles, sont comptées sur de vraies lignes.
    """
    a_valider = sum(1 for r in rdvs if not r["echu"])
    corps = [
        '<div class="hello">'
        f"<h1>Bonjour {escape(prenom)}</h1>"
        f"<p>{salutation}</p></div>"]

    if rdvs:
        lignes = []
        for r in rdvs:
            if r["echu"]:
                # Pas de boutons : le délai est passé, le domaine refuserait la
                # décision. Afficher une action qui ne peut qu'échouer serait mentir ;
                # la masquer serait pire, l'artisan doit savoir qu'il a laissé filer un
                # lead. ON NE DIT PAS « le client est prévenu » (R85) : le SMS part du
                # WORKER, et cette page ne sait pas s'il a tourné.
                acte = ('<span class="pill p-mut">Délai dépassé — créneau libéré</span>'
                        '<div class="d" style="width:100%;color:var(--muted);font-size:12.5px;margin-top:6px">'
                        "Rappelez le client si vous voulez le récupérer.</div>")
            elif vue_admin:
                acte = ('<span class="pill p-mut">Décision réservée à '
                        "l&#x27;artisan</span>")
            else:
                # TROIS actions, comme dans la maquette. « Modifier l'horaire »
                # ouvre un `<details>` natif : la reproposition est une fonction
                # entière du produit (nouveau créneau, SMS au client, lien de
                # confirmation) — l'oublier ici la ferait disparaître de l'écran
                # alors qu'elle existe côté serveur. R85 l'a rattrapée.
                ident = escape(r["id"])
                acte = (
                    '<div class="valid-act">'
                    f'<form method="post" action="/app/{ident}/valider">'
                    '<button class="btn btn-cu" type="submit">Valider</button></form>'
                    f'<details class="horaire"><summary class="btn">'
                    "Modifier l&#x27;horaire</summary>"
                    f'<form method="post" action="/app/{ident}/reproposer">'
                    '<label>Date</label><input type="date" name="date" required>'
                    '<label>De</label><input type="time" name="de" required>'
                    '<label>À</label><input type="time" name="a" required>'
                    '<button class="btn btn-cu" type="submit" '
                    'style="margin-top:10px">Envoyer au client</button>'
                    "</form></details>"
                    f'<form method="post" action="/app/{ident}/refuser">'
                    '<button class="btn btn-ghost-crit" type="submit">Refuser</button>'
                    "</form></div>")
            reste = ""
            if not r["echu"] and r.get("expire_dans"):
                teinte = "p-crit" if r["expire_minutes"] < 60 else "p-warn"
                reste = (f'<span class="pill {teinte}">expire dans '
                         f'{escape(r["expire_dans"])}</span>')
            lignes.append(
                '<div class="valid-item">'
                f'<span class="score {_classe_score(r["score"])}">{r["score"]}</span>'
                f'<div class="valid-info"><b>{escape(r["client"])}</b>'
                f'{" · " + escape(r["telephone_lisible"]) if r["telephone"] else ""}'
                f'<div class="d">{escape(r["motif"])}</div></div>'
                f'<div class="valid-slot">{escape(r["creneau"])}'
                '<div class="d">Créneau réservé par l&#x27;assistant</div></div>'
                f"{reste}{acte}</div>")
        corps.append(
            '<div class="card" style="border-left:3px solid var(--cuivre)">'
            '<div class="card-h"><h3>À valider</h3>'
            f'<span class="pill p-warn">{a_valider} rendez-vous en attente</span>'
            '<span class="sub" style="margin-left:auto">Le client reçoit un SMS dès '
            "votre décision</span></div>"
            + "".join(lignes) + "</div>")
    else:
        corps.append(
            '<div class="card"><div class="vide">'
            '<p class="gros">Rien à valider.</p>'
            "<p>Tout est à jour. Les appels reçus restent consultables dans "
            '<a href="/app/appels">Appels</a>.</p></div></div>')

    if chiffres:
        tuiles = "".join(
            f'<div class="card stat"><div class="card-b">'
            f'<span class="num">{n}</span><span class="lbl">{escape(libelle)}</span>'
            f"</div></div>"
            for libelle, n in chiffres)
        corps.append(f'<div class="grid g4">{tuiles}</div>')

    if activite:
        items = "".join(
            f'<li><time>{escape(a["heure"])}</time>'
            f'<span class="dot" style="background:var(--{a["couleur"]})"></span>'
            f'<span><b>{escape(a["titre"])}</b> — {escape(a["detail"])}</span></li>'
            for a in activite)
        corps.append(
            '<div class="card"><div class="card-h"><h3>Activité récente</h3></div>'
            f'<ul class="feed">{items}</ul></div>')

    return _page_nelyo(produit, "accueil", "".join(corps), entreprise=entreprise,
                       prenom=prenom, commune=commune, a_valider=a_valider,
                       vue_admin=vue_admin)


def liste_appels(produit: str, prenom: str, appels: list[dict],
                 filtres: list[tuple] = (), vue_admin: str = "",
                 entreprise: str = "", a_valider: int = 0, categorie: str = "",
                 commune: str = "") -> str:
    """« Appels » : tout ce que l'agent a pris, avec ou sans rendez-vous.

    La maquette met le transcript dans un panneau qui s'ouvre sous la ligne cliquée.
    Ici c'est un `<details>` natif : même geste, même rendu, et ça marche sans script.

    Les filtres sont des LIENS (un GET par catégorie). Plus lent qu'un filtre en JS,
    mais lisible sans script, compatible avec le bouton « précédent », et partageable
    par son URL — sur quelques dizaines de lignes, l'échange est franchement favorable.
    """
    enveloppe = lambda corps: _page_nelyo(  # noqa: E731
        produit, "appels", corps, entreprise=entreprise, prenom=prenom,
        commune=commune, a_valider=a_valider, vue_admin=vue_admin)

    barre = ""
    if filtres:
        barre = '<div class="filters">' + "".join(
            '<a class="fbtn{}" href="/app/appels{}">{} <b>{}</b></a>'.format(
                " on" if (c or "") == categorie else "",
                "" if c is None else "?categorie=" + c, escape(nom), n)
            for c, nom, n in filtres) + "</div>"

    if not appels:
        return enveloppe(
            barre + '<div class="card"><div class="vide">'
            '<p class="gros">Aucun appel ici.</p>'
            "<p>Dès qu&#x27;un client appellera, vous verrez ce qu&#x27;il a demandé, "
            "ce que l&#x27;assistant a répondu, et vous pourrez le rappeler d&#x27;un "
            "tap.</p></div></div>")

    lignes = []
    for a in appels:
        libelle, teinte = _CATEGORIES.get(a["categorie"], (a["categorie"], "p-mut"))
        tel = (f'<span>{escape(a["telephone_lisible"])}</span>'
               if a["telephone"] else '<span>—</span>')
        rang = (
            '<tr><td class="num">{}</td>'
            '<td class="caller"><b>{}</b>{}</td>'
            "<td>{}</td><td>{}</td>"
            '<td><span class="score {}" style="width:30px;height:30px">{}</span></td>'
            '<td class="num">{}</td>'
            '<td><span class="pill {}">{}</span></td></tr>'
        ).format(escape(a["heure"]), escape(a["client"]), tel, escape(a["motif"]),
                 escape(a["commune"]), _classe_score(a["score"]), a["score"],
                 escape(a["duree"]), teinte, escape(libelle))
        bulles = "".join(
            '<div class="bulle {}"><span class="who">{}</span>{}</div>'.format(
                "b-ia" if qui == "agent" else "b-cl",
                "Assistant " + escape(produit) if qui == "agent" else "Client",
                escape(texte))
            for qui, texte in a["transcript"])
        rappel = ""
        if a["telephone"]:
            rappel = ('<div><a class="btn btn-cu" href="tel:'
                      + escape(a["telephone"]) + '">Rappeler '
                      + escape(a["telephone_lisible"]) + "</a></div>")
        else:
            rappel = ('<div><span class="pill p-mut">Aucun numéro recueilli — '
                      "ce client n&#x27;est pas rappelable</span></div>")
        detail = ""
        if a["transcript"]:
            detail = (
                '<details class="appel"><summary><table class="calls">'
                f"<tbody>{rang}</tbody></table></summary>"
                f'<div class="transcript"><span class="eyebrow">Transcript — '
                f'{escape(a["client"])} · {escape(a["heure"])}</span>'
                f"{bulles}{rappel}</div></details>")
        else:
            detail = f'<table class="calls"><tbody>{rang}</tbody></table>'
        lignes.append(detail)

    entete = ('<table class="calls"><thead><tr><th>Heure</th><th>Appelant</th>'
              "<th>Motif</th><th>Commune</th><th>Score</th><th>Durée</th>"
              "<th>Issue</th></tr></thead></table>")
    return enveloppe(
        barre + '<div class="card" style="overflow-x:auto">'
        + entete + "".join(lignes) + "</div>")


def page_a_venir(produit: str, vue: str, entreprise: str, prenom: str,
                 manque: list[str], a_valider: int = 0, commune: str = "",
                 vue_admin: str = "") -> str:
    """Une vue de la maquette qui n'a pas encore ses données.

    ELLE DIT CE QU'IL MANQUE, précisément, plutôt que « bientôt ». Une page qui promet
    sans dire quoi ni pourquoi est une page qu'on revisite pour rien — et, sur un outil
    qu'un artisan paie, une promesse vague se retient comme un engagement. Dire « il
    faut d'abord brancher un agenda » est vérifiable ; « prochainement » ne l'est pas.
    """
    points = "".join(f"<li>{escape(m)}</li>" for m in manque)
    return _page_nelyo(
        produit, vue,
        '<div class="card aveu"><div class="card-b">'
        f'<p class="eyebrow">Pas encore disponible</p>'
        f"<h3 style=\"margin:6px 0 0\">{escape(_TITRES[vue])}</h3>"
        "<p style=\"color:var(--muted);margin:8px 0 0;font-size:13.5px\">"
        "Cet écran existe dans la maquette du produit. Il n&#x27;affiche rien pour "
        "l&#x27;instant parce qu&#x27;il demande des données que " + escape(produit)
        + " ne possède pas encore — et afficher des chiffres inventés serait pire "
          "que de ne rien afficher.</p>"
        f"<ul>{points}</ul></div></div>",
        entreprise=entreprise, prenom=prenom, commune=commune,
        a_valider=a_valider, vue_admin=vue_admin)


def _actions_evenement(e: dict, jour_iso: str) -> str:
    """Ce qu'on peut faire d'un bloc de l'agenda — et ça dépend de QUI l'a posé.

    **Un événement que l'artisan a inscrit lui-même** se déplace, se renomme et se
    retire : c'est sa note, elle n'engage personne d'autre.

    **Un rendez-vous NELYO ne se déplace pas d'ici.** Sa plage a été vendue à quelqu'un
    qui l'attend. On propose donc un AUTRE créneau — ce qui envoie au client un SMS avec
    un lien de confirmation (spec §3.5bis) — et le rendez-vous ne bouge qu'une fois qu'il
    a accepté. Déplacer une plage sans prévenir celui qui l'a achetée laisserait
    quelqu'un attendre chez lui ; c'est exactement la faute que R79 et R85 interdisent
    ailleurs dans le produit.
    """
    ident = escape(e["id"])
    if e["supprimable"]:
        options = "".join(
            '<option value="{0}"{1}>{2}</option>'.format(
                v, " selected" if e.get("type") == v else "", libelle)
            for v, libelle in (("rdv", "Rendez-vous"),
                               ("indisponible", "Indisponible")))
        return (
            "<details><summary>Modifier</summary>"
            f'<form method="post" action="/app/agenda/{ident}/modifier">'
            f'<label>Intitulé</label><input name="titre" required '
            f'value="{escape(e["titre"])}">'
            f'<label>Jour</label><input name="jour" type="date" required '
            f'value="{escape(jour_iso)}">'
            f'<label>De</label><input name="de" type="time" required '
            f'value="{escape(e["de"])}">'
            f'<label>À</label><input name="a" type="time" required '
            f'value="{escape(e["a"])}">'
            f'<label>Nature</label><select name="type">{options}</select>'
            '<div class="btns">'
            '<button class="btn btn-cu" type="submit">Déplacer</button></div>'
            "</form>"
            f'<form method="post" action="/app/agenda/{ident}/supprimer">'
            '<div class="btns">'
            '<button class="btn btn-ghost-crit" type="submit">Retirer</button>'
            "</div></form></details>")
    return (
        "<details><summary>Déplacer</summary>"
        f'<form method="post" action="/app/{ident}/reproposer">'
        '<label>Nouveau jour</label>'
        f'<input name="date" type="date" required value="{escape(jour_iso)}">'
        f'<label>De</label><input name="de" type="time" required '
        f'value="{escape(e["de"])}">'
        f'<label>À</label><input name="a" type="time" required '
        f'value="{escape(e["a"])}">'
        '<div class="btns">'
        '<button class="btn btn-cu" type="submit">Proposer au client</button></div>'
        "</form>"
        '<p class="avis">Le client recevra un SMS et devra confirmer. '
        "Le rendez-vous ne bouge pas avant sa réponse.</p></details>")


def agenda(produit: str, prenom: str, entreprise: str, jours: list[dict],
           semaine: str, precedente: str, suivante: str, a_valider: int = 0,
           commune: str = "", vue_admin: str = "", erreur: str = "") -> str:
    """L'agenda de l'artisan — le SIEN, sans Google ni Outlook.

    Il montre DEUX choses dans la même grille : ce que Nelyo a réservé (validé ou en
    attente) et ce que l'artisan a inscrit lui-même. C'est le point de toute la
    fonctionnalité : un agenda qui ne connaîtrait que la moitié des engagements de son
    propriétaire inspirerait une confiance qu'il ne mérite pas — et l'agent continuerait
    de vendre les plages manquantes.

    Les événements de l'artisan sont supprimables, les rendez-vous Nelyo ne le sont pas :
    ceux-là portent un engagement pris envers un client, et se refusent depuis l'accueil
    (ce qui prévient le client), jamais en les effaçant d'un agenda.
    """
    cases = []
    for j in jours:
        blocs = []
        for e in j["evenements"]:
            actions = ""
            if not vue_admin:
                actions = _actions_evenement(e, j["iso"])
            blocs.append(
                f'<div class="evt {e["classe"]}">'
                f'<time>{escape(e["heures"])}</time>'
                f'<b>{escape(e["titre"])}</b>'
                + (f' — {escape(e["detail"])}' if e["detail"] else "")
                + actions + "</div>")
        if not blocs:
            blocs.append('<div class="evt e-off" style="text-align:center">'
                         "Rien de prévu</div>")
        cases.append(
            f'<div class="day{" today" if j["aujourdhui"] else ""}">'
            f'<div class="day-h">{escape(j["nom"])}<span>{escape(j["date"])}</span></div>'
            f'<div class="day-b">{"".join(blocs)}</div></div>')

    alerte = f'<div class="card aveu"><div class="card-b">{escape(erreur)}</div></div>' \
        if erreur else ""

    formulaire = ""
    if not vue_admin:
        formulaire = (
            '<div class="card"><div class="card-h"><h3>Ajouter à mon agenda</h3>'
            '<span class="sub" style="margin-left:auto">Un chantier, un rendez-vous, '
            "des congés — l&#x27;assistant cessera de proposer ces heures</span></div>"
            '<div class="card-b"><form method="post" action="/app/agenda">'
            '<div class="ajout">'
            '<div class="large"><label for="t">Intitulé</label>'
            '<input id="t" name="titre" required placeholder="Chantier Morel"></div>'
            '<div><label for="j">Jour</label>'
            '<input id="j" name="jour" type="date" required></div>'
            '<div><label for="d">De</label>'
            '<input id="d" name="de" type="time" required value="08:00"></div>'
            '<div><label for="f">À</label>'
            '<input id="f" name="a" type="time" required value="10:00"></div>'
            '<div><label for="ty">Nature</label>'
            '<select id="ty" name="type">'
            '<option value="rdv">Rendez-vous</option>'
            '<option value="indisponible">Indisponible</option>'
            "</select></div>"
            '<div><button class="btn btn-cu" type="submit">Ajouter</button></div>'
            "</div></form></div></div>")

    corps = (
        '<div class="filters">'
        f'<a class="fbtn" href="/app/agenda?semaine={escape(precedente)}">◀</a>'
        f'<span class="chip" style="font-weight:600">{escape(semaine)}</span>'
        f'<a class="fbtn" href="/app/agenda?semaine={escape(suivante)}">▶</a>'
        '<span style="margin-left:auto" class="legend">'
        '<span><span class="sw" style="background:var(--marine-soft)"></span>'
        "RDV confirmé</span>"
        '<span><span class="sw" style="background:var(--cuivre-soft);'
        'border:1px dashed var(--cuivre)"></span>En attente de validation</span>'
        '<span><span class="sw" style="background:var(--surface-2);'
        'border:1px solid var(--line)"></span>Ajouté par vous</span>'
        "</span></div>"
        + alerte
        + f'<div class="week">{"".join(cases)}</div>'
        + formulaire)
    return _page_nelyo(produit, "agenda", corps, entreprise=entreprise, prenom=prenom,
                       commune=commune, a_valider=a_valider, vue_admin=vue_admin,
                       titre="Agenda")
