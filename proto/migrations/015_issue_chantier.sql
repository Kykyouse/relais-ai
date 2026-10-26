-- Relais — migration 015 : l'issue de chantier, déclarée par l'artisan (26/10).
--
-- POURQUOI : la maquette v5 fait du « CA récupéré » la métrique reine, et la décision du
-- 22/09 interdit d'afficher un chiffre que le produit ne connaît pas (« aucun chiffre
-- inventé : le produit s'arrête au rendez-vous validé »). Cette migration est ce qui
-- rend les deux compatibles : le chiffre d'affaires devient une SAISIE de l'artisan —
-- « chantier gagné, N euros » — jamais un calcul. L'écran Statistiques n'affiche que la
-- somme de ces déclarations, et le dit.
--
-- CE N'EST PAS UN STATUT : `valide` reste terminal, le cycle de vie vis-à-vis du client
-- est clos. L'issue est une annotation de l'artisan PAR-DESSUS un RDV validé — d'où des
-- colonnes à côté de `statut`, pas une valeur de plus dans `rdv_statut_connu`.

alter table rdv add column if not exists issue text;
alter table rdv add column if not exists issue_montant_eur integer;
alter table rdv add column if not exists issue_le timestamptz;

-- Vocabulaire fermé, comme partout : la base refuse ce que le domaine refuse
-- (`rdv.ISSUES`, `rdv.MONTANT_MAX_EUR`). La contrainte est reposée à chaque passage
-- (drop puis add) pour que modifier la règle ici suffise.
alter table rdv drop constraint if exists rdv_issue_connue;
alter table rdv add constraint rdv_issue_connue
    check (issue is null or issue in ('gagne', 'perdu'));

-- Un montant sans issue « gagne » est un défaut d'écriture, pas une donnée : il ne doit
-- pas pouvoir entrer. Borne haute alignée sur rdv.MONTANT_MAX_EUR (faute de frappe plus
-- vraisemblable qu'un chantier au-delà).
alter table rdv drop constraint if exists rdv_issue_montant;
alter table rdv add constraint rdv_issue_montant
    check (issue_montant_eur is null
           or (issue = 'gagne' and issue_montant_eur between 1 and 1000000));
