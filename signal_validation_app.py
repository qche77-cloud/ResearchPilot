"""Standalone offline validation UI: no environment loading, Runner or databases."""
import streamlit as st
from src.signal_validation_ui import render_signal_validation

st.set_page_config(page_title='ResearchPilot · 研究信号验证',page_icon='◈',layout='wide')
render_signal_validation()
