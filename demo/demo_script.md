# Script de démo vidéo — 75 secondes

> Objectif : enregistrement écran de 60-90s pour LinkedIn. Format vertical (9:16) ou carré (1:1) idéal.
> Outils gratuits : OBS Studio, Microsoft Clipchamp (intégré Windows 11), ou ShareX.

## Storyboard

| Temps | Écran | Voix-off / texte affiché |
|---|---|---|
| **00:00 – 00:08** | Capture du diagramme d'architecture (`IntelliMail_Architecture_EN.png`) | "Comment fait-on un agent IA déployable en banque ? On sépare le cerveau de l'exécuteur." |
| **00:08 – 00:18** | Zoom sur `Email Marie Dupont — facturation` (Studio, panneau de gauche) | "Email entrant : un client conteste sa facture." |
| **00:18 – 00:30** | Studio en plein écran. Click sur **Submit** → les 4 nœuds s'allument un par un | "Le Classifier identifie la catégorie. Le Drafter rédige. Le Critic valide." |
| **00:30 – 00:45** | Zoom sur l'état final → champ `draft` développé | "En 4 secondes, l'agent a produit une réponse contextualisée — sans inventer un seul chiffre." |
| **00:45 – 00:58** | Bascule sur UiPath Studio → on voit le log Excel + le fichier `.eml` dans `Data/Drafts` | "UiPath garde le contrôle exécution : audit Excel, déplacement Outlook, brouillon prêt à l'envoi." |
| **00:58 – 01:10** | Texte plein écran avec métriques | "78% d'auto-traitement · 12s par mail · 0,03€ de tokens" |
| **01:10 – 01:15** | Logo + lien GitHub | "Repo public + post LinkedIn pour les détails techniques 👇" |

## Préparation avant l'enregistrement

1. **Ferme tout** sauf : VS Code, navigateur sur Studio, UiPath Studio
2. Dans Studio LangGraph, **prépare l'email Marie Dupont** dans le panneau de gauche (déjà rempli)
3. Dans UiPath, ouvre `EmailClassifier_RPA_IA/Data/EmailLog.xlsx` (pour le bascule en fin de démo)
4. **Mode Présentation** Windows : `Win + P` → "Étendre l'écran" si tu as 2 écrans (sinon, ferme barre des tâches)
5. **Active les notifications Ne pas déranger** (`Win + N` → Focus)
6. Police OBS : 24pt minimum pour lisibilité mobile

## Texte à incruster pendant la démo (sous-titres)

```
[00:08] EMAIL ENTRANT
"Ma facture est incorrecte : 320€ au lieu de 280€."

[00:18] CLASSIFIER · gpt-4.1-mini
catégorie: facturation
priorité: haute
confiance: 0.93

[00:30] DRAFTER · gpt-4.1-mini
Réponse rédigée en 1.8s

[00:38] CRITIC · gpt-4.1-mini
✓ Ton approprié
✓ Aucune hallucination
✓ Conformité OK

[00:45] UIPATH ROBOT
→ Log Excel : ligne ajoutée
→ Outlook : brouillon créé
→ Email déplacé : IntelliMail/Facturation
```

## Mots-clés à dire à voix haute (si voix-off)

- "Architecture hybride RPA + Agentic"
- "Quatre agents spécialisés"
- "Garde-fou Critic pour zéro hallucination"
- "Score de confiance + seuils explicites"
- "Production-ready pour BFSI"

## Erreurs à éviter

❌ Montrer la clé API dans le code → masque le `.env` avant capture
❌ Cliquer pendant que la voix-off parle → enregistre voix après (overdub)
❌ Pas de musique → ou très discrète (ne couvre pas le storytelling)
❌ Plus de 90 secondes → l'algorithme LinkedIn coupe la portée

## Outils gratuits utiles

- **OBS Studio** : enregistrement écran (Win/Mac)
- **Clipchamp** (Windows 11) : édition + sous-titres auto
- **CapCut Desktop** : édition rapide + templates LinkedIn
- **Audacity** : nettoyer la voix-off (noise reduction)
