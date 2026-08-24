-- Relais — schéma initial (brique 3). Cible : Postgres managé, hébergement UE (spec §9).
--
-- Choix de types assumés :
--
-- * `timestamp` SANS fuseau — CHOIX ANNULÉ, voir la migration 007 (24/08/2026). Le
--   raisonnement d'origine confondait deux natures : les libellés de créneau (« demain
--   entre 08h et 10h ») sont bien des heures de pendule, mais ils sont stockés en texte
--   dans le `jsonb` `creneau` et n'ont jamais été concernés. Les échéances, elles, sont
--   des INSTANTS, et les garder naïfs rendait les durées fausses et l'ordre ambigu deux
--   nuits par an. Les colonnes ci-dessous sont donc passées en `timestamptz` par 007 ;
--   la doctrine est dans `relais_proto/temps.py`, les cas verrouillés dans R25.
--
-- * `jsonb` pour `etat_conversation`, `donnees` (lead), `creneau`, `historique` : ce sont
--   des blobs versionnés côté application (cf. Conversation.ETAT_VERSION), pas des
--   colonnes que le SQL doit interroger finement.
--
-- * `artisan_id` en `text` sans clé étrangère : la table `artisan` n'existe pas encore
--   (périmètre volontairement limité à appel/lead/rdv/message_sortant). La FK arrivera
--   avec elle, dans une migration dédiée.

create table if not exists appel (
    id                uuid primary key default gen_random_uuid(),
    artisan_id        text        not null,
    debut_a           timestamp   not null,
    fin_a             timestamp,
    lead_id           uuid,
    etat_conversation jsonb
);

create table if not exists lead (
    id         uuid primary key default gen_random_uuid(),
    appel_id   uuid  not null references appel (id),
    artisan_id text  not null,
    donnees    jsonb not null default '{}'::jsonb
);

create table if not exists rdv (
    id         uuid primary key default gen_random_uuid(),
    lead_id    uuid      not null references lead (id),
    artisan_id text      not null,
    creneau    jsonb     not null,
    duree_min  integer   not null,
    urgence    boolean   not null,
    statut     text      not null,
    expire_a   timestamp not null,
    cree_a     timestamp not null,
    notifie_a  timestamp,
    decide_a   timestamp,
    historique jsonb     not null default '[]'::jsonb,
    constraint rdv_statut_connu check (statut in
        ('tampon', 'en_attente_validation', 'valide', 'refuse', 'expire'))
);

-- La file du worker d'expiration : index partiel sur les seuls statuts non terminaux.
-- C'est la requête la plus fréquente du système (un cron toutes les N minutes).
create index if not exists rdv_file_worker on rdv (expire_a)
    where statut in ('tampon', 'en_attente_validation');

-- La boîte de validation de l'artisan (l'écran principal de l'app).
create index if not exists rdv_boite_validation on rdv (artisan_id)
    where statut in ('tampon', 'en_attente_validation');

create table if not exists message_sortant (
    id              uuid primary key default gen_random_uuid(),
    -- LA garantie anti-double-SMS : l'unicité est portée par la base, pas par la
    -- prudence de l'appelant. Deux workers concurrents peuvent tenter le même insert.
    cle_idempotence text      not null unique,
    destinataire    text      not null,
    canal           text      not null,
    cible           text      not null,
    texte           text      not null,
    statut          text      not null,
    cree_a          timestamp not null,
    envoye_a        timestamp,
    constraint message_statut_connu check (statut in ('a_envoyer', 'envoye', 'echec'))
);

create index if not exists message_a_envoyer on message_sortant (cree_a)
    where statut = 'a_envoyer';
