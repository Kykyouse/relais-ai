"""Nombres PRONONCÉS en toutes lettres → chiffres. Déterministe, sans LLM.

Au téléphone, personne n'épelle « neuf quatre un trois zéro ». On dit
« quatre-vingt-onze, deux cent soixante », et la transcription rend des MOTS. Nos
extracteurs, eux, cherchaient des chiffres : le code postal était dans la phrase et passait
à travers.

Mesuré le 26/08 sur trois appels vocaux d'affilée — c'est la forme NORMALE, pas un cas
tordu :

    « Quatre-vingt-onze soixante. »              → 91 60, incomplet, à redemander
    « Quatre-vingt-onze-deux-cent-soixante. »    → 91260
    « 4. 11. 60. »                               → déjà des chiffres

Pourquoi ici et pas dans le prompt d'extraction (règle n°1) : c'est une conversion, pas une
interprétation. Le modèle réel y arrive parfois — sur les trois appels, une fois sur deux —
et « parfois » ne fait pas un produit. Un code postal est une donnée qui décide si on
envoie un artisan chez quelqu'un ; elle ne dépend pas de l'humeur d'un modèle.

Sert aussi aux numéros de téléphone, dictés de la même façon (« zéro six, douze,
trente-quatre… ») : même mécanisme, même garantie.
"""
from __future__ import annotations

import re

# 0–16 : au-delà, le français compose (dix-sept = 10 + 7).
UNITES = {
    "zero": 0, "zéro": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4,
    "cinq": 5, "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "onze": 11,
    "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16,
}
# « septante », « nonante », « huitante » : la Suisse et la Belgique appellent aussi des
# plombiers, et les reconnaître ne coûte rien.
DIZAINES = {
    "vingt": 20, "vingts": 20, "trente": 30, "quarante": 40, "cinquante": 50,
    "soixante": 60, "septante": 70, "octante": 80, "huitante": 80, "nonante": 90,
}
# « quatre-vingt » est fusionné AVANT l'analyse (voir `_mots`) : sans cela, « quatre cent
# quatre-vingt-dix » se lit 404 puis 30, faute de savoir que ce « quatre » ouvre 80 et non
# les unités de 404. Un mot de plus dans la table coûte moins cher qu'un cas particulier
# dans l'automate.
DIZAINES["quatrevingt"] = 80
CENT = {"cent", "cents"}
MILLE = {"mille", "mil"}
LIAISONS = {"et", "-"}

_RE_MOT = re.compile(r"[a-zà-öø-ÿ]+", re.IGNORECASE)


def _mots(texte: str) -> list[str]:
    """Découpe en mots, et fusionne « quatre vingt(s) » en un seul token valant 80.

    C'est le seul endroit du français où un chiffre isolé change de rôle selon ce qui
    suit : dans « quatre cent quatre », le second « quatre » vaut 4 ; dans « quatre cent
    quatre-vingt-dix », il ouvre 80. Résoudre l'ambiguïté ici, par un regard en avant d'un
    mot, évite de la traîner dans tout l'automate.
    """
    bruts = _RE_MOT.findall((texte or "").lower().replace("-", " "))
    sortie: list[str] = []
    i = 0
    while i < len(bruts):
        if bruts[i] == "quatre" and i + 1 < len(bruts) and bruts[i + 1] in ("vingt",
                                                                           "vingts"):
            sortie.append("quatrevingt")
            i += 2
        else:
            sortie.append(bruts[i])
            i += 1
    return sortie


def groupes_dits(texte: str) -> list[str]:
    """Les nombres prononcés dans le texte, en chiffres, dans l'ordre.

    « j'habite au quatre-vingt-onze deux cent soixante » → ['91', '260'].

    Un nombre se TERMINE dès qu'un mot ne peut plus légalement le prolonger. C'est ce qui
    permet de séparer « quatre-vingt-onze » de « deux cent soixante » alors que rien ne les
    sépare dans la phrase : après une unité, seuls « cent » et « mille » peuvent suivre.
    Sans cette règle, on lirait 91 + 2 = 93.
    """
    groupes: list[str] = []
    total = 0
    courant: int | None = None
    apres_unite = apres_dizaine = apres_cent = apres_dix = False

    def fermer() -> None:
        nonlocal total, courant, apres_unite, apres_dizaine, apres_cent, apres_dix
        if courant is not None or total:
            groupes.append(str(total + (courant or 0)))
        total, courant = 0, None
        apres_unite = apres_dizaine = apres_cent = apres_dix = False

    for mot in _mots(texte):
        if mot in LIAISONS:
            continue
        if mot in CENT:
            courant = (courant or 1) * 100
            apres_cent, apres_unite, apres_dizaine, apres_dix = True, False, False, False
        elif mot in MILLE:
            # « mille » ne ferme pas le nombre : « quatre-vingt-onze mille deux cent
            # soixante » est UN nombre.
            total += (courant or 1) * 1000
            courant = None
            apres_unite = apres_dizaine = apres_cent = apres_dix = False
        elif mot in DIZAINES:
            v = DIZAINES[mot]
            if apres_cent:
                courant = (courant or 0) + v      # deux cent soixante
                apres_cent, apres_dizaine = False, True
            elif courant is None:
                courant, apres_dizaine = v, True
            else:
                fermer()
                courant, apres_dizaine = v, True
        elif mot in UNITES:
            v = UNITES[mot]
            if apres_dix and v in (7, 8, 9):
                # dix-sept, soixante-dix-huit, quatre-vingt-dix-neuf : « dix » n'est pas
                # fini tant qu'un 7, 8 ou 9 peut le suivre. Sans cette règle,
                # « soixante-dix-huit » se lit 70 puis 8 — et un numéro de téléphone dicté
                # à voix haute perd un chiffre en route.
                courant = (courant or 0) + v
                apres_dix, apres_unite = False, True
            elif apres_dizaine or apres_cent:
                courant = (courant or 0) + v      # soixante-dix, deux cent six
                apres_dizaine = apres_cent = False
                apres_unite, apres_dix = True, (v == 10)
            elif apres_unite:
                fermer()                          # deux nombres qui se suivent
                courant, apres_unite, apres_dix = v, True, (v == 10)
            else:
                courant, apres_unite, apres_dix = v, True, (v == 10)
        else:
            fermer()                              # un mot ordinaire clôt la suite
    fermer()
    return groupes


def suite_de_chiffres(texte: str, longueur: int) -> str | None:
    """Une suite CONSÉCUTIVE de nombres prononcés dont la concaténation fait exactement
    `longueur` chiffres, ou None.

    Consécutive et non « tous les chiffres du texte » : « j'ai deux enfants, j'habite au
    quatre-vingt-onze deux cent soixante » donne ['2', '91', '260'], où seul le fragment
    ['91', '260'] est un code postal. Exiger la longueur EXACTE est ce qui évite d'inventer
    une donnée à partir de bruit.
    """
    groupes = groupes_dits(texte)
    for debut in range(len(groupes)):
        assemble = ""
        for fin in range(debut, len(groupes)):
            assemble += groupes[fin]
            if len(assemble) == longueur:
                return assemble
            if len(assemble) > longueur:
                break
    return None
