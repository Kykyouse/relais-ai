-- Relais — migration 011 : la config de l'artisan vit en BASE, et chaque appel garde la
-- sienne.
--
-- POURQUOI ON DÉPLACE LA CONFIG. Jusqu'ici `artisan.config_fichier` désignait un JSON
-- versionné dans git, et c'était une décision motivée : l'historique git répondait à
-- « qu'est-ce que l'agent savait le jour de cet appel ? ». Le coût de cette réponse était
-- caché et il est apparu le 21/09 en préparant l'onboarding — **inscrire un artisan
-- exigeait un commit et un redéploiement.** Pas seulement l'inscrire : changer sa zone,
-- ses tarifs ou ses horaires aussi. Autrement dit, chaque ajustement d'un client passait
-- par le dépôt de code.
--
-- CE QUI REMPLACE LA GARANTIE DE GIT, et la remplace en mieux : `appel.config_utilisee`.
-- La config est FIGÉE sur la ligne d'appel au moment où l'appel s'ouvre. La question
-- devient une lecture — « voici exactement ce que l'agent savait pendant cet appel » — au
-- lieu d'un recoupement entre une date d'appel et des dates de déploiement. Git répondait
-- approximativement ; l'instantané répond exactement.
--
-- Les fichiers `config/*.json` ne disparaissent pas : ils deviennent des MODÈLES dont un
-- nouvel artisan part. `config_fichier` reste donc en place, et sert de repli tant que
-- `config` est nulle — une base existante continue de fonctionner sans être convertie.

-- La config vivante. `jsonb` comme les autres blobs versionnés côté application
-- (`etat_conversation`, `donnees`, `creneau`) : ce n'est pas un objet que le SQL doit
-- interroger finement, c'est un document que l'application valide.
alter table artisan add column if not exists config jsonb;

-- L'INSTANTANÉ. Nullable, et il le restera : les appels déjà en base n'en ont pas, et
-- inventer rétroactivement ce que l'agent savait serait précisément le mensonge que
-- cette colonne existe pour empêcher.
alter table appel add column if not exists config_utilisee jsonb;

-- ---------------------------------------------------------------- recherches indexables
--
-- Le registre cherche un artisan par jeton, par mobile et par numéro appelé. Tant qu'il
-- tenait tout en mémoire, l'index n'avait pas lieu d'être ; maintenant qu'il interroge la
-- base à chaque recherche, il en faut — et pour le téléphone, il faut d'abord une colonne
-- indexable.
--
-- POURQUOI DES COLONNES « normalise ». La comparaison passe par `registre._normaliser` :
-- « 06 12 34 56 78 », « +33612345678 » et « 0612345678 » désignent le même mobile. Cette
-- fonction vit en Python et n'a pas d'équivalent SQL évident. La refaire en PL/pgSQL
-- créerait une SECONDE définition de ce qu'est le même numéro, qui divergerait un jour —
-- et le jour où elle divergerait, un artisan deviendrait introuvable à la connexion, sans
-- message. On stocke donc le résultat de l'unique fonction, écrit par l'application.
alter table artisan add column if not exists telephone_normalise text;
alter table artisan add column if not exists numero_relais_normalise text;

-- Reprise des lignes existantes : la forme nationale à 10 chiffres pour les numéros
-- français déjà stockés en +33, sinon les chiffres seuls. C'est exactement ce que fait
-- `_normaliser`, mais UNE FOIS, sur l'existant — l'application reste seule responsable
-- des écritures suivantes.
update artisan set telephone_normalise = case
        when telephone is null then null
        when length(regexp_replace(telephone, '\D', '', 'g')) = 11
             and regexp_replace(telephone, '\D', '', 'g') like '33%'
            then '0' || substr(regexp_replace(telephone, '\D', '', 'g'), 3)
        else regexp_replace(telephone, '\D', '', 'g')
    end
where telephone is not null and telephone_normalise is null;

update artisan set numero_relais_normalise = case
        when numero_relais is null then null
        when length(regexp_replace(numero_relais, '\D', '', 'g')) = 11
             and regexp_replace(numero_relais, '\D', '', 'g') like '33%'
            then '0' || substr(regexp_replace(numero_relais, '\D', '', 'g'), 3)
        else regexp_replace(numero_relais, '\D', '', 'g')
    end
where numero_relais is not null and numero_relais_normalise is null;

-- Le numéro appelé DÉSIGNE l'artisan : deux artisans ne peuvent pas partager le même, et
-- la contrainte doit porter sur la forme normalisée, sinon « +33189701234 » et
-- « 0189701234 » passeraient pour deux numéros différents. `unique` partiel : plusieurs
-- artisans peuvent être sans numéro (une ligne « a_reprendre » de la migration 008 l'est).
create unique index if not exists artisan_numero_relais_norm
    on artisan (numero_relais_normalise) where numero_relais_normalise is not null;

-- Le mobile n'est PAS unique, et c'est délibéré : un même patron peut exploiter deux
-- entreprises. La connexion par code SMS devra alors lever l'ambiguïté plutôt que de
-- choisir au hasard — l'index sert la recherche, il ne tranche pas la règle métier.
create index if not exists artisan_telephone_norm
    on artisan (telephone_normalise) where telephone_normalise is not null;

-- Le jeton porteur : recherche à chaque requête de l'app artisan.
create index if not exists artisan_token
    on artisan (token_sha256) where token_sha256 is not null;
