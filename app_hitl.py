"""Écran de validation humaine (HITL) — Streamlit, page unique.

Lancement :  streamlit run app_hitl.py
L'API n'a pas besoin de tourner : l'écran lit directement la base SQLite
alimentée par /v1/triage.

Tout est visible d'un seul coup d'œil :
- bandeau de compteurs (rafraîchissement automatique optionnel)
- file d'attente | e-mail reçu | analyse automatique, côte à côte
- brouillon éditable et actions valider / corriger / rejeter
- motifs d'escalade et journal des décisions humaines en bas de page
Les réglages (seuils, table de règles) vivent dans la barre latérale.

Note sur la PII : le corps brut affiché ici contient les données réelles.
C'est volontaire — l'agent doit voir l'e-mail tel que le client l'a écrit.
Ce qui compte, c'est que le LLM, lui, n'ait vu que la version masquée : les
deux sont affichées au même endroit pour le prouver.

Note technique : aucune dépendance à pandas. `st.dataframe` et `st.bar_chart`
l'importent, or sa DLL native est bloquée par le contrôle d'application sur
certains postes Windows. Tableaux et graphiques sont rendus en HTML/CSS.
"""
import html
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import streamlit as st

import demo_mode
import live_demo
import rules
import runtime_config
import store

st.set_page_config(page_title="IntelliMail — Validation humaine",
                   page_icon="✉️", layout="wide",
                   initial_sidebar_state="expanded")

CATEGORIES = ["reclamation", "resiliation", "donnees_personnelles", "demande",
              "information", "facturation", "support_technique", "spam", "autre"]
PRIORITES = ["haute", "normale", "basse"]

# ─── Palette ────────────────────────────────────────────────────────────
NAVY, BLUE = "#0F2B46", "#1F6FEB"
ORANGE, RED, GREEN, VIOLET, GRAY = "#E67E22", "#C0392B", "#1E8449", "#7D3C98", "#64748B"

# Familles de motifs d'escalade : couleur + libellé métier + pastille
REASON_FAMILIES = {
    "rules_table":      (BLUE,   "Règle de catégorie",  "🟦"),
    "priorite":         (RED,    "Urgence",             "🟥"),
    "sensitive":        (ORANGE, "Opération sensible",  "🟧"),
    "output_guardrail": (VIOLET, "Garde-fou de sortie", "🟪"),
    "degenerate_input": (GRAY,   "Entrée vide",         "⬜"),
    "judge_reject":     (VIOLET, "Rejet du judge",      "🟪"),
    "seuils":           (GREEN,  "Seuil de confiance",  "🟩"),
}
PRIORITY_COLOR = {"haute": RED, "normale": BLUE, "basse": GRAY}
DECISION_STYLE = {
    store.STATUS_VALIDATED: (GREEN,  "Validé"),
    store.STATUS_EDITED:    (ORANGE, "Corrigé"),
    store.STATUS_REJECTED:  (RED,    "Rejeté"),
    store.STATUS_PENDING:   (GRAY,   "En attente"),
}

CSS = """
<style>
  .block-container {padding-top: 1.6rem; padding-bottom: 2rem; max-width: 1680px;}
  h1,h2,h3,h4 {color:#0F2B46; letter-spacing:-.3px;}
  hr {margin: .9rem 0;}

  @keyframes im-fade  {from{opacity:0;transform:translateY(9px)} to{opacity:1;transform:none}}
  @keyframes im-grow  {from{width:0} to{width:var(--w)}}
  @keyframes im-slide {0%,100%{background-position:0% 50%} 50%{background-position:100% 50%}}
  @keyframes im-pulse {0%{box-shadow:0 0 0 0 rgba(34,197,94,.55)}
                       70%{box-shadow:0 0 0 10px rgba(34,197,94,0)}
                       100%{box-shadow:0 0 0 0 rgba(34,197,94,0)}}
  @keyframes im-pop   {from{transform:scale(.94);opacity:0} to{transform:scale(1);opacity:1}}

  /* Bandeau titre : dégradé animé lent */
  .im-hero{
    background:linear-gradient(110deg,#0F2B46,#1F4E79,#1F6FEB,#1F4E79,#0F2B46);
    background-size:300% 100%; animation:im-slide 16s ease-in-out infinite;
    color:#fff; padding:18px 26px; border-radius:14px; margin-bottom:14px;
    display:flex; justify-content:space-between; align-items:center; gap:20px;
  }
  .im-hero h1{color:#fff;margin:0 0 3px 0;font-size:1.6rem;}
  .im-hero p {margin:0;opacity:.85;font-size:.88rem;}
  .im-live{display:inline-block;width:8px;height:8px;border-radius:50%;
           background:#22C55E;animation:im-pulse 1.9s infinite;margin-right:7px;}

  .im-kpis{display:flex;gap:12px;margin-bottom:6px;flex-wrap:wrap;}
  .im-kpi{
    flex:1 1 140px;background:#fff;border:1px solid #E3EAF3;
    border-left:5px solid var(--c);border-radius:11px;padding:11px 16px;
    box-shadow:0 1px 3px rgba(15,43,70,.06);
    animation:im-fade .5s ease both;transition:transform .18s,box-shadow .18s;
  }
  .im-kpi:hover{transform:translateY(-3px);box-shadow:0 8px 20px rgba(15,43,70,.11);}
  .im-kpi:nth-child(2){animation-delay:.06s} .im-kpi:nth-child(3){animation-delay:.12s}
  .im-kpi:nth-child(4){animation-delay:.18s} .im-kpi:nth-child(5){animation-delay:.24s}
  .im-kpi .lab{font-size:.72rem;text-transform:uppercase;letter-spacing:.6px;
               color:#64748B;font-weight:600;}
  .im-kpi .val{font-size:1.8rem;font-weight:700;color:var(--c);line-height:1.15;
               animation:im-pop .45s ease both;}

  .im-badge,.im-badge-soft{display:inline-block;padding:3px 11px;border-radius:999px;
    font-size:.75rem;font-weight:600;white-space:nowrap;}
  .im-badge{color:#fff;background:var(--c);}
  .im-badge-soft{color:var(--c);background:color-mix(in srgb,var(--c) 13%,white);
                 border:1px solid color-mix(in srgb,var(--c) 32%,white);}

  .im-card{background:#fff;border:1px solid #E3EAF3;border-radius:12px;
    padding:14px 16px;box-shadow:0 1px 3px rgba(15,43,70,.06);margin-bottom:10px;
    animation:im-fade .45s ease both;transition:transform .18s,box-shadow .18s;}
  .im-card:hover{transform:translateY(-2px);box-shadow:0 7px 18px rgba(15,43,70,.10);}

  .im-reason{border-left:5px solid var(--c);
    background:color-mix(in srgb,var(--c) 8%,white);
    border-radius:10px;padding:11px 15px;margin-bottom:10px;
    animation:im-fade .4s ease both;}
  .im-reason .t{font-weight:700;color:var(--c);font-size:.93rem;}
  .im-reason .w{color:#40566E;font-size:.84rem;margin-top:3px;}
  .im-reason code{background:rgba(15,43,70,.07);padding:1px 6px;border-radius:5px;
                  font-size:.78rem;color:#0F2B46;}

  .im-bar{height:9px;border-radius:6px;background:#EDF2F9;overflow:hidden;}
  .im-bar>span{display:block;height:100%;background:var(--c);width:var(--w);
               border-radius:6px;animation:im-grow .95s cubic-bezier(.2,.8,.2,1) both;}

  table.im-tbl{width:100%;border-collapse:collapse;font-size:.84rem;}
  table.im-tbl th{background:#0F2B46;color:#fff;text-align:left;padding:8px 10px;
    font-weight:600;font-size:.73rem;text-transform:uppercase;letter-spacing:.4px;
    position:sticky;top:0;}
  table.im-tbl td{padding:8px 10px;border-bottom:1px solid #EDF2F9;color:#23405B;}
  table.im-tbl tbody tr{transition:background .15s;}
  table.im-tbl tbody tr:hover td{background:#EAF2FE;}

  div[data-testid="stRadio"] label p{font-size:.86rem;}
  div[data-testid="stRadio"] label{border-radius:8px;padding:2px 6px;
    transition:background .15s;}
  div[data-testid="stRadio"] label:hover{background:#EAF2FE;}
  .stTextArea textarea{font-family:ui-monospace,"Cascadia Code",monospace;
                       font-size:.85rem;}
  .stButton button{transition:transform .12s, box-shadow .12s;}
  .stButton button:hover{transform:translateY(-1px);
                         box-shadow:0 5px 14px rgba(31,111,235,.22);}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ─── Mode démo publique ─────────────────────────────────────────────────
# Chaque visiteur reçoit sa propre copie de la file, reconstruite depuis une
# fixture versionnée : ses validations n'affectent personne d'autre, et aucun
# appel LLM n'est déclenché. Doit être exécuté AVANT toute lecture du store.
DEMO = demo_mode.is_demo()
if DEMO:
    if "demo_sid" not in st.session_state:
        st.session_state.demo_sid = uuid4().hex
        demo_mode.purger_anciennes()
    if demo_mode.preparer_session(st.session_state.demo_sid) is None:
        st.error(
            "Mode démo activé mais `demo/demo_fixture.json` est introuvable.\n\n"
            "Générez-la en local : `python seed_queue.py --reset` puis "
            "`python demo/export_fixture.py`, et committez le fichier.")
        st.stop()


# ─── Helpers de rendu (sans pandas) ─────────────────────────────────────
def _json(value, default):
    import json
    try:
        return json.loads(value) if value else default
    except Exception:
        return default


def _agent() -> str:
    """Identité de l'agent — journalisée avec chaque décision."""
    return st.session_state.get("agent_name") or "agent_anonyme"


def reason_family(reason: str):
    """(couleur, libellé métier, pastille) d'un motif d'escalade."""
    key = (reason or "seuils").split(":", 1)[0]
    return REASON_FAMILIES.get(key, (GRAY, key, "⬜"))


def badge(text, color, soft=False) -> str:
    cls = "im-badge-soft" if soft else "im-badge"
    return f'<span class="{cls}" style="--c:{color}">{html.escape(str(text))}</span>'


def bar_row(label: str, value: float, color: str, right: str = "") -> str:
    """Ligne libellé + barre animée. `value` dans [0,1]."""
    pct = max(0.0, min(1.0, value)) * 100
    return (f'<div style="margin-bottom:9px">'
            f'<div style="display:flex;justify-content:space-between;'
            f'font-size:.8rem;color:#23405B;margin-bottom:3px">'
            f'<span>{label}</span><b>{right}</b></div>'
            f'<div class="im-bar" style="--c:{color}">'
            f'<span style="--w:{pct:.0f}%"></span></div></div>')


def html_table(rows: list, renderers=None) -> str:
    """Tableau HTML. `renderers` = {colonne: fn -> HTML} pour les cellules
    riches (badges). Tout le reste est échappé."""
    if not rows:
        return ""
    renderers = renderers or {}
    cols = list(rows[0].keys())
    head = "".join(f"<th>{html.escape(c)}</th>" for c in cols)
    body = ""
    for r in rows:
        cells = "".join(
            f"<td>{renderers[c](r.get(c, '')) if c in renderers else html.escape(str(r.get(c, '')))}</td>"
            for c in cols)
        body += f"<tr>{cells}</tr>"
    return (f'<table class="im-tbl"><thead><tr>{head}</tr></thead>'
            f'<tbody>{body}</tbody></table>')


# ─── Barre latérale : agent, filtres, réglages ──────────────────────────
if DEMO:
    _fx = demo_mode.info_fixture()
    st.markdown(
        f'<div class="im-reason" style="--c:{ORANGE}">'
        f'<div class="t">🎭 Démonstration — données fictives</div>'
        f'<div class="w">Ces e-mails sont un jeu de test synthétique : aucun '
        f'client réel, aucune donnée personnelle authentique. Vous disposez de '
        f'votre propre copie de la file — validez, corrigez, rejetez librement, '
        f'personne d\'autre n\'est affecté.</div>'
        f'<div class="w">Aucun appel au modèle n\'est déclenché : les '
        f'brouillons et les décisions d\'escalade ont été calculés à l\'avance '
        f'par le pipeline{" le " + _fx["genere_le"][:10] if _fx.get("genere_le") else ""}.'
        f'</div></div>', unsafe_allow_html=True)

with st.sidebar:
    if DEMO:
        st.markdown("### 🎭 Démonstration")
        if st.button("↺ Réinitialiser ma file", use_container_width=True,
                     help="Restaure les cas d'origine et remet votre compteur "
                          "d'analyses à zéro. N'affecte que vous."):
            demo_mode.reinitialiser(st.session_state.demo_sid)
            st.session_state.live_count = 0
            st.rerun()
        st.caption("Code source : github.com/abdelhak-saket/intellimail")
        st.divider()

    st.markdown("### 👤 Agent")
    st.text_input("Votre identifiant", key="agent_name", placeholder="prenom.nom",
                  label_visibility="collapsed",
                  help="Journalisé avec chaque décision (piste d'audit).")
    if not st.session_state.get("agent_name"):
        st.caption("⚠️ Sans identifiant, les décisions seront signées "
                   "« agent_anonyme ».")

    st.markdown("### 🔎 Filtres")
    statut = st.selectbox("Statut", ["pending", "all", "validated", "edited",
                                     "rejected"], index=0)
    cat_filtre = st.selectbox("Catégorie", [""] + CATEGORIES, index=0,
                              format_func=lambda c: c or "toutes")
    auto = st.toggle("Actualisation auto (5 s)", value=False,
                     help="Rafraîchit les compteurs sans recharger la page.")
    if st.button("↻ Rafraîchir maintenant", use_container_width=True):
        st.rerun()

    st.divider()
    st.markdown("### ⚙️ Seuils de décision")
    st.caption("Relus par l'API au prochain e-mail, sans redémarrage. "
               "Chaque modification est horodatée et signée.")
    cfg = runtime_config.as_dict()
    meta = runtime_config.metadata()
    if meta:
        st.markdown(badge(f"modifié {meta.get('updated_at', '')[:16]} par "
                          f"{meta.get('updated_by')}", NAVY, soft=True),
                    unsafe_allow_html=True)

    seuil_auto = st.slider("SEUIL_AUTO — envoi automatique", 0.0, 1.0,
                           float(cfg["SEUIL_AUTO"]), 0.01)
    seuil_hitl = st.slider("SEUIL_HITL — validation humaine", 0.0, 1.0,
                           float(cfg["SEUIL_HITL"]), 0.01)
    seuil_judge = st.slider("Note minimale du judge", 0.0, 1.0,
                            float(cfg["CRITIC_APPROVE_THRESHOLD"]), 0.01)
    if seuil_hitl > seuil_auto:
        st.error("SEUIL_HITL doit rester sous SEUIL_AUTO.")

    st.markdown("### 🛡️ Table de règles")
    st.caption("Appliquées **avant** les seuils : un e-mail concerné part en "
               "validation humaine quelle que soit sa confiance.")
    cats = st.multiselect(
        "Catégories à escalade forcée", CATEGORIES,
        default=[c for c in CATEGORIES if c in
                 {x.strip() for x in str(cfg["HITL_FORCE_CATEGORIES"]).split(",")}])
    pris = st.multiselect(
        "Priorités à escalade forcée", PRIORITES,
        default=[p for p in PRIORITES if p in
                 {x.strip() for x in str(cfg["HITL_FORCE_PRIORITIES"]).split(",")}])
    sens_on = st.toggle("🟧 Règles d'opérations sensibles (entrée)",
                        value=bool(cfg["SENSITIVE_RULES_ENABLED"]))
    out_on = st.toggle("🟪 Garde-fou de sortie (brouillon)",
                       value=bool(cfg["OUTPUT_GUARDRAIL_ENABLED"]))

    sb1, sb2 = st.columns(2)
    if sb1.button("Enregistrer", type="primary", use_container_width=True,
                  disabled=seuil_hitl > seuil_auto):
        runtime_config.save({
            "SEUIL_AUTO": seuil_auto, "SEUIL_HITL": seuil_hitl,
            "CRITIC_APPROVE_THRESHOLD": seuil_judge,
            "HITL_FORCE_CATEGORIES": ",".join(cats),
            "HITL_FORCE_PRIORITIES": ",".join(pris),
            "SENSITIVE_RULES_ENABLED": sens_on,
            "OUTPUT_GUARDRAIL_ENABLED": out_on,
        }, updated_by=_agent())
        st.success("Réglages appliqués.")
        st.rerun()
    if sb2.button(".env", use_container_width=True, help="Revenir aux défauts"):
        runtime_config.reset()
        st.rerun()

    with st.expander("📖 Détail des règles"):
        st.markdown(badge("Entrée — opérations sensibles", ORANGE),
                    unsafe_allow_html=True)
        for lab, _, why in rules.SENSITIVE_PATTERNS:
            st.caption(f"**{lab}** — {why}")
        for k in ("expediteur_automatique", "pii_sensible",
                  "piece_jointe_sans_contexte"):
            st.caption(f"**{k}** — {rules.justification(k)}")
        st.markdown(badge("Sortie — brouillon produit", VIOLET),
                    unsafe_allow_html=True)
        for lab, _, why in rules.DRAFT_FORBIDDEN:
            st.caption(f"**{lab}** — {why}")


# ─── Bandeau + compteurs (fragment auto-rafraîchi si activé) ────────────
def _render_head():
    stats = store.stats()
    traites = sum(stats["by_status"].get(s, 0) for s in
                  (store.STATUS_VALIDATED, store.STATUS_EDITED,
                   store.STATUS_REJECTED))
    st.markdown(
        '<div class="im-hero"><div>'
        '<h1>✉️ IntelliMail — Validation humaine</h1>'
        '<p>Triage automatisé des e-mails clients · chaque escalade est motivée '
        'par une règle traçable · chaque décision humaine est journalisée</p>'
        '</div><div style="text-align:right;font-size:.82rem;opacity:.9">'
        f'<span class="im-live"></span>en direct<br>'
        f'{datetime.now().strftime("%d/%m/%Y %H:%M:%S")}</div></div>',
        unsafe_allow_html=True)
    cards = [("En attente", stats["pending"], BLUE),
             ("Validés", stats["by_status"].get(store.STATUS_VALIDATED, 0), GREEN),
             ("Corrigés", stats["by_status"].get(store.STATUS_EDITED, 0), ORANGE),
             ("Rejetés", stats["by_status"].get(store.STATUS_REJECTED, 0), RED),
             ("Décisions tracées", stats["total_decisions"], NAVY),
             ("Traités", traites, VIOLET)]
    st.markdown('<div class="im-kpis">' + "".join(
        f'<div class="im-kpi" style="--c:{c}"><div class="lab">{l}</div>'
        f'<div class="val">{v}</div></div>' for l, v, c in cards)
        + '</div>', unsafe_allow_html=True)
    return stats


# st.fragment (Streamlit ≥ 1.37) permet de rafraîchir ce bloc seul, sans
# relancer toute la page ni perdre la saisie en cours dans le brouillon.
try:
    _head = st.fragment(run_every=5 if auto else None)(_render_head)
except AttributeError:      # version plus ancienne : rendu statique
    _head = _render_head
_head()
stats = store.stats()

st.markdown("")

# ─── Ligne 1 : file · e-mail · analyse ──────────────────────────────────
col_file, col_mail, col_ana = st.columns([1.15, 1.5, 1.35], gap="medium")
cases = store.list_queue(status=statut, categorie=cat_filtre)

with col_file:
    st.markdown("#### 📥 File d'attente")
    if not cases:
        st.success("Aucun e-mail avec ces filtres.")
        case = None
    else:
        st.caption(f"{len(cases)} e-mail(s) — du plus ancien au plus récent")

        def _label(i):
            c = cases[i]
            _, fam, dot = reason_family(c["decision_reason"])
            return (f"{dot}  **#{c['id']}** · "
                    f"{(c['subject_raw'] or '(sans objet)')[:44]}  \n"
                    f"　　{c['categorie']} · {fam}")

        with st.container(height=430):
            idx = st.radio("File", range(len(cases)), format_func=_label,
                           label_visibility="collapsed")
        case = store.get_case(cases[idx]["id"])

if case:
    color, famille, dot = reason_family(case["decision_reason"])

    with col_mail:
        st.markdown("#### 📧 E-mail reçu")
        st.caption(f"De : {case['email_from']} · reçu {case['created_at'][:16]}")
        vue = st.radio("Vue", ["Brut (écrit par le client)",
                               "Masqué (vu par le LLM)"],
                       horizontal=True, key=f"vue_{case['id']}",
                       label_visibility="collapsed")
        brut = vue.startswith("Brut")
        st.text_input("Sujet",
                      case["subject_raw"] if brut else case["subject_masked"],
                      disabled=True, key=f"s_{case['id']}_{brut}")
        st.text_area("Corps", case["body_raw"] if brut else case["body_masked"],
                     height=230, disabled=True, key=f"b_{case['id']}_{brut}")
        pii = _json(case["pii_entities"], {})
        st.markdown(
            ("🛡️ PII masquée avant tout appel LLM : "
             + " ".join(badge(f"{k} ×{v}", GREEN, soft=True) for k, v in pii.items()))
            if pii else "🛡️ Aucune donnée personnelle détectée.",
            unsafe_allow_html=True)

    with col_ana:
        st.markdown("#### 🧭 Analyse automatique")
        why = rules.justification(
            case["decision_reason"].split(":", 1)[-1].split("+")[0])
        st.markdown(
            f'<div class="im-reason" style="--c:{color}">'
            f'<div class="t">{dot} Escalade — {html.escape(famille)}</div>'
            f'<div class="w">{html.escape(why) if why else ""}</div>'
            f'<div class="w"><code>{html.escape(case["decision_reason"])}</code>'
            f'</div></div>', unsafe_allow_html=True)
        st.markdown(
            badge(case["categorie"], NAVY) + " "
            + badge(f"priorité {case['priorite']}",
                    PRIORITY_COLOR.get(case["priorite"], GRAY)) + " "
            + badge(f"confiance {case['confiance']:.2f}",
                    GREEN if case["confiance"] >= .85 else ORANGE, soft=True),
            unsafe_allow_html=True)
        st.caption(case["resume"] or "—")

        scores = _json(case["judge_scores"], {})
        if scores:
            st.markdown(
                '<div class="im-card"><b style="font-size:.85rem">'
                'Évaluation du brouillon par le judge</b><div style="height:8px">'
                '</div>'
                + "".join(bar_row(k.capitalize(), v / 5, BLUE, f"{v}/5")
                          for k, v in scores.items())
                + '</div>', unsafe_allow_html=True)

        contexts = _json(case["contexts"], [])
        with st.expander(f"📚 Contextes documentaires ({len(contexts)})"):
            for ctx in contexts or ["Aucun contexte trouvé."]:
                st.caption(ctx)
        with st.expander("🔧 Trace des agents"):
            for t in _json(case["agent_trace"], []):
                st.caption(f"{'🟢' if t.get('success') else '🔴'} "
                           f"**{t.get('agent')}** · {t.get('duration_ms')} ms · "
                           f"{t.get('note') or ''}")
        st.caption(f"💰 {case['cost_usd']:.5f} $ · ⏱️ {case['duration_ms']} ms")

    # ─── Ligne 2 : brouillon + actions ──────────────────────────────────
    st.markdown("#### ✍️ Brouillon proposé")
    d_col, a_col = st.columns([2.6, 1], gap="medium")

    with d_col:
        reinj = _json(case["pii_reinjection"], {})
        if reinj:
            st.info("🔁 Réinjection par le robot à l'envoi : "
                    + ", ".join(f"`{k}` → **{v}**" for k, v in reinj.items()))
        draft = st.text_area("Réponse au client", case["draft"] or "", height=190,
                             key=f"draft_{case['id']}", label_visibility="collapsed")
        modifie = draft.strip() != (case["draft"] or "").strip()
        alertes = rules.check_draft_output(draft)
        if alertes:
            st.markdown(
                f'<div class="im-reason" style="--c:{VIOLET}">'
                f'<div class="t">🟪 Garde-fou de sortie déclenché</div>'
                + "".join(f'<div class="w">• <code>{html.escape(a)}</code> — '
                          f'{html.escape(rules.justification(a))}</div>'
                          for a in alertes) + '</div>', unsafe_allow_html=True)

    with a_col:
        commentaire = st.text_input("Commentaire", key=f"com_{case['id']}",
                                    placeholder="Motif de la correction…",
                                    label_visibility="collapsed")
        if case["status"] != store.STATUS_PENDING:
            c, lab = DECISION_STYLE.get(case["status"], (GRAY, case["status"]))
            st.markdown("Déjà traité — " + badge(lab, c), unsafe_allow_html=True)
        if st.button("✅ Valider et envoyer", use_container_width=True,
                     type="primary", disabled=modifie):
            store.record_decision(case["id"], store.STATUS_VALIDATED, _agent(),
                                  draft, commentaire)
            st.rerun()
        if st.button("✏️ Enregistrer la correction", use_container_width=True,
                     disabled=not modifie):
            store.record_decision(case["id"], store.STATUS_EDITED, _agent(),
                                  draft, commentaire)
            st.rerun()
        if st.button("🚫 Rejeter", use_container_width=True):
            store.record_decision(case["id"], store.STATUS_REJECTED, _agent(),
                                  "", commentaire)
            st.rerun()
        if modifie:
            st.caption("Brouillon modifié → « Enregistrer la correction ».")

        historique = store.decisions_for(case["id"])
        if historique:
            with st.expander(f"🕓 Historique ({len(historique)})"):
                for d in historique:
                    c, lab = DECISION_STYLE.get(d["decision"], (GRAY, d["decision"]))
                    st.markdown(f"{badge(lab, c)} **{d['decided_by']}**  \n"
                                f"{d['decided_at'][:16]} "
                                f"{html.escape(d['comment'] or '')}",
                                unsafe_allow_html=True)

st.divider()

# ─── Bac à sable : le visiteur soumet son propre e-mail ─────────────────
with st.expander("🧪 **Testez votre propre e-mail** — voyez ce que le système "
                 "en ferait", expanded=False):
    live_actif = live_demo.actif()
    used_jour, plafond_jour = live_demo.consommation_jour()
    fait_session = st.session_state.get("live_count", 0)

    c1, c2 = st.columns([1, 2])
    with c1:
        exemple = st.selectbox("Partir d'un exemple",
                               ["(vide)"] + list(live_demo.EXEMPLES))
        if st.button("Charger l'exemple", use_container_width=True,
                     disabled=exemple == "(vide)"):
            f, s, b = live_demo.EXEMPLES[exemple]
            st.session_state.update({"live_from": f, "live_subj": s, "live_body": b})
            st.rerun()
        if live_actif:
            st.caption(f"Analyses complètes : {live_demo.max_par_session() - fait_session} "
                       f"restantes pour vous · {plafond_jour - used_jour} "
                       f"aujourd'hui tous visiteurs confondus")
        else:
            st.caption("Analyse déterministe uniquement (masquage et règles). "
                       "Illimitée et instantanée.")

    with c2:
        e_from = st.text_input("Expéditeur", key="live_from",
                               placeholder="prenom.nom@exemple.fr")
        e_subj = st.text_input("Sujet", key="live_subj")
    e_body = st.text_area("Corps de l'e-mail", key="live_body", height=160,
                          placeholder="Écrivez ou collez un e-mail client…")

    b1, b2 = st.columns(2)
    lancer_det = b1.button("🛡️ Analyse déterministe (gratuite, instantanée)",
                           use_container_width=True)
    lancer_full = b2.button("🤖 Pipeline complet (appelle le modèle)",
                            use_container_width=True, type="primary",
                            disabled=not live_actif)

    if lancer_det or lancer_full:
        if not (e_body or "").strip():
            st.warning("Écrivez un e-mail, ou chargez un exemple.")
        else:
            det = live_demo.analyse_deterministe(e_from, e_subj, e_body)
            g1, g2 = st.columns(2)
            g1.markdown("**Ce que le client a écrit**")
            g1.text_area("brut", e_body, height=150, disabled=True,
                         key="live_out_raw", label_visibility="collapsed")
            g2.markdown("**Ce que le modèle verrait**")
            g2.text_area("masqué", det["corps_masque"], height=150, disabled=True,
                         key="live_out_masked", label_visibility="collapsed")
            st.markdown(
                ("🛡️ Masqué avant tout appel : "
                 + " ".join(badge(f"{k} ×{v}", GREEN, soft=True)
                            for k, v in det["pii"].items()))
                if det["pii"] else
                "🛡️ Aucune donnée personnelle détectée dans ce texte.",
                unsafe_allow_html=True)

            if det["degenere"]:
                st.markdown(
                    f'<div class="im-reason" style="--c:{GRAY}">'
                    f'<div class="t">⬜ Entrée dégénérée</div><div class="w">'
                    f'Corps trop court : escalade immédiate, <b>aucun appel au '
                    f'modèle</b>. Coût zéro.</div></div>', unsafe_allow_html=True)
            elif det["regles"]:
                st.markdown("".join(
                    f'<div class="im-reason" style="--c:{ORANGE}">'
                    f'<div class="t">🟧 {html.escape(r["code"])}</div>'
                    f'<div class="w">{html.escape(r["why"])}</div></div>'
                    for r in det["regles"]), unsafe_allow_html=True)
                st.caption("Ces règles suffisent à interdire l'envoi automatique, "
                           "sans qu'aucun modèle n'ait été consulté.")
            else:
                st.info("Aucune règle d'entrée déclenchée. La décision dépendrait "
                        "de la classification et de l'évaluation du brouillon.")

    if lancer_full and (e_body or "").strip():
        ok, motif = live_demo.verifier(e_body, fait_session)
        if not ok:
            st.warning(motif)
        else:
            with st.spinner("Classification, recherche documentaire, rédaction, "
                            "évaluation…"):
                try:
                    res = live_demo.analyse_complete(e_from, e_subj, e_body)
                except Exception as e:
                    res = None
                    st.error(f"Le pipeline a échoué : {type(e).__name__}: {e}")
            if res:
                # Une analyse qui n'a produit aucun brouillon (panne côté
                # modèle) ne consomme pas le quota du visiteur : il n'a rien
                # obtenu. Le plafond journalier, lui, reste décompté — des
                # jetons ont pu être consommés avant l'échec.
                echec_total = bool(res["errors"]) and not (res["draft"] or "").strip()
                if not echec_total:
                    st.session_state.live_count = fait_session + 1
                col, fam, dot = reason_family(res["decision_reason"])
                st.markdown(
                    f'<div class="im-reason" style="--c:{col}">'
                    f'<div class="t">{dot} Décision : {res["action"]} — '
                    f'{html.escape(fam)}</div>'
                    f'<div class="w">{html.escape(res["decision_why"] or "")}</div>'
                    f'<div class="w"><code>{html.escape(res["decision_reason"])}'
                    f'</code></div></div>', unsafe_allow_html=True)
                st.markdown(
                    badge(res["categorie"], NAVY) + " "
                    + badge(f"priorité {res['priorite']}",
                            PRIORITY_COLOR.get(res["priorite"], GRAY)) + " "
                    + badge(f"confiance {res['confiance']:.2f}",
                            GREEN if res["confiance"] >= .85 else ORANGE, soft=True)
                    + " " + badge(f"judge {res['judge_verdict']}", VIOLET, soft=True),
                    unsafe_allow_html=True)
                if res["errors"]:
                    st.error(
                        "**Les appels au modèle ont échoué.** Le pipeline a "
                        "appliqué son repli de sécurité (catégorie « autre », "
                        "confiance 0, escalade humaine) — c'est le comportement "
                        "voulu en cas de panne, mais aucun brouillon n'a pu "
                        "être rédigé.\n\n**Détail :**\n\n"
                        + "\n\n".join(f"- `{e[:400]}`" for e in res["errors"]))
                    emp = {}
                    if any("401" in e or "Authentication" in e
                           for e in res["errors"]):
                        import llm as _llm
                        # getattr : si le module déployé est d'une version
                        # antérieure, on n'affiche pas le diagnostic plutôt que
                        # de faire planter toute la page.
                        _emp = getattr(_llm, "empreinte_identifiants", None)
                        emp = _emp() if _emp else {}
                    if emp:
                        st.warning(
                            "**Diagnostic des identifiants** (aucune donnée "
                            "sensible n'est affichée) — comparez ces valeurs "
                            "avec celles qui fonctionnent en local :\n\n"
                            + "\n".join(f"- {k} : `{v}`" for k, v in emp.items())
                            + "\n\nUne longueur inattendue ou "
                              "`espaces_parasites: True` signale un caractère "
                              "invisible collé dans la valeur.")

                st.markdown("**Brouillon proposé**")
                st.text_area("draft", res["draft"] or "(aucun)", height=170,
                             disabled=True, key="live_out_draft",
                             label_visibility="collapsed")
                if res["contexts"]:
                    with st.expander(f"📚 Procédures utilisées ({len(res['contexts'])})"):
                        for c in res["contexts"]:
                            st.caption(c)
                st.caption(f"⏱️ {res['duration_ms']} ms · 💰 {res['cost_usd']:.5f} $ · "
                           f"{res['tokens_in']}+{res['tokens_out']} jetons")
                if res["errors"]:
                    st.caption("Incidents : " + " | ".join(res["errors"])[:300])

st.divider()

# ─── Ligne 3 : motifs d'escalade + journal d'audit ──────────────────────
col_motifs, col_journal = st.columns([1, 1.7], gap="medium")

with col_motifs:
    st.markdown("#### 📊 Motifs d'escalade")
    st.caption("Ce que les règles déterministes ont arrêté, et pourquoi.")
    by_reason = stats["by_reason"]
    if by_reason:
        top = max(by_reason.values()) or 1
        blocs = "".join(
            bar_row(f'{reason_family(r)[2]} <b>{html.escape(reason_family(r)[1])}</b>'
                    f' <code style="font-size:.72rem;color:#64748B">'
                    f'{html.escape(r)}</code>', n / top, reason_family(r)[0], str(n))
            for r, n in sorted(by_reason.items(), key=lambda kv: -kv[1]))
        st.markdown(f'<div class="im-card">{blocs}</div>', unsafe_allow_html=True)
    else:
        st.info("Aucun e-mail traité pour l'instant.")

with col_journal:
    st.markdown("#### 🔍 Journal des décisions humaines")
    st.caption("Append-only : une décision n'est jamais écrasée. Avec le motif "
               "d'escalade automatique, cela forme la piste d'audit complète.")
    lignes = []
    for c in store.list_queue(status="all", limit=1000):
        for d in store.decisions_for(c["id"]):
            lignes.append({
                "cas": f"#{c['id']}", "catégorie": c["categorie"],
                "motif d'escalade": c["decision_reason"],
                "décision": d["decision"], "agent": d["decided_by"],
                "horodatage": d["decided_at"][:16],
                "commentaire": d["comment"] or "",
            })
    if lignes:
        def _dec(v):
            c, lab = DECISION_STYLE.get(v, (GRAY, v))
            return badge(lab, c)

        def _motif(v):
            c, _, dot = reason_family(v)
            return f'{dot} <code style="color:{c}">{html.escape(str(v))}</code>'

        with st.container(height=330):
            st.markdown(html_table(lignes[::-1],
                                   {"décision": _dec, "motif d'escalade": _motif}),
                        unsafe_allow_html=True)
    else:
        st.info("Aucune décision enregistrée pour l'instant.")

    if st.button("⬇️ Exporter le journal en CSV (Power BI)"):
        out = Path(__file__).parent / "metrics" / "hitl_decisions.csv"
        out.parent.mkdir(exist_ok=True)
        n = store.export_decisions_csv(out)
        st.success(f"{n} ligne(s) → metrics/hitl_decisions.csv" if n
                   else "Rien à exporter.")
