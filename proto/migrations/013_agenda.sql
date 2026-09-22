-- Relais — migration 013 : l'agenda PROPRE de l'artisan.
--
-- « pour l'agenda on est quand même censé en avoir un sans forcément lié google ou
-- outlook, ca doit être un plus de synchronisation, mais s'ils veulent gérer leur agenda
-- uniquement sur Nelyo il faut que ce soit possible » (22/09).
--
-- Le raisonnement du projet était inversé jusque-là : le journal rangeait
-- l'anti-double-réservation derrière le calendrier externe. Or l'artisan SANS agenda
-- numérique est le cas courant — le journal le dit lui-même — et c'est celui qui n'a
-- aucun autre filet. Nelyo doit donc être un agenda à part entière ; Google et Outlook
-- deviennent une synchronisation optionnelle, pas une condition.
--
-- CE QUI MANQUAIT, une fois R98 posé : l'artisan ne peut inscrire QUE ce qui est passé
-- par Nelyo. Son chantier du jeudi décroché de bouche à oreille, son rendez-vous chez le
-- comptable, sa semaine de congés — rien de tout cela n'existe, donc l'agent continue de
-- vendre ces plages. Un agenda qui ne connaît que la moitié des engagements de son
-- propriétaire est pire qu'absent : il inspire une confiance qu'il ne mérite pas.

create table if not exists evenement_agenda (
    id         uuid        primary key default gen_random_uuid(),
    artisan_id text        not null references artisan (id) on delete restrict,
    -- `date` et non texte ISO, contrairement au créneau d'un RDV : celui-ci vit dans un
    -- `jsonb` pour des raisons historiques, mais une table neuve n'a aucune raison de
    -- reprendre ce compromis. Le tri et les bornes deviennent l'affaire de Postgres.
    jour       date        not null,
    -- « HH:MM » sur 24 h. Du TEXTE, et c'est délibéré : c'est déjà la forme que portent
    -- les créneaux (`de`, `a`) partout ailleurs, et faire coexister deux représentations
    -- d'une heure dans le même produit est le genre d'écart qui finit en bug de fuseau.
    de         text        not null,
    a          text        not null,
    titre      text        not null,
    -- `rdv` : un engagement pris hors Nelyo (chantier, devis, rendez-vous personnel).
    -- `indisponible` : congés, formation, maladie — rien à honorer, mais rien à vendre.
    -- Les deux bloquent le créneau de la même façon ; ils ne se racontent pas pareil à
    -- l'écran, et l'artisan doit pouvoir les distinguer d'un coup d'œil.
    type       text        not null default 'rdv',
    cree_a     timestamptz not null default now(),
    constraint evenement_type_connu check (type in ('rdv', 'indisponible')),
    -- Une plage qui se termine avant de commencer n'est pas un événement : c'est une
    -- faute de saisie, et la base est le dernier endroit où l'on peut la refuser.
    constraint evenement_plage_valide check (de < a)
);

-- La lecture est TOUJOURS « ce qu'il y a entre deux dates pour cet artisan » : l'agenda
-- de la semaine, et les plages à exclure des propositions de l'agent.
create index if not exists evenement_agenda_periode
    on evenement_agenda (artisan_id, jour);

-- `on delete restrict` sur l'artisan, comme partout ailleurs : on ne supprime pas un
-- artisan qui a des engagements derrière lui. Une résiliation se marque dans
-- `etat_abonnement`, elle n'efface rien.
