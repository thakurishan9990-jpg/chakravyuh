"""Dark console theme for the fraud dashboard."""

PALETTE = {
    "bg":          "#0F1115",
    "surface":     "#171A21",
    "surface_alt": "#1E222B",
    "border":      "#2A2F3A",
    "text":        "#E6E8EC",
    "text_dim":    "#9AA1AE",
    "accent":      "#4C8DFF",
    "safe":        "#2ECC8F",
    "review":      "#F5A623",
    "danger":      "#FF5C5C",
    "danger_dim":  "#3A1D1D",
    "review_dim":  "#3A2E17",
    "safe_dim":    "#153029",
}

TIER_STYLE = {
    "High risk": (PALETTE["danger"], PALETTE["danger_dim"]),
    "Review":    (PALETTE["review"], PALETTE["review_dim"]),
    "Safe":      (PALETTE["safe"],   PALETTE["safe_dim"]),
}

VERDICT_STYLE = {
    "YES":   (PALETTE["danger"], PALETTE["danger_dim"]),
    "MAYBE": (PALETTE["review"], PALETTE["review_dim"]),
    "NO":    (PALETTE["safe"],   PALETTE["safe_dim"]),
}


def css() -> str:
    p = PALETTE
    return f"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">

<style>
:root {{
  --bg: {p['bg']}; --surface: {p['surface']}; --surface-alt: {p['surface_alt']};
  --border: {p['border']}; --text: {p['text']}; --text-dim: {p['text_dim']};
  --accent: {p['accent']}; --safe: {p['safe']}; --review: {p['review']};
  --danger: {p['danger']};
}}

.stApp {{
  background: radial-gradient(900px 500px at 12% -10%, #1A2030 0%, transparent 60%), var(--bg);
  color: var(--text);
  font-family: 'Inter', -apple-system, sans-serif;
}}

h1 {{
  font-family: 'Inter', sans-serif !important; font-weight: 700 !important;
  font-size: 1.7rem !important; letter-spacing: -0.02em;
  color: var(--text) !important; margin-bottom: 0.1rem !important;
}}
h2, h3 {{
  font-family: 'Inter', sans-serif !important; font-weight: 600 !important;
  font-size: 0.78rem !important; letter-spacing: 0.13em;
  text-transform: uppercase; color: var(--text-dim) !important;
}}
p, span, div, label {{ color: var(--text); }}

div[data-testid="stMetric"] {{
  background: linear-gradient(180deg, var(--surface) 0%, var(--surface-alt) 100%);
  border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px;
}}
div[data-testid="stMetricLabel"] p {{
  font-size: 0.66rem !important; letter-spacing: 0.11em; text-transform: uppercase;
  color: var(--text-dim) !important; font-weight: 600 !important;
}}
div[data-testid="stMetricValue"] {{
  font-family: 'JetBrains Mono', monospace !important; font-size: 1.65rem !important;
  font-weight: 700 !important; color: var(--text) !important; letter-spacing: -0.02em;
}}

div[data-testid="stVerticalBlockBorderWrapper"] {{
  background: var(--surface); border: 1px solid var(--border) !important; border-radius: 12px;
}}

.stButton > button {{
  background: var(--surface-alt); color: var(--text); border: 1px solid var(--border);
  border-radius: 9px; font-weight: 600; font-size: 0.85rem; transition: all 0.15s ease;
}}
.stButton > button:hover {{ border-color: var(--accent); color: var(--accent); }}
.stButton > button[kind="primary"] {{
  background: var(--accent); border-color: var(--accent); color: #08111F;
}}

.stTextInput input, .stNumberInput input,
.stSelectbox div[data-baseweb="select"] > div {{
  background: var(--surface-alt) !important; border: 1px solid var(--border) !important;
  color: var(--text) !important; border-radius: 9px !important;
  font-family: 'JetBrains Mono', monospace !important; font-size: 0.85rem !important;
}}

div[data-testid="stDataFrame"] {{
  border: 1px solid var(--border); border-radius: 12px; overflow: hidden;
}}
div[data-testid="stDataFrame"] * {{
  font-family: 'JetBrains Mono', monospace !important; font-size: 0.78rem !important;
}}

.streamlit-expanderHeader, details summary {{
  font-size: 0.8rem !important; color: var(--text-dim) !important; font-weight: 500 !important;
}}

hr {{ border-color: var(--border) !important; margin: 0.9rem 0 !important; }}
div[data-testid="stCaptionContainer"] p {{
  color: var(--text-dim) !important; font-size: 0.76rem !important;
}}
#MainMenu, footer, header {{ visibility: hidden; }}
.block-container {{ padding-top: 2.2rem !important; max-width: 1500px; }}
.stSlider label {{ font-size: 0.76rem !important; color: var(--text-dim) !important; }}
</style>
"""


def verdict_badge(verdict: str, confidence: float = None) -> str:
    fg, bg = VERDICT_STYLE.get(verdict, (PALETTE["text_dim"], PALETTE["surface_alt"]))
    conf = ""
    if confidence is not None:
        conf = (f"<div style=\"font-family:'JetBrains Mono',monospace;font-size:0.62rem;"
                f"color:{PALETTE['text_dim']};letter-spacing:0.04em;margin-top:2px;\">"
                f"{confidence:.0%} confidence</div>")
    return (f"<div style='text-align:center;'>"
            f"<div style=\"font-family:'Inter',sans-serif;font-size:1.15rem;font-weight:800;"
            f"letter-spacing:0.08em;color:{fg};background:{bg};border:1px solid {fg}55;"
            f"border-radius:8px;padding:5px 0;\">{verdict}</div>{conf}</div>")


def status_pill(tier: str) -> str:
    fg, bg = TIER_STYLE.get(tier, (PALETTE["text_dim"], PALETTE["surface_alt"]))
    return (f"<span style=\"font-family:'Inter',sans-serif;font-size:0.68rem;font-weight:700;"
            f"letter-spacing:0.06em;text-transform:uppercase;color:{fg};background:{bg};"
            f"border:1px solid {fg}40;padding:3px 9px;border-radius:20px;\">{tier}</span>")


def risk_bar(score: float, tier: str) -> str:
    fg, _ = TIER_STYLE.get(tier, (PALETTE["text_dim"], PALETTE["surface_alt"]))
    pct = max(0, min(100, score * 100))
    return (f"<div style='margin-top:6px;'><div style='height:5px;"
            f"background:{PALETTE['surface_alt']};border-radius:3px;overflow:hidden;'>"
            f"<div style='height:100%;width:{pct:.0f}%;background:{fg};'></div></div></div>")


def big_score(score: float, tier: str) -> str:
    fg, _ = TIER_STYLE.get(tier, (PALETTE["text_dim"], ""))
    return (f"<div style=\"font-family:'JetBrains Mono',monospace;font-size:1.5rem;"
            f"font-weight:700;color:{fg};text-align:right;line-height:1;\">{score:.2f}</div>")


def vpa_label(vpa: str) -> str:
    return (f"<span style=\"font-family:'JetBrains Mono',monospace;font-size:0.92rem;"
            f"font-weight:500;color:{PALETTE['text']};\">{vpa}</span>")
