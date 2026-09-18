"""Streamlit UI — Agentic Tender Assistant (HPE qualification MVP).

Run with `streamlit run app.py` (default port is 8507, set in
.streamlit/config.toml). Business workflow: query -> tender search -> tender
selection -> analyze -> structured qualification briefing -> human approval
-> feedback recording. See IMPLEMENTATION_LOG.md for what's real vs. fallback
in this environment (SIMAP/Tavily/NeMo are not reachable — search and
documents come from the local data/sample_tenders* fixtures).

The underlying sample tender documents (data/sample_tenders/*) are real
French-language procurement text (SIMAP is a French/German/Italian-speaking
Swiss platform) and are left untouched — the deterministic extraction agent
in src/agents/ingestion.py parses their French section headers, and several
tests search on French query terms. This file keeps every citation pointing
at that original French source text (accurate provenance), while presenting
an English translation alongside it wherever the source text is shown, via
the FR_EN_GLOSS table below.

This module is the visual layer only. All business logic (search, retrieval,
matching, scoring, feedback) lives in src/agents and src/pipeline and is
called here unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st

from src.agents.feedback import record_feedback
from src.agents.workflow import WorkflowOrchestrator
from src.schemas.briefing import HumanDecision, QualificationBriefing
from src.schemas.common import MatchStatus

st.set_page_config(page_title="HPE Tender Intelligence", page_icon="▪", layout="wide")

# ---------------------------------------------------------------------------
# FR -> EN gloss table for the local sample fixtures (data/sample_tenders*).
# Keyed by the exact string produced by src/agents/ingestion.py's parser (or
# the raw Tender.title / Tender.scope from data/sample_tenders.json). Not
# found -> the original source text is shown as-is with a "source text" tag,
# never silently dropped.
# ---------------------------------------------------------------------------
FR_EN_GLOSS: dict[str, str] = {
    # Tender titles
    "Fourniture de services d'infrastructure cloud hybride et support technique": "Hybrid Cloud Infrastructure Services and Technical Support",
    "Services de cybersécurité managés pour l'administration cantonale": "Managed Cybersecurity Services for the Cantonal Administration",
    "Modernisation du centre de données et services réseau": "Data Center Modernization and Network Services",
    "Fourniture de mobilier de bureau pour les administrations communales": "Office Furniture Supply for Municipal Administrations",
    # Tender scopes (Tender.scope, shown on cards)
    "Exploitation et support d'une infrastructure cloud hybride (data center + cloud public) pour les services cantonaux, incluant support technique 24/7 et modernisation progressive du data center existant.": "Operation and support of a hybrid cloud infrastructure (data center + public cloud) for cantonal services, including 24/7 technical support and progressive modernization of the existing data center.",
    "Surveillance de sécurité 24/7 (SOC managé), réponse aux incidents et durcissement de l'infrastructure réseau pour l'ensemble des directions cantonales.": "24/7 security monitoring (managed SOC), incident response, and network infrastructure hardening for all cantonal departments.",
    "Renouvellement de l'infrastructure hyperconvergée du centre de données municipal et mise à niveau des services réseau et de sauvegarde.": "Renewal of the municipal data center's hyperconverged infrastructure and upgrade of network and backup services.",
    "Fourniture, livraison et installation de mobilier de bureau (bureaux, sièges, rangements) pour plusieurs bâtiments administratifs communaux.": "Supply, delivery, and installation of office furniture (desks, seating, storage units) for several municipal administrative buildings.",
    # Requirement / capability-match descriptions (data/sample_tenders/*/cahier_des_charges.txt)
    "Le soumissionnaire doit disposer d'une certification ISO/IEC 27001 valide.": "The bidder must hold a valid ISO/IEC 27001 certification.",
    "Le soumissionnaire doit justifier d'une couverture d'assurance responsabilité civile professionnelle d'au moins CHF 5'000'000.": "The bidder must provide evidence of professional liability insurance coverage of at least CHF 5,000,000.",
    "Le soumissionnaire doit être inscrit au registre du commerce suisse ou disposer d'un établissement stable en Suisse.": "The bidder must be registered in the Swiss commercial register or have a permanent establishment in Switzerland.",
    "Le prestataire doit proposer une solution d'infrastructure hyperconvergée avec redondance géographique sur au moins 2 sites.": "The provider must propose a hyperconverged infrastructure solution with geographic redundancy across at least 2 sites.",
    "Support technique 24/7 avec un temps de réponse maximum de 4h pour les incidents critiques.": "24/7 technical support with a maximum response time of 4 hours for critical incidents.",
    "Capacité de modernisation progressive du data center existant vers une architecture cloud hybride.": "Capability to progressively modernize the existing data center toward a hybrid cloud architecture.",
    "Mise en place de services réseau sécurisés entre le data center et le cloud public.": "Deployment of secure network services between the data center and the public cloud.",
    "ISO 9001 (souhaitée, non obligatoire)": "ISO 9001 (desired, not mandatory)",
    "Au moins 2 références de projets d'infrastructure cloud ou data center réalisés en Suisse au cours des 5 dernières années.": "At least 2 references for cloud infrastructure or data center projects delivered in Switzerland within the last 5 years.",
    "Délai de mise en oeuvre technique important (redondance géographique sur 2 sites).": "Significant technical implementation timeline (geographic redundancy across 2 sites).",
    "Dépendance à la disponibilité de personnel certifié cloud hybride.": "Dependency on the availability of certified hybrid cloud personnel.",
    "Le soumissionnaire doit exploiter un centre opérationnel de sécurité (SOC) actif 24 heures sur 24, 7 jours sur 7.": "The bidder must operate a Security Operations Center (SOC) active 24 hours a day, 7 days a week.",
    "Le soumissionnaire doit disposer d'une certification SOC 2 Type II valide pour son centre opérationnel de sécurité.": "The bidder must hold a valid SOC 2 Type II certification for its security operations center.",
    "Détection et réponse aux incidents (SOC/SIEM) avec temps de détection maximal de 15 minutes.": "Incident detection and response (SOC/SIEM) with a maximum detection time of 15 minutes.",
    "Durcissement de l'infrastructure réseau et gestion des vulnérabilités.": "Network infrastructure hardening and vulnerability management.",
    "Rapports mensuels de posture de sécurité.": "Monthly security posture reports.",
    "Au moins 1 référence de SOC managé pour une entité publique suisse.": "At least 1 reference for a managed SOC delivered to a Swiss public-sector entity.",
    "Délai de soumission très court (moins de 4 semaines depuis la publication).": "Very short submission deadline (less than 4 weeks from publication).",
    "Exigence de disponibilité 24/7 dès le démarrage du contrat.": "24/7 availability required from contract start.",
    "Le soumissionnaire doit démontrer au moins 1 référence de modernisation de centre de données en Suisse au cours des 5 dernières années.": "The bidder must demonstrate at least 1 data center modernization reference in Switzerland within the last 5 years.",
    "Renouvellement de l'infrastructure hyperconvergée (calcul, stockage, virtualisation).": "Renewal of the hyperconverged infrastructure (compute, storage, virtualization).",
    "Modernisation des services réseau du centre de données.": "Modernization of the data center's network services.",
    "Mise à niveau de la solution de sauvegarde et reprise après sinistre.": "Upgrade of the backup and disaster recovery solution.",
    "Accompagnement en conseil pour la feuille de route de modernisation à moyen terme.": "Advisory support for the medium-term modernization roadmap.",
    "Au moins 1 référence de modernisation de centre de données en Suisse.": "At least 1 data center modernization reference in Switzerland.",
    "Fenêtre de bascule du centre de données existant à planifier avec précaution.": "Cutover window for the existing data center must be planned carefully.",
    "Le soumissionnaire doit fournir et installer du mobilier de bureau ergonomique certifié conforme aux normes EN 1335.": "The bidder must supply and install ergonomic office furniture certified compliant with EN 1335 standards.",
    "Le soumissionnaire doit être inscrit au registre du commerce suisse.": "The bidder must be registered in the Swiss commercial register.",
    "Livraison et montage sur site dans un délai de 6 semaines après commande.": "On-site delivery and assembly within 6 weeks of order.",
    "Garantie minimale de 5 ans sur le mobilier fourni.": "Minimum 5-year warranty on the furniture supplied.",
    "Au moins 2 références de fourniture de mobilier de bureau à des collectivités suisses.": "At least 2 references for office furniture supply to Swiss public authorities.",
}


def gloss(text: str | None) -> str | None:
    """English translation for a known FR source string, else None."""
    if not text:
        return None
    return FR_EN_GLOSS.get(text.strip())


import re as _re

_FRENCH_HINT_RE = _re.compile(
    r"[À-ÖØ-öø-ÿ]|\b(?:le|la|les|de|des|du|et|ou|doit|être|au|aux|pour|une|un|dans|avec|sans)\b",
    _re.IGNORECASE,
)


def looks_french(text: str) -> bool:
    """Heuristic: does this untranslated string look like French source text,
    as opposed to a language-neutral code/standard name (e.g. 'ISO/IEC 27001')?"""
    return bool(_FRENCH_HINT_RE.search(text))


def en_or_original(text: str) -> str:
    """Best-effort English display string: translated if known, else the original."""
    return gloss(text) or text


_GAP_PREFIX = "Confirmed gap: "


def en_risk_description(text: str) -> str:
    """Like en_or_original, but also translates the FR tail of agent-generated
    'Confirmed gap: <requirement>' risk strings (src/agents/briefing.py)."""
    if text.startswith(_GAP_PREFIX):
        return _GAP_PREFIX + en_or_original(text[len(_GAP_PREFIX) :])
    return en_or_original(text)


def render_source_text(text: str) -> None:
    """Render a piece of tender-sourced text: English translation primary,
    original French shown underneath so the citation stays accurate."""
    translation = gloss(text)
    if translation:
        st.markdown(translation)
        st.caption(f"Original source text (French): _{text}_")
    elif looks_french(text):
        st.markdown(text)
        st.caption("Untranslated original source text (French)")
    else:
        st.markdown(text)


# ---------------------------------------------------------------------------
# HPE enterprise palette
# ---------------------------------------------------------------------------
GREEN = "#01A982"
NAVY = "#1D2739"
BG_LIGHT = "#F5F7F9"
BLUE = "#0070AD"
AMBER = "#F5A623"
RED = "#D64545"
BORDER = "#D9E1E8"
MUTED = "#5B6472"

GREEN_TINT = "#E6F7F2"
AMBER_TINT = "#FDF1DD"
RED_TINT = "#FBE9E9"
BLUE_TINT = "#E7F1F8"

_REC_STYLE = {
    "GO": (GREEN, GREEN_TINT, "GO"),
    "MAYBE": (AMBER, AMBER_TINT, "MAYBE"),
    "NO-GO": (RED, RED_TINT, "NO-GO"),
}
_CONFIDENCE_STYLE = {
    "HIGH": (GREEN, GREEN_TINT),
    "MEDIUM": (AMBER, AMBER_TINT),
    "LOW": (RED, RED_TINT),
}
_SEVERITY_STYLE = {
    "high": (RED, RED_TINT),
    "medium": (AMBER, AMBER_TINT),
    "low": (BLUE, BLUE_TINT),
}
_STATUS_STYLE = {
    MatchStatus.MATCH: (GREEN, GREEN_TINT, "✓", "MATCH"),
    MatchStatus.PARTIAL_MATCH: (AMBER, AMBER_TINT, "~", "PARTIAL MATCH"),
    MatchStatus.UNKNOWN: (AMBER, AMBER_TINT, "?", "UNKNOWN"),
    MatchStatus.NO_MATCH: (RED, RED_TINT, "✕", "GAP"),
}

CUSTOM_CSS = f"""
<style>
.block-container {{padding-top: 3rem; padding-bottom: 2rem; max-width: 1400px;}}

/* ---- header ---- */
.hpe-header {{display:flex; align-items:center; gap:0.65rem; margin:0 0 0.15rem 0;}}
.hpe-logo {{
    background:{GREEN}; color:#fff; font-weight:800; font-size:0.78rem;
    padding:0.3rem 0.5rem; border-radius:6px; letter-spacing:0.03em;
}}
.hpe-divider {{color:{BORDER}; font-weight:400;}}
.hpe-title {{font-size:1.35rem; font-weight:700; color:{NAVY}; margin:0;}}
.hpe-subtitle {{color:{MUTED}; font-size:0.88rem; margin:0.1rem 0 0.8rem 0;}}

/* ---- review status bar (sticky call-to-action) ---- */
div[class*="st-key-review_action_bar"] {{
    position: sticky; top: 0.4rem; z-index: 999;
    background: #fff; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 0.6rem 0.9rem 0.7rem 0.9rem; margin-bottom: 0.9rem;
    box-shadow: 0 1px 4px rgba(29,39,57,0.06);
}}
.review-status-bar {{border-left: 4px solid transparent; padding-left: 0.7rem;}}
.review-status-bar.pending {{border-left-color:{AMBER};}}
.review-status-title {{font-weight:700; font-size:0.95rem; color:{NAVY};}}
.review-status-sub {{color:{MUTED}; font-size:0.8rem; margin-top:0.1rem;}}
.review-meta-inline {{color:{MUTED}; font-weight:400;}}

/* ---- confirmation banners ---- */
@keyframes hpeFadeSlideIn {{
    from {{opacity:0; transform: translateY(-6px);}}
    to {{opacity:1; transform: translateY(0);}}
}}
.hpe-banner {{
    animation: hpeFadeSlideIn 0.35s ease-out;
    border-radius:8px; padding:0.6rem 0.9rem; margin-bottom:0.7rem;
    font-weight:600; font-size:0.88rem; display:flex; align-items:center; gap:0.5rem;
}}
.hpe-banner .banner-icon {{font-weight:800; font-size:1.05rem;}}

/* ---- compact score-breakdown rows ---- */
.dim-row {{display:flex; align-items:center; gap:0.6rem; margin-bottom:0.3rem;}}
.dim-label {{flex:0 0 200px; font-size:0.8rem; color:{NAVY}; font-weight:600;}}
.dim-value {{flex:0 0 68px; font-size:0.72rem; color:{MUTED};}}
.dim-bar-track {{flex:1 1 auto; height:6px; border-radius:3px; background:{BORDER}; overflow:hidden;}}
.dim-bar-fill {{height:6px; border-radius:3px;}}

/* ---- generic compact card ---- */
.tender-card {{
    border: 1px solid {BORDER}; border-radius: 8px; padding: 0.75rem 0.9rem;
    background:#fff; margin-bottom: 0.7rem; min-height: 158px;
}}
.tender-card.selected {{border: 2px solid {GREEN}; background: {GREEN_TINT};}}
.card-title {{font-weight:700; color:{NAVY}; font-size:0.92rem; line-height:1.3; margin-bottom:0.2rem;}}
.card-meta {{color:{MUTED}; font-size:0.78rem; margin-bottom:0.5rem;}}
.card-row {{display:flex; justify-content:space-between; font-size:0.76rem; color:{NAVY};
    border-top:1px solid {BORDER}; padding-top:0.35rem; margin-top:0.35rem;}}
.card-row .cr-label {{color:{MUTED}; text-transform:uppercase; letter-spacing:0.03em; font-size:0.66rem;}}

/* ---- recommendation / score header ---- */
.rec-badge {{
    display: inline-block; padding: 0.3rem 0.8rem; border-radius: 6px;
    font-size: 1.05rem; font-weight: 700; letter-spacing: 0.03em;
}}
.score-number {{font-size: 2.1rem; font-weight: 800; line-height: 1;}}
.score-label {{color: {MUTED}; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.04em;}}
.conf-chip {{display: inline-block; padding: 0.18rem 0.55rem; border-radius: 6px; font-weight: 700; font-size: 0.76rem;}}
.score-bar-track {{width:100%; height:8px; border-radius:4px; background:{BORDER}; margin:0.35rem 0 0.5rem 0;}}
.score-bar-fill {{height:8px; border-radius:4px;}}

/* ---- KPI cards ---- */
.kpi-card {{
    border: 1px solid {BORDER}; border-radius: 8px; padding: 0.55rem 0.7rem;
    text-align: center; background:#fff;
}}
.kpi-value {{font-size: 1.25rem; font-weight: 800; color:{NAVY};}}
.kpi-label {{color: {MUTED}; font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.03em;}}

/* ---- indicators / badges ---- */
.status-badge {{
    display:inline-block; padding:0.05rem 0.4rem; border-radius:4px; font-weight:700;
    font-size:0.72rem; margin-right:0.4rem;
}}
.risk-row, .action-row {{
    border-radius: 6px; padding: 0.45rem 0.7rem; margin-bottom: 0.4rem; font-size: 0.86rem;
    border-left: 3px solid transparent;
}}
.action-row {{background: {BLUE_TINT}; border-left-color: {BLUE};}}
.req-row {{border-bottom:1px solid {BORDER}; padding:0.4rem 0; font-size:0.86rem; color:{NAVY};}}
.req-row:last-child {{border-bottom:none;}}
.req-source {{color:{MUTED}; font-size:0.72rem;}}

small.muted {{color: {MUTED};}}
hr {{margin: 0.9rem 0;}}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def score_bar(pct: float, color: str) -> str:
    pct = min(max(pct, 0.0), 1.0) * 100
    return (
        f'<div class="score-bar-track"><div class="score-bar-fill" '
        f'style="width:{pct:.0f}%; background:{color};"></div></div>'
    )


def status_badge(status: MatchStatus) -> str:
    color, bg, symbol, label = _STATUS_STYLE[status]
    return f'<span class="status-badge" style="color:{color};background:{bg};">{symbol} {label}</span>'


def dim_row(label: str, value: float, max_points: float, color: str = BLUE) -> str:
    pct = min(max((value / max_points) if max_points else 0.0, 0.0), 1.0) * 100
    return (
        f'<div class="dim-row"><span class="dim-label">{label}</span>'
        f'<span class="dim-value">{value:.1f} / {max_points}</span>'
        f'<div class="dim-bar-track"><div class="dim-bar-fill" '
        f'style="width:{pct:.0f}%; background:{color};"></div></div></div>'
    )


# ---------------------------------------------------------------------------
# Human review — status chip + confirmation banner (kept in st.session_state
# so it survives Streamlit reruns) + the review form shared by the dialog /
# fallback expander below.
# ---------------------------------------------------------------------------
_REVIEW_STATUS_LABELS = {
    "PENDING": "Pending review",
    "APPROVED": "Approved",
    "REJECTED": "Rejected",
    "MORE_RESEARCH": "More research requested",
}
_REVIEW_STATUS_STYLE = {
    "PENDING": (MUTED, "#EEF1F4"),
    "APPROVED": (GREEN, GREEN_TINT),
    "REJECTED": (RED, RED_TINT),
    "MORE_RESEARCH": (AMBER, AMBER_TINT),
}
_BANNER_STYLE = {
    "approved": (GREEN, GREEN_TINT, "✓", "Qualification briefing approved"),
    "rejected": (RED, RED_TINT, "✕", "Qualification briefing rejected"),
    "more_research": (AMBER, AMBER_TINT, "↻", "Additional research requested"),
}
HAS_DIALOG = hasattr(st, "dialog")


def get_review_state(tender_id: str) -> dict:
    return st.session_state.reviews.setdefault(
        tender_id, {"status": "PENDING", "reviewer": "", "notes": "", "timestamp": None}
    )


_REVIEW_CONFIRMATION_MESSAGE = {
    "APPROVED": "This qualification briefing has been approved.",
    "REJECTED": "This qualification briefing has been rejected.",
    "MORE_RESEARCH": "Additional research has been requested before a final decision.",
}


def render_review_status_bar(briefing: QualificationBriefing) -> None:
    """Prominent, sticky call-to-action next to the tender header: shows
    whether a human decision is still pending (amber, not alarming red) or
    already recorded (green/red/amber persistent status + who/when), plus
    the "Review & decide" button that opens the review dialog."""
    tender_id = briefing.tender.id
    state = get_review_state(tender_id)
    status = state["status"]

    with st.container(key="review_action_bar"):
        bar_col, btn_col = st.columns([4, 1.4], vertical_alignment="center")
        with bar_col:
            if status == "PENDING":
                st.markdown(
                    '<div class="review-status-bar pending">'
                    '<div class="review-status-title">Human review required</div>'
                    '<div class="review-status-sub">The AI recommendation is ready for approval.</div>'
                    "</div>",
                    unsafe_allow_html=True,
                )
            else:
                color, bg = _REVIEW_STATUS_STYLE[status]
                meta_bits = []
                if state["reviewer"]:
                    meta_bits.append(f"by {state['reviewer']}")
                if state["timestamp"]:
                    meta_bits.append(state["timestamp"])
                meta = f' <span class="review-meta-inline">({" · ".join(meta_bits)})</span>' if meta_bits else ""
                st.markdown(
                    f'<div class="review-status-bar" style="border-left-color:{color};">'
                    f'<div class="review-status-title" style="color:{color};">{_REVIEW_STATUS_LABELS[status]}</div>'
                    f'<div class="review-status-sub">{_REVIEW_CONFIRMATION_MESSAGE[status]}{meta}</div>'
                    "</div>",
                    unsafe_allow_html=True,
                )
        with btn_col:
            review_clicked = st.button(
                "Review & decide", key=f"review_btn_{tender_id}", type="primary", use_container_width=True
            )
            if review_clicked:
                if HAS_DIALOG:
                    open_review_dialog(briefing)
                else:
                    st.session_state[f"show_review_panel_{tender_id}"] = True

        if not HAS_DIALOG and st.session_state.get(f"show_review_panel_{tender_id}"):
            with st.expander("Review & decide", expanded=True):
                render_review_form(briefing)


def render_pending_banner(tender_id: str) -> None:
    banner = st.session_state.get("pending_banner")
    if not banner or banner.get("tender_id") != tender_id:
        return
    color, bg, icon, message = _BANNER_STYLE[banner["kind"]]
    st.markdown(
        f'<div class="hpe-banner" style="background:{bg};border-left:4px solid {color};color:{NAVY};">'
        f'<span class="banner-icon" style="color:{color};">{icon}</span> {message}</div>',
        unsafe_allow_html=True,
    )
    del st.session_state["pending_banner"]


def _submit_review(briefing: QualificationBriefing, decision: HumanDecision, status_key: str, kind: str, reviewer: str, notes: str) -> None:
    record_feedback(briefing, decision, reviewer=reviewer, notes=notes)
    state = get_review_state(briefing.tender.id)
    state["status"] = status_key
    state["reviewer"] = reviewer
    state["notes"] = notes
    state["timestamp"] = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    st.session_state.pending_banner = {"tender_id": briefing.tender.id, "kind": kind}
    st.rerun()


def render_review_form(briefing: QualificationBriefing) -> None:
    tender_id = briefing.tender.id
    state = get_review_state(tender_id)
    reviewer = st.text_input("Reviewer name", value=state["reviewer"], key=f"reviewer_input_{tender_id}")
    notes = st.text_area("Notes", value=state["notes"], key=f"notes_input_{tender_id}")
    # Stacked full-width buttons (not a 3-column row) so every label,
    # including "Request more research", is always fully readable.
    if st.button("Approve", type="primary", use_container_width=True, key=f"approve_{tender_id}"):
        _submit_review(briefing, HumanDecision.APPROVED, "APPROVED", "approved", reviewer, notes)
    if st.button("Reject", use_container_width=True, key=f"reject_{tender_id}"):
        _submit_review(briefing, HumanDecision.REJECTED, "REJECTED", "rejected", reviewer, notes)
    if st.button("Request more research", use_container_width=True, key=f"more_research_{tender_id}"):
        _submit_review(briefing, HumanDecision.MORE_RESEARCH, "MORE_RESEARCH", "more_research", reviewer, notes)
    st.download_button(
        "Download briefing JSON",
        briefing.model_dump_json(indent=2),
        file_name=f"{briefing.tender.id}-briefing.json",
        mime="application/json",
        use_container_width=True,
        key=f"download_{tender_id}",
    )


if HAS_DIALOG:

    @st.dialog("Review & decide", width="medium")
    def open_review_dialog(briefing: QualificationBriefing) -> None:
        render_review_form(briefing)


@st.cache_resource
def get_orchestrator() -> WorkflowOrchestrator:
    return WorkflowOrchestrator()


orchestrator = get_orchestrator()

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if "tenders" not in st.session_state:
    st.session_state.tenders = []
if "briefings" not in st.session_state:
    st.session_state.briefings = {}  # tender.id -> QualificationBriefing
if "selected_id" not in st.session_state:
    st.session_state.selected_id = None
if "last_query" not in st.session_state:
    st.session_state.last_query = ""
if "reviews" not in st.session_state:
    st.session_state.reviews = {}  # tender.id -> {status, reviewer, notes, timestamp}

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown(
    '<div class="hpe-header"><span class="hpe-logo">HPE</span>'
    '<span class="hpe-divider">|</span>'
    '<span class="hpe-title">Tender Intelligence</span></div>'
    '<div class="hpe-subtitle">Public tender qualification workspace</div>',
    unsafe_allow_html=True,
)

with st.expander("System status", expanded=False):
    st.caption(
        f"Search adapter: **{orchestrator.search_tool.adapter.name}** · "
        f"Document adapter: **{orchestrator.retrieval_tool.adapter.name}**"
    )
    st.caption(
        "SIMAP / Tavily / NeMo Agent Toolkit are not reachable from this environment, so both fall back "
        "to the local sample data in data/sample_tenders*. See IMPLEMENTATION_LOG.md for the full audit."
    )

# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
search_col, button_col = st.columns([6, 1], vertical_alignment="bottom")
with search_col:
    query = st.text_input(
        "Search query",
        value=st.session_state.last_query or "Find Swiss tenders related to cloud infrastructure, managed services and cybersecurity",
        label_visibility="collapsed",
        placeholder="Search tenders (e.g. cloud infrastructure, managed services, cybersecurity)...",
    )
with button_col:
    search_clicked = st.button("Search", type="primary", use_container_width=True)

if search_clicked:
    st.session_state.tenders = orchestrator.search(query)
    st.session_state.last_query = query
    st.session_state.selected_id = None

# ---------------------------------------------------------------------------
# Results — compact three-column tender grid
# ---------------------------------------------------------------------------
if st.session_state.tenders:
    st.markdown(f"###### Tenders found ({len(st.session_state.tenders)})")
    tenders = st.session_state.tenders
    for row_start in range(0, len(tenders), 3):
        row_tenders = tenders[row_start : row_start + 3]
        cols = st.columns(3)
        for col, tender in zip(cols, row_tenders):
            is_selected = st.session_state.selected_id == tender.id
            with col:
                title = en_or_original(tender.title)
                deadline_str = (
                    tender.submission_deadline.isoformat() if tender.submission_deadline else "UNKNOWN"
                )
                source_str = tender.source.value.replace("_", " ").title()
                st.markdown(
                    f'<div class="tender-card{" selected" if is_selected else ""}">'
                    f'<div class="card-title">{title}</div>'
                    f'<div class="card-meta">{tender.buyer or "Buyer UNKNOWN"} &middot; '
                    f'{tender.location or "Location UNKNOWN"}</div>'
                    f'<div class="card-row"><span><span class="cr-label">Deadline</span><br>{deadline_str}</span>'
                    f'<span style="text-align:right;"><span class="cr-label">Source</span><br>{source_str}</span></div>'
                    f"</div>",
                    unsafe_allow_html=True,
                )
                analyze_clicked = st.button(
                    "Analyzed" if tender.id in st.session_state.briefings else "Analyze",
                    key=f"analyze-{tender.id}",
                    type="secondary" if tender.id in st.session_state.briefings else "primary",
                    use_container_width=True,
                )
                if analyze_clicked:
                    with st.spinner("Retrieving documents, extracting requirements, matching against HPE profile..."):
                        st.session_state.briefings[tender.id] = orchestrator.analyze_tender(tender)
                    st.session_state.selected_id = tender.id
                    st.rerun()
elif query:
    st.info("Enter a query and click **Search** to find tenders.")

# ---------------------------------------------------------------------------
# Selected tender briefing
# ---------------------------------------------------------------------------
briefing: QualificationBriefing | None = st.session_state.briefings.get(st.session_state.selected_id)

if briefing is None and st.session_state.briefings:
    # Fall back to the most recently analyzed tender if none explicitly selected.
    last_id = list(st.session_state.briefings.keys())[-1]
    briefing = st.session_state.briefings[last_id]
    st.session_state.selected_id = last_id

if briefing:
    st.divider()
    render_pending_banner(briefing.tender.id)

    header_left, header_right = st.columns([3, 2])
    with header_left:
        st.markdown(
            f'<div style="font-size:1.15rem; font-weight:700; color:{NAVY};">{en_or_original(briefing.tender.title)}</div>',
            unsafe_allow_html=True,
        )
        if gloss(briefing.tender.title):
            st.caption(f"Original source title (French): _{briefing.tender.title}_")
        deadline_str = briefing.deadlines[0].date.isoformat() if briefing.deadlines else (
            briefing.tender.submission_deadline.isoformat() if briefing.tender.submission_deadline else "UNKNOWN"
        )
        st.write(
            f"**{briefing.tender.buyer or 'Buyer UNKNOWN'}** — Deadline: **{deadline_str}**"
        )
        color, bg, label = _REC_STYLE[briefing.recommendation.value]
        st.markdown(
            f'<div class="rec-badge" style="color:#fff;background:{color};">{label}</div>',
            unsafe_allow_html=True,
        )

    with header_right:
        st.markdown(
            f'<div class="score-number" style="color:{color};">{briefing.score:.0f}'
            f'<span style="font-size:1rem;color:{MUTED};">/100</span></div>'
            '<div class="score-label">Qualification score</div>',
            unsafe_allow_html=True,
        )
        st.markdown(score_bar(briefing.score / 100, color), unsafe_allow_html=True)
        conf_color, conf_bg = _CONFIDENCE_STYLE[briefing.confidence.value]
        st.markdown(
            f'<span class="conf-chip" style="color:{conf_color};background:{conf_bg};">{briefing.confidence.value} CONFIDENCE</span>',
            unsafe_allow_html=True,
        )

    render_review_status_bar(briefing)

    days_left = None
    if briefing.deadlines:
        days_left = (briefing.deadlines[0].date - datetime.now(UTC).date()).days

    n_gaps = len(briefing.gaps)
    n_unknowns = len(briefing.unknowns)
    gaps_color = RED if n_gaps else NAVY
    unknowns_color = AMBER if n_unknowns else NAVY
    if days_left is None:
        days_color = NAVY
    elif days_left < 7:
        days_color = RED
    elif days_left < 14:
        days_color = AMBER
    else:
        days_color = NAVY

    kpi_cols = st.columns(4)
    kpi_data = [
        ("Mandatory reqs.", str(len(briefing.mandatory_requirements)), NAVY),
        ("Confirmed gaps", str(n_gaps), gaps_color),
        ("Unknowns", str(n_unknowns), unknowns_color),
        ("Days to deadline", str(days_left) if days_left is not None else "UNKNOWN", days_color),
    ]
    for col, (label, value, vcolor) in zip(kpi_cols, kpi_data):
        col.markdown(
            f'<div class="kpi-card"><div class="kpi-value" style="color:{vcolor};">{value}</div>'
            f'<div class="kpi-label">{label}</div></div>',
            unsafe_allow_html=True,
        )

    st.write("")
    tab_overview, tab_requirements, tab_risks, tab_sources = st.tabs(
        ["Overview", "Requirements & Matches", "Risks & Next Actions", "Sources"]
    )

    with tab_overview:
        tender = briefing.tender
        gap_note = f"{n_gaps} confirmed gap(s)" if n_gaps else "no confirmed gaps"
        unknown_note = f"{n_unknowns} open unknown(s)" if n_unknowns else "no open unknowns"
        st.markdown(
            f"**{en_or_original(tender.title)}** for {tender.buyer or 'an unknown buyer'} "
            f"({tender.location or 'location UNKNOWN'}). Recommendation **{briefing.recommendation.value}** "
            f"at a score of **{briefing.score:.0f}/100** ({briefing.confidence.value.lower()} confidence), "
            f"with {gap_note} and {unknown_note}."
        )

        with st.expander("Score breakdown (6 dimensions)", expanded=True):
            b = briefing.score_breakdown
            dims = [
                ("Capability fit", b.capability_fit, 30),
                ("Mandatory requirement fit", b.mandatory_requirement_fit, 25),
                ("Eligibility fit", b.eligibility_fit, 15),
                ("Delivery feasibility", b.delivery_feasibility, 10),
                ("Strategic relevance", b.strategic_relevance, 10),
                ("Information confidence", b.information_confidence, 10),
            ]
            st.markdown(
                "".join(dim_row(dim_label, value, max_points) for dim_label, value, max_points in dims),
                unsafe_allow_html=True,
            )
            st.caption(b.explanation)

        with st.expander("Full recommendation rationale (agent-generated)"):
            st.write(briefing.executive_summary)
            st.caption(
                "May include original French source text where it quotes a confirmed gap or "
                "unresolved requirement — see the Requirements tab for the English translation."
            )

    with tab_requirements:
        left, right = st.columns(2)
        with left:
            st.markdown("**Mandatory requirements**")
            if briefing.mandatory_requirements:
                for r in briefing.mandatory_requirements:
                    label_text = en_or_original(r.description)
                    source = (
                        f"{r.citation.document}" + (f", §{r.citation.section}" if r.citation.section else "")
                        if r.citation
                        else "UNKNOWN source"
                    )
                    st.markdown(
                        f'<div class="req-row">{label_text}<br>'
                        f'<span class="req-source">Source: {source}</span></div>',
                        unsafe_allow_html=True,
                    )
                    if gloss(r.description):
                        with st.expander("Original source text (French)"):
                            st.caption(r.description)
            else:
                st.caption("None extracted.")

        with right:
            st.markdown("**Capability matches**")
            if briefing.capability_matches:
                for m in briefing.capability_matches:
                    st.markdown(
                        f'<div class="req-row">{status_badge(m.status)}{en_or_original(m.requirement_description)}<br>'
                        f'<span class="req-source">{m.justification}</span></div>',
                        unsafe_allow_html=True,
                    )
                    if gloss(m.requirement_description):
                        with st.expander("Original source text (French)"):
                            st.caption(m.requirement_description)
            else:
                st.caption("No capability-matchable requirements extracted.")

    with tab_risks:
        left, right = st.columns(2)
        with left:
            st.markdown("**Gaps (confirmed)**")
            if briefing.gaps:
                for g in briefing.gaps:
                    color, bg = _SEVERITY_STYLE["high"]
                    st.markdown(
                        f'<div class="risk-row" style="background:{bg};border-left-color:{color};">'
                        f"{en_or_original(g)}</div>",
                        unsafe_allow_html=True,
                    )
            else:
                st.success("None confirmed.")

            st.markdown("**Unknowns**")
            if briefing.unknowns:
                for u in briefing.unknowns:
                    color, bg = _SEVERITY_STYLE["medium"]
                    st.markdown(
                        f'<div class="risk-row" style="background:{bg};border-left-color:{color};">'
                        f"{en_or_original(u)}</div>",
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("None.")

        with right:
            st.markdown("**Risks**")
            if briefing.risks:
                for r in briefing.risks:
                    color, bg = _SEVERITY_STYLE[r.severity]
                    st.markdown(
                        f'<div class="risk-row" style="background:{bg};border-left-color:{color};">'
                        f"<b>[{r.severity.upper()}]</b> {en_risk_description(r.description)}</div>",
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("None identified.")

            st.markdown("**Next actions**")
            if briefing.next_actions:
                for a in briefing.next_actions:
                    st.markdown(f'<div class="action-row">{a}</div>', unsafe_allow_html=True)
            else:
                st.caption("None.")

    with tab_sources:
        st.markdown("**Citations**")
        if briefing.citations:
            cite_cols = st.columns(2)
            for i, c in enumerate(briefing.citations):
                loc = ", ".join(filter(None, [f"§{c.section}" if c.section else None, f"p.{c.page}" if c.page else None]))
                cite_cols[i % 2].caption(f"{c.document}" + (f" ({loc})" if loc else ""))
        else:
            st.caption("No citations recorded.")
        st.caption(
            "Human review lives in the **Review & decide** action next to the tender header above."
        )
else:
    st.divider()
    st.caption("Search for tenders above, then click **Analyze** on one to see its qualification briefing here.")
