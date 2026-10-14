"""Financial screening of locally saved watchlist inputs, with explicit opt-in demo."""
import copy
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st
from src.financial_analysis import number
from src.financial_screening import screen_financials
from src.financial_ui import example_dataset


def demo_pool():
    first = example_dataset('002837')
    second = copy.deepcopy(first)
    second['symbol'] = '600000'
    for r in second['financial_records']:
        if r['metric'] == 'attributable_net_profit' and r['period_end'].startswith('2025'):
            r['value'] = str(number(r['value']) * 2)
    return {'002837': first, '600000': second}


def render_financial_screening(store, start_research):
    st.subheader('自选股财务筛选')
    st.caption('从本地已保存数据筛选值得进一步研究的公司。筛选不自动刷新数据，也不调用模型或搜索。')
    watches = store.watches()
    names = {w['symbol']: w['name'] for w in watches}
    demo = st.checkbox('使用离线虚构股票池演示（不保存）', key='screen_demo')
    options = list(demo_pool()) if demo else list(names)
    if demo:
        st.warning('示例股票代码只是展示标识，全部数值为虚构，不能作为这些公司的真实判断。')
    with st.form('financial_screening'):
        symbols = st.multiselect('筛选股票（最多 50 家）', options, default=options[:50], max_selections=50)
        left, right = st.columns(2)
        cutoff = left.date_input('筛选日期', value=datetime.now(ZoneInfo('Asia/Shanghai')).date())
        basis = right.selectbox('筛选期间口径', ['cumulative', 'single_quarter'],
                                format_func=lambda b: '年初至今累计' if b == 'cumulative' else '单季度')
        currency = left.selectbox('筛选币种', ['CNY', 'HKD', 'USD', 'EUR'])
        scope = right.selectbox('筛选报表范围', ['consolidated', 'parent_company'],
                                format_func=lambda s: '合并报表' if s == 'consolidated' else '母公司报表')
        revenue_min = left.number_input('营业收入同比下限（%）', value=0.0)
        profit_min = right.number_input('归母净利润同比下限（%）', value=0.0)
        submitted = st.form_submit_button('运行财务筛选')
    if submitted:
        payloads = {}
        fixtures = demo_pool() if demo else {}
        for symbol in symbols:
            imported = store.financial_dataset(symbol) if not demo else None
            snapshots = store.snapshots(symbol, 1) if not demo and not imported else []
            payloads[symbol] = fixtures[symbol] if demo else imported['payload'] if imported else snapshots[0]['payload'] if snapshots else {'symbol': symbol}
        try:
            result = screen_financials(payloads, as_of=cutoff, basis=basis, currency=currency, scope=scope,
                                       minimums={'revenue_yoy': str(revenue_min), 'attributable_profit_yoy': str(profit_min)})
            st.session_state.financial_screen_result = {'result': result, 'demo': demo}
        except ValueError as exc:
            st.error(str(exc))
    saved = st.session_state.get('financial_screen_result')
    if saved:
        result = saved['result']
        if saved['demo']:
            st.warning('下方结果来自虚构演示数据；不会提供真实公司研究触发按钮。')
        st.caption(f'已运行日期 {result["parameters"]["as_of"]} · 匹配 {result["matched_count"]}/{result["stock_count"]} 家；修改条件后请重新运行。')
        st.json(result['parameters'], expanded=False)
        rows = []
        for r in result['rows']:
            quality = r['quality']
            row = {'代码': r['symbol'], '名称': '虚构样本' if saved['demo'] else names.get(r['symbol'], r['symbol']),
                   '匹配': '是' if r['matched'] else '否', '财报期': quality['period_end'],
                   '可计算项': f'{quality["available_factors"]}/{quality["total_factors"]}', '原因': '；'.join(r['reasons'])}
            for f in quality['factors']:
                unit = '%' if f['unit'] == 'percent' else '倍'
                row[f['label'] + '（' + unit + '）'] = format(number(f['value']), '.2f') if f['value'] is not None else None
            rows.append(row)
        st.dataframe(rows, hide_index=True, use_container_width=True)
        st.download_button('下载筛选规则、结果和证据', json.dumps(result, ensure_ascii=False, indent=2), 'financial-screen.json')
        if not saved['demo']:
            matched = [r for r in result['rows'] if r['matched']]
            for r in matched:
                if st.button('Agent 核查 ' + r['symbol'], key='screen_research_' + r['symbol']):
                    params = json.dumps(result['parameters'], ensure_ascii=False)
                    start_research(f'核查 A 股 {r["symbol"]} 的财务筛选结果（规则：{params}）。核对原始财报和反面证据；这些指标不代表投资建议。', symbol=r['symbol'])
    elif not options:
        st.info('先在个股页加入自选并保存带来源的财务输入，或勾选离线演示查看功能。')
    st.caption('表格保留两位小数，下载保留精确值。该列表由你选择的股票池构成，不自动声称同业可比；缺少披露日期或财务口径的公司会说明未匹配原因。')
