# DKG Stories — mini-série TikTok « fruits »

Mini-série drama/mystère avec des fruits qui parlent, dans les appartements meublés **DKG Guest House** à Douala. Objectif : attirer des vues sur TikTok et générer des réservations.

## Arborescence
- `bible/personnages.md` : direction artistique, personnages, voix, règles de cohérence
- `episodes/ep01-pilote.md` : scénario du pilote avec le découpage plan par plan
- `prompts/personnages.md` : prompts et identifiants Higgsfield des personnages générés
- `assets/decor-photos/` : photos des appartements DKG (à fournir)
- `assets/personnages/` : visuels validés des personnages

## Pipeline (état au 2026-11-06)
1. Bible de série ✅ `bible-serie.json` / `bible-serie.md` (personnages, lieux réels, faits vérifiés, arc en 7 épisodes)
2. Pilote révisé ✅ `episodes/ep01/decoupage.json` → `plan.md` (34 s) → `projet.json` validé par Vidéo 4K 2.0
3. Budget ✅ 15,70 crédits dépensés (plafond 16)
4. Personnages, voix Eleven v4, thème musical ✅
5. Montage dans le bac à sable Higgsfield ✅
6. Export social-916, contrôle (CONFORME), grille 100/100 ✅
7. Livraison ✅ `episodes/ep01/livraison.md` — publication en attente de Pavel

## Outils
- `outils/serie.py` : moteur de la compétence TikTok Série Virale (+ recadrage `cadre`, étalonnage `nuit`/`tension`, silhouette, texte par plan)
- `outils/carte_finale.py` : fond de la carte finale (logo DKG réel + « Réserve ton séjour sur »)
- `assets/polices/` : Montserrat (licence SIL OFL 1.1, `OFL.txt`)

## Appel à l'action
« Réserve ton séjour sur **dkgguesthouse.com** » — vérifié le 2026-11-06 : demande de réservation depuis la fiche du logement, sans compte ni paiement en ligne, confirmation sur WhatsApp.
