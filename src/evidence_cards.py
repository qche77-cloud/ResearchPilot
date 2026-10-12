"""Inspectable excerpts; no claim that extraction equals independent verification."""
from urllib.parse import urlsplit
import streamlit as st
from src.stock_research import date_status


def cards(snapshot):
    result = []
    for eid, item in snapshot.get('evidence', {}).items():
        text = item.get('text') or ''
        excerpts = []
        for finding in snapshot.get('findings', []):
            for quote in finding.get('excerpts', []):
                if quote['evidence_id'] == eid and quote['text'] and quote['text'] in text:
                    excerpts.append(quote['text'])
        result.append(dict(item, eid=eid, excerpts=list(dict.fromkeys(excerpts)) or ([text[:450]] if text else []),
                           excerpt_kind='分析引用的逐字摘录' if excerpts else '采集文本开头（非针对结论挑选）'))
    return result


def render_cards(snapshot, prefix=''):
    for card in cards(snapshot):
        with st.expander(f'[{card["eid"]}] {card["title"]}'):
            st.caption('来源日期：' + str(card.get('date') or '未知') + ' · ' + date_status(card.get('date'), 30))
            if card.get('listing_page'):
                st.warning('这是滚动列表页，不是单篇公告。列表页日期不能当作某条公告的发布日期。')
            st.caption('日期依据：' + card.get('date_source', '历史记录未保存') + ' · 可信度：' + card.get('date_confidence', '未知'))
            st.caption('相关财报期间：' + str(card.get('report_period') or '未结构化核实，请对照原文') +
                       ' · 读取状态：' + card.get('read_status', '历史记录未保存'))
            if urlsplit(card.get('url', '')).scheme in {'http', 'https'}:
                st.link_button('打开原始来源 ↗', card['url'])
            st.caption(card['excerpt_kind'] + '；仅验证摘录来自采集文本，不代表事实已独立验证。')
            for excerpt in card['excerpts'][:3]:
                st.text(excerpt)
            for finding in snapshot.get('findings', []):
                if card['eid'] in finding.get('evidence_ids', []):
                    label = {'supported_fact': '模型归纳（附证据）', 'inference': '模型推断', 'gap': '待验证'}.get(finding['kind'], '模型分析')
                    st.write(label + '：' + finding['text'])
            with st.expander('查看完整采集文本'):
                st.text(card.get('text', ''))
