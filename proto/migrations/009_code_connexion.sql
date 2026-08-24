-- Relais — migration 009 : codes de connexion artisan (SMS à 6 chiffres).
--
-- Remplace le champ « jeton d'accès » provisoire de l'écran de connexion. Le mobile EST
-- l'identité professionnelle de l'artisan, et le canal SMS existe déjà. Un code à
-- 6 chiffres ne contient aucune URL : il part par numéro court dès aujourd'hui, sans
-- attendre la déclaration du Sender ID.
--
-- Même discipline que `session_artisan` et que les jetons de confirmation client : seule
-- l'EMPREINTE est stockée. Une fuite de base ne doit pas permettre d'ouvrir des sessions.
--
-- UN SEUL CODE VIVANT PAR ARTISAN — d'où la clé primaire sur `artisan_id` et non sur
-- l'empreinte. Ce n'est pas un détail de modélisation : avec 6 chiffres, chaque code en
-- circulation est une cible supplémentaire. Si demander un nouveau code n'invalidait pas
-- le précédent, en demander mille donnerait mille chances au lieu de trois. Le `do update`
-- de l'insertion écrase donc l'ancien code, par construction.

create table if not exists code_connexion (
    artisan_id text        primary key references artisan (id) on delete cascade,
    empreinte  text        not null,      -- SHA-256 du code, jamais le code
    cree_a     timestamptz not null,
    expire_a   timestamptz not null,
    essais     integer     not null default 0,
    -- le numéro auquel il a été envoyé, pour l'audit : « qui a demandé un code, quand,
    -- et vers où ». Sans ça, un envoi vers un numéro inattendu serait invisible.
    telephone  text
);

-- `on delete cascade` ci-dessus, à l'inverse du `restrict` des autres tables : un code de
-- connexion n'est pas un engagement envers un client, c'est un secret jetable. Il n'a
-- aucune raison d'empêcher la suppression d'un artisan.

-- Balayage des codes périmés (une tâche de ménage, pas un chemin de lecture : la lecture
-- se fait par clé primaire).
create index if not exists code_connexion_expire on code_connexion (expire_a);
