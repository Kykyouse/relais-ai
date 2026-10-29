"""Sert le SITE VITRINE en local, SANS BASE — pour le regarder et régler le portail.

POURQUOI CE FICHIER EXISTE. Le 29/10, « regarde la page en local » s'est heurté à deux
murs d'affilée : `uvicorn serveur:app` exige une connexion Postgres et s'arrête net sans
elle, et la base de dév était en pause. Or la vitrine ne lit RIEN en base — c'est une
page de présentation. Faire dépendre son aperçu de Supabase n'avait aucune raison d'être
autre qu'un accident de câblage.

C'est le même raisonnement que R93, appliqué à l'œil plutôt qu'aux tests : ce qui n'a pas
besoin d'une base ne doit pas mourir avec elle. Le dépôt mémoire est de la vraie
implémentation du port (`depot.DepotMemoire`), pas un bouchon de test — les pages servies
ici sont exactement celles de la production.

    python apercu_local.py                          # page publique
    python apercu_local.py --motdepasse chantier2026   # derrière le portail

⚠️ POUR REGARDER, PAS POUR SERVIR. Tout vit en mémoire et disparaît à l'arrêt : aucun
artisan, aucun rendez-vous, aucun SMS. `/app` et `/admin` répondront, mais vides.
"""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import sys

RACINE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(RACINE))


def construire(motdepasse: str | None):
    import json

    import uvicorn

    from relais_proto.api import creer_app
    from relais_proto.depot import DepotMemoire
    from relais_proto.llm import MockLLM
    from relais_proto.registre import Registre

    produit = json.loads((RACINE / "config" / "produit.json").read_text("utf-8"))
    # Aucun artisan : la vitrine n'en a pas besoin, et une table vide doit suffire à
    # construire l'API depuis R94. C'est aussi l'état de la vraie base de production.
    registre = Registre([], "", config_produit=produit)
    return creer_app(DepotMemoire(), registre, MockLLM,
                     lambda: dt.datetime.now(dt.timezone.utc),
                     base_url="http://localhost:8000",
                     # HTTP en local : un cookie `Secure` serait jeté par le navigateur,
                     # et le portail boucherait sans jamais s'ouvrir (cf. .env.example).
                     cookie_secure=False,
                     vitrine_motdepasse=motdepasse), uvicorn


def main() -> int:
    a = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--motdepasse", default=None,
                   help="met la vitrine derrière le portail d'aperçu (sinon publique)")
    a.add_argument("--port", type=int, default=8000)
    args = a.parse_args()

    app, uvicorn = construire(args.motdepasse)
    base = f"http://localhost:{args.port}"
    print(f"\n  vitrine        {base}/")
    if args.motdepasse:
        print(f"  portail        mot de passe : {args.motdepasse}")
        print(f"  lien tout prêt {base}/?cle={args.motdepasse}")
    else:
        print("  (publique — ajoute --motdepasse pour voir le portail)")
    print("  robots.txt     " + base + "/robots.txt")
    print("\n  Ctrl+C pour arrêter. Rien n'est écrit sur disque ni en base.\n")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
