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

    python apercu_local.py                             # page publique
    python apercu_local.py --motdepasse chantier2026   # derrière le portail
    python apercu_local.py --sans-demo                 # vitrine seule, base vide

L'ESPACE ARTISAN EST SEMÉ PAR DÉFAUT, avec un mot de passe que le lanceur affiche. Sans
lui, « montrer le produit » s'arrêtait à la page de vente : `/app` réclame une session,
la connexion cherche l'artisan par son mobile, et une base vide ne peut en fournir aucun.
Le visiteur à qui l'on demande un avis n'avait donc accès qu'à la moitié qui promet, pas
à celle qui livre.

LES APPELS SONT JOUÉS PAR LE VRAI MOTEUR (`semer_demo.APPELS_DEMO`, rejoué ici contre le
dépôt mémoire), pour la raison que ce fichier-là donne déjà : écrire des leads à la main
fabriquerait une deuxième définition de ce qu'est un lead, et la démo divergerait du
produit sans prévenir. Transcripts, scores et catégories sortent du moteur.

⚠️ POUR REGARDER, PAS POUR SERVIR. Tout vit en mémoire et disparaît à l'arrêt. Le mot de
passe de démonstration est affiché en clair dans la console — c'est voulu, et c'est aussi
pourquoi ce lanceur n'écoute que `127.0.0.1` : il n'a rien à faire sur un réseau.
"""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import sys

RACINE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(RACINE))


# L'artisan de démonstration. Même identité que `semer_demo.py` — c'est la même démo,
# jouée contre un dépôt mémoire au lieu de Supabase.
TELEPHONE_DEMO = "06 12 34 56 78"
MOTDEPASSE_DEMO = "demo-nelyo-2026"   # ≥ 10 caractères : `motdepasse.chiffrer` l'exige


def _semer_artisan(depot, produit: dict) -> dict:
    """Un artisan de démo et son historique, en mémoire. Rend de quoi l'annoncer."""
    import json

    import semer_demo
    from relais_proto import motdepasse as mdp_artisan
    from relais_proto import produit as produit_mod
    from relais_proto import temps
    from relais_proto.depot import LigneArtisan
    from relais_proto.registre import empreinte as emp_token

    brute = json.loads(
        (RACINE / "config" / semer_demo.CONFIG_DEMO).read_text(encoding="utf-8"))
    # La config BRUTE est celle qu'on stocke, la MERGÉE celle que l'agent utilise —
    # exactement comme `semer_demo` et comme `api.py`. Ouvrir l'appel autrement
    # produirait une démo qui n'éprouve pas le chemin réel.
    cfg = produit_mod.appliquer(brute, produit)

    depot.enregistrer_artisan(LigneArtisan(
        id=semer_demo.ARTISAN_DEMO, nom_affiche=cfg["entreprise"]["nom"],
        numero_relais=semer_demo.NUMERO_RELAIS_DEMO, telephone=TELEPHONE_DEMO,
        config=brute, token_sha256=emp_token("jeton-local-sans-valeur"),
        mot_de_passe=mdp_artisan.chiffrer(MOTDEPASSE_DEMO),
        etat_abonnement="actif"))

    maintenant = temps.maintenant()
    joues, a_valider = 0, 0
    for spec in semer_demo.APPELS_DEMO:
        # `semer_un_appel` et non `_jouer` : c'est lui qui pose le RDV ET le NOTIFIE.
        # Première version de ce lanceur : les appels étaient joués sans leur rendez-vous,
        # et la boîte de validation — l'écran principal, celui avec les boutons —
        # affichait « Rien à valider ». Le piège que `semer_demo` documente lui-même,
        # retombé dedans en recopiant la moitié de sa boucle.
        compte = semer_demo.semer_un_appel(depot, cfg, maintenant, spec)
        joues += 1
        a_valider += compte["reste_min"] is not None
    return {"entreprise": cfg["entreprise"]["nom"], "appels": joues,
            "a_valider": a_valider}


def construire(motdepasse: str | None, avec_demo: bool = True):
    import json

    import uvicorn

    from relais_proto.api import creer_app
    from relais_proto.depot import DepotMemoire
    from relais_proto.llm import MockLLM
    from relais_proto.registre import RegistreBase

    produit = json.loads((RACINE / "config" / "produit.json").read_text("utf-8"))
    depot = DepotMemoire()
    demo = _semer_artisan(depot, produit) if avec_demo else None

    # `RegistreBase` et non `Registre` : il lit la base À CHAQUE recherche, comme en
    # production. Une liste figée ici aurait fait de l'aperçu un chemin que personne
    # d'autre n'emprunte — donc un chemin non éprouvé.
    registre = RegistreBase(depot, produit, "", RACINE / "config", journal=lambda *_: None)
    app = creer_app(depot, registre, MockLLM,
                    lambda: dt.datetime.now(dt.timezone.utc),
                    base_url="http://localhost:8000",
                    # HTTP en local : un cookie `Secure` serait jeté par le navigateur,
                    # et le portail boucherait sans jamais s'ouvrir (cf. .env.example).
                    cookie_secure=False,
                    vitrine_motdepasse=motdepasse)
    return app, uvicorn, demo


def main() -> int:
    a = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--motdepasse", default=None,
                   help="met la vitrine derrière le portail d'aperçu (sinon publique)")
    a.add_argument("--sans-demo", action="store_true",
                   help="ne sème aucun artisan : la vitrine seule, sur une base vide")
    a.add_argument("--port", type=int, default=8000)
    args = a.parse_args()

    app, uvicorn, demo = construire(args.motdepasse, avec_demo=not args.sans_demo)
    base = f"http://localhost:{args.port}"
    print(f"\n  VITRINE        {base}/")
    if args.motdepasse:
        print(f"    portail      mot de passe : {args.motdepasse}")
        print(f"    lien prêt    {base}/?cle={args.motdepasse}")
    else:
        print("    (publique — ajoute --motdepasse pour voir le portail)")
    if demo:
        print(f"\n  ESPACE ARTISAN {base}/connexion")
        print(f"    entreprise   {demo['entreprise']} · {demo['appels']} appels joués, "
              f"{demo['a_valider']} RDV à valider")
        print(f"    mobile       {TELEPHONE_DEMO}")
        print(f"    mot de passe {MOTDEPASSE_DEMO}")
        print("    (le code par SMS marche aussi : il s'affiche ici même, "
              "RELAIS_SMS=journal)")
    else:
        print(f"\n  ESPACE ARTISAN aucun artisan semé (--sans-demo)")
    print(f"\n  robots.txt     {base}/robots.txt")
    print("\n  Ctrl+C pour arrêter. Rien n'est écrit sur disque ni en base.\n")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
