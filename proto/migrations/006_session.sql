-- Migration 006 : sessions artisan.
--
-- C'est la session qui rend l'app utilisable au quotidien : Julien valide des rendez-vous
-- plusieurs fois par jour, il ne peut pas s'identifier a chaque fois. La methode de
-- connexion (code par SMS, Google, mot de passe) devient un detail interchangeable
-- au-dessus de cette couche.
--
-- Seule l'EMPREINTE du jeton est stockee : le clair ne vit que dans le cookie du
-- navigateur. Une fuite de base ne permet donc pas d'usurper une session.
--
-- artisan_id en text sans cle etrangere : la table `artisan` n'existe pas encore (elle
-- remplacera config/artisans.json). La FK arrivera avec elle.

create table if not exists session_artisan (
    empreinte  text      primary key,       -- SHA-256 du jeton, jamais le jeton
    artisan_id text      not null,
    cree_a     timestamp not null,
    expire_a   timestamp not null,
    -- pour que l'artisan puisse un jour reconnaitre ses appareils et en revoquer un
    appareil   text
);

-- Le balayage des sessions perimees, et rien d'autre : la lecture se fait par cle primaire.
create index if not exists session_expiree on session_artisan (expire_a);
