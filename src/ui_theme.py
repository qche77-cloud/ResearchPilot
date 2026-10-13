"""Presentation helpers for the research desk; no research side effects."""
from datetime import datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo
import streamlit as st

def apply_theme():
    st.markdown('<style>' + Path(__file__).with_name('ui_polish.css').read_text(encoding='utf-8') + '</style>', unsafe_allow_html=True)

def page_motion(page_key):
    changed = st.session_state.get('_visual_page') != page_key
    st.session_state['_visual_page'] = page_key
    st.session_state['_visual_enter'] = changed

def workspace_bar(section):
    today = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y.%m.%d')
    st.markdown(f'<div class="rp-topbar"><span>WORKSPACE <b>/</b> {escape(section)}</span><span class="rp-topbar-right"><i></i> 本地工作台 <b>·</b> {today}</span></div>', unsafe_allow_html=True)

def brand():
    st.markdown('<div class="rp-brand"><span class="rp-logo" aria-hidden="true">r<span>p</span></span><div>ResearchPilot<small>你的 A 股研究工作台</small></div></div>', unsafe_allow_html=True)

def welcome():
    motion = ' rp-enter' if st.session_state.get('_visual_enter') else ''
    st.markdown(f'''<section class="rp-welcome{motion}">
<div class="rp-welcome-copy"><div class="rp-eyebrow">RESEARCH, WITH A CLEARER VIEW</div>
<h1>让每一次判断，<br>都有<em>据可循。</em></h1>
<p>从一个问题出发，穿过数据与线索。<br>核查事实、寻找反例，建立可以持续追踪的研究。</p>
<div class="rp-tags"><span>原始来源追溯</span><span>财务确定性计算</span><span>持续研究记录</span></div></div>
<div class="rp-research-map" aria-label="研究流程：问题、证据、假设、判断">
<div class="rp-map-label">THE RESEARCH LOOP <span>↗</span></div>
<div class="rp-map-node"><span>01</span><b>提出问题</b><small>明确研究对象与关注点</small></div>
<div class="rp-map-node"><span>02</span><b>核查证据</b><small>财报 · 公告 · 原始来源</small></div>
<div class="rp-map-node"><span>03</span><b>检验假设</b><small>支持与反例，共同构成判断</small></div>
<div class="rp-map-end"><i></i> 记录判断，持续验证 <span>↻</span></div></div></section>''', unsafe_allow_html=True)

def section_label(title, detail=''):
    st.markdown(f'<div class="rp-section-label"><h2>{escape(title)}</h2><span>{escape(detail)}</span></div>', unsafe_allow_html=True)

def starter_card(number, title, description):
    st.markdown(f'<div class="rp-starter"><span class="rp-card-number">{escape(number)}</span><h3>{escape(title)}</h3><p>{escape(description)}</p></div>', unsafe_allow_html=True)

def page_intro(title, description, *, animate=True):
    motion = ' rp-enter' if animate and st.session_state.get('_visual_enter') else ''
    st.markdown(f'<section class="rp-hero{motion}"><div class="rp-eyebrow">RESEARCH DESK</div><h1>{escape(title)}</h1><p>{escape(description)}</p></section>', unsafe_allow_html=True)

def status_strip(text):
    st.markdown(f'<div class="rp-status"><i></i>{escape(text)}</div>', unsafe_allow_html=True)

def summary_tiles(items):
    body = ''.join(f'<div class="rp-summary-tile"><small>{escape(str(label))}</small><strong>{escape(str(value))}</strong><span>{escape(str(note))}</span></div>' for label, value, note in items)
    st.markdown(f'<div class="rp-summary">{body}</div>', unsafe_allow_html=True)

def empty_state(title, description):
    st.markdown(f'<div class="rp-empty"><span aria-hidden="true">◎</span><h3>{escape(title)}</h3><p>{escape(description)}</p></div>', unsafe_allow_html=True)
