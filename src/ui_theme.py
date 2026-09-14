"""Shared presentation for the research workspace; no research side effects."""
from html import escape
from pathlib import Path
import streamlit as st


def apply_theme():
    st.markdown('''<style>
    :root {--rp-ink:#24282e;--rp-muted:#6b7078;--rp-line:#e8e8e6;--rp-green:#375e52}
    .stApp {background:#fcfcfa;color:var(--rp-ink)}
    .stApp, button, input, textarea {font-family:Inter,"Segoe UI","Microsoft YaHei",sans-serif}
    .block-container {padding-top:4.5rem;padding-bottom:6rem;max-width:1120px}
    [data-testid="stHeader"] {background:rgba(252,252,250,.94)}
    [data-testid="stSidebar"] {background:#f3f3f0;border-right:1px solid var(--rp-line)}
    [data-testid="stSidebarUserContent"] {padding-top:2rem}
    [data-testid="stSidebar"] button {text-align:left;background:transparent;border-color:transparent;box-shadow:none}
    [data-testid="stSidebar"] button p {text-align:left;font-size:.85rem}
    [data-testid="stSidebar"] button:hover {background:#e9eae5}
    h1,h2,h3 {color:var(--rp-ink);overflow-wrap:anywhere;line-height:1.4!important;letter-spacing:-.025em}
    [data-testid="stCaptionContainer"] {color:var(--rp-muted)}
    .rp-brand {font-size:1.25rem;font-weight:750;letter-spacing:-.04em;margin-bottom:.25rem}
    .rp-brand span {color:var(--rp-green);margin-right:.5rem}
    .rp-eyebrow {font-size:.72rem;font-weight:700;letter-spacing:.16em;color:var(--rp-green);margin-bottom:.7rem}
    .rp-hero {padding:1.4rem 0 2rem;margin-bottom:1rem;border-bottom:1px solid var(--rp-line)}
    .rp-hero h1 {font-size:clamp(1.6rem,3vw,2.3rem);font-weight:600;margin:0 0 .8rem;padding:0;letter-spacing:-.045em}
    .rp-hero p {color:var(--rp-muted);line-height:1.8;margin:0;max-width:760px}
    .rp-tags {display:flex;flex-wrap:wrap;gap:.5rem;margin-top:1.2rem}
    .rp-tag {font-size:.75rem;color:#355a4e;border:1px solid #ceddd4;background:#ffffff99;border-radius:30px;padding:.25rem .7rem}
    .rp-status {padding:.3rem 0 .8rem;margin-bottom:.25rem;font-size:.8rem;color:var(--rp-muted);font-variant-numeric:tabular-nums}
    .rp-status:before {content:"";display:inline-block;width:6px;height:6px;border-radius:50%;background:#858d88;margin-right:.6rem}
    .stButton>button,.stDownloadButton>button,.stLinkButton>a {border-radius:10px;min-height:2.6rem;border-color:var(--rp-line);transition:background .18s ease,border-color .18s ease,box-shadow .18s ease,transform .18s ease}
    .stButton>button:active {transform:translateY(1px)}
    .stButton>button:hover,.stDownloadButton>button:hover {border-color:var(--rp-green);color:var(--rp-green);background:#eef5f1}
    .stButton>button[kind="primary"] {background:var(--rp-green);border-color:var(--rp-green);color:white}
    .stButton>button[kind="primary"]:hover {background:#11513f;color:white}
    button:focus-visible,a:focus-visible {outline:3px solid #779d8c!important;outline-offset:3px}
    [data-testid="stChatMessage"] {background:transparent;border:none;border-radius:16px;padding:1.2rem .25rem;margin-bottom:1.2rem;box-shadow:none}
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {background:#f0f1ed;padding:1.2rem 1.4rem;border-radius:18px}
    [data-testid="stChatMessage"] p {line-height:1.8}
    [data-testid="stChatInput"] {border:1px solid #dedfd9;border-radius:18px;background:white;box-shadow:0 8px 32px #20282009;transition:border-color .2s,box-shadow .2s}
    [data-testid="stChatInput"]:focus-within {border-color:#81988a;box-shadow:0 8px 32px #20282010,0 0 0 3px #375e5209}
    [data-testid="stBottom"] {background:#fcfcfa}
    [data-testid="stMetric"] {background:white;border:1px solid var(--rp-line);border-radius:14px;padding:1rem 1.2rem}
    [data-testid="stMetricValue"] {white-space:normal;font-size:1.65rem;color:var(--rp-ink)}
    [data-testid="stExpander"] {border-color:var(--rp-line);border-radius:12px;background:#ffffff90}
    [data-testid="stForm"] {border:1px solid var(--rp-line);border-radius:16px;background:white;padding:1.25rem}
    [data-baseweb="tab-list"] {gap:1.2rem;border-bottom:1px solid var(--rp-line);margin-bottom:1rem}
    [data-baseweb="tab"] {height:auto;min-height:3rem;white-space:normal}
    [data-baseweb="tab"][aria-selected="true"] {color:var(--rp-green);font-weight:700}
    [data-baseweb="tab-highlight"] {background:var(--rp-green)}
    [data-testid="stDataFrame"] {border-radius:12px;overflow:hidden}
    @media(max-width:700px) {
      .block-container {padding-left:1rem;padding-right:1rem;padding-top:4.5rem}
      .rp-hero {padding:1.3rem;border-radius:16px}
      [data-testid="stChatMessage"] {padding:.9rem}
      [data-baseweb="tab-list"] {gap:.65rem}
    }
    @media(prefers-reduced-motion:reduce) {button,[data-testid="stChatInput"] {transition:none!important;transform:none!important}}
    </style>''', unsafe_allow_html=True)
    st.markdown('<style>' + Path(__file__).with_name('ui_polish.css').read_text(encoding='utf-8') + '</style>', unsafe_allow_html=True)


def page_motion(page_key):
    """Only animate a navigation change, never a polling or form rerun."""
    changed = st.session_state.get('_visual_page') != page_key
    st.session_state['_visual_page'] = page_key
    st.session_state['_visual_enter'] = changed


def welcome():
    motion = ' rp-enter' if st.session_state.get('_visual_enter') else ''
    st.markdown(f'''<section class="rp-welcome{motion}">
    <div class="rp-orbit" aria-hidden="true">◈</div>
    <div class="rp-eyebrow">YOUR PERSONAL RESEARCH DESK</div>
    <h1>看见数据背后，<br><em>更值得研究的问题。</em></h1>
    <p>从一家公司开始，把线索串成证据。<br>与你一起核查、追问，让每一次判断都有依据。</p>
    </section>''', unsafe_allow_html=True)


def starter_card(number, title, description):
    st.markdown(f'<div class="rp-starter"><small>{escape(number)} / RESEARCH</small><h3>{escape(title)}</h3><p>{escape(description)}</p></div>', unsafe_allow_html=True)


def page_intro(title, description):
    motion = ' rp-enter' if st.session_state.get('_visual_enter') else ''
    st.markdown(f'''<section class="rp-hero{motion}">
    <div class="rp-eyebrow">RESEARCH / 有据可循</div>
    <h1>{escape(title)}</h1><p>{escape(description)}</p>
    </section>''', unsafe_allow_html=True)


def status_strip(text):
    st.markdown(f'<div class="rp-status">{escape(text)}</div>', unsafe_allow_html=True)
