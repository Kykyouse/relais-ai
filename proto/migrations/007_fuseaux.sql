-- Relais — migration 007 : les horodatages deviennent des INSTANTS (timestamptz).
--
-- Lève la dette n°1 du journal, tranchée le 24/08/2026 (cf. relais_proto/temps.py pour la
-- doctrine et R25 pour les cas verrouillés).
--
-- POURQUOI. Les colonnes étaient en `timestamp` sans fuseau et le domaine en datetime
-- naïfs, censés porter de l'heure locale française. Deux pannes en découlaient :
--
--   1. une DURÉE fausse : « 24 h » calculées sur une pendule valent 23 ou 25 heures
--      réelles autour d'un changement d'heure ;
--   2. un ORDRE ambigu, pire : le dernier dimanche d'octobre, 02h00–02h59 arrive deux
--      fois. `expire_a <= maintenant` pouvait être vrai puis redevenir faux, donc un RDV
--      « dé-expirer » — en contradiction avec l'invariant « aucune sortie d'un état
--      terminal » et avec « l'échéance fait foi, pas le passage du worker ».
--
-- CE QUE FAIT LA CONVERSION. `at time zone 'Europe/Paris'` interprète chaque valeur
-- existante comme l'heure locale française qu'elle était, et la stocke comme l'instant
-- correspondant. C'est la lecture juste des données déjà en base — un cast nu les aurait
-- prises pour de l'UTC et décalé de deux heures en silence.
--
-- ⚠️ Une valeur tombant dans l'heure répétée du dernier dimanche d'octobre est ambiguë par
-- nature : Postgres retient la PREMIÈRE occurrence, comme `temps.instant_de` côté Python.
-- Aucune ligne du proto n'est concernée (jeux d'essai d'août), et le choix est le même des
-- deux côtés — ce qui est le point.
--
-- Les créneaux (« demain entre 08h et 10h ») ne sont PAS concernés : ce sont des heures de
-- pendule, stockées en texte dans le `jsonb` `creneau`, et elles doivent le rester.

alter table appel
    alter column debut_a type timestamptz using debut_a at time zone 'Europe/Paris',
    alter column fin_a   type timestamptz using fin_a   at time zone 'Europe/Paris';

alter table rdv
    alter column expire_a  type timestamptz using expire_a  at time zone 'Europe/Paris',
    alter column cree_a    type timestamptz using cree_a    at time zone 'Europe/Paris',
    alter column notifie_a type timestamptz using notifie_a at time zone 'Europe/Paris',
    alter column decide_a  type timestamptz using decide_a  at time zone 'Europe/Paris';

alter table message_sortant
    alter column cree_a        type timestamptz using cree_a        at time zone 'Europe/Paris',
    alter column envoye_a      type timestamptz using envoye_a      at time zone 'Europe/Paris',
    alter column envoyer_apres type timestamptz using envoyer_apres at time zone 'Europe/Paris';

alter table session_artisan
    alter column cree_a   type timestamptz using cree_a   at time zone 'Europe/Paris',
    alter column expire_a type timestamptz using expire_a at time zone 'Europe/Paris';
