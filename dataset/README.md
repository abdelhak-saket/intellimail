# Dataset — vérité terrain (Bloc 2)

## Fichiers

- `emails_labeled.jsonl` — 50 e-mails synthétiques étiquetés à la main.
  Répartition : 6 réclamation, 5 résiliation, 5 données personnelles,
  8 facturation, 8 demande, 5 information, 6 support technique, 4 spam, 3 autre.
- `emails_adversarial.jsonl` — 10 e-mails adverses : injection de prompt (directe,
  cachée, jailbreak), multilingue, pièce jointe seule, corps vide, ton agressif,
  demandes multiples, phishing, surcharge PII.

## Format (1 ligne JSON = 1 e-mail)

```json
{
  "id": "E01",
  "email_from": "...", "email_subject": "...", "email_body": "...",
  "expected": {
    "categorie": "reclamation",       // vérité terrain classification
    "priorite": "haute",              // vérité terrain priorité
    "verdict": "HITL"                 // AUTO_SEND | HITL (action attendue)
  },
  "notes": "pourquoi cet étiquetage"
}
```

Les adverses ont en plus `attack_type` et `success_criteria` (ce que le
pipeline doit — ou ne doit pas — produire pour que le cas soit réussi).

## Conventions d'étiquetage

- `verdict: HITL` = tout ce qui ne doit PAS partir automatiquement
  (revue humaine, classement sans réponse, routage interne).
- Catégories `reclamation`, `resiliation`, `donnees_personnelles` → toujours
  HITL (cohérent avec la table de règles `HITL_FORCE_CATEGORIES`).
- Le **taux de faux AUTO_SEND** (métrique reine du benchmark, Bloc 3) =
  cas étiquetés HITL pour lesquels le pipeline répond AUTO.

## Métriques du benchmark (Bloc 3)

Sur les 60 e-mails : taux de faux AUTO_SEND, précision de classification,
précision de priorité, taux d'escalade, latence moyenne, coût moyen par e-mail.
