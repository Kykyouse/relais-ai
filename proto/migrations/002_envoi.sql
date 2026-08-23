-- Brique 5 : envoi réel des messages sortants.
-- Compteur de réessais et dernière erreur : un échec fournisseur transitoire ne doit pas
-- perdre le SMS du client, et un échec permanent doit rester VISIBLE plutôt que d'être
-- réessayé sans fin. Même raisonnement que le worker d'expiration.

alter table message_sortant
    add column if not exists essais          integer not null default 0,
    add column if not exists derniere_erreur text,
    add column if not exists envoyer_apres   timestamp,
    add column if not exists reference       text;

-- La file d'envoi : messages à envoyer dont l'heure autorisée est passée.
create index if not exists message_file_envoi on message_sortant (envoyer_apres)
    where statut = 'a_envoyer';
