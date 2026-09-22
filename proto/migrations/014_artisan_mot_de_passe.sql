-- Relais — migration 014 : l'artisan peut avoir un mot de passe.
--
-- « j'suis pas contre que les artisans aient juste un id + mdp comme un site classique,
-- qu'ils pourront enregistré dans leurs appareils pour pas avoir a se reco en
-- permanence » (22/09).
--
-- LE CODE SMS NE DISPARAÎT PAS, et ce n'est pas de la prudence : il reste la seule voie
-- pour un artisan qui a perdu son mot de passe, changé de téléphone, ou qui n'en a jamais
-- défini. Les deux portes mènent à la MÊME session — c'est la session qui compte, la
-- méthode d'identification est une couche au-dessus (cf. l'en-tête de `session.py`, écrit
-- bien avant qu'un mot de passe soit envisagé).
--
-- POURQUOI LE MOBILE RESTE L'IDENTIFIANT, et pas un login à inventer : l'artisan le
-- connaît par cœur, il le tape déjà sur l'écran de connexion, et c'est son identité
-- professionnelle. Lui demander de retenir un nom d'utilisateur de plus serait un oubli
-- de plus à gérer par téléphone. R96 garantit déjà qu'un mobile partagé par deux artisans
-- ne laisse deviner ni l'un ni l'autre.

-- NULLABLE, et ça ne changera pas : un artisan inscrit ce matin n'a pas encore de mot de
-- passe, et il doit pouvoir entrer quand même. Une colonne `not null default ''` aurait
-- signifié « mot de passe vide » — c'est-à-dire une empreinte que `motdepasse.verifier`
-- refuse, mais qui se lit comme un compte configuré.
alter table artisan add column if not exists mot_de_passe text;

-- « scrypt$n$r$p$sel$empreinte », jamais le clair : les paramètres de dérivation voyagent
-- avec l'empreinte, pour que les durcir un jour n'invalide pas les mots de passe déjà
-- enregistrés (cf. `motdepasse.py`).
