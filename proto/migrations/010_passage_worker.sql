-- Relais — migration 010 : trace du dernier passage du worker.
--
-- Le 09/09, Geoffrey revient après une semaine et constate que ses rendez-vous n'ont pas
-- expiré. La cause était banale — son PC de développement était éteint. Mais pour
-- l'établir, il a fallu lire l'état des RDV, comparer des échéances et raisonner :
-- personne ne pouvait répondre à « le worker a-t-il tourné ? » autrement qu'à tâtons.
--
-- Même leçon que la migration du champ de révision et que `/sante` (R65) : **dater ce qui
-- tourne doit être une donnée, pas un raisonnement.**
--
-- Et le besoin grandira avec la mise en production, il ne disparaîtra pas. Un cron muet
-- qui ne tourne plus ressemble EXACTEMENT à un cron qui n'a rien à faire : mêmes journaux
-- vides, même base immobile. Un processus permanent bloqué sur une exception avalée
-- ressemble tout autant à un processus en bonne santé. Quelle que soit la forme retenue —
-- timer systemd, cron, process worker supervisé — c'est le même symptôme, et cette ligne
-- est ce qui le distingue.

-- UNE SEULE LIGNE, jamais plus : on veut savoir s'il tourne ENCORE, pas tenir un
-- historique. Un journal de passages serait un autre objet, il grossirait sans fin et
-- vieillirait mal. D'où la contrainte `cle = 'worker'` en clé primaire : le `on conflict
-- do update` de l'écriture écrase, par construction.
--
-- La table est volontairement générique (`cle`, `instant`) : le jour où un second jalon
-- doit être daté — dernier import, dernière synchronisation d'agenda — il se range ici
-- sans migration.
create table if not exists jalon (
    cle     text        primary key,
    instant timestamptz not null
);

-- `timestamptz` et non `timestamp` : règle n°7 du projet. Un horodatage est un INSTANT en
-- UTC ; l'affichage le convertit en heure de pendule au moment de le lire, jamais avant.
