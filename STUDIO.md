# LangGraph Studio — visu live du workflow

Studio te montre le graph en temps réel : chaque nœud s'allume pendant son exécution, tu peux inspecter l'état complet entre deux étapes, voir les retries du Critic, et rejouer un input modifié.

## Installation

```powershell
cd "D:\Dossier-principal\FormationsCertifications\Uipath LLM poc email\IntelliMail_Backend"
.venv\Scripts\activate                    # active le venv déjà créé
pip install -r requirements.txt           # installe langgraph-cli[inmem] aussi
```

## Lancement

```powershell
langgraph dev
```

Ça démarre un serveur local et ouvre automatiquement ton navigateur sur LangGraph Studio (interface web hébergée par LangChain, mais ton code et tes données restent **100% locaux** — le navigateur dialogue avec ton serveur en localhost).

URL typique : `https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024`

> Si le navigateur ne s'ouvre pas tout seul, copie l'URL imprimée dans le terminal.

## Utilisation

1. Dans Studio tu vois le graphe : `classifier → researcher → drafter ⇄ critic → END`
2. Panneau de droite « New thread » → tu colles un JSON d'entrée du type :

```json
{
  "email_from": "marie.dupont@example.com",
  "email_subject": "Erreur de facturation",
  "email_body": "Bonjour, ma facture de juillet est incorrecte. Le montant prélevé est de 320€ alors que mon contrat prévoit 280€. Cordialement, Marie Dupont",
  "drafter_retries": 0,
  "trace": []
}
```

3. Click **Submit** → les nœuds s'allument un par un en bleu pendant qu'ils tournent, vert quand ils finissent. Tu vois apparaître dans l'état partagé : `categorie`, `priorite`, `confiance`, `draft`, etc.
4. Click sur un nœud déjà exécuté → tu vois l'état d'entrée + l'état de sortie pour ce nœud précisément.
5. Click sur l'arête conditionnelle après `critic` → tu vois pourquoi le routage a choisi `drafter` (retry) ou `end`.

## Astuces

- **Replay** : tu peux cliquer sur un état intermédiaire, modifier des valeurs (ex: forcer `critic_approved=false`), et re-exécuter à partir de là → utile pour tester les chemins de retry.
- **Fork** : depuis n'importe quel point tu peux dupliquer le thread pour comparer deux exécutions.
- **Persistence locale** : tous tes runs sont sauvegardés dans `.langgraph_api/` à côté du projet. Ajoute ce dossier à `.gitignore`.

## Différence avec `python test_smoke.py`

| | smoke test | LangGraph Studio |
|---|---|---|
| **Sortie** | Texte stdout | UI interactive |
| **Step-by-step** | Non (tout d'un coup) | Oui (chaque nœud) |
| **Inspection d'état** | Non | Complète |
| **Replay / fork** | Non | Oui |
| **Test rapide CI** | ✓ | ✗ |

Garde les deux : `test_smoke.py` pour valider vite en console, Studio pour comprendre/déboguer un cas précis.
