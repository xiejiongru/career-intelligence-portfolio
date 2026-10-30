# Étude de cas : une offre d'emploi, de bout en bout

> Résumé en français. La version détaillée, avec toutes les valeurs vérifiables, est dans [case-study.md](case-study.md).

Ce résumé suit une annonce de démonstration assainie — [`data/demo/job_record_demo_1.json`](../data/demo/job_record_demo_1.json) — à travers les mêmes étapes que `pipeline/runner.py` : normalisation → identification → analyse → stockage.

## 1. L'annonce source

| Champ | Valeur |
|---|---|
| `source` | `greenhouse` |
| `source_job_id` | `demo-001` |
| Poste | Senior Data Engineer - Geospatial Platform |
| Entreprise | TechCorp |
| Lieu | Paris |
| Contrat | CDI |
| Télétravail | Partiel (`Partial`) |
| Salaire | 65k-85k EUR |

Le salaire est conservé tel quel. Si une source ne fournit pas un champ, la valeur reste `null` : elle n'est pas devinée.

## 2. Normalisation

La couche de résolution d'entités aligne les écritures hétérogènes : nom d'entreprise, lieu, type de contrat, politique de télétravail et URL canonique (paramètres de tracking supprimés). Si la normalisation est incertaine, la valeur d'origine est conservée et `normalization_warnings` enregistre la raison.

## 3. Identité : un identifiant stable, une empreinte de contenu

Deux identifiants répondent à deux questions différentes.

- **`job_id` — de quelle annonce s'agit-il ?** `greenhouse.demo-001` est produit par la stratégie 1 : `source` + `source_job_id`. Si la source n'expose pas d'identifiant stable, la chaîne de repli est : hash de l'URL canonique → `greenhouse.url.09485e0b1c3fdb18`, puis hash de `title|company|location` → `greenhouse.content.a6063c4587674835`.
- **`content_hash` — le contenu a-t-il changé ?** `681dee77769628993dc6ddb6d46abe0b31e10979e9031e6a6e8664fe90331b38` est le SHA-256 de `title|company|location|description`. Une nouvelle collecte de la même annonce conserve le `job_id` ; une description modifiée conserve le `job_id` mais change l'empreinte.

## 4. Analyse

L'analyse ne remplace jamais les champs bruts : elle est stockée à côté, avec les versions des règles et du modèle.

- **Filtre strict** : `passed: true`, aucune compétence manquante signalée.
- **Présélection** : décision `apply`, score `92.5`.

| Dimension | Score |
|---|---|
| `tech_match` | 95.0 |
| `function_match` | 90.0 |
| `domain_match` | 95.0 |
| `experience_match` | 90.0 |
| `growth_potential` | 88.0 |

- **Classement** : score final `94.2` — « Strong tech match (Python, PostGIS, GDAL, Cloud), perfect domain alignment (geospatial), senior experience match. »
- **Versions enregistrées** : `rules_version: 1.0`, `model_version: qwen2.5:7b-instruct`, `kernel_version: 1.0`.

## 5. Stockage

Le résultat est un `JobRecord` v1 valide, stocké dans un fichier JSONL indexé par `job_id`. Le schéma complet est dans [`schemas/job-record-v1.json`](../schemas/job-record-v1.json).

## 6. Limites explicites

- **Identité propre à la source** : la même offre publiée sur deux plateformes produit deux enregistrements. La résolution d'entités normalise les noms, mais la fusion inter-sources n'est pas implémentée.
- **Instantané, pas historique complet** : le JSONL est réécrit à chaque collecte ; une offre absente d'une collecte n'est pas conservée. Les transitions automatiques `closed` / `expired` ne sont pas encore implémentées.
- **Données publiques assainies** : aucune donnée candidat, aucune configuration privée.

## 7. Ce qu'une équipe peut en retenir

- **Ingestion idempotente** : des identifiants stables rendent les collectes rejouables sans doublons.
- **Détection des modifications** : l'empreinte de contenu expose les descriptions modifiées sans comparer le HTML brut.
- **Auditabilité** : données brutes et analyse restent séparées ; les versions des règles et du modèle accompagnent chaque décision.
- **Contrat testable** : chaque enregistrement est validé contre un schéma versionné en CI.

Les briques réutilisables sont le [schéma](../schemas/job-record-v1.json), les [règles d'identité](adr/0002-deterministic-job-id.md) et la [frontière de confidentialité](adr/0004-privacy-boundary.md).
