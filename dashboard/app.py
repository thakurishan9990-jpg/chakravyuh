"""UPI fraud monitoring console - dark theme, single page."""

import os
import sys
import time

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient                    # noqa: E402
from mock_api.app import app as gateway_app                  # noqa: E402
from detection.features import (                             # noqa: E402
    load_transactions, build_txn_graph, build_feature_matrix)
from detection.detector import score_accounts, evaluate      # noqa: E402
from dashboard.theme import (                                # noqa: E402
    css, PALETTE, TIER_STYLE, VERDICT_STYLE, status_pill, risk_bar,
    big_score, vpa_label, verdict_badge)

st.set_page_config(page_title="UPI Fraud Console", layout="wide",
                   initial_sidebar_state="collapsed")
st.markdown(css(), unsafe_allow_html=True)


def val(row, col, default=0.0):
    try:
        v = row[col]
    except Exception:
        return default
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return default
    return v


@st.cache_resource
def get_client():
    return TestClient(gateway_app)


@st.cache_data(show_spinner=False)
def run_detection(_nonce: int):
    client = get_client()
    df = load_transactions(client)
    if len(df) == 0:
        return None, None, None
    G = build_txn_graph(df)
    fdf = build_feature_matrix(df, G)
    scored = score_accounts(fdf)
    return df, scored, evaluate(scored)


def simulate(days, per_day, schemes):
    return get_client().post("/simulate", params={
        "num_days": days, "normal_txns_per_day": per_day,
        "num_schemes": schemes}).json()


def refresh():
    st.session_state.nonce += 1
    st.cache_data.clear()


st.session_state.setdefault("nonce", 0)
st.session_state.setdefault("cursor", 0)
st.session_state.setdefault("live", False)
st.session_state.setdefault("speed", 12)
st.session_state.setdefault("threshold", 0.40)


# --------------------------------------------------------------------------
# Header
# --------------------------------------------------------------------------

st.markdown(
    f"<h1>UPI Fraud Console</h1>"
    f"<p style=\"color:{PALETTE['text_dim']};font-size:0.88rem;margin-top:-4px;\">"
    f"Ponzi &amp; high-yield scam detection on UPI transaction streams</p>",
    unsafe_allow_html=True)

try:
    df, scored, metrics = run_detection(st.session_state.nonce)
except Exception as e:
    st.error(f"Detection failed: {type(e).__name__}: {e}")
    if st.button("Reset and regenerate", type="primary"):
        get_client().delete("/transactions")
        simulate(14, 400, 3)
        st.session_state.cursor = 0
        refresh()
        st.rerun()
    st.stop()

if df is None:
    with st.container(border=True):
        st.markdown("#### No data loaded")
        c = st.columns([1, 1, 1, 2])
        d = c[0].number_input("Days", 3, 30, 14)
        p = c[1].number_input("Txns/day", 100, 2000, 400, step=100)
        s = c[2].number_input("Scam rings", 1, 6, 3)
        c[3].markdown("<br>", unsafe_allow_html=True)
        if c[3].button("Generate dataset", type="primary", use_container_width=True):
            with st.spinner("Generating..."):
                simulate(d, p, s)
            st.session_state.cursor = 0
            refresh()
            st.rerun()
    st.stop()


thr = st.session_state.threshold
scored = scored.copy()
scored["risk_tier"] = scored["risk_score"].apply(
    lambda s: "High risk" if s >= max(thr + 0.3, 0.7) else ("Review" if s >= thr else "Safe"))

risk_by = scored["risk_score"].to_dict()
tier_by = scored["risk_tier"].to_dict()
verdict_by = scored["verdict"].to_dict() if "verdict" in scored.columns else {}

high = scored[scored.risk_tier == "High risk"]
review = scored[scored.risk_tier == "Review"]
live_metrics = evaluate(scored, threshold=thr) if "is_scam" in scored.columns else None
high_metrics = evaluate(scored, threshold=max(thr + 0.3, 0.7)) if "is_scam" in scored.columns else None


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

m = st.columns(6)
m[0].metric("Transactions", f"{len(df):,}")
m[1].metric("Accounts", f"{len(scored):,}")
m[2].metric("High risk", len(high))
m[3].metric("Review queue", len(review))
if live_metrics:
    m[4].metric("Recall", f"{live_metrics.get('recall', 0):.0%}")
    m[5].metric("False pos. rate", f"{live_metrics.get('fpr', 0):.1%}")

if high_metrics:
    # evaluate() may return different key sets depending on the detector
    # version in use, so read everything defensively.
    hp = high_metrics.get("precision", 0.0)
    tp = high_metrics.get("tp")
    flagged = high_metrics.get("flagged", len(high))
    detail = f" ({tp} of {flagged} correct)" if tp is not None else ""
    st.caption(
        f"High-risk tier precision: {hp:.0%}{detail}. "
        f"The review tier is deliberately over-inclusive — it is a queue for "
        f"human analysts, not an accusation.")

if "verdict" in scored.columns:
    vc = scored["verdict"].value_counts()
    bar = st.columns(3)
    for i, v in enumerate(["YES", "MAYBE", "NO"]):
        fg, bg = VERDICT_STYLE[v]
        n = int(vc.get(v, 0))
        label = {"YES": "Confirmed scam pattern",
                 "MAYBE": "Ambiguous — needs a human",
                 "NO": "No meaningful signal"}[v]
        bar[i].markdown(
            f"<div style='background:{bg};border:1px solid {fg}44;border-radius:12px;"
            f"padding:12px 16px;'>"
            f"<div style=\"font-family:'Inter',sans-serif;font-size:1.5rem;font-weight:800;"
            f"letter-spacing:0.08em;color:{fg};\">{v}"
            f"<span style=\"font-family:'JetBrains Mono',monospace;float:right;"
            f"font-size:1.3rem;\">{n}</span></div>"
            f"<div style='font-size:0.72rem;color:{PALETTE['text_dim']};margin-top:2px;'>"
            f"{label}</div></div>", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Live feed | Alert queue
# --------------------------------------------------------------------------

left, right = st.columns([3, 2], gap="large")

with left:
    h = st.columns([3, 1, 1])
    h[0].markdown("### Live transaction feed")
    if h[1].button("Pause" if st.session_state.live else "Start",
                   use_container_width=True,
                   type="secondary" if st.session_state.live else "primary"):
        st.session_state.live = not st.session_state.live
        st.rerun()
    if h[2].button("Restart", use_container_width=True):
        st.session_state.cursor = 0
        st.rerun()

    c1, c2 = st.columns(2)
    st.session_state.speed = c1.slider("Speed (txns/refresh)", 1, 60,
                                       st.session_state.speed)
    st.session_state.threshold = c2.slider("Alert threshold", 0.20, 0.90,
                                           st.session_state.threshold, 0.05)

    only_flagged = st.checkbox("Show flagged transactions only", value=False)

    cur = st.session_state.cursor
    window = df.iloc[max(0, cur - 200):cur]
    if only_flagged and len(window):
        window = window[window.sender.map(lambda a: tier_by.get(a, "Safe") != "Safe")]
    window = window.tail(22)

    if len(window) == 0:
        msg = ("Press <b>Start</b> to replay the stream" if cur == 0
               else "No flagged transactions in this window")
        st.markdown(
            f"<div style='border:1px dashed {PALETTE['border']};border-radius:12px;"
            f"padding:52px;text-align:center;color:{PALETTE['text_dim']};"
            f"font-size:0.88rem;'>{msg}</div>", unsafe_allow_html=True)
    else:
        rows = []
        for _, t in window.iloc[::-1].iterrows():
            tier = tier_by.get(t.sender, "Safe")
            rows.append({
                "Time": pd.to_datetime(t.timestamp).strftime("%d %b %H:%M"),
                "From": str(t.sender)[:24],
                "To": str(t.receiver)[:24],
                "Amount": f"{t.amount:,.0f}",
                "Category": t["category"] if "category" in t and t["category"] else "-",
                "City": t["city"] if "city" in t and t["city"] else "-",
                "Risk": f"{risk_by.get(t.sender, 0):.2f}",
                "Scam?": verdict_by.get(t.sender, "NO"),
                "Status": tier,
            })

        def paint(row):
            fg, bg = TIER_STYLE.get(row["Status"], (PALETTE["text"], PALETTE["surface"]))
            if row["Status"] == "Safe":
                return [f"background-color:{PALETTE['surface']};"
                        f"color:{PALETTE['text_dim']}"] * len(row)
            return [f"background-color:{bg};color:{fg};font-weight:600"] * len(row)

        st.dataframe(pd.DataFrame(rows).style.apply(paint, axis=1),
                     hide_index=True, use_container_width=True, height=420)

    pct = min(cur, len(df)) / len(df) * 100
    st.markdown(
        f"<div style='height:3px;background:{PALETTE['surface_alt']};border-radius:2px;"
        f"overflow:hidden;margin-top:6px;'><div style='height:100%;width:{pct:.1f}%;"
        f"background:{PALETTE['accent']};'></div></div>"
        f"<div style='color:{PALETTE['text_dim']};font-size:0.74rem;margin-top:5px;"
        f"font-family:JetBrains Mono,monospace;'>{min(cur, len(df)):,} / {len(df):,} "
        f"transactions replayed</div>", unsafe_allow_html=True)


with right:
    st.markdown("### Alert queue")
    query = st.text_input("Search account", placeholder="filter by VPA...",
                          label_visibility="collapsed")

    alerts = scored[scored.risk_tier != "Safe"]
    if query:
        alerts = alerts[alerts.index.str.contains(query.strip(), case=False, na=False)]
    alerts = alerts.head(10)

    if len(alerts) == 0:
        st.markdown(
            f"<div style='border:1px solid {PALETTE['border']};border-radius:12px;"
            f"padding:24px;text-align:center;color:{PALETTE['text_dim']};'>"
            f"No matching alerts</div>", unsafe_allow_html=True)
    else:
        for acct, row in alerts.iterrows():
            with st.container(border=True):
                a, b, c_ = st.columns([2.4, 1, 1])
                a.markdown(vpa_label(acct), unsafe_allow_html=True)
                a.markdown(status_pill(row.risk_tier), unsafe_allow_html=True)
                b.markdown(big_score(row.risk_score, row.risk_tier),
                           unsafe_allow_html=True)
                c_.markdown(verdict_badge(val(row, "verdict", "MAYBE"),
                                          val(row, "confidence", None)),
                            unsafe_allow_html=True)
                st.markdown(risk_bar(row.risk_score, row.risk_tier),
                            unsafe_allow_html=True)

                with st.expander("Evidence"):
                    reasons = val(row, "reasons", [])
                    if len(reasons) == 0:
                        st.markdown(
                            f"<div style='font-size:0.8rem;color:{PALETTE['text_dim']};'>"
                            f"Ranked by anomaly model; no rule fired.</div>",
                            unsafe_allow_html=True)
                    for r in reasons:
                        st.markdown(
                            f"<div style='font-size:0.8rem;color:{PALETTE['text']};"
                            f"margin:3px 0;'>› {r}</div>", unsafe_allow_html=True)
                    st.markdown(
                        f"<div style='font-family:JetBrains Mono,monospace;font-size:0.72rem;"
                        f"color:{PALETTE['text_dim']};margin-top:8px;padding-top:8px;"
                        f"border-top:1px solid {PALETTE['border']};'>"
                        f"rate {val(row,'dominant_payout_ratio'):.1%} · "
                        f"consistency {val(row,'ratio_consistency'):.0%} · "
                        f"cities {int(val(row,'distinct_cities'))} · "
                        f"hold {val(row,'median_hold_hours'):.1f}h · "
                        f"rule {val(row,'rule_score'):.2f} / ml {val(row,'ml_score'):.2f}"
                        f"</div>", unsafe_allow_html=True)

                with st.expander("Transaction network"):
                    try:
                        import matplotlib
                        matplotlib.use("Agg")
                        import matplotlib.pyplot as plt
                        import networkx as nx

                        at = df[(df.sender == acct) | (df.receiver == acct)]
                        if len(at) == 0:
                            st.caption("No transactions.")
                        else:
                            sample = at if len(at) <= 120 else at.sample(120, random_state=1)
                            Gn = nx.DiGraph()
                            Gn.add_node(acct)
                            for _, t in sample.iterrows():
                                if t.sender == acct:
                                    Gn.add_edge(acct, t.receiver, kind="out")
                                else:
                                    Gn.add_edge(t.sender, acct, kind="in")

                            vfg, _ = VERDICT_STYLE.get(val(row, "verdict", "MAYBE"),
                                                       (PALETTE["accent"], ""))
                            fig, ax = plt.subplots(figsize=(6, 4.5), dpi=110,
                                                   facecolor=PALETTE["surface"])
                            ax.set_facecolor(PALETTE["surface"])
                            pos = nx.spring_layout(Gn, k=1.8, iterations=50, seed=7)

                            ncolors = [vfg if n == acct else PALETTE["surface_alt"]
                                       for n in Gn.nodes()]
                            nsizes = [800 if n == acct else 110 for n in Gn.nodes()]
                            nx.draw_networkx_nodes(Gn, pos, node_color=ncolors,
                                                   node_size=nsizes, ax=ax,
                                                   edgecolors=PALETTE["border"],
                                                   linewidths=0.6)

                            ins = [(u, v) for u, v, d in Gn.edges(data=True) if d["kind"] == "in"]
                            outs = [(u, v) for u, v, d in Gn.edges(data=True) if d["kind"] == "out"]
                            nx.draw_networkx_edges(Gn, pos, edgelist=ins,
                                                   edge_color=PALETTE["danger"], width=1.0,
                                                   alpha=0.5, ax=ax, arrows=True, arrowsize=7)
                            nx.draw_networkx_edges(Gn, pos, edgelist=outs,
                                                   edge_color=PALETTE["safe"], width=1.0,
                                                   alpha=0.5, ax=ax, arrows=True, arrowsize=7)
                            nx.draw_networkx_labels(Gn, pos, {acct: acct.split("@")[0][:12]},
                                                    font_size=7, font_weight="bold",
                                                    font_color=PALETTE["text"], ax=ax)
                            ax.axis("off")
                            plt.tight_layout()
                            st.pyplot(fig, use_container_width=True)
                            plt.close(fig)

                            st.caption(
                                f"Red = money in ({len(ins)}) · Green = money out ({len(outs)})"
                                + (f" · sampled 120 of {len(at)}" if len(at) > 120 else ""))
                    except Exception as e:
                        st.warning(f"Graph failed: {e}")

    st.markdown("### VPA reputation check")
    st.caption("Simulated PSP-side lookup — not a real Paytm, PhonePe or NPCI API.")
    vpa = st.text_input("VPA", placeholder="scheme-s1@upi", label_visibility="collapsed")
    if vpa:
        r = get_client().get(f"/verify/{vpa.strip()}")
        if r.status_code != 200:
            st.error("Malformed VPA")
        else:
            res = r.json()
            colour = {"high_risk": PALETTE["danger"], "caution": PALETTE["review"],
                      "clean": PALETTE["safe"]}[res["verdict"]]
            st.markdown(
                f"<div style='border:1px solid {colour}55;border-radius:12px;"
                f"padding:13px 15px;background:{PALETTE['surface']};'>"
                f"<div style='color:{colour};font-weight:700;font-size:0.9rem;'>"
                f"{res['verdict'].replace('_',' ').title()}"
                f"<span style='font-family:JetBrains Mono,monospace;float:right;'>"
                f"{res['reputation_score']}/100</span></div></div>",
                unsafe_allow_html=True)
            for reason in res["reasons"]:
                st.markdown(f"<div style='font-size:0.78rem;color:{PALETTE['text_dim']};"
                            f"margin-top:5px;'>› {reason}</div>", unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Transaction locations | Inject
# --------------------------------------------------------------------------

st.markdown("---")
map_col, form_col = st.columns([3, 2], gap="large")

with map_col:
    st.markdown("### Transaction locations")
    only_scheme = st.checkbox("Show only scheme-operator activity", value=True)

    geo = df.dropna(subset=["lat", "lon"]).copy()
    if only_scheme and "is_scam" in scored.columns:
        scheme_accts = set(scored[scored.is_scam == 1].index)
        geo = geo[geo.sender.isin(scheme_accts) | geo.receiver.isin(scheme_accts)]

    if len(geo) == 0:
        st.info("No transactions with location data match this filter.")
    else:
        try:
            import pydeck as pdk
            pts = geo[["lat", "lon"]].dropna()
            layer = pdk.Layer(
                "ScatterplotLayer", data=pts,
                get_position="[lon, lat]",
                get_fill_color="[255, 92, 92, 130]",
                get_radius=18000, pickable=True)
            view = pdk.ViewState(latitude=float(pts.lat.mean()),
                                 longitude=float(pts.lon.mean()), zoom=3.6)
            st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view,
                                     map_style="dark"))
            st.caption(f"{len(pts):,} transactions plotted across "
                      f"{geo['city'].nunique()} cities.")
        except Exception as e:
            st.warning(f"Map failed ({e}); showing table instead.")
            st.dataframe(geo[["timestamp", "sender", "receiver", "city"]].head(40),
                        hide_index=True, use_container_width=True)

with form_col:
    st.markdown("### Inject transaction")
    with st.form("inject", border=False):
        f1, f2 = st.columns(2)
        s_ = f1.text_input("From", "tester@upi")
        r_ = f2.text_input("To", "scheme-s1@upi")
        f3, f4 = st.columns(2)
        amt = f3.number_input("Amount", 1.0, 500000.0, 5000.0, step=500.0)
        typ = f4.selectbox("Type", ["deposit", "payout"])
        f5, f6 = st.columns(2)
        cat = f5.selectbox("Category", ["p2p", "crypto", "investment", "gaming",
                                        "forex", "grocery", "retail"])
        city = f6.selectbox("City", get_client().get("/cities").json()["cities"])
        if st.form_submit_button("Submit & re-score", use_container_width=True,
                                 type="primary"):
            get_client().post("/transaction", json={
                "sender": s_, "receiver": r_, "amount": amt,
                "type": typ, "category": cat, "city": city})
            refresh()
            st.rerun()


# --------------------------------------------------------------------------
# Tables + tools
# --------------------------------------------------------------------------

st.markdown("---")
st.markdown("### All accounts")

cols = [c for c in ["verdict", "confidence", "risk_score", "risk_tier",
                    "rule_score", "ml_score", "ratio_consistency",
                    "payout_ratio_match_count", "impossible_trips",
                    "distinct_cities", "high_risk_txn_share",
                    "median_hold_hours", "passthrough_ratio", "is_scam"]
        if c in scored.columns]

table = scored[cols].copy()
for c in table.columns:
    if table[c].dtype.kind == "f":
        table[c] = table[c].round(3)

st.dataframe(table, use_container_width=True, height=300)
st.download_button("Download results as CSV", table.to_csv().encode(),
                   "fraud_detection_results.csv", "text/csv")

c_left, c_right = st.columns(2)

with c_left:
    with st.expander("Threshold sweep"):
        if "is_scam" in scored.columns:
            sweep = []
            for t in [round(x * 0.05, 2) for x in range(4, 19)]:
                mm = evaluate(scored, threshold=t)
                sweep.append({"threshold": t,
                              "precision": round(mm.get("precision", 0), 3),
                              "recall": round(mm.get("recall", 0), 3),
                              "fpr": round(mm.get("fpr", 0), 3),
                              "flagged": mm.get("flagged", 0)})
            st.dataframe(pd.DataFrame(sweep), hide_index=True,
                         use_container_width=True, height=250)
            st.caption("Use this to justify your chosen threshold.")

with c_right:
    with st.expander("Diagnostics"):
        gt = int(scored["is_scam"].sum()) if "is_scam" in scored.columns else 0
        st.markdown(
            f"<div style='font-family:JetBrains Mono,monospace;font-size:0.76rem;"
            f"color:{PALETTE['text_dim']};line-height:1.8;'>"
            f"ground-truth operators: <b style='color:{PALETTE['text']}'>{gt}</b>"
            f" (expect 1 per ring)<br>"
            f"geo enrichment: {'present' if df['lat'].notna().any() else 'MISSING'}<br>"
            f"categories: {df['category'].nunique() if 'category' in df else 0} distinct<br>"
            f"feature columns: {len(scored.columns)}</div>",
            unsafe_allow_html=True)
        if gt > 20:
            st.warning("Ground truth looks wrong — regenerate the dataset.")
        if st.button("Wipe database & regenerate", use_container_width=True):
            get_client().delete("/transactions")
            with st.spinner("Regenerating..."):
                simulate(14, 400, 3)
            st.session_state.cursor = 0
            refresh()
            st.rerun()

with st.expander("Regenerate dataset"):
    g = st.columns([1, 1, 1, 2])
    gd = g[0].number_input("Days", 3, 30, 14, key="gd")
    gp = g[1].number_input("Txns/day", 100, 2000, 400, step=100, key="gp")
    gs = g[2].number_input("Scam rings", 1, 6, 3, key="gs")
    g[3].markdown("<br>", unsafe_allow_html=True)
    if g[3].button("Regenerate", use_container_width=True):
        get_client().delete("/transactions")
        with st.spinner("Generating..."):
            simulate(gd, gp, gs)
        st.session_state.cursor = 0
        refresh()
        st.rerun()

st.markdown(
    f"<div style='color:{PALETTE['text_dim']};font-size:0.74rem;line-height:1.6;"
    f"margin-top:10px;'>Rule layer (explainable) + Isolation Forest (anomaly "
    f"ranking). The model refines ranking but cannot raise an alert alone — every "
    f"alert traces to a stated rule. Synthetic data; this flags for review, it "
    f"does not block payments.</div>", unsafe_allow_html=True)


if st.session_state.live and st.session_state.cursor < len(df):
    st.session_state.cursor = min(st.session_state.cursor + st.session_state.speed,
                                  len(df))
    time.sleep(0.35)
    st.rerun()
