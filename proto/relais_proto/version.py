"""La révision qui tourne : `RELAIS_VERSION`, puis git, puis « inconnue ».

Extrait de `serveur.py` le 20/09 (R93). Le résolveur lui-même n'a pas changé d'un
caractère — c'est son VOISINAGE qui posait problème.

R65 avait besoin de l'éprouver, et l'éprouvait par `import serveur`. Or `serveur.py`
est le câblage de PRODUCTION : il exécute `app = construire()` à l'import, donc il
OUVRE UNE CONNEXION POSTGRES. La suite de non-régression — annoncée « sans clé ni
base », obligatoire avant tout changement (règle n°3) — dépendait ainsi d'une base
joignable pour tester une fonction qui lit une variable d'environnement.

Le jour où la base de dév a été mise en pause, la suite n'a pas échoué : elle s'est
INTERROMPUE sur une trace, au milieu, après 64 tests verts. Un harnais qui meurt au
lieu de rendre un verdict ne dit plus si le code est bon — et il meurt pour une raison
qui n'a rien à voir avec le code qu'il mesure.

D'où ce module : aucune action à l'import, aucune dépendance hors bibliothèque
standard. Ce qui doit être éprouvable sans base doit VIVRE hors du câblage.
"""
from __future__ import annotations

import os
import pathlib

# La racine du dépôt : deux crans au-dessus de `relais_proto/`. Calculée ici plutôt que
# reçue, pour que le résolveur reste appelable sans rien savoir de son appelant.
RACINE_DEPOT = pathlib.Path(__file__).resolve().parents[2]


def resoudre(racine: pathlib.Path | None = None) -> str:
    """Le commit qui tourne, ou « inconnue ».

    Priorité à `RELAIS_VERSION` : c'est elle qui sert en conteneur, où le dépôt git
    n'est pas là (Render la peuple depuis `RENDER_GIT_COMMIT`, cf. `render.yaml`).
    Repli sur git pour la machine de dév. **Jamais bloquant** : une version inconnue
    ne doit pas empêcher le serveur de démarrer — dater ce qui tourne est un confort
    de diagnostic, pas une condition de service.

    Une variable présente mais VIDE (ou blanche) est traitée comme absente : sur un
    tableau de bord d'hébergeur, une case vidée par mégarde est plus probable qu'une
    case supprimée.
    """
    depuis_env = (os.environ.get("RELAIS_VERSION") or "").strip()
    if depuis_env:
        return depuis_env
    try:
        import subprocess
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                           cwd=racine or RACINE_DEPOT,
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return "inconnue"
