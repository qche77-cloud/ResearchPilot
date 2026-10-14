"""Usable financial analysis, accounting-basis verification and traceable charts."""
from __future__ import annotations

import json
import math
from decimal import Decimal
import streamlit as st
from src.ui_theme import empty_state
from src.financial_analysis import (METRICS, analyze_financials, chart_points, financial_evidence,
                                    number, valuation, identity)

REASONS = {'unknown_unit': '单位未明确', 'unknown_currency': '币种未明确',
           'unknown_period_basis': '单季/累计口径未明确', 'unknown_accounting_scope': '合并/母公司口径未明确',
           'missing_or_invalid_value': '缺失或无效数值', 'conflicting_duplicate': '同期间存在冲突值',
           'zero_base': '基期为零', 'negative_base_not_conventional_growth': '基期亏损，常规增长率不适用',
           'missing_comparison_period': '缺少比较期间', 'missing_or_ambiguous_previous_cumulative': '缺少唯一上一累计期',
           'incomparable_scope': '比较口径不一致', 'invalid_input': '输入未通过校验',
           'ratio_cannot_be_differenced': '不能对累计毛利率直接做差', 'incomparable_period_or_ratio': '期间或指标不可直接比较'}


def example_dataset(symbol='002837'):
    rows = []
    for year, revenues, profits in [(2024, [100, 230, 380, 550], [10, 25, 45, 70]),
                                    (2025, [120, 280, 470, 700], [8, 20, 34, 55])]:
        for index, (month, day) in enumerate(((3, 31), (6, 30), (9, 30), (12, 31))):
            period = f'{year}-{month:02d}-{day}'
            for metric, value in [('revenue', revenues[index]), ('attributable_net_profit', profits[index]),
                                  ('cost_of_revenue', Decimal(revenues[index]) * Decimal('.7')), ('operating_cash_flow', Decimal(profits[index]) * Decimal('.8'))]:
                rows.append({'metric': metric, 'value': str(value), 'unit': '万元', 'currency': 'CNY',
                             'scope': 'consolidated', 'basis': 'cumulative', 'period_end': period,
                             'published_at': f'{year + 1}-04-30',
                             'source_url': 'https://example.invalid/synthetic-financial-report'})
    return {'symbol': symbol, 'provenance': 'synthetic_fixture', 'fetched_at': '2026-10-12T00:00:00Z', 'financial_records': rows}


def render_analysis(analysis, *, key):
    st.caption(f'可用原始记录 {analysis["usable_records"]} 条 · 口径或数据待核对 {analysis["blocked_records"]} 条')
    records = analysis['records']
    if not records:
        empty_state('等待财务数据', '导入带来源的财务记录，或核对已有快照的单位与口径后开始分析。')
        return
    record_table = [{ '指标': r['label'], '期间': r['period_end'], '口径': r['basis'], '范围': r['scope'],
                     '币种': r['currency'], '标准值': r['value'] if r['status'] == 'ok' else None,
                     '单位': r['unit'], '状态': '可计算' if r['status'] == 'ok' else '待核对',
                     '原因': '；'.join(REASONS.get(i, i) for i in r['issues']), '记录 ID': r['id'] } for r in records]
    computations = analysis['computations']
    metrics, bases = st.columns(2)
    metric = metrics.selectbox('多期财务图表', sorted({r['metric'] for r in records}), format_func=lambda m: METRICS[m], key=key + '_metric')
    basis = bases.selectbox('比较口径', ['cumulative', 'single_quarter', 'instant'],
                         format_func=lambda b: {'cumulative': '年初至今累计', 'single_quarter': '单季度', 'instant': '期末时点'}[b], key=key + '_basis')
    points = chart_points(analysis, metric, basis)
    if points:
        scopes = sorted({(p['currency'], p['scope']) for p in points})
        chosen = st.selectbox('币种与报表范围', scopes, key=key + '_scope',
                              format_func=lambda s: f'{s[0]} · ' + {'consolidated': '合并报表', 'parent_company': '母公司报表'}.get(s[1], s[1]))
        selected = [p for p in points if (p['currency'], p['scope']) == chosen]
        display = []
        for p in selected:
            value = float(p['value'])
            if math.isfinite(value):
                display.append(dict(p, chart_value=value))
        st.vega_lite_chart(display, {'height': 300, 'mark': {'type': 'line', 'point': True, 'color': '#19766b', 'strokeWidth': 2.5},
            'encoding': {'x': {'field': 'period', 'type': 'ordinal', 'sort': 'ascending', 'title': '财报期末'},
                         'y': {'field': 'chart_value', 'type': 'quantitative', 'title': f'{chosen[0]} {selected[0]["unit"]}'},
                         'tooltip': [{'field': f, 'type': 'nominal'} for f in ('period', 'value', 'currency', 'basis', 'record_id', 'source_url', 'fetched_at')]} })
        st.caption('图表仅将确定性计算结果转换为绘图坐标；精确值、原始记录 ID 与来源可在下表和下载文件中核对。')
        with st.expander('图表精确值与来源'):
            st.dataframe(selected, hide_index=True, use_container_width=True)
    else:
        st.info('此口径没有通过校验的图表数据；未知值不会画成零。')
    with st.expander('原始记录与数据质量'):
        st.dataframe(record_table, hide_index=True, use_container_width=True)
    with st.expander('计算结果与输入记录'):
        st.dataframe([{'指标': METRICS.get(c['metric'], c['metric']), '期间': c['period_end'], '口径': c['basis'],
                      '计算': c['kind'], '结果': c['value'], '单位': c['unit'], '状态': c['status'],
                      '说明': REASONS.get(c.get('reason'), c.get('reason')), '输入记录': ', '.join(c['input_ids'])}
                     for c in computations], hide_index=True, use_container_width=True)
    with st.expander('计算公式与原始数据追溯'):
        st.json(financial_evidence(analysis))
    st.download_button('下载财务分析与证据', json.dumps(financial_evidence(analysis), ensure_ascii=False, indent=2),
                       f'{analysis["symbol"]}-financial-evidence.json', key=key + '_download')


def render_financial_tools(store, symbol, snapshot=None):
    st.subheader('多期财务分析')
    st.caption('同比、单季环比和毛利率由 Python 计算；单季值只在累计期完整且口径一致时差分。')
    imported = store.financial_dataset(symbol)
    payload = imported['payload'] if imported else snapshot or {'symbol': symbol}
    if imported:
        st.caption('当前分析输入：你导入的财务数据 · 保存时间 ' + imported['created'])
    else:
        st.caption('当前分析输入：行情快照中的财务源值；未知单位或期间口径会阻止计算。')
    render_analysis(analyze_financials(payload), key='fin_' + symbol)
    from src.financial_quality_ui import render_financial_quality
    render_financial_quality(payload, key='quality_' + symbol)
    if snapshot and snapshot.get('finance'):
        with st.expander('核对快照财务口径后启用计算'):
            with st.form('fin_metadata_' + symbol):
                currency = st.selectbox('财报币种', ['CNY', 'HKD', 'USD', 'EUR'])
                unit = st.selectbox('数据源金额字段单位（以源值口径为准）', ['元', '万元', '亿元'])
                basis = st.selectbox('收入、利润、现金流期间口径', ['cumulative', 'single_quarter'],
                                     format_func=lambda b: '年初至今累计' if b == 'cumulative' else '单季度')
                scope = st.selectbox('报表范围', ['consolidated', 'parent_company'],
                                     format_func=lambda s: '合并报表' if s == 'consolidated' else '母公司报表')
                evidence = st.text_input('核对依据（原财报链接或数据口径说明）')
                confirmed = st.checkbox('我已核对上述单位、币种和报表口径')
                if st.form_submit_button('保存核对后的分析输入'):
                    if not confirmed or not evidence.strip():
                        st.warning('填写核对依据并勾选确认后才能启用计算。')
                    else:
                        verified = dict(snapshot, provenance='user_verified_provider_snapshot',
                                        finance_metadata=dict(verified=True, currency=currency, money_unit=unit,
                                                              flow_basis=basis, scope=scope, basis_evidence=evidence.strip()))
                        store.save_financial_dataset(symbol, verified)
                        st.rerun()
    with st.expander('导入带来源的财务数据 / 查看合成演示'):
        st.caption('JSON 顶层包含 symbol、fetched_at、financial_records。每条指标明确 metric/value/unit/currency/basis/scope/period_end/source_url；估值与体检另需 published_at，延迟可用或重述版本可加 available_at。导入是用户提供数据，并非自动核实来源真实性。')
        st.download_button('下载 JSON 格式示例（虚构数值）', json.dumps(example_dataset(symbol), ensure_ascii=False, indent=2),
                           'synthetic-financial-example.json', key='fin_example_' + symbol)
        upload = st.file_uploader('导入财务 JSON（最大 2 MB）', type=['json'], key='fin_upload_' + symbol)
        if st.button('保存导入数据', key='fin_import_' + symbol):
            try:
                if upload is None or upload.size > 2 * 1024 * 1024:
                    raise ValueError('请选择不超过 2 MB 的 JSON 文件')
                imported_payload = json.loads(upload.getvalue())
                if not isinstance(imported_payload, dict):
                    raise ValueError('JSON 顶层必须为对象')
                imported_payload.setdefault('provenance', 'user_import')
                store.save_financial_dataset(symbol, imported_payload)
                st.rerun()
            except (ValueError, TypeError, KeyError) as exc:
                st.error(str(exc))
        if st.checkbox('查看离线合成演示（不写入研究数据）', key='fin_demo_' + symbol):
            st.warning('以下为合成示例，不代表这家公司的真实财务数据。')
            render_analysis(analyze_financials(example_dataset(symbol)), key='demo_' + symbol)
            render_financial_quality(example_dataset(symbol), key='quality_demo_' + symbol)
    with st.expander('基础估值计算（PE / PB）'):
        analysis = analyze_financials(payload)
        eligible = [r for r in analysis['records'] + analysis['ttm_records'] if r['status'] == 'ok' and
                    r['metric'] in {'attributable_net_profit', 'attributable_net_assets'}]
        if not eligible:
            st.info('估值需可核对的归母净利润或归母净资产；总净利润不能替代归母净利润。')
        else:
            with st.form('valuation_' + symbol):
                denominator = st.selectbox('财务分母', eligible, format_func=lambda r: f'{r["label"]} {r["period_end"]} {r["basis"]}')
                kind = st.selectbox('估值指标', ['pe', 'pb'])
                cap = st.text_input('总市值（元；与财报币种一致）')
                cap_date = st.date_input('市值日期')
                cap_source = st.text_input('市值来源链接')
                if st.form_submit_button('计算估值'):
                    market = dict(id=identity([symbol, cap, str(cap_date)], 'M'), symbol=symbol,
                                  value=cap, unit='元', currency=denominator['currency'], as_of=str(cap_date), source_url=cap_source)
                    result = valuation(market, denominator, kind)
                    if result['status'] == 'ok':
                        st.metric(kind.upper(), result['value'] + ' 倍')
                    else:
                        st.warning('不能计算：' + result['reason'])
                    st.json(result)
