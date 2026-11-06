# Épisode 1 — générations prévues et coûts (à valider par Pavel)

Coûts mesurés avec `get_cost` le **2026-11-06** · forfait Higgsfield **Pro** · solde **610 crédits** · mode **économique**
(fruits incrustés sur les vraies photos DKG, aucun décor généré).

| # | Génération | Modèle | Qté | Unitaire | Sous-total |
|---|---|---|---|---|---|
| 1 | Poses sans fond : bana-chuchote, bana-visite, bana-choquee, mangue-arrivee, mangue-inquiete, ananas-profil, feuille-ananas (image de référence = job validé) | gpt_image_2_6, 9:16 | 7 | 0,25 | 1,75 |
| 2 | Échantillons de voix (3 voix candidates × Bana, Mangue, Ananas), une phrase chacun | seed_audio | 9 | 0,20 | 1,80 |
| 3 | Répliques du pilote (E01, E03, E04, E05, E06, E07, E08, E09, E11, E13) | seed_audio, voice_id figés | 10 | 0,20 | 2,00 |
| 4 | Thème musical de la série, 40 s, instrumental (réutilisé à chaque épisode) | elevenlabs_music_v2_5 | 1 | 5,82 | 5,82 |
| | **Total prévu** | | | | **11,37** |
| | Marge de reprises (2 poses, 5 répliques ≈ 1,5) | | | | ≈ 1,5 |
| | **Plafond demandé** | | | | **13 crédits** (solde après : ≈ 597) |

Non compris (coût à mesurer avant, accord séparé) : `remove_background` si gpt_image_2_6 ne rend pas un fond transparent propre ; `virality_predictor` (pas d'estimation possible).

## Option premium (non retenue par défaut)
Trois plans animés Kling 3.0 de 5 s (hook Bana, silhouette d'Ananas, porte qui tremble) : 3 × 10 = **30 crédits**.
Risque : Kling régénère l'image et peut altérer le décor réel → chaque plan serait comparé à la photo et refusé au moindre écart (règle « décors toujours réels »).

## Montage, export, contrôle
Gratuit : bac à sable Higgsfield (ffmpeg) et moteurs `serie.py` / `video4k.py`.

## Dépenses réelles (mise à jour 2026-11-06, 09 h 10)

| Poste | Prévu | Réel |
|---|---|---|
| Échantillons de voix (9 prévus ; 13 faits, dont 3 de rattrapage pour Bana et 1 de plus) | 1,80 | **4,20** (seed_audio facturé 0,3-0,4 selon la longueur, pas 0,2) |
| Thème musical 40 s | 5,82 | 5,82 |
| Poses sans fond | 1,75 | 0 (non soumises : images de référence introuvables sur ce compte) |
| **Total dépensé** | | **10,02** — solde 599,98 |

Reste à faire : 7 poses (1,75) + 10 répliques (≈ 0,3 chacune réellement, ≈ 3,0) ≈ **4,75** → dépasse le plafond de 13 de ≈ 1,8. Extension demandée : plafond porté à **16 crédits**.
