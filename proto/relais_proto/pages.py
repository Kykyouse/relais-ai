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
from urllib.parse import urlencode

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
    """Premier écran : le mobile, et le mot de passe pour qui en a un.

    `type="tel"` fait sortir le pavé numérique du téléphone, et `autocomplete="tel"`
    laisse le navigateur proposer le numéro déjà connu — sur un chantier, une main libre
    et un écran sale, chaque frappe évitée compte.

    LE MOT DE PASSE EST FACULTATIF, sur le même formulaire (22/09). Deux écrans séparés
    auraient obligé à choisir sa porte AVANT de savoir laquelle on a ; ici on remplit ce
    qu'on sait, et le serveur tranche. Laissé vide, c'est le code SMS — la seule voie
    pour qui a perdu son mot de passe, changé de téléphone, ou n'en a jamais défini.

    `autocomplete="username"` sur le mobile et `current-password` sur le second champ :
    c'est ce couple, et lui seul, qui fait proposer l'enregistrement au gestionnaire du
    navigateur. Sans lui, « l'enregistrer dans son appareil » ne marche tout simplement
    pas — l'artisan retaperait son mot de passe à chaque fois.
    """
    alerte = f'<p class="raisons">{escape(erreur)}</p>' if erreur else ""
    return _page_app(
        produit,
        "Connexion",
        "<h1>Connexion</h1>"
        '<p class="raisons">Votre mobile et votre mot de passe. Sans mot de passe, '
        "vous recevrez un code par SMS.</p>"
        + alerte
        + '<form method="post" action="/connexion">'
          "<label>Mobile</label>"
          '<input type="tel" name="telephone" autocomplete="username" '
          'inputmode="numeric" placeholder="06 12 34 56 78" required>'
          "<label>Mot de passe <small>(si vous en avez un)</small></label>"
          '<input type="password" name="mot_de_passe" '
          'autocomplete="current-password">'
          '<label></label><button type="submit">Se connecter</button></form>')


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
                  erreurs: list = (), jeton: str = "", cree: bool = False,
                  lien: str = "", mot_de_passe: str = "") -> str:
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
    if lien:
        secret += ('<div class="secret"><b>Lien de connexion — valable 15 minutes, '
                   "un seul usage.</b><br>" + escape(lien) + "<br>"
                   "Il ouvre la session de cet artisan. Ne le transmettez qu&#x27;à lui."
                   "</div>")
    if mot_de_passe:
        secret += ('<div class="secret"><b>Mot de passe — affiché une seule fois.</b>'
                   "<br>" + escape(mot_de_passe) + "<br>"
                   "L&#x27;artisan se connectera avec son mobile et ce mot de passe, "
                   "que son navigateur pourra retenir.</div>")
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
        ident_a = escape(artisan["id"])
        regenerer = (
            '<div style="margin-top:18px;display:flex;gap:10px;flex-wrap:wrap">'
            # OUVRIR UNE SESSION SANS SMS. En production `RELAIS_SMS=journal` : le code
            # ne part pas, il s'imprime dans les journaux de l'hébergeur. Ce lien évite
            # d'aller les lire — et servira surtout à faire entrer un vrai artisan le
            # jour de son inscription, sans dépendre d'un SMS qui coûte et peut ne pas
            # arriver.
            '<form method="post" action="/admin/artisan/' + ident_a + '/lien">'
            '<button class="discret" type="submit">Lien de connexion (15 min)</button>'
            "</form>"
            '<form method="post" action="/admin/artisan/' + ident_a + '/motdepasse">'
            '<button class="discret" type="submit">Définir un mot de passe</button>'
            "</form>"
            '<form method="post" action="/admin/artisan/' + ident_a + '/jeton">'
            '<button class="discret" type="submit">Régénérer le jeton porteur</button>'
            "</form></div>")
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
#
# ──────────────────────────────────────────────────────────────────────────────────
# LE SOCLE EST PARTAGÉ AVEC LE SITE VITRINE, et c'est la raison d'être de la coupure.
# Jetons de couleur, polices, reset, et les composants que les DEUX portent (boutons,
# avatar, pastille de logo, bulles de conversation) vivent ici, une seule fois. La
# tentation était de donner sa propre feuille à la vitrine : elle aurait dérivé de
# l'espace artisan au premier changement de teinte, et personne ne l'aurait vu — un
# prospect et un client ne regardent jamais les deux pages côte à côte. C'est la même
# leçon que T17 (« l'écran MONTRE ce que la machine dit, il n'en garde pas une copie »),
# appliquée au style plutôt qu'au texte.
_SOCLE_NELYO = """
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
/* UN LIBELLÉ EST AU-DESSUS DE SON CHAMP, PAR DÉFAUT ET PARTOUT (R103, étendu le 29/10).
   La première version de R103 exigeait que toute règle visant un `label` déclare son
   `display` — ce qui ne dit rien des labels qu'AUCUNE règle ne couvre. L'écran « Mon
   compte » en a fait la démonstration le jour même : ses libellés, sans règle, sont
   repartis en `inline` et se sont placés à côté de leurs champs selon la largeur
   disponible. Le défaut ne vient donc pas d'une règle fautive mais d'une règle ABSENTE,
   et il ne se corrige pas écran par écran. */
label{display:block}
/* ---------- composants portés par l'espace ET la vitrine ---------- */
.btn{border:1px solid var(--line);background:var(--surface);color:var(--ink);
  border-radius:8px;padding:8px 14px;font:600 13px "Instrument Sans",sans-serif;
  cursor:pointer;text-decoration:none;display:inline-block}
.btn:hover{background:var(--surface-2)}
.btn-cu{background:var(--cuivre);border-color:var(--cuivre);color:#fff}
.btn-cu:hover{background:var(--cuivre-deep);border-color:var(--cuivre-deep)}
.btn-ghost-crit{color:var(--crit)}
.eyebrow{font-size:11px;letter-spacing:.08em;text-transform:uppercase;
  color:var(--faint);font-weight:600}
.avatar{width:34px;height:34px;border-radius:50%;background:var(--cuivre-soft);
  color:var(--cuivre);display:grid;place-items:center;font-weight:600;font-size:13px;
  flex:0 0 34px}
.logo-mark{width:32px;height:32px;border-radius:9px;background:var(--cuivre);
  display:grid;place-items:center;flex:0 0 32px}
.logo-mark svg{width:18px;height:18px}
.bulle{max-width:520px;padding:8px 13px;border-radius:12px;font-size:13px;
  line-height:1.45}
.b-ia{background:var(--marine-soft);color:var(--ink);border-top-left-radius:3px;
  align-self:flex-start}
.b-cl{background:var(--surface);border:1px solid var(--line);
  border-top-right-radius:3px;align-self:flex-end}
.bulle .who{display:block;font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;
  color:var(--faint);margin-bottom:2px;font-weight:600}
"""

# L'espace artisan : tout ce qui n'a de sens qu'une fois connecté.
_STYLE_NELYO = _SOCLE_NELYO + """
.app{display:flex;min-height:100vh}
/* ---------- barre latérale ---------- */
.side{width:228px;flex:0 0 228px;background:var(--sidebar);color:var(--sidebar-ink);
  display:flex;flex-direction:column;position:sticky;top:0;height:100vh}
.logo{display:flex;align-items:center;gap:10px;padding:22px 20px 18px;color:#fff;
  text-decoration:none}
.logo b{font-family:"Bricolage Grotesque";font-size:19px;font-weight:700;
  letter-spacing:.2px}
.logo small{display:block;font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;
  opacity:.65;font-weight:500}
/* SCOPÉ à la barre latérale, exprès (R100) : une règle `nav{…}` nue matchait AUSSI la
   <nav class="mobilebar"> du bas d'écran — qui héritait de flex-direction:column et
   s'empilait verticalement sur 270 px de haut, sur mobile, c'est-à-dire sur l'appareil
   normal de l'artisan. La règle du média query redéclare display et position, mais pas
   flex-direction : ce qui n'est pas redéclaré FUIT. */
.side nav{padding:6px 12px;display:flex;flex-direction:column;gap:2px}
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
.side .avatar{background:rgba(255,255,255,.12);color:#fff}
.artisan b{color:#fff;font-size:13.5px;display:block}
.artisan span{font-size:11.5px;opacity:.65}
/* `.side-lien` et non `.side-foot a` : la couleur d'un lien ne dépend pas de son
   conteneur (R101), et un bouton posé dans ce pied garderait la sienne. */
.side-lien{display:block;margin-top:10px;color:var(--sidebar-ink);font-size:12px;
  font-weight:500;text-decoration:none}
.side-lien:hover{color:#fff;text-decoration:underline}
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
.chip{display:inline-flex;align-items:center;border:1px solid var(--line);
  background:var(--surface-2);border-radius:99px;padding:4px 11px;font-size:12.5px;
  font-weight:500}
.chip.x{border-style:dashed;color:var(--muted)}
.grid{display:grid;gap:16px}
.g4{grid-template-columns:repeat(4,1fr)}
.g3{grid-template-columns:repeat(3,1fr)}
.g2{grid-template-columns:repeat(2,1fr)}
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
table.calls{width:100%;border-collapse:collapse;font-size:13.5px;
  table-layout:fixed;min-width:760px}
.calls td{overflow-wrap:anywhere}
/* La ligne de repli n'a ni bordure ni rembourrage tant qu'elle est fermée : elle ne
   doit pas peser une ligne de plus sous chaque appel. */
.calls tr.depli>td{padding:0;border-bottom:1px solid var(--line)}
.calls tr.ligne>td{border-bottom:0}
.calls details.appel>summary{list-style:none;cursor:pointer;color:var(--faint);
  font-size:11.5px;padding:4px 14px 8px;display:block}
.calls details.appel>summary::-webkit-details-marker{display:none}
.calls details.appel>summary:hover{color:var(--ink)}
.calls th{font-size:11px;letter-spacing:.07em;text-transform:uppercase;
  color:var(--faint);text-align:left;padding:11px 14px;
  border-bottom:1px solid var(--line);font-weight:600}
.calls td{padding:12px 14px;border-bottom:1px solid var(--line);vertical-align:middle}
.calls tr:last-child td{border-bottom:0}
.caller b{display:block}
.caller span{color:var(--faint);font-size:12px}
.transcript{background:var(--surface-2);border-top:1px dashed var(--line);
  padding:16px 18px;display:flex;flex-direction:column;gap:10px}
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
.evt form label{display:block;margin:0;font-size:10.5px}
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
/* `display` EXPLICITE (R103) : cette règle s'appuyait sur `details.horaire label`,
   qui ne la couvre pas — les libellés se plaçaient donc à CÔTÉ de leur champ, ou
   au-dessus, selon la place restante. Un libellé ne se repère pas à la largeur. */
.ajout label{display:block;font-size:12px;color:var(--muted);margin:0 0 3px}
.ajout .large{grid-column:span 2}
/* ---------- mini-calendrier du mois (maquette v5) ---------- */
.agenda-wrap{display:grid;grid-template-columns:276px 1fr;gap:14px;align-items:start}
.minical{background:var(--surface);border:1px solid var(--line);
  border-radius:var(--r);box-shadow:var(--shadow);padding:14px;position:sticky;top:14px}
.mc-head{display:flex;align-items:center;justify-content:space-between;
  margin-bottom:10px}
.mc-head b{font-family:"Bricolage Grotesque","Instrument Sans",sans-serif;
  font-size:15px;text-transform:capitalize}
.mc-btn{border:1px solid var(--line);background:var(--surface);color:var(--muted);
  border-radius:8px;width:28px;height:28px;font-size:11px;line-height:26px;
  text-align:center;text-decoration:none;display:inline-block}
.mc-btn:hover{border-color:var(--marine);color:var(--marine)}
.mc-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:2px;text-align:center}
.mc-grid .wd{font-size:10.5px;font-weight:600;color:var(--faint);padding:4px 0;
  letter-spacing:.04em}
/* `.mc-d` est une CLASSE, jamais `.mc-grid a` : la couleur d'un lien ne dépend pas de
   son conteneur (R101), et un bouton posé ici garderait la sienne. */
.mc-d{position:relative;color:var(--ink);text-decoration:none;
  font:500 12.5px/34px "Instrument Sans",sans-serif;font-variant-numeric:tabular-nums;
  height:34px;border-radius:8px;display:block}
.mc-d:hover{background:var(--surface-2)}
.mc-d.out{color:var(--faint);opacity:.55}
.mc-d.today{box-shadow:inset 0 0 0 1.5px var(--cuivre)}
.mc-d.sel{background:var(--marine);color:#fff}
.mc-d .dot{position:absolute;left:50%;transform:translateX(-50%);bottom:4px;width:4px;
  height:4px;border-radius:50%;background:var(--cuivre)}
.mc-d.sel .dot{background:#fff}
.mc-foot{margin-top:12px;font-size:11.5px;color:var(--faint);display:flex;gap:6px;
  align-items:center;flex-wrap:wrap}
.mc-foot .dot{width:5px;height:5px;border-radius:50%;background:var(--cuivre);
  display:inline-block}
.mc-foot .ring{width:11px;height:11px;border-radius:4px;
  box-shadow:inset 0 0 0 1.5px var(--cuivre);display:inline-block;margin-left:10px}
@media (max-width:940px){
  .week{grid-template-columns:repeat(2,1fr)}
  /* Empilé, et le calendrier n'est plus collant : un bloc sticky de 300 px de haut
     mangerait l'écran d'un téléphone pendant qu'on fait défiler la semaine. */
  .agenda-wrap{grid-template-columns:1fr}
  .minical{position:static;max-width:340px}
}
@media (max-width:520px){.week{grid-template-columns:1fr}}
.numline{display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.numline .n{font-family:"Bricolage Grotesque";font-size:22px;font-weight:700;
  letter-spacing:.5px}
.kv{display:grid;grid-template-columns:1fr auto;gap:8px 16px;font-size:13.5px}
.kv dt{color:var(--muted)}
.kv dd{margin:0;font-weight:600;text-align:right;font-variant-numeric:tabular-nums}
.chips{display:flex;gap:8px;flex-wrap:wrap}
.dit{background:var(--surface-2);border:1px solid var(--line);border-radius:8px;
  padding:13px 15px;font-size:13.5px;line-height:1.55;font-style:italic;
  color:var(--muted);margin:0 0 10px}
.dit b{font-style:normal;color:var(--ink);display:block;font-size:11px;
  letter-spacing:.06em;text-transform:uppercase;margin-bottom:5px;font-weight:600}
.note{color:var(--muted);font-size:12.5px;margin:14px 0 0}
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
  .calls{min-width:520px}
  /* Commune (5) et Durée (7). Les rangs ont bougé le 29/10 quand « Canal » est
     passé en première colonne : masquer par NUMÉRO oblige à relire la liste des
     en-têtes à chaque changement, et c'est exactement ce qu'on vient de faire. */
  .calls th:nth-child(5),.calls td:nth-child(5),
  .calls th:nth-child(7),.calls td:nth-child(7){display:none}
  .mobilebar{display:flex;position:fixed;bottom:0;left:0;right:0;
    background:var(--surface);border-top:1px solid var(--line);z-index:20;
    justify-content:space-around;
    padding:6px 4px calc(6px + env(safe-area-inset-bottom,0px))}
  /* `.onglet` et non `a` : la couleur d'un lien ne doit pas dépendre du bloc où il est
     posé (R101). Le jour où un `.btn` entre dans cette barre, il garderait la sienne. */
  .mobilebar .onglet{border:0;background:none;color:var(--faint);
    font:500 10px "Instrument Sans";display:flex;flex-direction:column;
    align-items:center;gap:3px;padding:4px 8px;text-decoration:none}
  .mobilebar .onglet.on{color:var(--cuivre)}
  .mobilebar svg{width:19px;height:19px}
}
@media (max-width:520px){.g4,.g3{grid-template-columns:1fr}}
"""

# Les icônes de la navigation, reprises de la maquette. En SVG INLINE : ce n'est pas une
# ressource externe, donc rien à charger et rien à fuiter.
_ICONES = {
    "accueil": '<path d="M3 11 12 4l9 7"/><path d="M5 10v10h14V10"/>',
    "demandes": ('<path d="M5 4h4l2 5-2.5 1.5a12 12 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16'
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
    ("demandes", "Demandes", "/app/demandes"),
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
        '<a class="onglet{}" href="{}">{}{}</a>'.format(
            " on" if cle == vue else "", href, _svg(cle, 19),
            escape("Accueil" if cle == "accueil" else libelle.split()[0]))
        for cle, libelle, href in _NAV)

    ini = _initiales(entreprise or prenom)
    pied_lateral = (
        '<div class="side-foot"><div class="artisan">'
        f'<span class="avatar">{escape(ini)}</span>'
        f"<div><b>{escape(entreprise or '—')}</b>"
        f"<span>{escape(prenom)}{' · ' + escape(commune) if commune else ''}</span>"
        "</div></div>"
        # « Mon compte » n'a PAS d'entrée de navigation : la maquette v5 en a six, et une
        # septième pour un écran qu'on visite deux fois par an déséquilibrerait la barre.
        # Il vit ici, sous le nom de l'artisan — là où l'œil cherche déjà son propre nom.
        + ("" if vue_admin else
           '<a class="side-lien" href="/app/compte">Mon compte</a>'
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
        + f"<div><b>{escape(produit)}</b><small>Vos RDV, même sur chantier</small></div></a>"
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
# CE QUE CHAQUE CANAL VEUT DIRE à l'écran. Vocabulaire fermé, aligné sur `depot.CANAUX`.
# Un canal inconnu s'affiche tel quel plutôt que d'être masqué : mieux vaut un libellé
# brut qu'une demande escamotée (même règle que pour les catégories).
_CANAUX = {
    "telephone":  ("Appel", "p-marine"),
    "formulaire": ("Formulaire", "p-ok"),
}

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
            "<p>Tout est à jour. Les demandes reçues restent consultables dans "
            '<a href="/app/demandes">Demandes</a>.</p></div></div>')

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
                 commune: str = "", canaux: list[tuple] = (),
                 canal: str = "") -> str:
    """« Demandes » : tout ce qui est entré, par quelque canal que ce soit.

    La maquette met le transcript dans un panneau qui s'ouvre sous la ligne cliquée.
    Ici c'est un `<details>` natif : même geste, même rendu, et ça marche sans script.

    Les filtres sont des LIENS (un GET par catégorie). Plus lent qu'un filtre en JS,
    mais lisible sans script, compatible avec le bouton « précédent », et partageable
    par son URL — sur quelques dizaines de lignes, l'échange est franchement favorable.
    """
    enveloppe = lambda corps: _page_nelyo(  # noqa: E731
        produit, "demandes", corps, entreprise=entreprise, prenom=prenom,
        commune=commune, a_valider=a_valider, vue_admin=vue_admin)

    barre = ""
    if filtres:
        def _lien(**params):
            """Un lien de filtre qui GARDE l'autre filtre. Deux barres qui s'annulent
            l'une l'autre sont une façon sûre de faire croire qu'une demande a
            disparu."""
            garde = {k: v for k, v in {"categorie": categorie, "canal": canal,
                                       **params}.items() if v}
            return "/app/demandes" + ("?" + urlencode(garde) if garde else "")

        barre = '<div class="filters">' + "".join(
            '<a class="fbtn{}" href="{}">{} <b>{}</b></a>'.format(
                " on" if (c or "") == categorie else "",
                _lien(categorie=c or ""), escape(nom), n)
            for c, nom, n in filtres) + "</div>"
    if canaux:
        barre += '<div class="filters">' + "".join(
            '<a class="fbtn{}" href="{}">{} <b>{}</b></a>'.format(
                " on" if (c or "") == canal else "", _lien(canal=c or ""),
                escape(nom), n)
            for c, nom, n in canaux) + "</div>"

    if not appels:
        return enveloppe(
            barre + '<div class="card"><div class="vide">'
            '<p class="gros">Aucune demande ici.</p>'
            "<p>Dès qu&#x27;un client appellera — ou remplira votre formulaire — "
            "vous verrez ce qu&#x27;il a demandé, ce que l&#x27;assistant a répondu, "
            "et vous pourrez le rappeler d&#x27;un tap.</p></div></div>")

    lignes = []
    for a in appels:
        libelle, teinte = _CATEGORIES.get(a["categorie"], (a["categorie"], "p-mut"))
        tel = (escape(a["telephone_lisible"]) if a["telephone"] else "—")
        canal_nom, canal_teinte = _CANAUX.get(a.get("canal") or "telephone",
                                              ("Appel", "p-mut"))
        # L'URGENCE EST DITE, même quand le score ne la porte pas. Le barème est bâti
        # autour d'un créneau réservé (`scoring._score`) : une demande venue du
        # formulaire ne peut pas l'atteindre, et une urgence réelle y plafonne à 2.
        # `est_urgent` est la MÊME fonction que celle du score — elle a été extraite
        # le 21/09 pour ça, importée dans l'API le même jour, et jamais utilisée.
        urgence = ('<span class="pill p-crit" style="margin-left:5px">Urgence</span>'
                   if a.get("urgent") else "")
        rang = (
            '<tr class="ligne">'
            '<td><span class="pill {}">{}</span></td>'
            '<td class="num">{}</td>'
            '<td class="caller"><b>{}</b><span>{}</span></td>'
            "<td>{}</td><td>{}</td>"
            '<td><span class="score {}" style="width:30px;height:30px">{}</span></td>'
            '<td class="num">{}</td>'
            '<td><span class="pill {}">{}</span>{}</td></tr>'
        ).format(canal_teinte, escape(canal_nom),
                 escape(a["heure"]), escape(a["client"]), tel, escape(a["motif"]),
                 escape(a["commune"]), _classe_score(a["score"]), a["score"],
                 escape(a["duree"]), teinte, escape(libelle), urgence)

        detail = ""
        if a["transcript"]:
            bulles = "".join(
                '<div class="bulle {}"><span class="who">{}</span>{}</div>'.format(
                    "b-ia" if qui == "agent" else "b-cl",
                    "Assistant " + escape(produit) if qui == "agent" else "Client",
                    escape(texte))
                for qui, texte in a["transcript"])
            if a["telephone"]:
                rappel = ('<div><a class="btn btn-cu" href="tel:'
                          + escape(a["telephone"]) + '">Rappeler '
                          + escape(a["telephone_lisible"]) + "</a></div>")
            else:
                rappel = ('<div><span class="pill p-mut">Aucun numéro recueilli — '
                          "ce client n&#x27;est pas rappelable</span></div>")
            # LE TRANSCRIPT OCCUPE TOUTE LA LARGEUR, dans une ligne qui enjambe les sept
            # colonnes. C'est ce qui permet de n'avoir QU'UN tableau : chaque appel
            # devient un `<tbody>` de deux lignes, et les colonnes restent celles du
            # tableau — donc alignées, quoi que contienne une cellule.
            detail = (
                '<tr class="depli"><td colspan="8">'
                '<details class="appel"><summary>Voir la conversation ({} tours)'
                "</summary>"
                '<div class="transcript"><span class="eyebrow">Transcript — {} · {}'
                "</span>{}{}</div></details></td></tr>"
            ).format(len(a["transcript"]), escape(a["client"]), escape(a["heure"]),
                     bulles, rappel)
        lignes.append(f"<tbody>{rang}{detail}</tbody>")

    # LES LARGEURS SONT DÉCLARÉES, et le tableau est en `fixed` : sans ça, chaque colonne
    # se dimensionne sur son contenu le plus long, et un motif bavard décale tout le
    # reste. C'est même ce qui avait cassé l'alignement — il y avait UN TABLEAU PAR
    # LIGNE, chacun calculant ses largeurs dans son coin.
    colonnes = ("<colgroup>"
                '<col style="width:92px"><col style="width:66px">'
                '<col style="width:20%"><col style="width:22%">'
                '<col style="width:14%"><col style="width:64px">'
                '<col style="width:68px"><col style="width:16%"></colgroup>')
    return enveloppe(
        barre + '<div class="card" style="overflow-x:auto">'
        + '<table class="calls">' + colonnes
        + "<thead><tr><th>Canal</th><th>Reçue</th><th>Prospect</th><th>Motif</th>"
        + "<th>Commune</th><th>Score</th><th>Durée</th><th>Issue</th></tr></thead>"
        + "".join(lignes) + "</table></div>")


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


def stats(produit: str, prenom: str, entreprise: str, ca_eur: int, gagnes: int,
          gagnes_sans_montant: int, perdus: int, tuiles: list[tuple],
          a_declarer: list[dict], declares: list[dict], a_valider: int = 0,
          commune: str = "", vue_admin: str = "",
          fenetre: dict | None = None) -> str:
    """« Statistiques » : ce que Nelyo rapporte — en déclarations de l'artisan, jamais
    en inventions.

    L'écart fermé ici datait du 22/09 : la maquette fait du « CA récupéré » la métrique
    reine, et le produit s'arrêtait au rendez-vous validé — afficher un chiffre
    d'affaires aurait été l'inventer. La règle de cet écran est donc la même que celle
    de l'écran « Assistant IA » (T17) : **rien n'est affirmé qui ne soit su.**

      1. le CA affiché est la SOMME DES DÉCLARATIONS de l'artisan (« chantier gagné,
         N euros », migration 015) — et la page le dit en toutes lettres sous le
         chiffre, pour que personne ne croie à un calcul savant ;
      2. un chantier gagné SANS montant saisi compte pour zéro euro et la page dit
         combien sont dans ce cas — sinon le CA baisse en silence à chaque artisan
         pressé ;
      3. le taux de transformation n'est calculé QUE sur les RDV déclarés : des RDV
         passés sans déclaration ne sont ni des gagnés ni des perdus, ce sont des
         inconnus, et ils sont affichés comme tels (c'est la liste « à déclarer ») ;
      4. en mode support (vue_admin), les formulaires de déclaration n'apparaissent
         pas : la lecture seule est STRUCTURELLE côté serveur (T14), l'écran ne promet
         donc pas un geste que le POST refuserait.

    LA PÉRIODE est arrivée le 29/10 (maquette v5). Quatre raccourcis et une plage libre,
    et **le libellé exact de la fenêtre est répété sur la carte du CA** : c'est le
    chiffre qu'on retient, et celui qu'on cite de mémoire trois jours plus tard. Un
    total sans sa période est un total faux dès qu'on change de période.

    La plage libre est un formulaire GET à deux `input type="date"` — la maquette
    ouvrait un calendrier en JavaScript, l'espace artisan n'en a pas (écart assumé n°2).
    Le sélecteur natif du navigateur fait le même travail, y compris sur mobile, et
    chaque période reste une URL qu'on peut mettre en favori ou envoyer à son comptable.
    """
    fen = fenetre or {"du": "", "au": "", "preset": "tout",
                      "libelle": "depuis le début", "erreur": ""}
    corps = []

    # ---- la période : quatre préréglages, puis la plage libre ----
    raccourcis = "".join(
        '<a class="fbtn{}" href="/app/stats?preset={}">{}</a>'.format(
            " on" if fen.get("preset") == cle else "", cle, escape(libelle))
        for cle, libelle in (("mois", "Ce mois"), ("3mois", "3 mois"),
                             ("12mois", "12 mois"), ("tout", "Tout")))
    champ = ('min-height:34px;border:1px solid var(--line);border-radius:8px;'
             'padding:0 9px;background:var(--surface);color:var(--ink);'
             'font:500 12.5px "Instrument Sans",sans-serif')
    # « Tout » est borné par des sentinelles (01/01/2000 → 31/12/2100). Les recopier
    # dans les champs donnerait l'air d'une plage que quelqu'un aurait demandée, et
    # un clic sur « Appliquer » la figerait pour de bon. Vu au rendu.
    val_du, val_au = (("", "") if fen.get("preset") == "tout"
                      else (fen.get("du", ""), fen.get("au", "")))
    corps.append(
        '<div class="filters">' + raccourcis
        + '<form method="get" action="/app/stats" '
          'style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">'
          '<label for="du" style="font-size:12.5px;color:var(--muted)">du</label>'
          f'<input id="du" type="date" name="du" value="{escape(val_du)}" '
          f'style="{champ}">'
          '<label for="au" style="font-size:12.5px;color:var(--muted)">au</label>'
          f'<input id="au" type="date" name="au" value="{escape(val_au)}" '
          f'style="{champ}">'
          '<button class="btn" type="submit">Appliquer</button></form></div>')
    if fen.get("erreur"):
        corps.append('<div class="card aveu"><div class="card-b">'
                     f'<p style="margin:0">{escape(fen["erreur"])}</p></div></div>')

    # ---- la métrique reine, et d'où elle sort ----
    quali = (f"{gagnes} chantier{'s' if gagnes > 1 else ''} déclaré"
             f"{'s' if gagnes > 1 else ''} gagné{'s' if gagnes > 1 else ''}"
             + (f", dont {gagnes_sans_montant} sans montant saisi"
                if gagnes_sans_montant else ""))
    corps.append(
        '<div class="card" style="background:var(--marine-deep);border:0">'
        '<div class="card-b" style="color:#fff">'
        '<span style="font-size:12px;letter-spacing:.04em;text-transform:uppercase;'
        'opacity:.75">CA récupéré par ' + escape(produit) + " — "
        + escape(fen.get("libelle") or "depuis le début") + "</span>"
        f'<div class="num" style="font-size:34px;font-weight:700;margin:2px 0">'
        f"{_eur(ca_eur)}</div>"
        '<p style="margin:0;font-size:12.5px;opacity:.75">'
        f"Somme des montants que <b>vous</b> avez déclarés ({escape(quali)}). "
        + escape(produit) + " n&#x27;invente jamais ce chiffre.</p>"
        "</div></div>")

    if tuiles:
        corps.append('<div class="grid g4">' + "".join(
            f'<div class="card stat"><div class="card-b">'
            f'<span class="num">{n}</span><span class="lbl">{escape(libelle)}</span>'
            "</div></div>"
            for libelle, n in tuiles) + "</div>")

    # ---- la saisie qui fabrique le chiffre ----
    if a_declarer:
        lignes = []
        for r in a_declarer:
            ident = escape(r["id"])
            if vue_admin:
                acte = ('<span class="pill p-mut">Déclaration réservée à '
                        "l&#x27;artisan</span>")
            else:
                acte = (
                    '<div class="valid-act">'
                    f'<form method="post" action="/app/{ident}/issue">'
                    '<input type="hidden" name="issue" value="gagne">'
                    '<input name="montant" inputmode="numeric" autocomplete="off" '
                    'placeholder="Montant € (optionnel)" '
                    'style="min-height:38px;border:1px solid var(--line);'
                    'border-radius:8px;padding:0 10px;background:var(--surface-2);'
                    'color:var(--ink);width:170px;margin-right:6px">'
                    '<button class="btn btn-cu" type="submit">Chantier gagné</button>'
                    "</form>"
                    f'<form method="post" action="/app/{ident}/issue">'
                    '<input type="hidden" name="issue" value="perdu">'
                    '<button class="btn" type="submit">Sans suite</button></form>'
                    "</div>")
            lignes.append(
                '<div class="valid-item">'
                f'<div class="valid-info"><b>{escape(r["client"])}</b>'
                f'<div class="d">{escape(r["motif"])}</div></div>'
                f'<div class="valid-slot">{escape(r["creneau"])}'
                "<div class=\"d\">RDV validé — que s&#x27;est-il passé ensuite ?</div>"
                f"</div>{acte}</div>")
        corps.append(
            '<div class="card" style="border-left:3px solid var(--cuivre)">'
            '<div class="card-h"><h3>Chantier gagné ?</h3>'
            f'<span class="pill p-warn">{len(a_declarer)} RDV passé'
            f"{'s' if len(a_declarer) > 1 else ''} sans déclaration</span>"
            # HORS PÉRIODE, et il faut le dire : sans cette mention, la liste
            # contredirait le total juste au-dessus dès qu'on resserre la fenêtre, et
            # on chercherait l'erreur dans les chiffres au lieu de la lire ici.
            '<span class="sub" style="margin-left:auto">C&#x27;est cette saisie qui '
            "fait le chiffre ci-dessus — <b>toutes périodes confondues</b></span>"
            "</div>" + "".join(lignes) + "</div>")
    else:
        corps.append(
            '<div class="card"><div class="vide">'
            '<p class="gros">Rien à déclarer.</p>'
            "<p>Quand un RDV validé sera passé, il apparaîtra ici pour que vous "
            "disiez s&#x27;il est devenu un chantier.</p></div></div>")

    # ---- transformation : seulement sur ce qui est déclaré ----
    declares_n = gagnes + perdus
    if declares_n:
        taux = round(100 * gagnes / declares_n)
        corps.append(
            '<div class="card"><div class="card-b">'
            f'<span class="num" style="font-size:26px;font-weight:700">{taux} %</span>'
            '<span class="lbl" style="color:var(--muted);font-size:12.5px;'
            'display:block">Transformation RDV → chantier — calculée sur les '
            f"{declares_n} RDV déclarés, pas sur les inconnus</span></div></div>")

    if declares:
        items = "".join(
            '<li><time>' + escape(d["quand"]) + "</time>"
            '<span class="dot" style="background:var(--'
            + ("ok" if d["issue"] == "gagne" else "faint") + ')"></span>'
            f'<span><b>{escape(d["client"])}</b> — '
            + ("chantier gagné" + (f" · {_eur(d['montant'])}" if d["montant"] else
                                   " · montant non saisi")
               if d["issue"] == "gagne" else "sans suite")
            + "</span></li>"
            for d in declares)
        corps.append(
            '<div class="card"><div class="card-h"><h3>Déjà déclarés</h3></div>'
            f'<ul class="feed">{items}</ul></div>')

    return _page_nelyo(produit, "stats", "".join(corps), entreprise=entreprise,
                       prenom=prenom, commune=commune, a_valider=a_valider,
                       vue_admin=vue_admin)


def _eur(montant: int) -> str:
    """1480 → « 1 480 € ». L'espace fine insécable des maquettes est un espace
    insécable simple ici : même rendu, et un copier-coller qui survit."""
    return f"{montant:,}".replace(",", " ") + " €"


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


_JOURS_COURTS = ("L", "M", "M", "J", "V", "S", "D")


def _minical(cal: dict) -> str:
    """Le mini-calendrier mensuel de la maquette v5, SANS JavaScript.

    Chaque jour est un `<a>` vers `?semaine=<ce jour>` : cliquer une date recale la
    semaine, l'état vit dans l'URL, le bouton « précédent » fonctionne et un agenda
    mis en favori rouvre là où on l'avait laissé. La maquette faisait la même chose
    avec un `onclick` et un état en mémoire.

    Les flèches feuillettent les MOIS sans déplacer la semaine, et emportent
    `semaine=` avec elles — sinon regarder décembre ramènerait l'agenda à aujourd'hui,
    et on perdrait ce qu'on était en train de regarder.

    Quatre états par case, qui ne s'excluent pas : hors du mois affiché, aujourd'hui,
    dans la semaine ouverte, et « occupé » (une pastille). `.mc-d` est une CLASSE et
    non un sélecteur `… a` — R101 : la couleur d'un lien ne dépend jamais de son bloc.
    """
    entetes = "".join(f'<span class="wd">{j}</span>' for j in _JOURS_COURTS)
    cases = []
    for c in cal["cases"]:
        classes = "mc-d"
        classes += " out" if c["hors_mois"] else ""
        classes += " today" if c["aujourdhui"] else ""
        classes += " sel" if c["dans_semaine"] else ""
        titre = c["iso"] + (" · occupé" if c["occupe"] else "")
        cases.append(
            f'<a class="{classes}" href="/app/agenda?semaine={escape(c["iso"])}'
            f'" title="{escape(titre)}" aria-label="{escape(titre)}">{c["jour"]}'
            + ('<span class="dot"></span>' if c["occupe"] else "")
            + "</a>")
    lien_mois = "/app/agenda?semaine=" + escape(cal["semaine"]) + "&amp;mois="
    return (
        '<div class="minical"><div class="mc-head">'
        f'<a class="mc-btn" href="{lien_mois}{escape(cal["precedent"])}" '
        'aria-label="Mois précédent">◀</a>'
        f'<b>{escape(cal["titre"])}</b>'
        f'<a class="mc-btn" href="{lien_mois}{escape(cal["suivant"])}" '
        'aria-label="Mois suivant">▶</a></div>'
        f'<div class="mc-grid">{entetes}{"".join(cases)}</div>'
        '<div class="mc-foot"><span class="dot"></span> journée occupée'
        '<span class="ring"></span> aujourd&#x27;hui</div></div>')


def agenda(produit: str, prenom: str, entreprise: str, jours: list[dict],
           semaine: str, precedente: str, suivante: str, a_valider: int = 0,
           commune: str = "", vue_admin: str = "", erreur: str = "",
           calendrier: dict | None = None, aujourdhui: str = "") -> str:
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
        # « Aujourd'hui » de la maquette : sans lui, revenir de décembre demande de
        # compter les semaines en arrière.
        + (f'<a class="fbtn" href="/app/agenda?semaine={escape(aujourdhui)}">'
           "Aujourd&#x27;hui</a>" if aujourdhui else "")
        + '<span style="margin-left:auto" class="legend">'
        '<span><span class="sw" style="background:var(--marine-soft)"></span>'
        "RDV confirmé</span>"
        '<span><span class="sw" style="background:var(--cuivre-soft);'
        'border:1px dashed var(--cuivre)"></span>En attente de validation</span>'
        '<span><span class="sw" style="background:var(--surface-2);'
        'border:1px solid var(--line)"></span>Ajouté par vous</span>'
        "</span></div>"
        + alerte
        # Le mini-calendrier et la semaine côte à côte (`.agenda-wrap`), empilés sur
        # mobile. Le calendrier d'ABORD dans le flux : sur un téléphone, c'est par lui
        # qu'on choisit le jour, et le faire passer après six colonnes de semaine
        # obligerait à défiler pour naviguer.
        + ('<div class="agenda-wrap">' + _minical(calendrier)
           + f'<div class="week">{"".join(cases)}</div></div>'
           if calendrier else f'<div class="week">{"".join(cases)}</div>')
        + formulaire)
    return _page_nelyo(produit, "agenda", corps, entreprise=entreprise, prenom=prenom,
                       commune=commune, a_valider=a_valider, vue_admin=vue_admin,
                       titre="Agenda")


# Ce que l'artisan lit au-dessus de chaque phrase de son assistant. Les clés viennent
# de la config (`accueil.promesse_rappel`) ; une clé inconnue retombe sur sa forme brute
# — mieux vaut un libellé laid qu'une promesse invisible.
_QUAND = {
    "accueil": "À l'ouverture de chaque appel",
    "ouvree": "Quand il promet un rappel, en journée",
    "soir_weekend": "Quand il promet un rappel, le soir ou le week-end",
}


def assistant(produit: str, prenom: str, entreprise: str, bloc: dict,
              a_valider: int = 0, commune: str = "", vue_admin: str = "") -> str:
    """« Assistant IA » : ce que la machine SAIT et ce qu'elle DIT, pour cet artisan.

    Geoffrey, le 24/09 : « je comprends pas pourquoi l'onglet assistant IA ne peut pas
    déjà exister, même avec les données factices de Dupont Chauffage ». Il avait raison,
    et ma justification confondait deux choses très différentes : MODIFIER la config
    (vrai travail — un champ mal rempli casse un appel en cours) et la MONTRER, qui est
    disponible depuis toujours puisque l'agent la lit à chaque appel.

    C'est même sans doute l'écran le plus rassurant du produit. Quelqu'un qui paie une
    machine pour décrocher à sa place veut savoir exactement ce qu'elle raconte à ses
    clients — et ici, les phrases affichées sont LES phrases, pas des exemples :
    `formule_accueil` est la fonction qu'appelle le moteur, les consignes de sécurité et
    les tarifs sont les chaînes que l'agent prononce.

    DEUX CHOSES SONT DITES ABSENTES, plutôt que devinées. La maquette affiche « Renvoi
    d'appel actif — vérifié il y a 2 j » : Nelyo ne teste jamais ce renvoi, il constate
    seulement les appels qui arrivent. Et les boutons « Modifier » n'y sont pas encore —
    les afficher sans qu'ils fassent quelque chose serait promettre ce qui n'existe pas.
    """
    def chips(items, barres=()):
        return '<div class="chips">' + "".join(
            f'<span class="chip">{escape(str(i))}</span>' for i in items
        ) + "".join(
            f'<span class="chip x">{escape(str(i))}</span>' for i in barres
        ) + "</div>"

    def kv(paires):
        return '<dl class="kv">' + "".join(
            f"<dt>{escape(k)}</dt><dd>{escape(str(v))}</dd>" for k, v in paires
        ) + "</dl>"

    def carte(titre, corps, sous=""):
        return ('<div class="card"><div class="card-h">'
                f"<h3>{escape(titre)}</h3>"
                + (f'<span class="sub" style="margin-left:auto">{escape(sous)}</span>'
                   if sous else "")
                + f'</div><div class="card-b">{corps}</div></div>')

    etat = bloc["etat_abonnement"]
    teinte = "p-ok" if etat == "actif" else ("p-warn" if etat == "essai" else "p-crit")
    entete = (
        '<div class="card"><div class="card-b numline">'
        '<div><div class="eyebrow">Votre numéro ' + escape(produit) + "</div>"
        f'<div class="n num">{escape(bloc["numero_relais"])}</div></div>'
        f'<span class="pill {teinte}">Assistant {escape(etat)}</span>'
        '<span class="pill p-marine">Annonce IA en ouverture (AI Act)</span>'
        '<span class="pill p-mut">Renvoi d&#x27;appel : non vérifié</span>'
        "</div></div>")

    dits = "".join(
        f'<p class="dit"><b>{escape(_QUAND.get(cle, cle.replace("_", " ")))}</b>'
        f"{escape(texte)}</p>"
        for cle, texte in bloc["dit"])

    return _page_nelyo(
        produit, "ia",
        entete
        + carte("Ce que votre assistant dit", dits,
                "mot pour mot, ce que vos clients entendent")
        + '<div class="grid g2">'
        + carte("Prestations", chips(bloc["couvertes"], bloc["refusees"]),
                f'{len(bloc["couvertes"])} acceptées')
        + carte("Zone d'intervention",
                chips(bloc["communes"], [f"{c} (limitrophe)"
                                         for c in bloc["limitrophes"]]),
                "les limitrophes sont acceptées au cas par cas")
        + "</div>"
        + '<div class="grid g2">'
        + carte("Rendez-vous", kv(bloc["agenda"]))
        + carte("Validation et SMS", kv(bloc["validation"]))
        + "</div>"
        + carte("Tarifs que l'assistant peut annoncer",
                "".join(f'<p class="dit">{escape(p)}</p>' for p in bloc["tarifs"])
                or '<p class="note">Aucun tarif communicable : l&#x27;assistant '
                   "refusera d&#x27;annoncer un prix.</p>")
        + carte("Sécurité",
                "".join(f'<p class="dit">{escape(str(c))}</p>'
                        for c in bloc["consignes"])
                + kv(bloc["securite"]),
                "les seules consignes que l'assistant a le droit de donner")
        + '<p class="note">Ces réglages se modifient pour l&#x27;instant depuis '
          "l&#x27;administration. L&#x27;édition par vous-même viendra, avec les "
          "vérifications qui empêchent de casser l&#x27;assistant en plein appel.</p>",
        entreprise=entreprise, prenom=prenom, commune=commune,
        a_valider=a_valider, vue_admin=vue_admin, titre="Assistant IA")


# ══════════════════════════════════════════════ LE SITE VITRINE — la page publique
#
# LA RÉFÉRENCE EST `docs/maquette/nelyo-maquette.html` (`#landing`, maquette v5), et la
# structure en est reprise section par section : nav, hero, bandeau de preuve, démo,
# fonctionnement, ROI sombre, confiance, tarif, FAQ, bandeau final, pied.
#
# CE QUI N'EST PAS REPRIS, ET POURQUOI — c'est la partie importante de cet en-tête.
#
# La maquette porte des PREUVES FABRIQUÉES : trois témoignages signés « Karim M. »,
# « Julien D. », « Sofiane L. », un « ×32 de retour moyen, mesuré en € signés »,
# « 18 750 € récupérés le mois dernier », « +22 RDV récupérés en septembre », un numéro
# de ligne de démonstration et trois extraits audio à écouter. Dans une maquette, ce
# sont des lorem ipsum ; sur la page publique, ce sont des affirmations adressées à un
# artisan qui décide d'acheter. Nelyo n'a aucun client : il n'y a ni témoin, ni moyenne,
# ni enregistrement, ni ligne de démo.
#
# C'est la décision du 22/09 (« aucun chiffre inventé ») appliquée là où elle coûte
# quelque chose. Elle a été prise pour le tableau de bord de l'artisan ; elle vaut
# d'abord ici, parce que le tableau de bord parle à quelqu'un qui a déjà payé et que
# cette page parle à quelqu'un qui n'a pas encore signé. Et la leçon de 2bis vaut
# aussi : « ce qu'on promet doit être tenable, sur TOUS les chemins » — une page de
# vente est un chemin.
#
# Les emplacements sont donc GARDÉS, et remplis de ce qui est vrai :
#
# - les témoignages → « Ce que Nelyo fait, et ce qu'il ne fait pas encore ». Dire à un
#   artisan ce qui n'est pas prêt est un argument, pas un aveu : il a déjà été déçu ;
# - « ×32 mesuré » → le calcul est présenté comme une HYPOTHÈSE qu'il ajuste, et le
#   seul chiffre présenté comme mesuré est celui que T18 rend réel — le CA qu'il aura
#   DÉCLARÉ lui-même ;
# - les extraits audio et la ligne de démo → la vraie première phrase de l'assistant,
#   rendue par `engine.formule_accueil` (T17 : la page MONTRE ce que la machine dit,
#   elle n'en garde pas une copie) ;
# - les canaux « formulaire » et « email » → marqués « bientôt », parce qu'ils n'existent
#   qu'en maquette. Ils étaient annoncés au présent dans la FAQ et dans les puces.
#
# RESTENT DEUX CHOSES QUE LE CODE NE PEUT PAS TRANCHER, signalées dans le journal :
# les mentions légales (il faut une raison sociale, un SIRET, un hébergeur — d'où
# l'absence de liens morts en pied de page plutôt qu'un gabarit à trous), et le fait
# que l'offre suppose une entrée téléphonique française qui n'existe pas encore.
_STYLE_VITRINE = _SOCLE_NELYO + """
/* ---------- barre du haut ---------- */
.l-nav{display:flex;align-items:center;gap:12px;padding:16px 6vw;
  background:var(--surface);border-bottom:1px solid var(--line);position:sticky;top:0;
  z-index:5}
.l-nav b{font-family:"Bricolage Grotesque";font-size:18px}
.l-nav .links{margin-left:auto;display:flex;gap:22px;font-size:13.5px;font-weight:500;
  color:var(--muted);align-items:center}
/* SCOPÉ AUX ANCRES, pas à tous les `a` de la barre. `.l-nav .links a{color:inherit}`
   pèse plus lourd que `.btn-cu{color:#fff}` : le bouton cuivre héritait du gris des
   liens de menu et son libellé devenait illisible sur son propre fond. Même famille
   que R100 — une règle écrite pour un rôle qui en attrape un second. */
.l-nav .links .nav-ancre{color:inherit;text-decoration:none}
.l-nav .links .nav-ancre:hover{color:var(--ink)}
.l-nav .logo-mark{width:30px;height:30px;flex:0 0 30px}
.l-nav .logo-mark svg{width:16px;height:16px}
/* `line-height` et `white-space` explicites : le raccourci `font:` du socle remet la
   hauteur de ligne à `normal`, et dans la barre du haut « Demander un accès » passait
   à la ligne À L'INTÉRIEUR du bouton, en débordant de son fond. Vu au rendu. */
a.btn{text-decoration:none;display:inline-flex;align-items:center;
  justify-content:center;line-height:1.25;white-space:nowrap}
.btn-xl{padding:13px 22px;font-size:15px;border-radius:10px}
html{scroll-behavior:smooth}
.l-sec,.l-dark{scroll-margin-top:72px}
/* ---------- hero ---------- */
.hero{display:grid;grid-template-columns:1.1fr .9fr;gap:48px;align-items:center;
  padding:64px 6vw 56px;max-width:1240px;margin:0 auto}
.hero h1{font-size:clamp(30px,4.2vw,52px);font-weight:800;line-height:1.08;
  margin:14px 0 18px;text-wrap:balance}
.hero h1 em{font-style:normal;color:var(--cuivre)}
.hero .sub{font-size:16.5px;color:var(--muted);max-width:52ch;margin:0 0 26px;
  line-height:1.6}
.l-badge{display:inline-flex;align-items:center;gap:8px;border:1px solid var(--cuivre);
  color:var(--cuivre);border-radius:99px;padding:6px 14px;font-size:11.5px;
  font-weight:700;letter-spacing:.06em;text-transform:uppercase}
.cta-row{display:flex;gap:12px;flex-wrap:wrap}
.checks{display:flex;gap:16px;flex-wrap:wrap;margin-top:14px;font-size:12.5px;
  color:var(--faint)}
.checks span::before{content:"\\2713";color:var(--ok);font-weight:700;margin-right:6px}
.phone{background:var(--surface);border:1px solid var(--line);border-radius:26px;
  box-shadow:var(--shadow);padding:18px 16px 20px;max-width:360px;margin-left:auto;
  position:relative}
.phone .ph-top{display:flex;align-items:center;gap:9px;padding-bottom:12px;
  border-bottom:1px solid var(--line);margin-bottom:12px;font-size:13px}
.phone .ph-top .avatar{width:28px;height:28px;flex:0 0 28px;font-size:11px}
.phone .ph-top .st{margin-left:auto;font-size:11px;color:var(--ok);font-weight:600}
.phone .flux{display:flex;flex-direction:column;gap:9px}
.phone .fin{background:var(--ok-bg);color:var(--ok);align-self:center;font-weight:600;
  font-size:12.5px}
.phone .avis{margin:12px 0 0;font-size:11px;color:var(--faint);text-align:center;
  line-height:1.45}
.ring-badge{position:absolute;top:-14px;left:-14px;background:var(--cuivre);color:#fff;
  font-size:11.5px;font-weight:700;border-radius:99px;padding:6px 12px;
  box-shadow:var(--shadow)}
/* ---------- bandeau de preuve ---------- */
.proof{background:var(--marine-deep);color:#fff}
/* GRILLE et non flex : en `space-between` avec retour à la ligne, la quatrième entrée
   tombait seule sur une deuxième ligne dès que la fenêtre se resserrait un peu — quatre
   colonnes puis deux puis une est le seul découpage qui ne produit jamais d'orphelin. */
.proof .wrap{max-width:1240px;margin:0 auto;padding:30px 6vw;display:grid;
  grid-template-columns:repeat(4,1fr);gap:28px}
.proof .it b{font-family:"Bricolage Grotesque";font-size:30px;font-weight:700;
  display:block}
.proof .it span{font-size:12.5px;opacity:.75}
/* ---------- sections ---------- */
.l-sec{max-width:1240px;margin:0 auto;padding:56px 6vw}
.l-sec h2{font-size:clamp(22px,2.6vw,32px);font-weight:700;margin:0 0 8px;
  text-wrap:balance}
.l-sec .lead{color:var(--muted);margin:0 0 30px;max-width:60ch}
.demo3{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.dcard{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);
  padding:22px;box-shadow:var(--shadow);display:flex;flex-direction:column;gap:12px}
.dcard h3{margin:0;font-size:16px}
.dcard p{margin:0;color:var(--muted);font-size:13.5px;line-height:1.55}
.dcard .dit{background:var(--surface-2);border:1px solid var(--line);border-radius:10px;
  padding:13px 15px;font-size:13.5px;line-height:1.55;font-style:italic;color:var(--ink);
  margin:0}
.dcard ul{margin:0;padding-left:18px;color:var(--muted);font-size:13.5px;
  line-height:1.6}
.dcard .pied{margin-top:auto;font-size:12px;color:var(--faint)}
.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.step{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);
  padding:22px;box-shadow:var(--shadow)}
.step .nbr{width:34px;height:34px;border-radius:50%;background:var(--cuivre-soft);
  color:var(--cuivre);display:grid;place-items:center;
  font:700 15px "Bricolage Grotesque";margin-bottom:12px}
.step h3{margin:0 0 6px;font-size:16px}
.step p{margin:0;color:var(--muted);font-size:13.5px}
.canaux{display:flex;gap:14px;flex-wrap:wrap;margin-top:18px;align-items:center}
.canaux .c{display:flex;align-items:center;gap:9px;background:var(--surface);
  border:1px solid var(--line);border-radius:99px;padding:9px 16px;font-weight:600;
  font-size:13.5px}
.canaux .c.plus-tard{color:var(--faint);border-style:dashed}
/* ---------- le calcul (section sombre) ---------- */
.l-dark{background:var(--marine-deep);color:#fff}
.l-dark h2{color:#fff}
.l-dark .lead{color:rgba(255,255,255,.65)}
.vs{display:grid;grid-template-columns:1fr 1fr;gap:16px;max-width:880px}
.vs-card{border-radius:14px;padding:24px;border:1px solid rgba(255,255,255,.14)}
.vs-card.bad{background:rgba(255,255,255,.04)}
.vs-card.good{background:rgba(192,107,69,.16);border-color:var(--cuivre)}
.vs-card h3{margin:0 0 16px;font-size:15px}
.vs-card dl{margin:0;display:grid;grid-template-columns:1fr auto;gap:10px 14px;
  font-size:13.5px}
.vs-card dt{opacity:.68}
.vs-card dd{margin:0;font-weight:700;text-align:right;font-variant-numeric:tabular-nums;
  white-space:nowrap}
.vs-card .total{border-top:1px solid rgba(255,255,255,.18);margin-top:16px;
  padding-top:13px;display:flex;justify-content:space-between;gap:12px;font-weight:800;
  font-family:"Bricolage Grotesque","Instrument Sans",sans-serif;font-size:16px}
.vs-note{margin:22px 0 0;font-size:13.5px;opacity:.78;max-width:62ch}
.vs-note b{color:#fff}
.hypo{display:inline-block;border:1px dashed rgba(255,255,255,.4);border-radius:99px;
  padding:3px 10px;font-size:11px;letter-spacing:.06em;text-transform:uppercase;
  font-weight:700;opacity:.8;margin-bottom:14px}
/* ---------- ce qui est prêt, ce qui ne l'est pas ---------- */
.franchise{display:grid;grid-template-columns:1fr 1fr;gap:16px;max-width:880px}
.fcard{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);
  padding:22px;box-shadow:var(--shadow)}
.fcard h3{margin:0 0 12px;font-size:15px;display:flex;align-items:center;gap:9px}
.fcard ul{margin:0;padding-left:18px;color:var(--muted);font-size:13.5px;
  line-height:1.65}
.fcard li b{color:var(--ink);font-weight:600}
/* ---------- confiance ---------- */
.trust{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}
.titem{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);
  padding:18px;box-shadow:var(--shadow)}
.titem .ico{font-size:20px}
.titem b{display:block;margin:8px 0 4px;font-size:14px}
.titem p{margin:0;color:var(--muted);font-size:12.5px;line-height:1.5}
/* ---------- tarif ---------- */
.l-price{background:var(--surface);border:1px solid var(--line);border-radius:14px;
  box-shadow:var(--shadow);max-width:430px;margin:0 auto;padding:28px;text-align:center}
.l-price .pp{font-family:"Bricolage Grotesque";font-size:44px;font-weight:800}
.l-price .pp small{font-size:15px;color:var(--muted);font-weight:500}
.l-price .incl{text-align:left;max-width:300px;margin:14px auto 0;padding-left:18px;
  color:var(--muted);font-size:13.5px;line-height:1.7}
.l-price .btn{margin-top:20px;width:100%}
.l-price .fine{font-size:12px;color:var(--faint);margin:10px 0 0}
/* ---------- faq ---------- */
.faq{max-width:760px}
.faq details{background:var(--surface);border:1px solid var(--line);border-radius:10px;
  padding:0 18px;margin-bottom:10px}
.faq summary{cursor:pointer;font-weight:600;font-size:14.5px;padding:15px 0;
  list-style:none;display:flex;align-items:center;gap:12px}
.faq summary::-webkit-details-marker{display:none}
.faq summary::after{content:"+";margin-left:auto;
  font-family:"Bricolage Grotesque","Instrument Sans",sans-serif;font-size:19px;
  color:var(--cuivre);flex:0 0 auto}
.faq details[open] summary::after{content:"\\2013"}
.faq details p{margin:0;padding:0 0 16px;color:var(--muted);font-size:13.5px;
  line-height:1.6}
/* ---------- bandeau final et pied ---------- */
.l-cta{background:linear-gradient(120deg,var(--cuivre),var(--cuivre-deep));color:#fff}
.l-cta .in{max-width:1240px;margin:0 auto;padding:56px 6vw;text-align:center}
.l-cta h2{font-size:clamp(24px,3vw,36px);margin:0 0 10px;text-wrap:balance}
.l-cta p{margin:0 auto 24px;opacity:.92;max-width:52ch}
.l-cta .cta-row{justify-content:center}
/* Fond BLANC en dur, donc texte sombre EN DUR : `var(--cuivre-deep)` s'éclaircit en
   mode sombre (#A85837 → #E08B60) et donnait du cuivre pâle sur blanc. Un jeton qui
   s'inverse n'a rien à faire en face d'une couleur qui ne s'inverse pas. */
.l-cta .btn-clair{background:#fff;color:#A85837;border:0}
.l-cta .btn-creux{background:none;color:#fff;border:1px solid rgba(255,255,255,.55)}
.l-foot{border-top:1px solid var(--line);color:var(--faint);font-size:12.5px;
  padding:22px 6vw;display:flex;gap:18px;flex-wrap:wrap;max-width:1240px;margin:0 auto}
.l-foot .fin{margin-left:auto}
/* ---------- responsive ---------- */
/* LE MÊME ANGLE MORT QUE R100 : tout ce qui est en colonnes ici doit retomber sur une
   colonne, et la page se REGARDE au viewport mobile avant livraison. L'artisan visé
   est sur un chantier ; le téléphone n'est pas le cas dégradé, c'est le cas normal. */
@media (max-width:940px){
  .hero{grid-template-columns:1fr;padding:40px 16px;gap:32px}
  /* `margin-left:auto` collait le téléphone à droite, et le `.ring-badge` qui dépasse
     de 14px vers la gauche venait lécher le bord de l'écran. Centré, puis rentré de la
     largeur du badge : il doit déborder de la CARTE, pas de la PAGE. */
  .phone{margin:0 auto;max-width:min(360px,100%)}
  .ring-badge{left:0}
  .steps,.demo3,.vs,.franchise{grid-template-columns:1fr}
  .trust,.proof .wrap{grid-template-columns:repeat(2,1fr)}
  .l-sec{padding:40px 16px}
  .l-nav{padding:14px 16px;gap:9px;flex-wrap:wrap}
  .l-nav .links{gap:10px}
  .l-nav .links .nav-ancre{display:none}
  .proof .wrap{gap:24px;padding:26px 16px}
  /* Le pied des cartes de comparaison est un libellé long face à un montant : côte à
     côte, « À un panier de 780 € » se coupait entre le nombre et son unité. */
  .vs-card .total{flex-direction:column;gap:4px}
  .l-cta .in{padding:40px 16px}
  .l-foot{padding:22px 16px}
}
@media (max-width:520px){
  .trust,.proof .wrap{grid-template-columns:1fr}
  .l-foot .fin{margin-left:0}
}
"""

# L'ADRESSE DE CONTACT est la seule destination réelle des boutons d'appel à l'action :
# il n'y a pas encore d'inscription en ligne, un artisan entre à la main par `/admin`.
# Un bouton « Essayer gratuitement » qui ouvre un courriel est honnête ; le même bouton
# pointant vers une page d'inscription qui n'existe pas ne l'est pas.
#
# ⚠️ À CONFIRMER PAR GEOFFREY : que cette boîte existe et soit relevée. Un formulaire
# de contact qui tombe dans le vide coûte plus cher que pas de formulaire du tout.
CONTACT_VITRINE = "contact@nelyo.fr"


def vitrine(produit: str, accueil_demo: str, contact: str = CONTACT_VITRINE,
            prive: bool = False) -> str:
    """La page publique : ce qu'un artisan voit avant d'avoir un compte.

    `accueil_demo` est la VRAIE première phrase de l'assistant, rendue par
    `engine.formule_accueil` et passée par l'API — pas une copie. C'est T17 appliqué
    à la page de vente : la promesse affichée et la machine qui l'exécute ne peuvent
    pas diverger, puisqu'il n'y a qu'une source.

    **`prive` et le `noindex` ne font qu'un, délibérément.** C'est normalement la seule
    page du produit qui DOIT être trouvée — mais tant qu'elle est derrière le portail
    d'aperçu, la faire indexer serait absurde : un moteur publierait le titre et le
    résumé d'une page que personne ne peut ouvrir, et l'adresse se retrouverait dans
    les résultats avant le lancement. Lier les deux à un seul paramètre évite le
    scénario où l'on retire le rideau en oubliant le `noindex` — ou l'inverse, qui est
    pire : une page privée référencée.
    """
    mailto = "mailto:" + escape(contact)
    nom = escape(produit)

    nav = (
        '<div class="l-nav">'
        '<span class="logo-mark"><svg viewBox="0 0 24 24" fill="none" stroke="#fff" '
        'stroke-width="2.2" stroke-linecap="round"><path d="M5 4v6a7 7 0 0 0 14 0V4"/>'
        '<path d="M12 17v3"/></svg></span>'
        f"<b>{nom}</b>"
        '<div class="links">'
        '<a class="nav-ancre" href="#fonctionnement">Fonctionnement</a>'
        '<a class="nav-ancre" href="#demo">Démo</a>'
        '<a class="nav-ancre" href="#tarif">Tarif</a>'
        '<a class="nav-ancre" href="#faq">FAQ</a>'
        '<a class="btn" href="/connexion">Se connecter</a>'
        f'<a class="btn btn-cu" href="{mailto}">Demander un accès</a>'
        "</div></div>")

    hero = (
        '<div class="hero"><div>'
        f'<span class="l-badge">L&#x27;assistant des artisans du bâtiment</span>'
        "<h1>Vos appels. Vos RDV.<br><em>Même quand vous êtes sur chantier.</em></h1>"
        '<p class="sub">Un prospect appelle pendant que vous avez les mains dans une '
        f"chaudière ? {nom} répond, qualifie la demande et réserve le rendez-vous. "
        "Vous validez d&#x27;un pouce — <b>vos prospects ne partent plus chez le "
        "concurrent.</b></p>"
        '<div class="cta-row">'
        f'<a class="btn btn-cu btn-xl" href="{mailto}">Demander un accès</a>'
        '<a class="btn btn-xl" href="#demo">Voir ce que vos clients entendent</a>'
        "</div>"
        '<div class="checks"><span>Sans engagement</span>'
        "<span>Vous gardez votre numéro</span>"
        "<span>Aucun RDV confirmé sans vous</span>"
        "<span>Hébergé dans l&#x27;Union européenne</span></div>"
        "</div>"
        # La conversation du hero est une ILLUSTRATION, et le dit sous la carte. Ce
        # qu'elle montre est en revanche le comportement réel de la machine à états :
        # consigne de sécurité, commune demandée, créneau proposé, et la confirmation
        # qui n'arrive QU'APRÈS la validation de l'artisan (règle n°5).
        '<div class="phone">'
        '<span class="ring-badge">Vous n&#x27;avez pas décroché</span>'
        '<div class="ph-top"><span class="avatar">N</span>'
        f"<b>Assistant {nom}</b><span class=\"st\">● en ligne, 24 h/24</span></div>"
        '<div class="flux">'
        '<div class="bulle b-cl"><span class="who">Prospect · 19 h 42</span>'
        "Bonjour, j&#x27;ai une fuite sous l&#x27;évier, c&#x27;est urgent !</div>"
        '<div class="bulle b-ia"><span class="who">Assistant</span>'
        "Je comprends, on va s&#x27;occuper de vous. Si possible, coupez "
        "l&#x27;arrivée d&#x27;eau. Vous êtes sur quelle commune ?</div>"
        '<div class="bulle b-cl"><span class="who">Prospect</span>'
        "Nogent-sur-Marne. Vous pouvez venir demain matin ?</div>"
        '<div class="bulle b-ia"><span class="who">Assistant</span>'
        "Je vous réserve demain entre 8 h et 10 h. Vous recevrez un SMS dès que "
        "l&#x27;artisan a confirmé.</div>"
        '<div class="bulle fin">Validé en 1 tap par l&#x27;artisan → SMS au client'
        "</div></div>"
        '<p class="avis">Exemple de conversation, reconstitué à partir du '
        "déroulé réel de l&#x27;assistant.</p>"
        "</div></div>")

    # LE BANDEAU DE PREUVE. La maquette y plaçait « ×32 : retour moyen sur
    # l'abonnement, mesuré en € signés » — un chiffre qu'aucune mesure ne soutient,
    # puisqu'il n'y a pas encore d'abonné. Les quatre entrées retenues sont soit des
    # propriétés du produit, soit son prix : rien qui demande une moyenne.
    preuve = (
        '<div class="proof"><div class="wrap">'
        '<div class="it"><b>19 h 42</b>'
        "<span>l&#x27;heure où un chantier part chez le concurrent</span></div>"
        '<div class="it"><b class="num">24 h/24</b>'
        "<span>un appel manqué trouve toujours quelqu&#x27;un</span></div>"
        '<div class="it"><b>1 tap</b>'
        "<span>pour valider un rendez-vous, depuis le chantier</span></div>"
        '<div class="it"><b class="num">149 €</b>'
        "<span>par mois, sans installation ni minutes comptées</span></div>"
        "</div></div>")

    # LA DÉMO. Trois cartes à la place des trois de la maquette (extrait audio, ligne
    # de démonstration, rappel automatique) — aucune des trois n'existe. Ce qui existe,
    # et qui vaut mieux : la phrase exacte, les règles que l'assistant ne peut pas
    # enfreindre, et un humain à qui écrire.
    demo = (
        '<div class="l-sec" id="demo">'
        "<h2>Ce que vos clients entendent</h2>"
        '<p class="lead">Pas une promesse de marketing : la première phrase '
        "ci-dessous est celle que la machine prononce, lue dans le produit au moment "
        "où cette page s&#x27;affiche.</p>"
        '<div class="demo3">'
        '<div class="dcard"><h3>La première phrase, mot pour mot</h3>'
        f'<p class="dit">{escape(accueil_demo)}</p>'
        "<p>Elle s&#x27;annonce comme assistant dès la première seconde — la loi "
        "l&#x27;exige, et vos clients ont le droit de le savoir.</p>"
        '<p class="pied">Vous l&#x27;adaptez à votre entreprise : c&#x27;est votre '
        "config qui parle, pas un script figé.</p></div>"
        '<div class="dcard"><h3>Ce qu&#x27;il ne fera jamais</h3>'
        "<ul><li>Inventer un prix que vous n&#x27;avez pas autorisé</li>"
        "<li>Confirmer un rendez-vous sans votre validation</li>"
        "<li>Promettre un rappel sans avoir un numéro</li>"
        "<li>Se faire passer pour un humain</li></ul>"
        '<p class="pied">Ces quatre règles sont dans le code, pas dans une '
        "consigne donnée au modèle.</p></div>"
        '<div class="dcard"><h3>Parler à quelqu&#x27;un</h3>'
        f"<p>{nom} démarre avec ses premiers artisans, et l&#x27;accès se fait "
        "encore à la main : vous écrivez, on vous installe, vous testez pendant "
        "30 jours.</p>"
        f'<p class="dit">{escape(contact)}</p>'
        '<p class="pied">Réponse par un humain — en l&#x27;occurrence celui qui '
        "écrit le produit.</p></div>"
        "</div></div>")

    fonctionnement = (
        '<div class="l-sec" id="fonctionnement">'
        f"<h2>Vous travaillez. {nom} décroche.</h2>"
        '<p class="lead">Aucun changement d&#x27;habitude : vous gardez votre numéro '
        "et vos clients ne voient aucune différence — sauf qu&#x27;on leur répond.</p>"
        '<div class="steps">'
        '<div class="step"><div class="nbr">1</div>'
        "<h3>Activez le renvoi d&#x27;appel</h3>"
        "<p>Un code à composer, une fois. Quand vous ne décrochez pas, l&#x27;appel "
        f"bascule vers votre assistant {nom}. Vous reprenez la main quand vous "
        "voulez.</p></div>"
        '<div class="step"><div class="nbr">2</div>'
        "<h3>L&#x27;assistant répond et qualifie</h3>"
        "<p>Besoin, commune, urgence, coordonnées : il pose les bonnes questions et "
        "réserve un créneau selon VOS règles — jamais un prix inventé, jamais une "
        "promesse en votre nom.</p></div>"
        '<div class="step"><div class="nbr">3</div>'
        "<h3>Vous validez en 1 tap</h3>"
        "<p>Vous recevez le résumé sur votre téléphone : valider, déplacer ou "
        "refuser. Le client reçoit alors son SMS de confirmation, et votre agenda se "
        "remplit.</p></div>"
        "</div>"
        # Les canaux « site » et « email » n'existent QUE dans la maquette. Les
        # annoncer au présent était la promesse la moins tenable de la page.
        '<div class="canaux"><span class="eyebrow">Vos canaux :</span>'
        '<span class="c">Appels manqués</span>'
        '<span class="c plus-tard">Formulaire de votre site — bientôt</span>'
        '<span class="c plus-tard">Emails entrants — bientôt</span>'
        '<span class="c plus-tard">WhatsApp — bientôt</span>'
        "</div></div>")

    # LE CALCUL. La maquette affirmait « nos artisans signent ×32 leur abonnement » et
    # « 18 750 € récupérés le mois dernier ». Ici les chiffres de gauche sont donnés
    # pour ce qu'ils sont — une hypothèse à ajuster — et le seul chiffre présenté comme
    # mesurable est celui que l'artisan DÉCLARE lui-même (T18, migration 015).
    roi = (
        '<div class="l-dark" id="roi"><div class="l-sec">'
        "<h2>Combien vous coûtent vos appels manqués ?</h2>"
        '<p class="lead">Pendant une intervention, impossible de décrocher. Et un '
        "prospect qui tombe sur la messagerie ne laisse pas de message : il appelle "
        "le suivant.</p>"
        '<div class="vs">'
        '<div class="vs-card bad"><h3>Sans assistant</h3>'
        '<span class="hypo">Hypothèse — ajustez à votre activité</span>'
        "<dl><dt>Appels manqués en intervention</dt><dd>6 / sem.</dd>"
        "<dt>Qui raccrochent sans message</dt><dd>7 sur 10</dd>"
        "<dt>Chantiers perdus</dt><dd>≈ 5 / mois</dd>"
        "<dt>Soir &amp; week-end</dt><dd>personne</dd></dl>"
        '<div class="total"><span>À un panier de 780 €</span>'
        '<span class="num">≈ 3 900 € / mois</span></div></div>'
        '<div class="vs-card good"><h3>Avec ' + nom + "</h3>"
        '<span class="hypo">Ce que vous achetez</span>'
        "<dl><dt>Abonnement, tout compris</dt><dd>149 € / mois</dd>"
        "<dt>Réponse</dt><dd>24 h/24</dd>"
        "<dt>Décision</dt><dd>vous, en 1 tap</dd>"
        "<dt>Engagement</dt><dd>aucun</dd></dl>"
        '<div class="total"><span>CA récupéré</span>'
        "<span>celui que vous déclarez</span></div></div>"
        "</div>"
        '<p class="vs-note">Les chiffres de gauche sont une hypothèse, pas une '
        "moyenne mesurée : remplacez-les par les vôtres, vous connaissez votre panier "
        f"mieux que nous. <b>Et {nom} ne devine jamais ce qu&#x27;il vous rapporte</b> "
        ": quand un chantier est fait, vous indiquez s&#x27;il a été gagné et pour "
        "quel montant. Votre tableau de bord additionne vos déclarations — rien "
        "d&#x27;autre.</p>"
        "</div></div>")

    # LA PLACE DES TÉMOIGNAGES. Trois artisans inventés y disaient le bien qu'ils
    # pensaient du produit. Ce qui tient cette place est la seule chose qu'on puisse
    # honnêtement dire d'un produit sans client : ce qu'il fait, et ce qu'il ne fait
    # pas encore. Un artisan qui s'est déjà fait avoir lit la seconde colonne d'abord.
    franchise = (
        '<div class="l-sec" id="franchise">'
        f"<h2>{nom} démarre. Autant vous le dire.</h2>"
        '<p class="lead">Pas de témoignages fabriqués ni de moyennes inventées sur '
        "cette page : le produit cherche ses premiers artisans, et le prix en tient "
        "compte.</p>"
        '<div class="franchise">'
        '<div class="fcard"><h3>Ce qui tourne aujourd&#x27;hui</h3>'
        "<ul><li><b>L&#x27;assistant</b> : il répond, qualifie, propose un créneau "
        "et s&#x27;arrête net là où vous ne l&#x27;avez pas autorisé</li>"
        "<li><b>La validation en 1 tap</b>, et le SMS au client une fois que vous "
        "avez dit oui</li>"
        "<li><b>Votre espace</b> : demandes reçues, agenda, règles de "
        "l&#x27;assistant, chiffre d&#x27;affaires déclaré</li>"
        "<li><b>Vos données dans l&#x27;UE</b>, exportables, supprimables</li>"
        "</ul></div>"
        '<div class="fcard"><h3>Ce qui n&#x27;est pas encore là</h3>'
        "<ul><li>Les demandes venues de <b>votre site et de vos emails</b> — "
        "l&#x27;assistant ne traite aujourd&#x27;hui que les appels</li>"
        "<li>L&#x27;<b>inscription en ligne</b> : on vous installe à la main, et "
        "c&#x27;est aussi l&#x27;occasion de régler l&#x27;assistant avec vous</li>"
        "<li>La <b>facturation automatique</b></li>"
        "<li>Le <b>transfert d&#x27;un appel urgent</b> vers votre portable</li>"
        "</ul></div>"
        "</div></div>")

    confiance = (
        '<div class="l-sec" id="confiance">'
        "<h2>Conçu pour inspirer confiance</h2>"
        '<p class="lead">À vos clients comme à vous : des règles strictes, écrites '
        "dans le produit plutôt que dans une charte.</p>"
        '<div class="trust">'
        # PAS DE DRAPEAU 🇪🇺 ICI, ni 🇫🇷 au pied de page, contrairement à la maquette :
        # Windows ne sait pas composer les indicatifs régionaux et affiche les deux
        # lettres brutes. Vu au rendu — « Hébergé en Europe · EU », « Fait en France FR ».
        # Un PC est l'écran normal d'un artisan qui s'informe le soir.
        '<div class="titem"><span class="ico">🔒</span><b>Hébergé en Europe</b>'
        "<p>Données stockées dans l&#x27;Union européenne, conformes au RGPD. "
        "Export et suppression sur simple demande.</p></div>"
        '<div class="titem"><span class="ico">🤖</span><b>IA annoncée</b>'
        "<p>L&#x27;assistant se présente comme tel dès les premières secondes de "
        "l&#x27;appel, comme la loi l&#x27;exige.</p></div>"
        '<div class="titem"><span class="ico">✅</span><b>Vous gardez la main</b>'
        "<p>Aucun rendez-vous confirmé, aucun SMS envoyé à votre client sans votre "
        "validation.</p></div>"
        '<div class="titem"><span class="ico">🚫</span><b>Jamais de prix inventé</b>'
        "<p>L&#x27;assistant n&#x27;annonce que les tarifs que vous avez autorisés. "
        "Aucun devis improvisé en votre nom.</p></div>"
        "</div></div>")

    tarif = (
        '<div class="l-sec" id="tarif">'
        "<h2>Un prix simple. Un retour que vous mesurez.</h2>"
        '<p class="lead">Pas de minutes comptées, pas de frais d&#x27;installation : '
        "un abonnement, et un tableau de bord qui additionne ce que vous avez "
        "déclaré avoir gagné.</p>"
        '<div class="l-price">'
        f'<div class="eyebrow">{nom} Pro</div>'
        '<div class="pp num">149 €<small> HT / mois</small></div>'
        '<ul class="incl">'
        "<li>Appels illimités, 24 h/24</li>"
        "<li>SMS de confirmation à vos clients</li>"
        "<li>Validation, agenda, statistiques</li>"
        "<li>Réglages de l&#x27;assistant faits avec vous</li>"
        "<li>30 jours d&#x27;essai, sans engagement</li></ul>"
        f'<a class="btn btn-cu btn-xl" href="{mailto}">Demander un accès</a>'
        '<p class="fine">Un seul chantier récupéré rembourse plusieurs mois '
        "d&#x27;abonnement.</p>"
        "</div></div>")

    faq = (
        '<div class="l-sec" id="faq">'
        "<h2>Questions fréquentes</h2>"
        '<div class="faq">'
        "<details><summary>Est-ce que mon numéro change ?</summary>"
        f"<p>Non. {nom} s&#x27;active par renvoi d&#x27;appel conditionnel : "
        "l&#x27;assistant ne décroche que si vous ne répondez pas. Un code à composer "
        "pour l&#x27;activer, un autre pour l&#x27;arrêter.</p></details>"
        "<details><summary>Les clients savent-ils qu&#x27;ils parlent à une IA ?"
        "</summary><p>Oui, l&#x27;assistant se présente comme IA dès le début de "
        "l&#x27;appel — c&#x27;est une obligation légale et une question de "
        "confiance. Ce que vos clients veulent, c&#x27;est une réponse et un "
        "rendez-vous, pas une messagerie.</p></details>"
        "<details><summary>Comment les rendez-vous sont-ils pris ?</summary>"
        "<p>L&#x27;assistant propose des créneaux selon vos règles — zones, horaires, "
        "fenêtres d&#x27;urgence — dans un agenda tampon. Rien n&#x27;est confirmé au "
        "client avant que vous ayez validé ; il reçoit alors son SMS.</p></details>"
        "<details><summary>Et si l&#x27;assistant ne comprend pas une demande ?"
        "</summary><p>Il ne force jamais. Si la demande sort de son périmètre, il "
        "prend les coordonnées et vous transmet la demande avec le résumé de "
        "l&#x27;appel. S&#x27;il n&#x27;a pas de numéro, il ne promet aucun "
        "rappel — il vous le signale comme tel.</p></details>"
        "<details><summary>Donne-t-il des prix au téléphone ?</summary>"
        "<p>Uniquement ceux que vous avez explicitement autorisés, comme un tarif de "
        "déplacement. Jamais d&#x27;estimation improvisée, jamais d&#x27;engagement en "
        "votre nom.</p></details>"
        "<details><summary>D&#x27;où viennent les demandes ?</summary>"
        "<p>Aujourd&#x27;hui, de vos appels manqués. Le formulaire de votre site et "
        "vos emails entrants arriveront dans le même espace, qualifiés de la même "
        "façon — ils ne sont pas encore ouverts.</p></details>"
        "<details><summary>Et si je veux arrêter ?</summary>"
        "<p>Sans engagement : vous désactivez le renvoi d&#x27;appel et tout "
        "s&#x27;arrête. Vos données vous appartiennent et restent exportables.</p>"
        "</details>"
        "</div></div>")

    final = (
        '<div class="l-cta"><div class="in">'
        "<h2>Prêt à ne plus perdre de chantiers ?</h2>"
        "<p>30 jours d&#x27;essai, sans engagement et sans changer de numéro. "
        "On vous installe à la main, et on règle l&#x27;assistant avec vous.</p>"
        '<div class="cta-row">'
        f'<a class="btn btn-xl btn-clair" href="{mailto}">Demander un accès</a>'
        '<a class="btn btn-xl btn-creux" href="#demo">Voir ce que vos clients '
        "entendent</a>"
        "</div></div></div>")

    # PAS DE LIENS « Mentions légales / CGV / Confidentialité » comme dans la maquette :
    # ils seraient morts. Ils demandent une raison sociale, un SIRET et un hébergeur —
    # des informations que le dépôt n'a pas et qu'on n'invente pas. À poser avant
    # d'ouvrir la page au public (la mention légale est une obligation, pas un détail).
    pied = (
        '<div class="l-foot">'
        f"<span>© 2026 {nom}</span>"
        f'<span><a href="{mailto}">{escape(contact)}</a></span>'
        '<span class="fin">Conçu et hébergé en France</span>'
        "</div>")

    return (
        "<!DOCTYPE html>\n"
        '<html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        + ('<meta name="robots" content="noindex, nofollow">' if prive else "")
        + '<meta name="description" content="'
        f"{nom} répond aux appels que vous manquez sur chantier, qualifie la demande "
        'et réserve le rendez-vous. Vous validez en 1 tap avant toute confirmation.">'
        f"<title>{nom} — vos appels manqués deviennent des rendez-vous</title>"
        f"<style>{_STYLE_VITRINE}</style></head><body>"
        + nav + hero + preuve + demo + fonctionnement + roi + franchise
        + confiance + tarif + faq + final + pied
        + "</body></html>")


# ══════════════════════════════════════════ LE PORTAIL D'APERÇU (29/10)
#
# Le rideau devant la vitrine, le temps de la montrer à des collaborateurs. Sa seule
# exigence de fond : **ne rien laisser filtrer de la page qu'il garde**. Pas d'extrait,
# pas de titre accrocheur, pas de tarif — sinon le rideau serait une vitrine de plus, et
# le visiteur non invité aurait l'essentiel sans le mot de passe.
#
# Il dit en revanche CE QUE C'EST et À QUI S'ADRESSER : une page qui demande un mot de
# passe sans se présenter ressemble à une erreur de configuration, et un relecteur à qui
# l'on demande un avis commence par douter du lien qu'on lui a envoyé.
_STYLE_PORTAIL = _SOCLE_NELYO + """
.sas{min-height:100vh;display:grid;place-items:center;padding:24px 16px}
.sas-carte{background:var(--surface);border:1px solid var(--line);border-radius:14px;
  box-shadow:var(--shadow);padding:30px 28px;width:100%;max-width:400px}
.sas-logo{display:flex;align-items:center;gap:10px;margin-bottom:20px}
.sas-logo b{font-family:"Bricolage Grotesque";font-size:20px}
.sas h1{font-size:19px;margin:0 0 7px}
.sas .intro{color:var(--muted);font-size:13.5px;line-height:1.55;margin:0 0 20px}
.sas label{display:block;font-size:12.5px;color:var(--muted);margin:0 0 5px}
.sas input{width:100%;min-height:42px;border:1px solid var(--line);border-radius:9px;
  padding:0 12px;background:var(--surface-2);color:var(--ink);
  font:500 14.5px "Instrument Sans",sans-serif}
.sas button{width:100%;margin-top:14px;min-height:42px;font-size:14.5px}
.sas .refus{background:var(--crit-bg);color:var(--crit);border-radius:9px;
  padding:10px 13px;font-size:13px;font-weight:600;margin:0 0 16px}
.sas .pied{color:var(--faint);font-size:12px;line-height:1.5;margin:18px 0 0}
.sas .pied a{color:var(--muted)}
"""


def portail_apercu(produit: str, contact: str = CONTACT_VITRINE,
                   erreur: str = "") -> str:
    """La page de mot de passe devant la vitrine.

    TOUJOURS `noindex` : elle n'a aucune raison d'exister dans un moteur de recherche,
    et son indexation révélerait l'adresse de ce qu'elle protège.

    Le champ est en `type="password"` et le formulaire en POST : un GET aurait écrit le
    secret dans les journaux du serveur et dans l'historique du navigateur. Le lien
    partageable `?cle=…` existe pour le confort, mais l'API s'en débarrasse par une
    redirection aussitôt qu'elle l'a lu — c'est le seul endroit où il transite.
    """
    nom = escape(produit)
    refus = f'<p class="refus">{escape(erreur)}</p>' if erreur else ""
    return (
        "<!DOCTYPE html>\n"
        '<html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex, nofollow">'
        f"<title>Aperçu privé · {nom}</title>"
        f"<style>{_STYLE_PORTAIL}</style></head><body>"
        '<div class="sas"><div class="sas-carte">'
        '<div class="sas-logo"><span class="logo-mark">'
        '<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" '
        'stroke-linecap="round"><path d="M5 4v6a7 7 0 0 0 14 0V4"/>'
        '<path d="M12 17v3"/></svg></span>'
        f"<b>{nom}</b></div>"
        "<h1>Aperçu privé</h1>"
        '<p class="intro">Cette page est en cours de préparation et n&#x27;est pas '
        "encore publique. Si vous avez reçu un mot de passe, saisissez-le pour y "
        "accéder.</p>"
        + refus
        + '<form method="post" action="/">'
        '<label for="mdp">Mot de passe</label>'
        '<input id="mdp" name="motdepasse" type="password" autofocus '
        'autocomplete="current-password">'
        '<button class="btn btn-cu" type="submit">Voir la page</button>'
        "</form>"
        f'<p class="pied">Vous cherchez votre espace ? '
        f'<a href="/connexion">Se connecter</a>.<br>'
        f'Une question : <a href="mailto:{escape(contact)}">{escape(contact)}</a>.</p>'
        "</div></div></body></html>")


# ══════════════════════════════════════════ LE FORMULAIRE PUBLIC (29/10)
#
# La page que l'artisan met sur son site, ou dont il colle le lien. Elle s'adresse à SES
# clients, pas à lui : elle porte donc SON nom, et Nelyo n'y apparaît qu'en mention de
# pied — c'est lui qu'on appelle, pas nous.
#
# ELLE POSE LES QUESTIONS QUE L'AGENT POSE AU TÉLÉPHONE, et exactement celles-là :
# besoin, commune, coordonnées, urgence. Le lead qui en sort est scoré par le même code
# (`engine.lead_de_formulaire`), donc il atterrit dans la même liste, avec la même
# catégorie et le même barème. Un formulaire qui demanderait autre chose fabriquerait
# une deuxième définition du prospect.
_STYLE_FORMULAIRE = _STYLE_PORTAIL + """
.sas-carte.large{max-width:520px}
.sas textarea{width:100%;min-height:92px;border:1px solid var(--line);border-radius:9px;
  padding:10px 12px;background:var(--surface-2);color:var(--ink);resize:vertical;
  font:400 14px/1.5 "Instrument Sans",sans-serif}
.sas .champ{margin-bottom:14px}
.sas .coche{display:flex;align-items:flex-start;gap:9px;background:var(--cuivre-soft);
  border:1px solid var(--cuivre);border-radius:9px;padding:11px 13px;margin-bottom:16px}
.sas .coche input{width:auto;min-height:0;margin:2px 0 0}
.sas .coche label{display:block;margin:0;color:var(--ink);font-weight:600;
  font-size:13.5px}
.sas .coche small{display:block;color:var(--muted);font-weight:400;font-size:12px}
/* Le piège à robots. `left:-9999px` et non `display:none` : un remplisseur automatique
   ignore ce qui est masqué par `display`, et le piège ne prendrait plus rien. */
.sas .piege{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden}
.sas .merci{background:var(--ok-bg);color:var(--ok);border-radius:9px;padding:12px 14px;
  font-weight:600;font-size:14px;margin:0 0 14px}
.sas .pied-nelyo{color:var(--faint);font-size:11.5px;margin:18px 0 0;text-align:center}
"""

# Le champ-piège. Son nom doit ressembler à un vrai champ pour qu'un robot le remplisse,
# et ne jamais ressembler à ce qu'un humain verrait — il est hors écran, pas caché.
PIEGE_FORMULAIRE = "societe"


def _carte_formulaire(produit: str, entreprise: str, titre: str, corps: str) -> str:
    """L'enveloppe commune au formulaire et à son accusé. `noindex` : c'est la page
    d'UN artisan, elle n'a pas à être trouvée par un moteur à la place de son site."""
    return (
        "<!DOCTYPE html>\n"
        '<html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex, nofollow">'
        f"<title>{escape(titre)} · {escape(entreprise)}</title>"
        f"<style>{_STYLE_FORMULAIRE}</style></head><body>"
        '<div class="sas"><div class="sas-carte large">'
        + corps
        + f'<p class="pied-nelyo">Demande transmise par {escape(produit)}</p>'
        "</div></div></body></html>")


def formulaire_public(produit: str, entreprise: str, prenom: str, artisan_id: str,
                      erreur: str = "", champs: dict | None = None) -> str:
    """Le formulaire que remplit le client de l'artisan.

    LES VALEURS SAISIES SONT RENVOYÉES en cas d'erreur. Sans ça, un champ refusé vide
    tout le reste, et la personne recommence — ou s'en va. C'est la différence entre un
    formulaire et un interrogatoire.
    """
    v = champs or {}
    refus = f'<p class="refus">{escape(erreur)}</p>' if erreur else ""
    coche = ' checked' if v.get("urgence") else ""
    return _carte_formulaire(
        produit, entreprise, "Demander une intervention",
        f"<h1>Demander une intervention</h1>"
        f'<p class="intro">Décrivez votre besoin : {escape(prenom)} vous rappelle. '
        "Réponse assurée, même en dehors des heures d&#x27;ouverture.</p>"
        + refus
        + f'<form method="post" action="/formulaire/{escape(artisan_id)}">'
        '<div class="champ"><label for="besoin">Votre besoin</label>'
        '<textarea id="besoin" name="besoin" required maxlength="600" '
        'placeholder="Ex. : fuite sous l&#x27;évier, l&#x27;eau coule encore">'
        + escape(v.get("besoin") or "") + "</textarea></div>"
        '<div class="champ"><label for="commune">Votre commune</label>'
        '<input id="commune" name="commune" required maxlength="80" '
        'autocomplete="address-level2" value="' + escape(v.get("commune") or "")
        + '"></div>'
        '<div class="champ"><label for="telephone">Votre téléphone</label>'
        '<input id="telephone" name="telephone" type="tel" required maxlength="25" '
        'autocomplete="tel" placeholder="06 12 34 56 78" value="'
        + escape(v.get("telephone") or "") + '"></div>'
        '<div class="champ"><label for="nom">Votre nom</label>'
        '<input id="nom" name="nom" maxlength="80" autocomplete="name" value="'
        + escape(v.get("nom") or "") + '"></div>'
        '<div class="coche"><input id="urgence" name="urgence" type="checkbox" '
        f'value="1"{coche}>'
        '<label for="urgence">C&#x27;est une urgence'
        "<small>Fuite, panne de chauffage, plus d&#x27;eau chaude — votre demande "
        "passera en tête.</small></label></div>"
        # Hors écran, et jamais annoncé : un humain ne le voit pas, un robot le remplit.
        f'<div class="piege" aria-hidden="true"><label for="{PIEGE_FORMULAIRE}">'
        f'Société</label><input id="{PIEGE_FORMULAIRE}" name="{PIEGE_FORMULAIRE}" '
        'tabindex="-1" autocomplete="off"></div>'
        '<button class="btn btn-cu" type="submit">Envoyer ma demande</button>'
        "</form>")


def formulaire_merci(produit: str, entreprise: str, prenom: str,
                     sms_envoye: bool) -> str:
    """Ce qu'on affiche une fois la demande reçue.

    `sms_envoye` est VRAI ou FAUX et l'écran le dit : annoncer « vous allez recevoir un
    SMS » à quelqu'un dont le numéro n'a pas été reconnu serait la promesse intenable
    que 2bis interdit, et il l'attendrait au lieu de rappeler.
    """
    suite = ("Vous allez recevoir un SMS de confirmation."
             if sms_envoye else
             "Nous n&#x27;avons pas pu lire votre numéro : si vous le pouvez, "
             "rappelez directement.")
    return _carte_formulaire(
        produit, entreprise, "Demande envoyée",
        '<p class="merci">Votre demande est bien arrivée.</p>'
        f"<h1>Merci</h1>"
        f'<p class="intro">{escape(prenom)} a reçu votre demande et vous rappelle. '
        + suite + "</p>")


# ══════════════════════════════════════════ MON COMPTE (29/10)
#
# L'ÉCRAN QUI MANQUAIT, et Geoffrey l'a dit sans détour : « c'est quoi ce délire de mdp
# généré tout le temps ? un artisan voudra juste avoir son mdp enregistré dans son
# navigateur et y accéder quand bon lui semble ». Il avait raison sur le fond et à
# moitié sur les faits, et la distinction vaut d'être écrite :
#
#   * la session dure DÉJÀ 90 jours en cookie persistant, et `/connexion` accepte DÉJÀ
#     téléphone + mot de passe avec `autocomplete` sur les deux champs (T16, 23/09) —
#     personne n'est censé refaire le parcours du code SMS à chaque visite ;
#   * mais le seul mot de passe possible était ENGENDRÉ par l'admin
#     (`secrets.token_urlsafe(18)`, du genre `kJ8x-Qp2mNvR7tLw3aZ`). On ne « retient »
#     pas ça, on le colle une fois. L'artisan ne pouvait ni le choisir, ni le changer.
#
# Le docstring de la route d'admin l'annonçait d'ailleurs depuis le 23/09 : « L'artisan
# le changera pour le sien quand il aura son espace. » Cet écran est cet espace.
#
# CE QU'IL NE FAIT PAS, et c'est délibéré : révoquer les AUTRES sessions. Pour un artisan
# qui a un téléphone et un PC, « changer mon mot de passe me déconnecte partout » est une
# nuisance quotidienne opposée à une menace lointaine (un cookie volé). Le jour où un
# artisan signalera un appareil perdu, la réponse sera un bouton « me déconnecter
# partout » — un geste explicite, pas un effet de bord.
#
# PAS D'ENTRÉE DE NAVIGATION : la maquette v5 en a six, et en ajouter une septième pour
# un écran qu'on visite deux fois par an déséquilibrerait la barre. L'accès se fait par
# la carte artisan du pied de barre latérale, là où l'œil cherche déjà son propre nom.
def compte(produit: str, prenom: str, entreprise: str, telephone: str,
           a_un_mot_de_passe: bool, a_valider: int = 0, commune: str = "",
           vue_admin: str = "", erreur: str = "", fait: str = "",
           code_envoye: bool = False) -> str:
    """« Mon compte » : l'artisan pose SON mot de passe, celui qu'il retiendra.

    En mode support, aucun formulaire : la lecture seule est structurelle (T14), et un
    administrateur n'a pas à changer le mot de passe de quelqu'un depuis sa session.
    """
    bandeau = ""
    if erreur:
        bandeau = ('<div class="card aveu"><div class="card-b">'
                   f'<p style="margin:0">{escape(erreur)}</p></div></div>')
    elif fait:
        bandeau = ('<div class="card" style="border-left:3px solid var(--ok)">'
                   '<div class="card-b"><p style="margin:0;color:var(--ok);'
                   f'font-weight:600">{escape(fait)}</p></div></div>')

    champ = ('width:100%;max-width:320px;min-height:40px;border:1px solid var(--line);'
             'border-radius:9px;padding:0 12px;background:var(--surface-2);'
             'color:var(--ink);font:500 14px "Instrument Sans",sans-serif')

    if vue_admin:
        formulaire = ('<p class="note" style="margin:0">Le mot de passe est réservé à '
                      "l&#x27;artisan : il ne se change pas depuis une session "
                      "d&#x27;administration.</p>")
    else:
        ancien = ""
        if a_un_mot_de_passe and code_envoye:
            # LA SORTIE DE SECOURS, et elle remplace le champ plutôt que de s'y ajouter :
            # qui demande un code ne connaît pas son mot de passe, lui laisser les deux
            # champs serait lui proposer une case qu'il ne peut pas remplir.
            ancien = (
                '<label for="code">Code reçu par SMS</label>'
                '<input id="code" name="code" inputmode="numeric" required '
                f'autocomplete="one-time-code" maxlength="6" style="{champ}">'
                '<p class="note" style="margin:6px 0 16px">Envoyé à votre mobile, '
                "valable quelques minutes. Il remplace le mot de passe actuel pour "
                "cette fois.</p>")
        elif a_un_mot_de_passe:
            ancien = (
                '<label for="ancien">Mot de passe actuel</label>'
                '<input id="ancien" name="ancien" type="password" required '
                f'autocomplete="current-password" style="{champ}">'
                '<p class="note" style="margin:6px 0 16px">Demandé parce que le cookie '
                "prouve la session, pas l&#x27;identité : un navigateur resté ouvert "
                "suffirait sinon.</p>")
        formulaire = (
            '<form method="post" action="/app/compte/motdepasse">'
            + ancien
            + '<label for="nouveau">Nouveau mot de passe</label>'
              '<input id="nouveau" name="nouveau" type="password" required '
              f'minlength="10" autocomplete="new-password" style="{champ}">'
              '<p class="note" style="margin:6px 0 16px">Dix caractères au minimum. '
              "Choisissez-le, votre navigateur le retiendra.</p>"
              '<label for="confirmation">Confirmez-le</label>'
              '<input id="confirmation" name="confirmation" type="password" required '
              f'minlength="10" autocomplete="new-password" style="{champ}">'
              '<div style="margin-top:18px">'
              '<button class="btn btn-cu" type="submit">Enregistrer</button></div>'
              "</form>"
            # POSER LA SORTIE SOUS LE FORMULAIRE, et seulement quand elle sert : un
            # artisan qui n'a pas encore de mot de passe n'a rien à oublier. Jusqu'au
            # 29/10, celui qui ne connaissait pas le sien — engendré par l'admin et
            # affiché une fois — ne pouvait plus jamais en changer.
            + ('<form method="post" action="/app/compte/code" '
               'style="margin-top:14px">'
               '<button class="btn" type="submit">Je ne connais pas mon mot de passe '
               "actuel</button></form>"
               if a_un_mot_de_passe and not code_envoye else ""))

    etat = ("Un mot de passe est défini." if a_un_mot_de_passe
            else "Aucun mot de passe : vous entrez par code SMS.")
    corps = (
        bandeau
        + '<div class="card"><div class="card-h"><h3>Comment vous vous connectez</h3>'
          f'<span class="sub" style="margin-left:auto">{escape(etat)}</span></div>'
          '<div class="card-b">'
          '<dl class="kv"><dt>Votre mobile</dt><dd>' + escape(telephone or "—")
        + "</dd>"
          "<dt>Durée de connexion</dt><dd>90 jours</dd></dl>"
          '<p class="note">C&#x27;est votre mobile qui vous identifie, avec votre mot '
          "de passe ou un code reçu par SMS. <b>Le code SMS ne disparaîtra jamais</b> : "
          "c&#x27;est la seule voie si vous oubliez votre mot de passe ou changez "
          "d&#x27;appareil.</p></div></div>"
        + '<div class="card"><div class="card-h">'
          f"<h3>{'Changer' if a_un_mot_de_passe else 'Définir'} mon mot de passe</h3>"
          "</div>"
          f'<div class="card-b">{formulaire}</div></div>')
    return _page_nelyo(produit, "compte", corps, entreprise=entreprise, prenom=prenom,
                       commune=commune, a_valider=a_valider, vue_admin=vue_admin,
                       titre="Mon compte")
