-- Migration 004 : rattacher chaque message sortant a son artisan.
--
-- Defaut corrige : sans cette colonne, l'expediteur ne pouvait pas savoir de quel artisan
-- relevait un message et appliquait la plage de silence du premier a tous les clients.
-- `worker.py` refusait donc de tourner au-dela d'un artisan (garde volontairement bruyante).
--
-- Colonne NULLABLE et sans reprise de donnees : aucune base de production n'existe encore,
-- et l'expediteur REFUSE d'envoyer un message sans artisan_id plutot que de deviner. Un
-- message ancien reste donc en file, visible dans le rapport du worker — bruyant, pas muet.

alter table message_sortant add column if not exists artisan_id text;

-- La file d'envoi est balayee par artisan des qu'il y en a plusieurs.
create index if not exists message_par_artisan on message_sortant (artisan_id)
    where statut = 'a_envoyer';
