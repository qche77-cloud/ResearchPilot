"""UI for daily stock snapshots, watchlists, explicit memory and thesis journals."""
import json
import pandas as pd
import streamlit as st
from src.stock_data import normalize_symbol, fetch_stock, changes, data_error_message
from src.stock_presentation import search_directory, fetch_directory, financial_summary
from src.ui_theme import page_intro, empty_state
from src.stock_research import freshness, stock_history
from src.judgment_ui import render_judgment
from src.financial_ui import render_financial_tools


def render_workbench(store, start_research, repo=None):
    page_intro('个股研究台', '跟踪业绩与现金流，把数据、研究档案和投资判断连在一起。')
    stock, watch, comparison, screening, memory = st.tabs(['个股与复盘', '自选股变化', '公司对比', '财务筛选', '长期偏好'])
    with stock:
        search, directory_action = st.columns([4, 1], vertical_alignment='bottom')
        query = search.text_input('股票名称或六位代码', '002837', max_chars=40)
        if directory_action.button('更新股票名称目录', use_container_width=True):
            try:
                with st.spinner('更新名称目录…'):
                    store.save_directory(fetch_directory())
                st.success('名称目录已更新，可离线搜索。')
            except Exception as exc:
                st.error(data_error_message(exc) + '仍可用代码查询或搜索已有目录。')
        directory = store.directory()
        matches = search_directory(query, directory)
        symbol = query.strip()
        name = next((r['name'] for r in matches if r['symbol'] == symbol), symbol)
        if not (symbol.isdigit() and len(symbol) == 6):
            if matches:
                chosen = st.selectbox('匹配股票', matches, format_func=lambda r: f'{r["name"]} · {r["exchange"]}:{r["symbol"]}')
                symbol, name = chosen['symbol'], chosen['name']
            else:
                st.info('没有匹配到名称。可更新股票目录，或直接输入六位代码。')
        try:
            code, exchange = normalize_symbol(symbol)
        except ValueError as exc:
            st.info(str(exc))
            code = None
        if code:
            st.caption(f'{name} · {exchange}:{code} · 盘后日线研究')
            c1, c2, c3 = st.columns(3)
            if c1.button('更新行情与财务', type='primary', use_container_width=True):
                try:
                    with st.spinner('获取真实数据…'):
                        store.save_snapshot(code, fetch_stock(code))
                    st.success('已保存快照。')
                except Exception as exc:
                    st.error(data_error_message(exc) + '已有快照保留；下方如有数据，仍是缓存快照。')
            if c2.button('加入自选', use_container_width=True):
                store.watch(code, name)
                st.success('已加入自选。')
            if c3.button('Agent 研究个股', use_container_width=True):
                start_research(f'研究 A 股 {exchange}:{code} 的财务质量、现金流、近期公告、估值和风险，给出证据及推翻判断的条件。')
            snapshots = store.snapshots(code)
            overview_tab, financial_tab, profile_tab, thesis_tab = st.tabs(['行情概览', '财务分析', '研究档案', '投资复盘'])
            with overview_tab:
                if snapshots:
                    data = snapshots[0]['payload']
                    st.caption(f"来源：{data['provider']} · 获取时间：{data['fetched_at']} · {data['adjustment']}")
                    st.caption('当前展示本地已保存快照，并非实时行情；获取时间不等于交易日期。')
                    with st.expander('数据时效检查'):
                        st.json(freshness(data))
                    daily = pd.DataFrame(data['daily'])
                    last = daily.iloc[-1]
                    c1, c2, c3 = st.columns(3)
                    c1.metric('最近收盘（元）', f"{float(last['收盘']):.2f}")
                    c2.metric('交易日期', str(last['日期'])[:10])
                    c3.metric('成交量（手）', f"{float(last['成交量']):,.0f}")
                    daily['日期'] = pd.to_datetime(daily['日期'])
                    chart = st.radio('图表', ['收盘走势', '日 K 线'], horizontal=True)
                    if chart == '收盘走势':
                        st.line_chart(daily.set_index('日期')[['收盘']])
                    else:
                        st.vega_lite_chart(daily, {
                            'encoding': {'x': {'field': '日期', 'type': 'temporal'},
                                'color': {'condition': {'test': 'datum.收盘 >= datum.开盘', 'value': '#d85454'}, 'value': '#178576'}},
                            'layer': [
                                {'mark': 'rule', 'encoding': {'y': {'field': '最低', 'type': 'quantitative', 'scale': {'zero': False}}, 'y2': {'field': '最高'}}},
                                {'mark': {'type': 'bar', 'size': 4}, 'encoding': {'y': {'field': '开盘', 'type': 'quantitative', 'scale': {'zero': False}}, 'y2': {'field': '收盘'},
                                 'tooltip': [{'field': k, 'type': 'quantitative'} for k in ['开盘', '收盘', '最高', '最低']]}}]}, use_container_width=True)
                    st.caption('不复权价格；除权除息可能影响比较，不等于投资收益率。')
                    if len(snapshots) > 1:
                        st.info(changes(snapshots[1]['payload'], data))
                    for warning in data['warnings']:
                        st.warning(warning)
                    st.download_button('下载数据快照', json.dumps(data, ensure_ascii=False, indent=2), f'{code}.json')
                else:
                    empty_state('还没有行情快照', '点击「更新行情与财务」获取数据。已有财务导入可在财务分析页查看。')
            with financial_tab:
                if snapshots:
                    data = snapshots[0]['payload']
                    if data['finance']:
                        st.subheader('财务摘要')
                        period = st.selectbox('财报期间', sorted({str(r['报告期']) for r in data['finance']}, reverse=True), key='financial_period')
                        st.dataframe(pd.DataFrame(financial_summary(data['finance'], period)), hide_index=True)
                        st.caption('只有源字段或指标名称明确提供货币单位时才换算为亿元；单位未知的值保留原口径。季度期间可能是年初至今累计值。')
                    with st.expander('公司概况与财务原始指标'):
                        st.dataframe(pd.DataFrame(data['info']), hide_index=True)
                        st.caption('保留原始报告期与指标单位，未统一口径前不自动跨期或跨公司比较。')
                        finance = pd.DataFrame(data['finance'])
                        columns = [c for c in ['报告期', 'item_title', 'item_value', 'item_tongbi'] if c in finance]
                        st.dataframe(finance[columns].astype(str).rename(columns={'item_title': '指标', 'item_value': '源值（单位以原报告为准）', 'item_tongbi': '同比原值'}), hide_index=True)
                        st.link_button('核对财务数据源', f'https://vip.stock.finance.sina.com.cn/corp/go.php/vFD_FinanceSummary/stockid/{code}.phtml')
                render_financial_tools(store, code, snapshots[0]['payload'] if snapshots else None)
            with profile_tab:
                with st.container():
                    st.subheader('个股研究档案')
                    profile = store.profile(code)
                    with st.form('profile_' + code):
                        focus = st.text_area('关注点', profile['focus'])
                        supporting = st.text_area('支持证据与来源（用户记录）', profile['supporting'])
                        contrary = st.text_area('反面证据与来源（用户记录）', profile['contrary'])
                        questions = st.text_area('待核查问题', profile['questions'])
                        if st.form_submit_button('保存档案'):
                            store.save_profile(code, focus, supporting, contrary, questions)
                            st.success('已保存；Agent 只提供建议，不自动覆盖你的判断。')
                    st.caption('投资观点在「投资复盘」页管理。上述内容是用户记录，不等于已核实事实。')
                    if repo is not None:
                        history = stock_history(store, repo, code)
                        if st.button('更新这家公司', key='refresh_research_' + code, type='primary'):
                            start_research(f'更新 A 股 {code} 的研究：检查新增公告、业绩与风险，逐项对照上次判断。', symbol=code, update=True)
                        if history:
                            st.caption('历史关联：明确绑定的研究及按代码匹配的单股旧研究；名称型旧记录仍可在侧栏搜索。')
                            for previous in history[:10]:
                                if st.button(f'{previous.created_at[:10]} · {previous.status} · {previous.topic[:28]}', key='stock_run_' + previous.run_id):
                                    st.session_state.run_id = previous.run_id
                                    st.session_state.page = '研究对话'
                                    st.rerun()
                        else:
                            st.caption('尚无关联研究；首次研究将作为后续比较的起点。')
            with thesis_tab:
                st.subheader('投资观点与复盘')
                with st.form('thesis'):
                    thesis = st.text_area('为什么关注？')
                    catalyst = st.text_input('关注的事件')
                    invalidation = st.text_input('什么证据会推翻判断？')
                    if st.form_submit_button('保存假设') and thesis.strip():
                        store.add_thesis(code, thesis, catalyst, invalidation)
                        st.rerun()
                for item in store.theses(code):
                    with st.expander(item['status'] + ' · ' + item['thesis'][:40]):
                        st.write(item['thesis'])
                        st.write('催化：' + item['catalyst'])
                        st.write('什么情况会改变判断：' + item['invalidation'])
                        with st.form(item['id']):
                            review = st.text_area('复盘记录', item['review'])
                            options = ['观察中', '得到支持', '被推翻', '已结束']
                            status = st.selectbox('状态', options, index=options.index(item['status']))
                            if st.form_submit_button('保存复盘'):
                                store.review(item['id'], review, status)
                                st.rerun()
                        if st.button('核查投资观点', key='verify_' + item['id']):
                            start_research(f"核查 A 股 {code} 的假设：{item['thesis']}；催化：{item['catalyst']}；什么情况会改变判断：{item['invalidation']}。搜索公告和反例，不预设结论。")
                        if repo is not None:
                            render_judgment(store, repo, code, item)
    with watch:
        st.caption('可手动刷新，也可开启工作日 16 点后的自动更新。仅在本地服务运行时执行，变化记录显示在这里，不发送外部通知。')
        for item in store.watches():
            code = item['symbol']
            st.subheader(f'{item["name"]} · {code}' if item['name'] != code else code)
            config = next((m for m in store.monitors() if m['symbol'] == code), {})
            enabled = st.checkbox('启用盘后自动更新', value=bool(config.get('enabled')), key='monitor_' + code)
            if enabled != bool(config.get('enabled')):
                store.set_monitor(code, enabled)
            with st.expander('监控频率、来源与运行记录'):
                with st.form('monitor_settings_' + code):
                    hours = st.number_input('最短更新间隔（小时）', min_value=1, max_value=168,
                                            value=max(1, int(config.get('interval_seconds', 72000) / 3600)))
                    modes = ['daily_and_financials', 'daily']
                    mode = st.selectbox('监控内容', modes, index=modes.index(config.get('source_mode', modes[0])),
                                        format_func=lambda m: '日线与财务源值变化' if m == modes[0] else '日线变化')
                    if st.form_submit_button('保存监控设置'):
                        store.configure_monitor(code, int(hours) * 3600, mode)
                        st.success('已保存；仍只在本地服务运行且满足盘后时段时执行。')
                st.caption('日线来源：AKShare/东方财富；财务来源：新浪。源值变化不是已核实的新公告，不会自动调用模型或搜索。')
                events = store.monitor_events(code)
                if events:
                    st.dataframe([{'时间': e['created'], '状态': e['status'], '来源': e['source'], '明细': json.dumps(e['detail'], ensure_ascii=False)} for e in events], hide_index=True)
            for alert in store.alerts(code):
                st.caption(alert['created'] + ' · ' + alert['content'])
            snapshots = store.snapshots(code)
            if len(snapshots) > 1:
                st.write(changes(snapshots[1]['payload'], snapshots[0]['payload']))
            else:
                st.caption('需要至少两份快照才能比较变化。')
            c1, c2, c3 = st.columns(3)
            if c1.button('更新快照', key='update_' + code):
                try:
                    with st.spinner('更新中…'):
                        store.save_snapshot(code, fetch_stock(code))
                    st.rerun()
                except Exception as exc:
                    st.error(data_error_message(exc) + '已有快照保留。')
            if c2.button('研究最新变化', key='research_' + code):
                start_research(f'更新 A 股 {code} 的公告、业绩、回购减持和业务变化，核查是否影响原判断。', symbol=code, update=True)
            if c3.button('移出自选', key='remove_' + code):
                store.unwatch(code)
                store.set_monitor(code, False)
                st.rerun()
        if not store.watches():
            empty_state('建立你的观察名单', '在个股页点击「加入自选」，集中跟踪公司变化与研究进展。')
    with comparison:
        st.caption('选择已有快照的自选股进行比较。财务只展示共同报告期，不混用不同期间。')
        available = [w['symbol'] for w in store.watches() if store.snapshots(w['symbol'], 1)]
        selected = st.multiselect('对比股票（最多 4 只）', available, max_selections=4)
        if len(selected) >= 2:
            data = {code: store.snapshots(code, 1)[0]['payload'] for code in selected}
            rows = [{'代码': code, '交易日': p['daily'][-1]['日期'][:10], '收盘（元，不复权）': p['daily'][-1]['收盘'], '获取时间': p['fetched_at']} for code, p in data.items()]
            st.dataframe(pd.DataFrame(rows), hide_index=True)
            periods = [set(r['报告期'] for r in p['finance']) for p in data.values()]
            common = sorted(set.intersection(*periods), reverse=True)
            if common:
                period = st.selectbox('共同财报期间', common)
                table = []
                for code, payload in data.items():
                    for row in financial_summary(payload['finance'], str(period)):
                        table.append({'代码': code, **row})
                st.dataframe(pd.DataFrame(table).drop_duplicates(), hide_index=True)
                st.caption('单位待核对的指标不可直接比较；同报告期也需核对会计口径。')
            else:
                st.info('缺少共同财报期间，暂不比较财务指标。')
            if st.button('深入研究比较'):
                start_research('比较 A 股 ' + '、'.join(selected) + ' 的业务壁垒、现金流及业绩兑现；统一财务期间和单位，缺少可比数据时明确说明。')
    with screening:
        from src.financial_screening_ui import render_financial_screening
        render_financial_screening(store, start_research)
    with memory:
        with st.form('preferences'):
            value = st.text_area('明确保存的偏好（例如只看 A 股、优先公告、关注现金流）', store.preferences(), height=150)
            if st.form_submit_button('保存偏好'):
                store.save_preferences(value)
                st.success('已保存，供新研究和后续追问使用。')
        if st.button('清除偏好'):
            store.save_preferences('')
            st.rerun()
        st.caption('历史消息保存在本地；追问带最近 12 条消息及最多 30 条较早消息的摘录，不是无限上下文。')
