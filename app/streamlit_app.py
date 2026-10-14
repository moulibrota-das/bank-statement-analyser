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

st.set_page_config(page_title="Bank Statement Intel", page_icon="🏦", layout="wide")


def api(method: str, path: str, **kw):
    return httpx.request(method, f"{API_BASE_URL}{path}", timeout=120, **kw)


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
        return httpx.get(f"{base}/samples", timeout=10).json()
    except Exception:  # noqa: BLE001
        return []


# ---------------------------------------------------------------- sidebar
st.sidebar.title("🏦 Bank Statement Intel")
h = health(API_BASE_URL)
if h is None:
    st.sidebar.error(f"API unreachable at {API_BASE_URL}")
elif h["mode"] == "mock":
    st.sidebar.warning("API online · **MOCK mode** (offline stub LLM, no API key)")
else:
    st.sidebar.success(f"API online · live LLM (`{h['model']}`)")
if h:
    st.sidebar.caption(f"v{h['version']} · prompt `{h['classify_prompt']}`")

source = st.sidebar.radio("Statement source", ["Bundled sample", "Upload file"])
use_llm = st.sidebar.toggle("Use LLM", value=True, help="Off = rules and template summary only")
report = None
error = None
if source == "Upload file":
    up = st.sidebar.file_uploader("PDF, CSV or XLSX", type=["pdf", "csv", "xlsx"])
    if up and st.sidebar.button("Analyze", type="primary"):
        with st.spinner("Analyzing…"):
            try:
                r = api("POST", "/analyze", params={"use_llm": use_llm}, files={"file": (up.name, up.getvalue())})
                if r.status_code == 200:
                    report = r.json()
                else:
                    error = r.json().get("detail", r.text)
            except httpx.HTTPError as e:
                error = f"Could not reach the API: {e}"
else:
    names = [s["name"] for s in samples(API_BASE_URL)]
    pick = st.sidebar.selectbox("Sample (synthetic data)", names) if names else None
    if pick and st.sidebar.button("Analyze sample", type="primary"):
        with st.spinner("Analyzing…"):
            try:
                r = api("GET", f"/samples/{pick}/analyze", params={"use_llm": use_llm})
                if r.status_code == 200:
                    report = r.json()
                else:
                    error = r.json().get("detail", r.text)
            except httpx.HTTPError as e:
                error = f"Could not reach the API: {e}"

if report is not None:
    st.session_state["report"] = report
if error:
    st.error(error)
report = st.session_state.get("report")

st.title("Bank Statement Analyzer")
if not report:
    st.info("Pick a bundled synthetic sample or upload a statement in the sidebar, then press **Analyze**.")
    st.stop()

meta, rec, an, summ = report["meta"], report["reconciliation"], report["analytics"], report["summary"]
proc = report["processing"]
if proc["mock_mode"] and use_llm:
    st.warning("Mock mode: classifications and narrative come from an offline stub, not a real model.")

# ---------------------------------------------------------------- overview
st.subheader("Account")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Account", meta["account_number_masked"] or "n/a")
c2.metric("Holder", meta["account_holder"] or "n/a")
c3.metric("Period", f"{meta['period_start']} → {meta['period_end']}")
c4.metric("Layout", meta["layout"] or "n/a")
st.caption(f"{meta.get('bank_name') or ''} · IFSC {meta['ifsc'] or 'n/a'} · {meta['branch'] or ''} · "
           f"opening {inr(meta['opening_balance']) if meta['opening_balance'] else 'n/a'} · "
           f"closing {inr(meta['closing_balance']) if meta['closing_balance'] else 'n/a'}")

if rec["passed"]:
    st.success(f"✅ Reconciliation passed: {rec['rows_checked']} running balances verified; "
               f"opening + credits − debits = closing ({inr(rec['expected_closing'])}).")
else:
    st.error(f"❌ Reconciliation FAILED: {len(rec['issues'])} issue(s). Extracted data may be wrong.")
    for i in rec["issues"]:
        st.markdown(f"- {i['message']}")
for w in report["warnings"]:
    if "Reconciliation failed" not in w:
        st.caption(f"⚠️ {w}")

k1, k2, k3, k4 = st.columns(4)
k1.metric("Total credits", inr(an["total_credits"]))
k2.metric("Total debits", inr(an["total_debits"]))
k3.metric("Net", inr(an["net"]))
k4.metric("LLM calls", proc["llm_calls"], help=f"cache hits: {proc['cache_hits']} · {proc['elapsed_ms']} ms")

# ---------------------------------------------------------------- summary
st.subheader("Summary")
st.markdown(f"**{summ['account_summary']}**  \n{summ['period']}")
st.write(summ["narrative"])
st.caption(f"Narrative source: {summ['source']} · figures verified against computed data: "
           f"{'yes' if summ['faithfulness_passed'] else 'no'}")

# ---------------------------------------------------------------- charts
ch1, ch2 = st.columns(2)
spend = an["spend_by_category"]
if spend:
    fig = go.Figure(go.Bar(x=[s["category"] for s in spend], y=[float(s["total"]) for s in spend],
                           marker_color=BLUE, customdata=[[s["pct_of_debits"], s["count"]] for s in spend],
                           hovertemplate="%{x}<br>₹%{y:,.2f}<br>%{customdata[0]}% of debits · "
                                         "%{customdata[1]} txns<extra></extra>"))
    fig.update_layout(title="Spend by category", yaxis_title="₹ debited", height=340, margin=dict(t=50, b=10),
                      plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
    ch1.plotly_chart(fig, width="stretch")
mon = an["monthly"]
if mon:
    fig = go.Figure([
        go.Bar(name="Credits", x=[m["month"] for m in mon], y=[float(m["credits"]) for m in mon], marker_color=BLUE),
        go.Bar(name="Debits", x=[m["month"] for m in mon], y=[float(m["debits"]) for m in mon], marker_color=ORANGE)])
    fig.update_layout(title="Monthly credits vs debits", barmode="group", height=340, margin=dict(t=50, b=10),
                      yaxis_title="₹", legend=dict(orientation="h", y=1.12), plot_bgcolor="rgba(0,0,0,0)",
                      paper_bgcolor="rgba(0,0,0,0)")
    ch2.plotly_chart(fig, width="stretch")

# ---------------------------------------------------------------- anomalies
st.subheader(f"Anomalies ({len(report['anomalies'])})")
tx_by_idx = {t["idx"]: t for t in report["transactions"]}
if not report["anomalies"]:
    st.success("No anomalies flagged.")
for a in report["anomalies"]:
    with st.expander(f"{SEV[a['severity']]} {a['code']} · {a['severity']}", expanded=a["severity"] == "high"):
        st.write(a["reason"])
        rows = [tx_by_idx[i] for i in a["txn_idx"] if i in tx_by_idx]
        if rows:
            st.dataframe(pd.DataFrame([{"date": t["date"], "narration": t["narration"], "amount": float(t["amount"]),
                                        "direction": t["direction"]} for t in rows]), hide_index=True)

# ---------------------------------------------------------------- transactions
st.subheader("Transactions")
df = pd.DataFrame([{
    "date": t["date"], "narration": t["narration"], "channel": t["channel"], "counterparty": t["counterparty"],
    "direction": t["direction"], "amount": float(t["amount"]), "balance": float(t["balance"]) if t["balance"] else None,
    "category": t["category"], "source": t["category_source"], "confidence": t["category_confidence"],
    "recurring": t["is_recurring"], "rationale": t["category_rationale"]} for t in report["transactions"]])
f1, f2, f3, f4 = st.columns(4)
cats = f1.multiselect("Category", sorted(df["category"].unique()))
srcs = f2.multiselect("Source", sorted(df["source"].unique()))
dirs = f3.multiselect("Direction", ["credit", "debit"])
minc = f4.slider("Min confidence", 0.0, 1.0, 0.0, 0.05)
q = st.text_input("Search narration / counterparty")
view = df
if cats:
    view = view[view["category"].isin(cats)]
if srcs:
    view = view[view["source"].isin(srcs)]
if dirs:
    view = view[view["direction"].isin(dirs)]
view = view[view["confidence"] >= minc]
if q:
    m = view["narration"].str.contains(q, case=False, na=False) | view["counterparty"].str.contains(q, case=False, na=False)
    view = view[m]
st.caption(f"{len(view)} of {len(df)} transactions")
st.dataframe(view, hide_index=True, width="stretch",
             column_config={"confidence": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f"),
                            "amount": st.column_config.NumberColumn(format="₹%.2f"),
                            "balance": st.column_config.NumberColumn(format="₹%.2f")})

if an["recurring"]:
    with st.expander("Recurring payments"):
        st.dataframe(pd.DataFrame([{"counterparty": r["counterparty"], "amount": float(r["typical_amount"]),
                                    "times": r["occurrences"], "direction": r["direction"],
                                    "category": r["category"]} for r in an["recurring"]]), hide_index=True)

st.download_button("⬇️ Download report JSON", json.dumps(report, indent=2, ensure_ascii=False),
                   file_name="report.json", mime="application/json")
