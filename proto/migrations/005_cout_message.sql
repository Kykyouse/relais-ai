-- Migration 005 : conserver le COUT de chaque message envoye.
--
-- OVH renvoie `totalCreditsRemoved` a chaque envoi. On le jetait, en ne gardant que
-- `creditsLeft` (la reserve, pour l'alerte). Or c'est le cout PAR MESSAGE qui permettra de
-- calculer la depense SMS reelle par artisan et par mois -- donc de savoir quand changer de
-- fournisseur se rentabilise (spec produit S10 : le SMS est un cout variable).
--
-- Cette donnee ne repasse jamais : ne pas la stocker aujourd'hui, c'est ne jamais pouvoir
-- la reconstituer. Colonne nullable : les messages anterieurs n'auront pas de cout, et
-- EnvoyeurJournal en simule un d'apres la vraie regle de facturation.

alter table message_sortant add column if not exists cout integer;
