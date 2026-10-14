"""Inspectable financial quality panel sharing the existing financial dataset."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st
from src.financial_quality import financial_quality
from src.financial_analysis import number

REASONS = {'missing_comparable_inputs': '缺少同期间同口径数据', 'missing_comparison_period': '缺少同比基期',
           'invalid_input': '数据或日期未通过校验', 'zero_base': '基期为零',
           'negative_base_not_conventional_growth': '基期亏损，常规增长率不适用', 'nonpositive_denominator': '分母非正，不能解释为正常比率'}


def render_financial_quality(payload, *, key):
    st.subheader('财务质量体检')
    st.caption('用已披露且口径明确的数据查看增长、利润率和现金兑现。当前提供指标与异常线索，不生成综合评分。')
    date_col, basis_col, currency_col, scope_col = st.columns(4)
    cutoff = date_col.date_input('体检日期', value=datetime.now(ZoneInfo('Asia/Shanghai')).date(), key=key + '_date')
    basis = basis_col.selectbox('指标期间口径', ['cumulative', 'single_quarter'],
                              format_func=lambda b: '累计' if b == 'cumulative' else '单季度', key=key + '_basis')
    currency = currency_col.selectbox('指标币种', ['CNY', 'HKD', 'USD', 'EUR'], key=key + '_currency')
    scope = scope_col.selectbox('指标报表范围', ['consolidated', 'parent_company'],
                               format_func=lambda s: '合并报表' if s == 'consolidated' else '母公司', key=key + '_scope')
    result = financial_quality(payload, as_of=cutoff, basis=basis, currency=currency, scope=scope)
    st.caption(f'最近可用财报期：{result["period_end"] or "未知"} · 可计算 {result["available_factors"]}/{result["total_factors"]} 项 · '
               f'数据/时点受限记录 {result["blocked_records"]} 条')
    st.dataframe([{'指标': f['label'], '数值': format(number(f['value']), '.2f') if f['value'] is not None else None, '单位': '%' if f['unit'] == 'percent' else '倍',
                   '状态': '可计算' if f['status'] == 'ok' else '不可计算',
                   '原因': REASONS.get(f['reason'], f['reason']), '财报期': f['period_end'],
                   '输入记录': ', '.join(f['input_ids'])} for f in result['factors']], hide_index=True, use_container_width=True)
    for flag in result['flags']:
        st.info(flag['message'])
    if result['available_factors'] == 0:
        st.info('补充原始数据的 published_at（披露日期）及单位、币种、期间口径后才能体检；缺失值没有替换为零。')
    st.caption('表格保留两位小数，下载保留精确值。按日期筛选，不提供盘中历史回放或交易日生效推断；重述版本需明确 available_at。现金兑现率使用同范围净利润，不能以归母利润替代。')
    with st.expander('体检公式与来源追溯'):
        st.json(result)
    st.download_button('下载财务体检与证据', json.dumps(result, ensure_ascii=False, indent=2),
                       str(payload.get('symbol', 'stock')) + '-financial-quality.json', key=key + '_download')
