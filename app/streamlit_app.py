"""Streamlit UI. Talks to the FastAPI backend over HTTP only (API_BASE_URL); never imports the pipeline."""
from __future__ import annotations

import json
import os

import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")
BLUE, ORANGE = "#2a78d6", "#eb6834"  # categorical slots 1 and 2
SEV = {"high": "🔴", "medium": "🟠", "low": "🟡"}

st.set_page_config(page_title="Bank Statement Analyzer", page_icon="🏦", layout="centered",
                   initial_sidebar_state="collapsed")
st.markdown("""
<style>
#MainMenu, footer, [data-testid="stSidebar"], [data-testid="collapsedControl"] {display: none;}
.block-container {max-width: 1000px; padding-top: 2.2rem;}
h1 {font-weight: 600; letter-spacing: -0.02em;}
[data-testid="stFileUploaderDropzone"] {padding: 3rem 1rem; border-radius: 14px; border-width: 2px;}
[data-testid="stMetricValue"] {font-size: 1.5rem;}
.hero {text-align: center; margin: 3.5rem 0 1.5rem;}
.hero h1 {margin-bottom: .2rem;}
.hero p {color: #898781; margin: 0;}
.pill {font-size: .8rem; color: #898781; text-align: right;}
</style>
""", unsafe_allow_html=True)


def inr(x: float | str) -> str:
    return f"₹{float(x):,.2f}"


@st.cache_data(ttl=15, show_spinner=False)
def health(base: str):
    try:
        return httpx.get(f"{base}/health", timeout=5).json()
    except Exception:  # noqa: BLE001
        return None


@st.cache_data(ttl=60, show_spinner=False)
def samples(base: str):
    try:
        return [s["name"] for s in httpx.get(f"{base}/samples", timeout=10).json()]
    except Exception:  # noqa: BLE001
        return []


def analyze(label: str, request) -> None:
    with st.spinner(f"Analyzing {label}…"):
        try:
            r = request()
        except httpx.HTTPError as e:
            st.session_state["error"] = f"Could not reach the API at {API_BASE_URL}: {e}"
            return
    if r.status_code == 200:
        st.session_state.update(report=r.json(), label=label, error=None)
    else:
        st.session_state["error"] = r.json().get("detail", r.text)


# ---------------------------------------------------------------- status line
h = health(API_BASE_URL)
if h is None:
    status = f"🔴 API unreachable at {API_BASE_URL}"
elif h["mode"] == "mock":
    status = "🟠 API online · mock mode (offline stub, no API key)"
else:
    status = f"🟢 API online · {h['model']}"
st.markdown(f'<div class="pill">{status}</div>', unsafe_allow_html=True)

report = st.session_state.get("report")

# ---------------------------------------------------------------- landing: central upload
if not report:
    st.markdown('<div class="hero"><h1>Bank Statement Analyzer</h1>'
                "<p>Upload a statement to see transactions, categories, spending and anything unusual.</p></div>",
                unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 6, 1])
    with mid:
        use_llm = st.toggle("Use AI for ambiguous rows and the summary", value=True,
                            help="Off: deterministic rules and a template summary only.")
        up = st.file_uploader("Upload statement", type=["pdf", "csv", "xlsx"], label_visibility="collapsed",
                              help="PDF, CSV or XLSX · max 10 MB · processed in memory, never stored")
        st.caption("PDF, CSV or XLSX · processed in memory and never stored · account numbers are masked")
        if up is not None:
            analyze(up.name, lambda: httpx.post(f"{API_BASE_URL}/analyze", params={"use_llm": use_llm},
                                                files={"file": (up.name, up.getvalue())}, timeout=120))
            if st.session_state.get("report"):
                st.rerun()
        names = samples(API_BASE_URL)
        if names:
            with st.expander("No statement handy? Try a synthetic sample"):
                pick = st.selectbox("Sample", names, label_visibility="collapsed")
                if st.button("Analyze sample"):
                    analyze(pick, lambda: httpx.get(f"{API_BASE_URL}/samples/{pick}/analyze",
                                                    params={"use_llm": use_llm}, timeout=120))
                    if st.session_state.get("report"):
                        st.rerun()
        if st.session_state.get("error"):
            st.error(st.session_state["error"])
    st.stop()

# ---------------------------------------------------------------- results
meta, rec, an, summ, proc = (report[k] for k in ("meta", "reconciliation", "analytics", "summary", "processing"))
top_l, top_r = st.columns([4, 1])
top_l.markdown(f"### {st.session_state.get('label', 'Statement')}")
if top_r.button("New statement", width="stretch"):
    for k in ("report", "label", "error"):
        st.session_state.pop(k, None)
    st.rerun()
st.caption(f"{meta.get('bank_name') or ''} · {meta['account_holder'] or ''} · a/c {meta['account_number_masked'] or 'n/a'} · "
           f"{meta['period_start']} → {meta['period_end']}")
if proc["mock_mode"]:
    st.caption("🟠 Mock mode: AI classifications and narrative come from an offline stub, not a real model.")

if rec["passed"]:
    st.success(f"Balances reconcile ({rec['rows_checked']} rows verified).")
else:
    st.error(f"Reconciliation failed: {len(rec['issues'])} issue(s). Extracted data may be wrong.")
    for i in rec["issues"]:
        st.markdown(f"- {i['message']}")

k1, k2, k3 = st.columns(3)
k1.metric("Credits", inr(an["total_credits"]))
k2.metric("Debits", inr(an["total_debits"]))
k3.metric("Net", inr(an["net"]))

t_sum, t_tx, t_an = st.tabs(["Summary", "Transactions", f"Anomalies ({len(report['anomalies'])})"])

with t_sum:
    st.write(summ["narrative"])
    st.caption(f"Written by {'AI' if summ['source'] == 'llm' else 'template'} · figures verified against computed data")
    layout = dict(height=320, margin=dict(t=40, b=10, l=10, r=10), plot_bgcolor="rgba(0,0,0,0)",
                  paper_bgcolor="rgba(0,0,0,0)")
    spend = an["spend_by_category"]
    if spend:
        fig = go.Figure(go.Bar(
            x=[s["category"] for s in spend], y=[float(s["total"]) for s in spend], marker_color=BLUE,
            customdata=[[s["pct_of_debits"], s["count"]] for s in spend],
            hovertemplate="%{x}<br>₹%{y:,.2f}<br>%{customdata[0]}% of debits · %{customdata[1]} txns<extra></extra>"))
        fig.update_layout(title="Spend by category", yaxis_title="₹", **layout)
        st.plotly_chart(fig, width="stretch")
    mon = an["monthly"]
    if mon:
        fig = go.Figure([
            go.Bar(name="Credits", x=[m["month"] for m in mon], y=[float(m["credits"]) for m in mon],
                   marker_color=BLUE),
            go.Bar(name="Debits", x=[m["month"] for m in mon], y=[float(m["debits"]) for m in mon],
                   marker_color=ORANGE)])
        fig.update_layout(title="Monthly credits vs debits", barmode="group", yaxis_title="₹",
                          legend=dict(orientation="h", y=1.15), **layout)
        st.plotly_chart(fig, width="stretch")
    if an["recurring"]:
        st.markdown("**Recurring**")
        st.dataframe(pd.DataFrame([{"counterparty": r["counterparty"], "amount": float(r["typical_amount"]),
                                    "times": r["occurrences"], "category": r["category"]}
                                   for r in an["recurring"]]), hide_index=True, width="stretch",
                     column_config={"amount": st.column_config.NumberColumn(format="₹%.2f")})

with t_tx:
    df = pd.DataFrame([{
        "date": t["date"], "narration": t["narration"], "direction": t["direction"], "amount": float(t["amount"]),
        "category": t["category"], "source": t["category_source"], "confidence": t["category_confidence"],
        "balance": float(t["balance"]) if t["balance"] else None, "rationale": t["category_rationale"]}
        for t in report["transactions"]])
    f1, f2, f3 = st.columns(3)
    cats = f1.multiselect("Category", sorted(df["category"].unique()))
    srcs = f2.multiselect("Source", sorted(df["source"].unique()))
    minc = f3.slider("Min confidence", 0.0, 1.0, 0.0, 0.05)
    q = st.text_input("Search", placeholder="Search narration…", label_visibility="collapsed")
    view = df
    if cats:
        view = view[view["category"].isin(cats)]
    if srcs:
        view = view[view["source"].isin(srcs)]
    view = view[view["confidence"] >= minc]
    if q:
        view = view[view["narration"].str.contains(q, case=False, na=False)]
    st.caption(f"{len(view)} of {len(df)} transactions")
    st.dataframe(view, hide_index=True, width="stretch", column_config={
        "confidence": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f"),
        "amount": st.column_config.NumberColumn(format="₹%.2f"),
        "balance": st.column_config.NumberColumn(format="₹%.2f")})

with t_an:
    tx_by_idx = {t["idx"]: t for t in report["transactions"]}
    if not report["anomalies"]:
        st.success("Nothing unusual found.")
    for a in report["anomalies"]:
        with st.expander(f"{SEV[a['severity']]} {a['code'].replace('_', ' ').title()}", expanded=a["severity"] == "high"):
            st.write(a["reason"])
            rows = [tx_by_idx[i] for i in a["txn_idx"] if i in tx_by_idx]
            if rows:
                st.dataframe(pd.DataFrame([{"date": t["date"], "narration": t["narration"],
                                            "amount": float(t["amount"]), "direction": t["direction"]}
                                           for t in rows]), hide_index=True, width="stretch")

st.download_button("Download report (JSON)", json.dumps(report, indent=2, ensure_ascii=False),
                   file_name="report.json", mime="application/json")
