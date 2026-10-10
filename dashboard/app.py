"""
Atlas Funding — Scholarship Intelligence Engine Production Dashboard.
Built with Streamlit, providing real-time analytics, explainable 100-point confidence rubrics,
verbatim source evidence traces, and automated delta change audit tracking.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
import pandas as pd
import streamlit as st

# Configure page layout and metadata
st.set_page_config(
    page_title="Atlas Funding — Scholarship Intelligence Engine",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from storage.database import (
    get_all_scholarships,
    get_audit_logs,
    get_scholarship_by_id,
    get_scholarship_evidence,
    init_db,
)
from core.lifecycle.runner import run_cycle_delta_check, run_discovery_and_crawl

# ------------------------------------------------------------------------------
# Premium Custom Styling & Design System
# ------------------------------------------------------------------------------
CUSTOM_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    .main-title {
        font-size: 2.1rem;
        font-weight: 700;
        background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 50%, #06b6d4 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.2rem;
    }

    .subtitle {
        color: #64748b;
        font-size: 1.0rem;
        margin-bottom: 1.5rem;
    }

    .metric-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 1rem 1.25rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        transition: transform 0.15s ease-in-out;
    }
    .metric-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);
    }

    .badge-verified {
        background-color: #dcfce7;
        color: #15803d;
        padding: 0.25rem 0.6rem;
        border-radius: 9999px;
        font-weight: 600;
        font-size: 0.8rem;
        display: inline-block;
    }

    .badge-review {
        background-color: #fef3c7;
        color: #b45309;
        padding: 0.25rem 0.6rem;
        border-radius: 9999px;
        font-weight: 600;
        font-size: 0.8rem;
        display: inline-block;
    }

    .badge-expired {
        background-color: #fee2e2;
        color: #b91c1c;
        padding: 0.25rem 0.6rem;
        border-radius: 9999px;
        font-weight: 600;
        font-size: 0.8rem;
        display: inline-block;
    }

    .badge-expiring {
        background-color: #ffedd5;
        color: #c2410c;
        padding: 0.25rem 0.6rem;
        border-radius: 9999px;
        font-weight: 600;
        font-size: 0.8rem;
        display: inline-block;
    }

    .score-high {
        color: #16a34a;
        font-weight: 700;
    }
    .score-med {
        color: #d97706;
        font-weight: 700;
    }
    .score-low {
        color: #dc2626;
        font-weight: 700;
    }

    .quote-box {
        background-color: #f8fafc;
        border-left: 3px solid #3b82f6;
        padding: 0.5rem 0.75rem;
        font-style: italic;
        color: #334155;
        border-radius: 0 6px 6px 0;
        margin: 0.25rem 0;
    }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ------------------------------------------------------------------------------
# Sidebar Controls & Pipeline Triggers
# ------------------------------------------------------------------------------
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3135/3135810.png", width=64)
    st.title("Atlas Intelligence")
    st.caption("Autonomous Indian Scholarship Crawler & Grounded Audit Platform")
    st.divider()

    st.subheader("⚡ Continuous Pipeline Controls")
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("🚀 Run 1: Ingest", help="Run full discovery & crawl pipeline"):
            with st.spinner("Executing Run 1 (Ingesting 22 authentic schemes)..."):
                res1 = run_discovery_and_crawl(target_count=22)
                st.success(f"Ingested {res1.get('total_ingested')} schemes!")
                st.rerun()

    with col_btn2:
        if st.button("🔄 Run 2: Delta", help="Execute change detection & stale lifecycle audit"):
            with st.spinner("Executing Run 2 (Delta tracking & stale audit)..."):
                res2 = run_cycle_delta_check()
                st.success(f"Audit Complete! {res2.get('deltas_detected')} deltas logged.")
                st.rerun()

    st.divider()
    st.subheader("🔍 Filters & Search")
    status_filter = st.selectbox(
        "Verification Status",
        options=["ALL", "VERIFIED", "REVIEW_REQUIRED", "EXPIRED", "EXPIRING_SOON"],
        index=0,
    )
    source_type_filter = st.selectbox(
        "Source Category",
        options=["ALL", "GOVERNMENT", "APEX_BODY", "CORPORATE_CSR", "NGO_TRUST"],
        index=0,
    )
    min_confidence = st.slider(
        "Minimum Confidence Score (%)",
        min_value=0,
        max_value=100,
        value=0,
        step=5,
    )

    st.divider()
    st.caption(f"Database: `{settings.db_path.name}`")
    st.caption(f"Primary LLM: `{settings.gemini_model}`")
    st.caption(f"Fallback LLM: `{settings.ollama_model}`")


# ------------------------------------------------------------------------------
# Load Data from SQLite
# ------------------------------------------------------------------------------
init_db()
all_scholarships = get_all_scholarships(limit=200)
all_audit_logs = get_audit_logs(limit=200)

if not all_scholarships:
    st.warning("No scholarships currently found in the database. Click **'Run 1: Ingest'** in the sidebar to populate the knowledge repository.")
    if st.button("Run Ingestion Now"):
        with st.spinner("Ingesting authoritative schemes..."):
            run_discovery_and_crawl(target_count=22)
            st.rerun()
    st.stop()

# Convert to DataFrame for filtering and analytics
df = pd.DataFrame(all_scholarships)

# Apply filters
filtered_df = df.copy()
if status_filter != "ALL":
    filtered_df = filtered_df[filtered_df["status"] == status_filter]
if source_type_filter != "ALL":
    filtered_df = filtered_df[filtered_df["source_type"] == source_type_filter]
if min_confidence > 0:
    filtered_df = filtered_df[filtered_df["confidence_score"] >= float(min_confidence)]


# ------------------------------------------------------------------------------
# Header & Analytics Metrics Bar
# ------------------------------------------------------------------------------
st.markdown('<div class="main-title">Atlas Scholarship Intelligence Engine</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">Real-time canonical discovery, deterministic verification rubrics, and zero-hallucination evidence traces for Indian students.</div>', unsafe_allow_html=True)

# Metrics calculation
total_count = len(df)
verified_count = len(df[df["status"] == "VERIFIED"])
review_count = len(df[df["status"] == "REVIEW_REQUIRED"])
expired_count = len(df[df["status"] == "EXPIRED"])
expiring_count = len(df[df["status"] == "EXPIRING_SOON"])
active_count = len(df[~df["status"].isin(["EXPIRED", "NO_LONGER_VERIFIABLE"])])
avg_confidence = df["confidence_score"].mean() if not df.empty else 0.0

col_m1, col_m2, col_m3, col_m4, col_m5, col_m6 = st.columns(6)
with col_m1:
    st.metric("Total Opportunities", f"{total_count}", help="Total unique schemes stored in database")
with col_m2:
    st.metric("Verified (≥95%)", f"{verified_count}", delta=f"{verified_count/total_count*100:.0f}% rate", help="Gated as authentic canonical opportunities")
with col_m3:
    st.metric("Review Required", f"{review_count}", help="Pending manual check or missing application portal")
with col_m4:
    st.metric("Active & Live", f"{active_count}", help="Currently active or open application windows")
with col_m5:
    st.metric("Expired / Stale", f"{expired_count}", delta=f"-{expired_count}", delta_color="inverse", help="Closing date passed current local date")
with col_m6:
    st.metric("Fleet Confidence", f"{avg_confidence:.1f}%", help="Mathematical average across all records")

st.markdown("<br>", unsafe_allow_html=True)


# ------------------------------------------------------------------------------
# Search Bar & Interactive Inventory Table
# ------------------------------------------------------------------------------
search_query = st.text_input(
    "🔎 Search Opportunities (by Scheme Name, Disbursing Provider, Eligibility, or Domicile):",
    placeholder="e.g., Pragati, Reliance, Minority, Engineering, Assam, SC/ST...",
)

if search_query.strip():
    q = search_query.strip().lower()
    filtered_df = filtered_df[
        filtered_df["name"].str.lower().str.contains(q)
        | filtered_df["provider"].str.lower().str.contains(q)
        | filtered_df["eligibility_criteria"].str.lower().str.contains(q)
        | filtered_df["domicile_requirements"].str.lower().str.contains(q)
        | filtered_df["amount_benefit"].str.lower().str.contains(q)
    ]

tab_inventory, tab_audit, tab_analytics = st.tabs(["📋 Scholarship Inventory", "📜 Change Audit Trail", "📊 Fleet Analytics"])

with tab_inventory:
    st.markdown(f"**Displaying {len(filtered_df)} opportunities:**")

    # Present table view
    display_cols = ["id", "name", "provider", "source_type", "amount_benefit", "closing_date", "confidence_score", "status"]
    available_cols = [c for c in display_cols if c in filtered_df.columns]
    
    st.dataframe(
        filtered_df[available_cols].rename(columns={
            "id": "ID",
            "name": "Scheme Title",
            "provider": "Provider / Authority",
            "source_type": "Source Type",
            "amount_benefit": "Financial Benefit",
            "closing_date": "Deadline",
            "confidence_score": "Confidence (%)",
            "status": "Verification Status",
        }),
        use_container_width=True,
        hide_index=True,
    )

    st.divider()

    # --------------------------------------------------------------------------
    # Deep-Dive Detailed Inspection Modal/Expander
    # --------------------------------------------------------------------------
    st.subheader("🔬 Deep-Dive Opportunity Inspector")
    scheme_options = {row["name"]: row["id"] for _, row in filtered_df.iterrows()}
    
    if scheme_options:
        selected_name = st.selectbox("Select a scholarship to inspect full grounding, score rubric, and audit trail:", list(scheme_options.keys()))
        selected_id = scheme_options[selected_name]
        selected_record = get_scholarship_by_id(selected_id)

        if selected_record:
            # Header Cards
            c_head1, c_head2, c_head3 = st.columns([2, 1, 1])
            with c_head1:
                st.markdown(f"### {selected_record['name']}")
                st.markdown(f"**Disbursing Authority:** {selected_record['provider']} | **Type:** `{selected_record['source_type']}`")
            with c_head2:
                status_val = selected_record['status']
                badge_class = "badge-verified" if status_val == "VERIFIED" else ("badge-review" if status_val == "REVIEW_REQUIRED" else "badge-expired")
                st.markdown(f"<div style='margin-top: 15px;'><span class='{badge_class}'>{status_val}</span></div>", unsafe_allow_html=True)
            with c_head3:
                score_val = selected_record['confidence_score']
                score_color = "score-high" if score_val >= 95 else ("score-med" if score_val >= 80 else "score-low")
                st.markdown(f"<div style='margin-top: 15px;'><span class='{score_color}' style='font-size: 1.5rem;'>{score_val:.1f}% Confidence</span></div>", unsafe_allow_html=True)

            # Direct Links
            col_l1, col_l2 = st.columns(2)
            with col_l1:
                st.markdown(f"🌐 **Official Source:** [{selected_record['official_source_url']}]({selected_record['official_source_url']})")
            with col_l2:
                app_link = selected_record['application_url']
                if app_link and app_link != "Not specified":
                    st.markdown(f"📝 **Application Gateway:** [{app_link}]({app_link})")
                else:
                    st.markdown("📝 **Application Gateway:** *Not specified*")

            # Structured Details Grid
            st.markdown("#### 📌 Key Eligibility & Award Specifications")
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                st.markdown(f"**💰 Award Benefit:** {selected_record['amount_benefit']}")
                st.markdown(f"**🎯 Core Eligibility:** {selected_record['eligibility_criteria']}")
                st.markdown(f"**🎓 Academic Requirements:** {selected_record['academic_requirements']}")
                st.markdown(f"**📅 Application Deadline:** {selected_record['closing_date']}")
            with col_d2:
                st.markdown(f"**💼 Income Criteria:** {selected_record['income_criteria']}")
                st.markdown(f"**👥 Category / Caste:** {selected_record['category_criteria']}")
                st.markdown(f"**⚧ Gender Targeting:** {selected_record['gender_criteria']}")
                st.markdown(f"**📍 Domicile / State:** {selected_record['domicile_requirements']}")

            # Explainable 100-Point Scoring Breakdown
            st.markdown("#### 🧮 Explainability Rubric (Why this score?)")
            breakdown = selected_record.get("score_breakdown")
            if isinstance(breakdown, str):
                try:
                    breakdown = json.loads(breakdown)
                except Exception:
                    breakdown = {}

            if breakdown and isinstance(breakdown, dict):
                st.progress(min(1.0, float(selected_record['confidence_score']) / 100.0))
                
                col_r1, col_r2, col_r3 = st.columns(3)
                with col_r1:
                    da = breakdown.get("domain_authority", {})
                    st.markdown(f"**Domain Authority:** `{da.get('points', 0)} / 30 pts`")
                    st.caption(da.get("reason", "N/A"))

                    aa = breakdown.get("application_authenticity", {})
                    st.markdown(f"**Application Gateway:** `{aa.get('points', 0)} / 20 pts`")
                    st.caption(aa.get("reason", "N/A"))

                with col_r2:
                    eg = breakdown.get("evidence_grounding", {})
                    st.markdown(f"**Verbatim Grounding:** `{eg.get('points', 0)} / 20 pts`")
                    st.caption(eg.get("reason", "N/A"))

                    dv = breakdown.get("deadline_verifiability", {})
                    st.markdown(f"**Deadline Format:** `{dv.get('points', 0)} / 15 pts`")
                    st.caption(dv.get("reason", "N/A"))

                with col_r3:
                    hh = breakdown.get("host_health", {})
                    st.markdown(f"**Host Reachability:** `{hh.get('points', 0)} / 10 pts`")
                    st.caption(hh.get("reason", "N/A"))

                    ac = breakdown.get("anti_conflict", {})
                    st.markdown(f"**Anti-Conflict:** `{ac.get('points', 0)} / 5 pts`")
                    st.caption(ac.get("reason", "N/A"))

            # Verbatim Ground-Truth Evidence Traces
            st.markdown("#### 🔍 Verbatim Evidence Grounding Traces")
            evidence_rows = get_scholarship_evidence(selected_id)
            if evidence_rows:
                ev_display = []
                for ev in evidence_rows:
                    ev_display.append({
                        "Field": ev["field_name"],
                        "Extracted Fact": ev["extracted_value"],
                        "Verbatim Source Quote (Substring Proof)": ev["evidence_quote"],
                        "Captured At": ev["captured_at"],
                    })
                st.dataframe(pd.DataFrame(ev_display), use_container_width=True, hide_index=True)
            else:
                st.info("No detailed evidence traces recorded for this entry.")

            # Scheme-Specific Audit History
            scheme_logs = get_audit_logs(scholarship_id=selected_id)
            if scheme_logs:
                st.markdown("#### ⏱️ Scheme Change History (Audit Log)")
                st.dataframe(pd.DataFrame(scheme_logs)[["field_name", "old_value", "new_value", "evidence_quote", "detected_at"]], use_container_width=True, hide_index=True)


with tab_audit:
    st.markdown("### 📜 System-Wide Delta Tracking & Change History")
    st.markdown("Every detected revision (deadline extensions, benefit enhancements, or criteria updates) is automatically logged here with exact verbatim quotes and timestamps.")

    if all_audit_logs:
        audit_df = pd.DataFrame(all_audit_logs)
        st.dataframe(
            audit_df[["scholarship_id", "field_name", "old_value", "new_value", "evidence_quote", "detected_at"]].rename(columns={
                "scholarship_id": "Scholarship ID",
                "field_name": "Field Modified",
                "old_value": "Previous Value",
                "new_value": "Updated Value",
                "evidence_quote": "Verbatim Verification Quote",
                "detected_at": "Timestamp Detected",
            }),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No changes logged yet. Click **'Run 2: Delta'** in the sidebar to run the change detection pass.")


with tab_analytics:
    st.markdown("### 📊 Fleet Diversity & Verification Distribution")
    col_c1, col_c2 = st.columns(2)

    with col_c1:
        st.markdown("**Opportunities by Source Type:**")
        type_counts = df["source_type"].value_counts().reset_index()
        type_counts.columns = ["Source Type", "Count"]
        st.bar_chart(type_counts.set_index("Source Type"))

    with col_c2:
        st.markdown("**Opportunities by Verification Status:**")
        status_counts = df["status"].value_counts().reset_index()
        status_counts.columns = ["Status", "Count"]
        st.bar_chart(status_counts.set_index("Status"))
