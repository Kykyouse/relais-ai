-- Relais — migration 008 : la table `artisan`, et les clés étrangères qu'elle permet.
--
-- Remplace `config/artisans.json` (le REGISTRE : qui est qui, par quelle porte il entre).
-- Les `config/*.json` restent des fichiers versionnés dans git — décision du 25/08 : la
-- config est ce que l'agent SAIT, et son historique git répond directement à l'exigence
-- d'audit de la spec (« qu'est-ce que l'agent savait le jour de cet appel ? »). Un tarif
-- se change par un commit relu, pas par un UPDATE.
--
-- Choix de types assumés :
--
-- * `id` en **text**, pas en uuid. Les colonnes `artisan_id` existantes portent déjà des
--   valeurs comme « art-dupont » : une clé en uuid rendrait toute reprise impossible.
--   L'identifiant lisible est d'ailleurs un avantage en exploitation — un rapport de
--   worker qui dit « artisan art-dupont inconnu » se lit sans jointure.
--
-- * `numero_relais` et `telephone` NULLABLES, ce qui peut surprendre pour des champs
--   aussi essentiels. C'est la condition pour poser les FK sur des données déjà là :
--   la migration crée d'abord une ligne pour chaque `artisan_id` déjà référencé, dont on
--   ne connaît, en SQL, rien d'autre que l'identifiant. Ces lignes sont marquées
--   `etat_abonnement = 'a_reprendre'` — visibles, et écrasées par la synchronisation
--   depuis le registre fichier. Un `unique` tolère plusieurs NULL, c'est ce qu'on veut.
--
-- * `token_sha256` nullable : le jeton porteur ne sert qu'à l'API et à la future app
--   mobile. Le navigateur passe par le code SMS (migration 009), et un artisan qui
--   n'utilise que son téléphone n'a aucune raison de porter un secret de longue durée.

create table if not exists artisan (
    id              text        primary key,
    nom_affiche     text,                       -- pour les rapports et l'admin, pas pour l'agent
    numero_relais   text        unique,         -- le numéro appelé : c'est LUI qui désigne l'artisan
    telephone       text,                       -- mobile du patron : identité pro + canal du code SMS
    config_fichier  text,                       -- « dupont.json », relatif à proto/config/
    token_sha256    text,                       -- jamais le jeton en clair (cf. registre.py)
    etat_abonnement text        not null default 'actif',
    cree_a          timestamptz not null default now(),
    constraint artisan_etat_connu check (etat_abonnement in
        ('actif', 'essai', 'suspendu', 'resilie', 'a_reprendre'))
);

-- Reprise des artisans déjà référencés par des données existantes. Sans ça, les clés
-- étrangères ci-dessous échouent sur toute base non vide. `distinct` sur l'union des
-- quatre tables : on ne présume pas de laquelle porte l'historique le plus complet.
insert into artisan (id, nom_affiche, etat_abonnement)
select distinct connus.artisan_id, connus.artisan_id, 'a_reprendre'
from (
    select artisan_id from appel
    union select artisan_id from lead
    union select artisan_id from rdv
    union select artisan_id from message_sortant where artisan_id is not null
    union select artisan_id from session_artisan
) as connus
where connus.artisan_id is not null and connus.artisan_id <> ''
on conflict (id) do nothing;

-- Les FK que `rdv.artisan_id` « attendait déjà » depuis la migration 001.
--
-- `on delete restrict` (le défaut) est volontaire : on ne supprime pas un artisan qui a
-- des rendez-vous ou des messages derrière lui — ce sont des engagements pris envers des
-- clients. Une résiliation se marque dans `etat_abonnement`, elle n'efface rien.
--
-- Posées dans une boucle conditionnelle parce que **les migrations sont rejouées en
-- entier** à chaque `run_depot_pg.py --migrer` : un `alter table add constraint` nu
-- passerait la première fois et ferait échouer toutes les suivantes.
--
-- `message_sortant` est traité à part : ses lignes d'avant la migration 004 peuvent avoir
-- un `artisan_id` vide, et une base ancienne ferait échouer la contrainte. On ne la pose
-- que si plus aucune ligne orpheline ne traîne. Le worker sait déjà refuser d'expédier un
-- message dont l'artisan est inconnu — il le signale au lieu de deviner.
do $$
declare
    cible record;
begin
    for cible in
        select * from (values
            ('appel',           'appel_artisan_fk'),
            ('lead',            'lead_artisan_fk'),
            ('rdv',             'rdv_artisan_fk'),
            ('session_artisan', 'session_artisan_fk')
        ) as t(table_cible, nom_contrainte)
    loop
        if not exists (select 1 from pg_constraint
                       where conname = cible.nom_contrainte) then
            execute format(
                'alter table %I add constraint %I foreign key (artisan_id) '
                'references artisan (id)', cible.table_cible, cible.nom_contrainte);
        end if;
    end loop;

    if not exists (select 1 from pg_constraint where conname = 'message_artisan_fk')
       and not exists (
            select 1 from message_sortant m
            where coalesce(m.artisan_id, '') <> ''
              and not exists (select 1 from artisan a where a.id = m.artisan_id))
    then
        alter table message_sortant add constraint message_artisan_fk
            foreign key (artisan_id) references artisan (id);
    end if;
end $$;
