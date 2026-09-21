-- Relais — migration 012 : le compte ADMIN, sujet distinct de l'artisan.
--
-- « je suis pas un artisan je suis le maitre du produit, si on me demande de l'assistance
-- il faut que je puisse tout faire » (21/09). D'où un sujet à part entière, et non un
-- drapeau `role` posé sur une ligne `artisan` : les deux n'ont ni le même cycle de vie, ni
-- la même façon de se connecter, ni les mêmes droits, et une colonne booléenne aurait
-- rangé sous le même toit un client et son fournisseur.
--
-- TABLES SÉPARÉES PLUTÔT QUE COLONNES AJOUTÉES, et c'est un choix de risque. Généraliser
-- `code_connexion` et `session_artisan` à un « sujet » aurait supprimé la duplication —
-- mais `code_connexion.artisan_id` est sa CLÉ PRIMAIRE avec clé étrangère, donc la
-- généraliser signifie démonter une table éprouvée qui porte le parcours de connexion des
-- artisans. Le code partagé, lui, ne se duplique pas : `session.py` et `admin.py` servent
-- les deux sujets. Seul le stockage se dédouble, et il est trivial.

create table if not exists admin (
    id           text        primary key,
    identifiant  text        not null unique,   -- ce qu'on tape pour se connecter
    nom          text,
    -- « scrypt$n$r$p$sel$empreinte » — les PARAMÈTRES voyagent avec l'empreinte, pour que
    -- les durcir un jour n'invalide pas les mots de passe déjà enregistrés. Jamais le mot
    -- de passe en clair, évidemment : la base ne doit pas pouvoir le rendre.
    mot_de_passe text        not null,
    actif        boolean     not null default true,
    cree_a       timestamptz not null default now()
);

-- Session d'admin : même mécanique que `session_artisan` (empreinte seule, expiration
-- explicite, révocable), durée plus COURTE côté application — une session qui peut tout
-- faire doit se refermer plus vite qu'une session qui valide un rendez-vous.
--
-- `on delete cascade` : désactiver un admin doit fermer ses sessions. Un compte révoqué
-- dont le cookie continue d'ouvrir les portes n'est pas révoqué.
create table if not exists session_admin (
    empreinte text        primary key,          -- SHA-256 du jeton, jamais le jeton
    admin_id  text        not null references admin (id) on delete cascade,
    cree_a    timestamptz not null,
    expire_a  timestamptz not null,
    appareil  text
);

create index if not exists session_admin_expiree on session_admin (expire_a);

-- `timestamptz` partout (règle n°7) : un horodatage est un INSTANT en UTC. La table
-- `session_artisan` de la migration 006 utilisait `timestamp` nu, corrigé depuis par 007 ;
-- on ne refait pas l'erreur ici.
