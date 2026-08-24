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
@media (prefers-color-scheme: dark) {
  body { background: #14181f; color: #e8eaed; }
  main { background: #1d232c; box-shadow: none; }
  .entreprise, .jour, .apres { color: #9aa4b2; }
}
"""


def _page(titre: str, corps: str) -> str:
    return (
        "<!DOCTYPE html>\n"
        '<html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        # une page de confirmation n'a rien à faire dans un index de moteur de recherche
        '<meta name="robots" content="noindex, nofollow">'
        f"<title>{escape(titre)}</title><style>{_STYLE}</style></head>"
        f"<body><main>{corps}</main></body></html>"
    )


def proposition(entreprise: str, prenom: str, creneau_label: str, action: str) -> str:
    """Page vue par le client au bout du lien SMS : un créneau, un bouton.

    Volontairement pauvre en informations : ni son nom, ni son téléphone, ni le motif de
    l'intervention. L'URL vaut capacité — quiconque la possède ne doit rien apprendre sur
    la personne. Le formulaire poste sur la MÊME URL : pas de JS, donc ça marche partout.
    """
    return _page(
        f"Valider votre rendez-vous — {entreprise}",
        f"<h1>Votre rendez-vous</h1>"
        f'<p class="entreprise">{escape(entreprise)}</p>'
        f'<p class="creneau">{escape(creneau_label)}</p>'
        f'<p class="jour">Proposé par {escape(prenom)}</p>'
        f'<form method="post" action="{escape(action)}">'
        f"<button type=\"submit\">Ça me convient</button></form>"
        f'<p class="apres">En validant, {escape(prenom)} est prévenu immédiatement.</p>')


def confirmee(entreprise: str, prenom: str, creneau_label: str) -> str:
    return _page(
        f"Rendez-vous confirmé — {entreprise}",
        f'<p class="ok">✅</p><h1>C\'est confirmé</h1>'
        f'<p class="entreprise">{escape(entreprise)}</p>'
        f'<p class="creneau">{escape(creneau_label)}</p>'
        f'<p class="apres">{escape(prenom)} a été prévenu. Vous n\'avez plus rien à '
        f"faire.</p>")


def lien_invalide() -> str:
    """404 ET 410 : le même texte pour un lien inconnu, déjà utilisé ou périmé.

    Ne pas distinguer les cas est délibéré côté sécurité — mais surtout, ce message doit
    rassurer le client qui a déjà validé et recharge sa page. Il ne doit pas croire que sa
    validation a échoué.
    """
    return _page(
        "Lien expiré",
        "<h1>Ce lien n'est plus valide</h1>"
        '<p class="apres">Il a peut-être déjà été utilisé, ou le créneau n\'est plus '
        "proposé. <strong>Si vous venez de valider, c\'est bien pris en compte</strong> "
        "et l'artisan a été prévenu. Sinon, il vous recontacte pour convenir d'un autre "
        "horaire.</p>")


def creneau_perime(prenom: str) -> str:
    return _page(
        "Créneau expiré",
        "<h1>Ce créneau n'est plus disponible</h1>"
        f'<p class="apres">Le délai de validation est passé. {escape(prenom)} vous '
        f"recontacte pour vous en proposer un autre.</p>")
