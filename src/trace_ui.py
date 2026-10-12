"""Compact research trace display; missing usage and rates remain visible."""
import streamlit as st


def render_trace(state):
    summary = state.diagnostics.get('trace_summary')
    if not summary:
        st.caption('这份历史研究没有统一调用轨迹；不推算旧任务的 Token 和费用。')
        return
    st.caption(f'模型调用 {summary["model_calls"]} 次 · 工具记录 {summary["tool_calls"]} 条 · '
               f'已记录 Token {summary["known_total_tokens"]} · usage 未知 {summary["unknown_usage_calls"]} 次')
    if summary.get('total_model_cost_usd') is None:
        st.caption(f'模型费用未知；已知部分小计 USD {summary["known_cost_subtotal_usd"]}，'
                   f'{summary["unknown_model_cost_calls"]} 次调用缺 usage 或费率依据。')
    else:
        st.caption('模型 Token 费用估算 USD ' + summary['total_model_cost_usd'])
    st.caption('上述仅为配置费率下的模型 Token 估算；搜索等工具费用未知。')
    rows = []
    for item in state.diagnostics.get('trace', []):
        rows.append({'调用': item['operation'], '类型': item['kind'], '阶段': item['stage'],
                     '状态': item['status'], '开始': item['started_at'], '耗时 ms': item.get('elapsed_ms'),
                     '模型': item.get('model'), 'Token': (item.get('usage') or {}).get('total_tokens'),
                     '路由': item.get('routing'),
                     '费用 USD': (item.get('estimated_cost') or {}).get('amount')})
    if rows:
        st.dataframe(rows, hide_index=True)
