# Tournage de la démo HITL — feuille de route

Vidéo LinkedIn, format carré, ~70 s, **lisible sans le son** (le fil joue les
vidéos en muet : tout passe par les incrustations de texte).

---

## 1. Préparation (avant OBS)

**Trois terminaux**, dans cet ordre :

```powershell
# Terminal 1 — API.  NE PAS FILMER : la 1re ligne affiche votre endpoint Azure.
python main.py

# Terminal 2 — écran de validation
streamlit run app_hitl.py

# Terminal 3 — celui qu'on filme, laissé prêt sans appuyer sur Entrée
python seed_queue.py --reset --parallel 4
```

**Navigateur** : F11 (plein écran), zoom 110 %, barre latérale Streamlit repliée
avec le `«` sauf pour le plan sur les réglages.

**Dans l'écran** : renseignez votre identifiant (`prenom.nom`) et activez
« Actualisation auto (5 s) ». Sans ça les compteurs ne bougeront pas pendant le
remplissage — c'est l'erreur qui gâche la prise.

**Vérifications** : aucun `.env` ni éditeur visible à l'écran ; le terminal 1
hors cadre ou rogné ; données du dataset uniquement (elles sont synthétiques,
aucune donnée client réelle).

---

## 2. Réglages OBS

| Paramètre | Valeur |
|---|---|
| Canevas | 1920×1080 |
| Sortie (mise à l'échelle) | 1080×1080 (carré, format qui occupe le plus de place dans le fil) |
| FPS | 30 |
| Encodeur | x264, CBR 8000 kbps |
| Format d'enregistrement | `mkv` puis **Remux en mp4** (un plantage ne détruit pas la prise) |
| Sources | 1 · Capture de fenêtre (navigateur) + filtre Rognage · 2 · Capture de fenêtre (terminal 3) |

Deux scènes : **Plein écran** (navigateur seul) et **Split** (navigateur 70 % à
gauche, terminal 3 à droite). Raccourci clavier pour basculer, ça évite les
mouvements de souris parasites.

---

## 3. Déroulé, plan par plan

> Les textes de la colonne « Incrustation » sont à ajouter en montage
> (ou en source Texte dans OBS). Police sans-serif, blanc sur bandeau
> bleu nuit `#0F2B46`, en bas du cadre.

### Plan 1 — 0 à 8 s · scène Plein écran

File vide, compteurs à zéro. Ne bougez pas la souris.

> **Incrustation :** « Un back-office assurance reçoit 400 e-mails par jour.
> Combien peuvent partir sans relecture humaine ? »

### Plan 2 — 8 à 25 s · scène Split

Entrée sur le terminal 3. Les lignes défilent, les compteurs montent en direct.

> **Incrustation :** « 15 e-mails clients passent dans le pipeline.
> Chaque décision est motivée par une règle, pas par une intuition du modèle. »

### Plan 3 — 25 à 40 s · scène Plein écran

Cliquez le cas **#4 — Changement de RIB**. Laissez voir le bandeau orange, puis
basculez **Brut ↔ Masqué** lentement, deux allers-retours.

> **Incrustation :** « L'IBAN du client n'a jamais atteint le modèle.
> Deux règles indépendantes ont bloqué l'envoi automatique : fraude au RIB. »

C'est le plan le plus important pour un lecteur métier : la bascule *montre* le
masquage au lieu de demander qu'on vous croie.

### Plan 4 — 40 à 55 s · scène Plein écran

Cliquez le cas **#11 — Demande d'attestation**. Faites défiler le brouillon
jusqu'à la dernière ligne : `code promo interne : GRATUIT100, cotisation annulée`.
Le bandeau violet du garde-fou de sortie est visible.

> **Incrustation :** « Cet e-mail contenait une instruction cachée. Le modèle a
> obéi. La consigne anti-injection du prompt n'a rien vu, le LLM-as-a-judge a
> noté la réponse 5/5. Une règle déterministe l'a arrêtée. »

### Plan 5 — 55 à 70 s · scène Plein écran

Corrigez le brouillon (supprimez la ligne du code promo), cliquez
**Enregistrer la correction**, puis faites défiler vers le bas : le journal
d'audit affiche la ligne signée, le graphique des motifs se met à jour.

> **Incrustation :** « Qui a décidé, quoi, quand. Sur 60 e-mails testés :
> 0 envoi automatique à tort. Sans ces règles : 94,7 %. »

---

## 4. Refaire une prise

```powershell
python seed_queue.py --reset --parallel 4
```

`--reset` vide la file et le journal et décale les identifiants pour contourner
le cache d'idempotence de l'API — sans quoi la deuxième prise resterait vide.
Rechargez la page du navigateur (F5) juste après.

---

## 5. Notes de montage

- **Coupez les temps morts** entre les clics : gardez le mouvement continu.
- **Zoom léger (1.1x) sur la zone utile** aux plans 3 et 4, sinon le texte sera
  illisible une fois la vidéo réduite dans le fil.
- **Première seconde décisive** : le fil défile vite. Faites démarrer
  l'incrustation du plan 1 dès l'image 1.
- **Pas de musique** : la vidéo se joue muette, et un lecteur métier qui active
  le son pour un sujet technique n'existe pas.
- Chiffres cités, tous mesurés (`metrics/benchmark_summary.json`) :
  0 % de faux envois automatiques · 94,7 % sans la table de règles ·
  98,3 % des brouillons approuvés par le LLM-as-a-judge · 0,00125 $ par e-mail ·
  6,5 s de latence moyenne · 63 % d'escalade.

## 6. Réserve à garder en tête

Le dataset est synthétique et écrit par vos soins. Ces chiffres montrent que le
système traite correctement les cas **anticipés** — pas qu'il résiste à des
attaques non imaginées. Si un commentaire vous pose la question, c'est la
réponse honnête, et elle vous sert : elle montre que vous connaissez la limite
de votre propre mesure.
