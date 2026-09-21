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


# ══════════════════════════════════════════════════ L'ESPACE ARTISAN (son outil)
#
# UNE ENVELOPPE À PART, et non une extension du gabarit client. Jusqu'au 21/09 l'espace
# artisan héritait de `_STYLE` : une carte de 30 rem centrée, pensée pour quelqu'un qui
# ouvre un lien SMS UNE FOIS. Sur un écran d'ordinateur, ça donnait une colonne étroite
# perdue dans du vide, sans en-tête, sans navigation, sans nom d'entreprise — « une simple
# page immonde et vide », et le mot était juste.
#
# Les deux publics n'ont rien en commun : le client voit une page, une fois, sur son
# téléphone, et doit pouvoir taper un bouton en trois secondes. L'artisan revient tous les
# jours, souvent sur un PC, et doit pouvoir S'ORIENTER. Un même gabarit ne peut pas servir
# les deux sans en trahir un.
#
# TOUJOURS SANS JAVASCRIPT : une mise en page n'en a pas besoin. Grille CSS et requêtes de
# média suffisent, et la page reste lisible, imprimable, et rapide sur un réseau de
# chantier.
_STYLE_ESPACE = """
:root { color-scheme: light dark;
  --fond: #f2f4f7; --carte: #fff; --trait: #e2e5ea; --texte: #14181f;
  --doux: #5b6472; --faible: #9aa4b2; --accent: #1a6b3c; --accent-doux: #e8f3ec;
  --alerte: #98261a; --alerte-doux: #fde8e4; --attention: #7a5510;
  --attention-doux: #fdf3df; --info: #1c3f7a; --info-doux: #e7eefb; }
* { box-sizing: border-box; }
body { margin: 0; font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI",
  Roboto, sans-serif; background: var(--fond); color: var(--texte); }

/* ---- en-tête : l'identité et la navigation, présentes partout ---- */
.entete { background: var(--carte); border-bottom: 1px solid var(--trait); }
.entete-int { max-width: 74rem; margin: 0 auto; padding: 0 22px; display: flex;
  align-items: center; flex-wrap: wrap; gap: 6px 18px; min-height: 62px; }
.logo { font-weight: 800; font-size: 1.05rem; letter-spacing: .01em;
  color: var(--accent); text-decoration: none; }
.qui { color: var(--doux); font-size: .92rem; }
.qui b { color: var(--texte); font-weight: 650; }
.entete .pousse { margin-left: auto; }
.entete form { display: inline; }
.quitter { background: none; border: 0; color: var(--doux); font-size: .9rem;
  cursor: pointer; padding: 6px 2px; width: auto; min-height: 0;
  text-decoration: underline; }

/* ---- onglets ---- */
.onglets { background: var(--carte); border-bottom: 1px solid var(--trait); }
.onglets-int { max-width: 74rem; margin: 0 auto; padding: 0 22px; display: flex;
  gap: 4px; overflow-x: auto; }
.onglets a { padding: 12px 14px 10px; font-size: .95rem; font-weight: 600;
  color: var(--doux); text-decoration: none; border-bottom: 3px solid transparent;
  white-space: nowrap; }
.onglets a:hover { color: var(--texte); }
.onglets a.actif { color: var(--accent); border-bottom-color: var(--accent); }
.onglets .compte { display: inline-block; margin-left: 6px; font-size: .78rem;
  font-weight: 700; background: var(--accent-doux); color: var(--accent);
  border-radius: 999px; padding: 1px 7px; vertical-align: 1px; }

/* ---- contenu ---- */
.contenu { max-width: 74rem; margin: 0 auto; padding: 24px 22px 64px; }
.contenu h1 { font-size: 1.45rem; margin: 0 0 4px; }
.sous-titre { color: var(--doux); margin: 0 0 22px; font-size: .96rem; }

/* La GRILLE : une colonne sur téléphone, autant que la largeur en permet ensuite.
   `auto-fill` plutôt qu'un nombre fixe de colonnes — c'est la place disponible qui
   décide, pas une taille d'écran devinée à l'avance. */
.grille { display: grid; gap: 14px;
  grid-template-columns: repeat(auto-fill, minmax(20rem, 1fr)); }
.carte { background: var(--carte); border: 1px solid var(--trait); border-radius: 12px;
  padding: 16px 17px; display: flex; flex-direction: column; }
.carte .bas { margin-top: auto; }
.carte.perime { opacity: .68; border-style: dashed; }

/* ---- pastilles ---- */
.pastille { display: inline-block; font-size: .8rem; font-weight: 700; padding: 2px 9px;
  border-radius: 999px; background: #eef1f5; color: #3c454a; }
.pastille.ok { background: var(--accent-doux); color: var(--accent); }
.pastille.urgent, .pastille.alerte { background: var(--alerte-doux); color: var(--alerte); }
.pastille.action { background: var(--attention-doux); color: var(--attention); }
.tete-carte { display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  margin: 0 0 10px; }
.quand { color: var(--faible); font-size: .84rem; margin: 0 0 8px; }
.creneau { font-size: 1.16rem; font-weight: 650; margin: 0 0 4px; line-height: 1.35; }
.raisons { color: var(--doux); font-size: .92rem; margin: 0 0 14px; }

/* ---- actions ---- */
.actions { display: flex; gap: 9px; }
.actions form { flex: 1; }
button { width: 100%; min-height: 46px; font-size: 1rem; font-weight: 650; border: 0;
  border-radius: 9px; background: var(--accent); color: #fff; cursor: pointer; }
button:hover { filter: brightness(1.08); }
button.refus { background: var(--carte); color: var(--alerte);
  border: 1px solid #e2b5ae; }
button.discret { background: var(--carte); color: var(--doux);
  border: 1px solid var(--trait); min-height: 38px; font-size: .9rem; width: auto;
  padding: 0 13px; }
details { margin-top: 12px; }
summary { cursor: pointer; color: var(--doux); font-size: .9rem; min-height: 30px; }
label { display: block; font-size: .86rem; color: var(--doux); margin: 10px 0 4px; }
input, select, textarea { width: 100%; min-height: 44px; font-size: 1rem; padding: 0 10px;
  border: 1px solid #cfd5de; border-radius: 8px; background: var(--carte);
  color: var(--texte); font-family: inherit; }
a { color: var(--accent); }

/* ---- états vides : ils doivent RASSURER, pas ressembler à une panne ---- */
.vide { background: var(--carte); border: 1px dashed var(--trait); border-radius: 12px;
  padding: 34px 24px; text-align: center; color: var(--doux); }
.vide .gros { font-size: 1.08rem; color: var(--texte); font-weight: 600;
  margin: 0 0 6px; }
.vide p { margin: 0; font-size: .95rem; }

/* ---- divers ---- */
.perdu { color: var(--alerte); font-size: .9rem; margin: 0; }
.rappel a { display: inline-block; min-height: 42px; line-height: 42px;
  font-weight: 650; text-decoration: none; }
.dit-agent, .dit-client { margin: 5px 0; font-size: .9rem; }
.dit-agent { color: var(--doux); }
.filtres { display: flex; flex-wrap: wrap; gap: 7px; margin: 0 0 20px; }
.filtres a { font-size: .88rem; text-decoration: none; padding: 5px 11px;
  border: 1px solid var(--trait); border-radius: 999px; background: var(--carte);
  color: var(--doux); }
.filtres a.actif { border-color: var(--accent); background: var(--accent-doux);
  color: var(--accent); font-weight: 650; }
.support { background: var(--info-doux); color: var(--info);
  border-bottom: 1px solid #c9d8f0; }
.support-int { max-width: 74rem; margin: 0 auto; padding: 11px 22px; font-size: .93rem;
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.support form { margin-left: auto; }
.support button { background: var(--carte); color: var(--info); border: 1px solid #b6c8e8;
  width: auto; min-height: 34px; font-size: .87rem; padding: 0 12px; }
.pied { max-width: 74rem; margin: 0 auto; padding: 0 22px 34px; color: var(--faible);
  font-size: .78rem; letter-spacing: .08em; text-transform: uppercase; }

/* Sur téléphone : une colonne, cibles tactiles plus grandes, et l'en-tête se resserre.
   C'est le cas du CHANTIER — il ne doit rien perdre à ce que le bureau gagne. */
@media (max-width: 640px) {
  .entete-int, .onglets-int, .contenu, .support-int, .pied { padding-left: 15px;
    padding-right: 15px; }
  .contenu { padding-top: 18px; }
  .grille { grid-template-columns: 1fr; }
  button { min-height: 50px; }
}
@media (prefers-color-scheme: dark) {
  :root { --fond: #10141a; --carte: #1b2027; --trait: #2c3542; --texte: #e8eaed;
    --doux: #9aa4b2; --faible: #6b7684; --accent: #4bbd7e; --accent-doux: #16311f;
    --alerte: #f0a99f; --alerte-doux: #3d2320; --attention: #e0c07a;
    --attention-doux: #3a3322; --info: #a8c4ee; --info-doux: #1c2a40; }
  .pastille { background: #2c3542; color: #c8d0da; }
  button.refus { border-color: #5a3a34; }
  input, select, textarea { border-color: #2c3542; }
  .support { border-bottom-color: #2a3a55; }
  .support button { border-color: #35496b; }
}
"""


def _page_espace(produit: str, titre: str, corps: str, *, entreprise: str = "",
                 prenom: str = "", onglet: str = "", a_valider: int = 0,
                 vue_admin: str = "") -> str:
    """L'enveloppe de l'espace artisan : en-tête, onglets, contenu.

    L'ONGLET ACTIF EST UN PARAMÈTRE, pas une déduction faite dans le gabarit : la page
    sait où elle est, l'enveloppe n'a pas à le redeviner en lisant une URL.

    Le compteur « à valider » vit dans les onglets et pas seulement sur la page des RDV.
    C'est le seul chiffre qui appelle une action, et l'artisan doit le voir depuis
    n'importe quel écran — sinon il faut y aller pour savoir s'il faut y aller.
    """
    bandeau = ""
    if vue_admin:
        bandeau = (
            '<div class="support"><div class="support-int">'
            "<span><b>Mode support — lecture seule.</b> Vous regardez l&#x27;espace de "
            + escape(vue_admin) + " ; aucune action n&#x27;est possible d&#x27;ici."
            "</span>"
            '<form method="post" action="/admin/vue/fin">'
            '<button type="submit">Revenir à l&#x27;administration</button></form>'
            "</div></div>")

    def lien(href: str, texte: str, cle: str, compte: int = 0) -> str:
        pastille = (f'<span class="compte">{compte}</span>' if compte else "")
        actif = " class=\"actif\"" if onglet == cle else ""
        return f'<a href="{href}"{actif}>{texte}{pastille}</a>'

    identite = ""
    if entreprise:
        identite = ('<span class="qui"><b>' + escape(entreprise) + "</b>"
                    + (" · " + escape(prenom) if prenom else "") + "</span>")
    deconnexion = ""
    if not vue_admin:
        deconnexion = ('<span class="pousse">'
                       '<form method="post" action="/deconnexion">'
                       '<button class="quitter" type="submit">Se déconnecter</button>'
                       "</form></span>")
    return (
        "<!DOCTYPE html>\n"
        '<html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex, nofollow">'
        f"<title>{escape(titre)} · {escape(produit)}</title>"
        f"<style>{_STYLE_ESPACE}</style></head><body>"
        + bandeau
        + '<header class="entete"><div class="entete-int">'
        + f'<a class="logo" href="/app">{escape(produit)}</a>'
        + identite + deconnexion
        + "</div></header>"
        + '<nav class="onglets"><div class="onglets-int">'
        + lien("/app", "Rendez-vous à valider", "rdv", a_valider)
        + lien("/app/appels", "Mes appels", "appels")
        + "</div></nav>"
        + f'<main class="contenu">{corps}</main>'
        + f'<p class="pied">{escape(produit)}</p>'
        + "</body></html>")


# Ce que chaque catégorie VEUT DIRE à l'artisan, et ce qu'il peut en faire. Vocabulaire
# fermé, aligné sur `engine.py` — une catégorie inconnue s'affiche telle quelle plutôt
# que d'être masquée : mieux vaut un libellé brut qu'un appel escamoté.
#
# R79 appliqué à l'écran : « une catégorie doit dire à l'artisan ce qu'il peut FAIRE ».
# La teinte n'est pas décorative — elle sépare ce sur quoi il peut agir de ce qui est
# clos. D'où l'absence de bouton d'appel sur `injoignable` : c'est précisément la
# catégorie où il n'y a PAS de numéro.
_CATEGORIES = {
    "rdv_reserve":    ("RDV réservé", "ok"),
    "prioritaire":    ("À rappeler — urgent", "urgent"),
    "a_rappeler":     ("À rappeler", "action"),
    "injoignable":    ("Sans numéro", ""),
    "hors_zone":      ("Hors zone", ""),
    "hors_perimetre": ("Hors prestations", ""),
    "spam":           ("Indésirable", ""),
    "appel_muet":     ("Appel muet", ""),
    "autre":          ("Autre", ""),
}


def boite_validation(produit: str, prenom: str, rdvs: list[dict],
                     vue_admin: str = "", entreprise: str = "") -> str:
    """LA fonction produit : les rendez-vous à valider.

    Sans JavaScript : chaque action est un formulaire qui poste puis redirige. Les champs
    de date et d'heure utilisent les types natifs, donc le sélecteur du téléphone — c'est
    précisément là qu'un composant maison serait pire que le natif.

    Les RDV encore décidables d'abord, le plus pressé en tête ; les échus ensuite, à titre
    d'information. L'artisan doit voir en haut ce sur quoi il peut agir.
    """
    a_decider = sum(1 for r in rdvs if not r["echu"])
    enveloppe = lambda corps, titre: _page_espace(  # noqa: E731
        produit, titre, corps, entreprise=entreprise, prenom=prenom,
        onglet="rdv", a_valider=a_decider, vue_admin=vue_admin)

    if not rdvs:
        return enveloppe(
            "<h1>Rendez-vous à valider</h1>"
            '<p class="sous-titre">Ce que votre agent a réservé et qui attend votre '
            "accord.</p>"
            '<div class="vide"><p class="gros">Rien à valider.</p>'
            "<p>Tout est à jour. Les appels reçus restent consultables dans "
            '<a href="/app/appels">Mes appels</a>.</p></div>',
            "Rien à valider")

    blocs = []
    for r in sorted(rdvs, key=lambda x: (x["echu"], x["expire_a"])):
        ident = escape(r["id"])
        pastilles = [f'<span class="pastille{" urgent" if r["urgence"] else ""}">'
                     f'{r["score"]}/5{" URGENCE" if r["urgence"] else ""}</span>']
        if r["echu"]:
            pastilles.append('<span class="pastille alerte">Délai dépassé</span>')
        if r["echu"]:
            # Pas de boutons : le délai est passé, le domaine refuserait toute décision.
            # Afficher des actions qui ne peuvent qu'échouer serait mentir à l'artisan —
            # mais le masquer serait pire : il doit savoir qu'il a laissé filer un lead.
            # ON NE DIT PAS « le client est prévenu » (R85). Le SMS d'expiration est mis
            # en file par le WORKER, et cette page ne sait pas s'il a tourné : le 09/09,
            # quatre RDV traînaient depuis des jours avec cette phrase à l'écran alors
            # qu'aucun client n'avait rien reçu. Même faute que R79 dans `_sans_rdv`.
            #
            # Ce qui est SÛR se dit quand même : le délai est passé, le créneau est rendu,
            # et rappeler reste possible.
            actions = ('<p class="perdu">Le créneau est libéré. Rappelez le client si '
                       "vous voulez le récupérer.</p>")
        elif vue_admin:
            # MODE SUPPORT : les actions ne sont pas désactivées, elles sont ABSENTES.
            # Un bouton grisé invite à cliquer et laisse croire à une panne ; et de toute
            # façon le serveur refuserait — l'identité d'emprunt n'existe pas sur le
            # chemin des actions. Ce qui s'affiche doit dire ce que le serveur ferait.
            actions = '<p class="raisons">Décision réservée à l&#x27;artisan.</p>'
        else:
            actions = (
                '<div class="actions">'
                f'<form method="post" action="/app/{ident}/valider">'
                '<button type="submit">Valider</button></form>'
                f'<form method="post" action="/app/{ident}/refuser">'
                '<button type="submit" class="refus">Refuser</button></form>'
                "</div>"
                "<details><summary>Proposer un autre créneau</summary>"
                f'<form method="post" action="/app/{ident}/reproposer">'
                '<label>Date</label><input type="date" name="date" required>'
                '<label>De</label><input type="time" name="de" required>'
                '<label>À</label><input type="time" name="a" required>'
                '<label></label><button type="submit">Envoyer au client</button>'
                "</form></details>")
        blocs.append(
            f'<div class="carte{" perime" if r["echu"] else ""}">'
            f'<div class="tete-carte">{"".join(pastilles)}</div>'
            f'<p class="creneau">{escape(r["creneau"])}</p>'
            f'<p class="raisons">{escape(" · ".join(r["raisons"])) if r["raisons"] else ""}</p>'
            f'<div class="bas">{actions}</div></div>')

    titre = f"{a_decider} à valider" if a_decider else "Rien à valider"
    sous = ("Validez ou refusez : le client reçoit un SMS dès votre décision."
            if a_decider else "Plus rien à décider — ce qui suit est passé.")
    return enveloppe(
        "<h1>Rendez-vous à valider</h1>"
        f'<p class="sous-titre">{sous}</p>'
        f'<div class="grille">{"".join(blocs)}</div>',
        titre)


def liste_appels(produit: str, prenom: str, appels: list[dict],
                 filtres: list[tuple] = (), vue_admin: str = "",
                 entreprise: str = "", a_valider: int = 0,
                 categorie: str = "") -> str:
    """« Mes appels » : ce que l'agent a répondu, RDV ou pas.

    Ajoutée le 21/09 parce qu'il manquait la moitié de la promesse produit. `/app` ne
    montrait que les RDV à valider ; un appel qui n'aboutissait pas — un client hors
    zone, un client à rappeler, un numéro jamais obtenu — était capté, scoré, stocké, et
    vu par personne.

    Sans JavaScript, comme le reste : les filtres sont des LIENS (un GET par catégorie),
    le transcript un `<details>` natif. Un filtre qui recharge la page est plus lent
    qu'un filtre en JS ; il est aussi lisible sans script, compatible avec le bouton
    « précédent », et partageable par son URL.
    """
    enveloppe = lambda corps, titre: _page_espace(  # noqa: E731
        produit, titre, corps, entreprise=entreprise, prenom=prenom,
        onglet="appels", a_valider=a_valider, vue_admin=vue_admin)

    # Les filtres disent COMBIEN : un filtre qui mène à une page vide est une déception
    # qu'on peut éviter AVANT le clic. Ils s'affichent aussi sur une liste vide — c'est
    # là qu'ils sont le plus utiles, puisqu'ils disent où sont les appels manquants.
    liens = "".join(
        '<a href="/app/appels{}"{}>{} ({})</a>'.format(
            "" if c is None else "?categorie=" + c,
            ' class="actif"' if (c or "") == categorie else "",
            escape(nom), n)
        for c, nom, n in filtres)
    barre = f'<div class="filtres">{liens}</div>' if filtres else ""

    if not appels:
        return enveloppe(
            "<h1>Mes appels</h1>"
            '<p class="sous-titre">Tout ce que votre agent a pris, avec ou sans '
            "rendez-vous.</p>" + barre +
            '<div class="vide"><p class="gros">Aucun appel ici.</p>'
            "<p>Dès qu&#x27;un client appellera, vous verrez ce qu&#x27;il a demandé "
            "et pourrez le rappeler d&#x27;un tap.</p></div>",
            "Mes appels")

    blocs = []
    for a in appels:
        libelle, teinte = _CATEGORIES.get(a["categorie"], (a["categorie"], ""))
        urgent = " urgent" if a["urgence"] else ""
        # Le numéro est la SEULE action possible depuis cette page, et c'est un lien
        # `tel:` : sur le téléphone de l'artisan, un tap suffit. Rien ne s'affiche quand
        # il n'y en a pas — R79 porté à l'écran : une catégorie doit dire ce qu'on peut
        # FAIRE, et « Rappeler » sans numéro envoie chercher un téléphone inexistant.
        if a["telephone"]:
            action = ('<p class="rappel"><a href="tel:' + escape(a["telephone"]) + '">'
                      "Rappeler " + escape(a["telephone_lisible"]) + "</a></p>")
        else:
            action = ('<p class="perdu">Aucun numéro recueilli — '
                      "ce client n&#x27;est pas rappelable.</p>")
        detail = ""
        if a["transcript"]:
            lignes = "".join(
                '<p class="{}"><b>{}</b> {}</p>'.format(
                    "dit-agent" if qui == "agent" else "dit-client",
                    "Agent" if qui == "agent" else "Client", escape(texte))
                for qui, texte in a["transcript"])
            detail = ("<details><summary>Voir la conversation ("
                      + str(len(a["transcript"])) + " tours)</summary>"
                      + lignes + "</details>")
        blocs.append(
            '<div class="carte">'
            + f'<p class="quand">{escape(a["quand"])}</p>'
            + f'<div class="tete-carte"><span class="pastille{urgent}">'
              f'{a["score"]}/5</span>'
            + f'<span class="pastille {teinte}">{escape(libelle)}</span></div>'
            + f'<p class="creneau">{escape(a["resume"])}</p>'
            + f'<div class="bas">{action}{detail}</div></div>')

    return enveloppe(
        "<h1>Mes appels</h1>"
        '<p class="sous-titre">Tout ce que votre agent a pris, avec ou sans '
        "rendez-vous.</p>" + barre
        + f'<div class="grille">{"".join(blocs)}</div>',
        "Mes appels")
