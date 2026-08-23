-- Brique 6 : reproposition d'un créneau par l'artisan, confirmation par le client via un
-- lien reçu par SMS (remplace le « Répondez OUI » de la spec produit §3.5bis — un sender
-- alphanumérique est unidirectionnel, et les numéros mobiles FR sont interdits à l'A2P).
--
-- Idempotente : ce fichier est rejoué à chaque `run_depot_pg.py --migrer`.

alter table rdv add column if not exists confirmation_sha256 text;

-- Nouveau statut « repropose » : en attente du CLIENT, et non terminal (un client qui ne
-- répond pas doit finir par expirer comme les autres).
alter table rdv drop constraint if exists rdv_statut_connu;
alter table rdv add constraint rdv_statut_connu check (statut in
    ('tampon', 'en_attente_validation', 'repropose', 'valide', 'refuse', 'expire'));

-- Les deux index partiels doivent inclure le nouveau statut, sinon un RDV reproposé
-- disparaît silencieusement de la file du worker ET de la boîte de validation.
drop index if exists rdv_file_worker;
create index rdv_file_worker on rdv (expire_a)
    where statut in ('tampon', 'en_attente_validation', 'repropose');

drop index if exists rdv_boite_validation;
create index rdv_boite_validation on rdv (artisan_id)
    where statut in ('tampon', 'en_attente_validation', 'repropose');

-- Recherche par jeton : c'est la seule chose que le client présente, il n'a pas de compte.
-- UNIQUE : deux RDV ne peuvent pas partager un jeton de confirmation.
create unique index if not exists rdv_confirmation on rdv (confirmation_sha256)
    where confirmation_sha256 is not null;
