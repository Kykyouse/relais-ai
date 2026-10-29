-- Relais — migration 016 : le CANAL d'une demande (29/10).
--
-- POURQUOI. La maquette v5 renomme « Appels » en « Demandes » et y ajoute une colonne
-- Canal : appel manqué, formulaire du site, email. Jusqu'ici le produit n'avait qu'un
-- canal, et il était si évident qu'il n'était écrit nulle part — la table s'appelle
-- `appel`, la source du lead valait `appel_telephonique` en dur dans `scoring.py`.
--
-- Le canal du FORMULAIRE n'est pas un affichage de plus : c'est la seule façon de
-- capter un prospect **sans numéro de téléphone joignable depuis la France**, qui est
-- le dernier mur du produit (dette n°1 du journal). Un artisan peut donc recevoir des
-- demandes qualifiées avant même que la ligne vocale existe.
--
-- CE QUI N'EST PAS FAIT ICI, et qu'il ne faut pas lire entre les lignes : la
-- qualification par SMS d'un prospect venu du formulaire. Elle suppose de RECEVOIR des
-- SMS, ce que le produit ne sait pas faire (c'est la dette « réception SMS », suspendue
-- aux trois questions OVH). Le formulaire pose donc les mêmes questions que l'agent
-- poserait, en une fois, et le lead qui en sort est scoré par le même code.
--
-- LA TABLE NE CHANGE PAS DE NOM. `appel` continue de désigner une demande entrante,
-- quel que soit son canal. Renommer aurait touché dix-huit requêtes, deux adaptateurs
-- et la suite de contrat pour un gain de vocabulaire — et le vocabulaire d'INTERFACE
-- (« Demandes ») n'a pas à être celui du schéma.

alter table appel add column if not exists canal text not null default 'telephone';

-- Vocabulaire fermé, comme partout : la base refuse ce que le domaine refuse
-- (`depot.CANAUX`). Reposée à chaque passage pour qu'ajouter un canal ici suffise.
alter table appel drop constraint if exists appel_canal_connu;
alter table appel add constraint appel_canal_connu
    check (canal in ('telephone', 'formulaire'));

-- Les lignes existantes sont des appels téléphoniques, et le `default` ci-dessus les a
-- déjà remplies. C'est le seul rattrapage honnête : avant cette migration, il n'y avait
-- pas d'autre canal, donc aucune ligne n'est reclassée à tort.

-- L'écran « Demandes » filtre par canal ; sans cet index, chaque filtre relit la table
-- entière de l'artisan. Elle est petite aujourd'hui, elle ne le restera pas.
create index if not exists appel_artisan_canal on appel (artisan_id, canal);
