"""Research validation with read-only analysis and explicit local ledger saves."""
from datetime import date, datetime
import json
from zoneinfo import ZoneInfo
import streamlit as st

from src.research_signal_fixtures import demo_manifest
from src.research_signals import DEFAULT_RULES, LIMITATIONS, evaluate_experiment, score_financials

METHODS = {'baseline':'增长基线','rules':'财务综合规则','agent':'登记研究判断'}
OUTCOMES = {'not_due':'未到复盘日','waiting_for_data':'等待可比数据',
            'criterion_met':'财务判据满足','criterion_not_met':'财务判据未满足'}


def _read_upload(upload):
    if upload is None:
        raise ValueError('请先选择本地 JSON 文件')
    content=upload.getvalue()
    if len(content)>2*1024*1024:
        raise ValueError('JSON 文件不能超过 2 MB')
    return json.loads(content.decode('utf-8-sig'))


def _json(value):
    return json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)


def _prediction(value):
    return '预期满足' if value is True else '预期未满足' if value is False else '未判断'


def _score_detail(score):
    st.caption(f'评分期 {score["period_end"] or "未知"} · 截止日 {score["as_of"]} · 规则 {score["rules"]["version"]}')
    st.caption(f'综合分 {score["score"] if score["score"] is not None else "数据不足"} / 100 · 覆盖权重 {score["coverage_weight"]}%')
    st.dataframe([{'指标':f['label'],'原值':f['value'],'单位':f['unit'],'权重':f['weight'],
                   '分档阈值':' / '.join(f['cutoffs']),'因子分':f['points'],'加权贡献':f['contribution'],
                   '缺口':f['reason'],'输入编号':' / '.join(f['input_ids'])} for f in score['factors']],
                 hide_index=True,use_container_width=True)
    if score['flags']:
        st.info('；'.join(f['message'] for f in score['flags']))
    with st.expander('计算公式、原始数值与来源记录'):
        st.json(score['inputs'])


def _result(result):
    if result['provenance']=='synthetic_offline_fixture':
        st.warning('当前全部公司、数字和登记判断均为虚构。这里没有运行模型，示例成绩不代表 Agent 实际能力或收益。')
    st.caption(f'已运行验证截止日 {result["as_of"]} · 实验 {result["id"][:12]} · 修改输入后需重新运行')
    st.caption('验证任务：'+result['label_definition'])
    columns=st.columns(3)
    columns[0].metric('登记样本',result['case_count'])
    columns[1].metric('规则与基线共同样本',result['rule_baseline_cohort']['n'])
    columns[2].metric('三种方法共同样本',result['all_methods_cohort']['n'])
    cohort_name=st.radio('比较范围',['规则与增长基线','加入登记研究判断'],horizontal=True,key='signal_cohort')
    cohort=result['rule_baseline_cohort' if cohort_name=='规则与增长基线' else 'all_methods_cohort']
    if not cohort['n']:
        st.info('没有同时具备判断和已知结果的共同样本，暂不计算比较成绩。')
    st.dataframe([{'方法':METHODS[m],'共同样本数':v['n'],'正确率':v['accuracy'],
                   '精确率':v['precision'],'召回率':v['recall'],'真阳性':v['tp'],'真阴性':v['tn'],
                   '假阳性':v['fp'],'假阴性':v['fn']} for m,v in cohort['metrics'].items()],
                 hide_index=True,use_container_width=True)
    st.caption('比率范围为 0–1；分母为零时显示为空。只在同一批样本上比较，不把未到期或缺数据当成失败。')
    with st.expander('全部样本的覆盖情况'):
        st.dataframe([{'方法':METHODS[m],'有判断':v['decisions'],'有可验证结果':v['labeled'],'登记总数':v['total']}
                      for m,v in result['coverage'].items()],hide_index=True,use_container_width=True)
    st.subheader('逐项检查与失败案例')
    st.dataframe([{'样本':r['id'],'代码':r['symbol'],'决策日':r['decision_on'],
                   '综合分':r['score']['score'],'覆盖权重':r['score']['coverage_weight'],
                   '增长基线':_prediction(r['predictions']['baseline']),
                   '综合规则':_prediction(r['predictions']['rules']),
                   '登记判断':_prediction(r['predictions']['agent']),
                   '后续结果':OUTCOMES[r['outcome_status']]} for r in result['rows']],
                 hide_index=True,use_container_width=True)
    selected=st.selectbox('查看样本证据',[r['id'] for r in result['rows']],key='signal_case')
    row=next(r for r in result['rows'] if r['id']==selected)
    _score_detail(row['score'])
    st.caption(row['agent_note'])
    with st.expander('未来财务判据与该版本的观测'):
        st.json({'criterion':next(c['criterion'] for c in result['replay']['manifest']['cases'] if c['id']==selected),
                 'outcome':row['outcome'],'feature_hash':row['feature_hash'],'outcome_hash':row['outcome_hash']})
    st.download_button('下载完整验证结果与重放输入',_json(result),'research-signal-result.json',mime='application/json',key='signal_export')


def render_signal_validation(store=None):
    st.title('研究信号验证')
    st.caption('把财务评分、事前研究判断与后续财务判据放在可追溯记录中。分析读取本地输入；前向账本仅在点击保存时追加记录。不调用模型、抓取行情或交易。')
    historical,current,forward,readiness,policy=st.tabs(['历史验证','当前财务评分','前向研究','数据检查','规则与边界'])
    with historical:
        source=st.radio('实验来源',['离线虚构实验','本地实验 JSON'],horizontal=True,key='signal_source')
        upload=st.file_uploader('实验 JSON（最多 2 MB）',type=['json'],key='signal_experiment_upload') if source=='本地实验 JSON' else None
        with st.form('signal_experiment_form'):
            cutoff=st.date_input('验证截止日',value=date(2026,5,2),key='signal_review_date')
            submitted=st.form_submit_button('运行离线验证')
        if submitted:
            try:
                loaded=demo_manifest() if source=='离线虚构实验' else _read_upload(upload)
                replay=loaded.get('replay') if isinstance(loaded,dict) else None
                manifest=replay['manifest'] if isinstance(replay,dict) else loaded
                rules=replay['rules'] if isinstance(replay,dict) else None
                st.session_state['signal_result']=evaluate_experiment(manifest,as_of=cutoff,rules=rules)
                st.session_state.pop('signal_error',None)
            except (ValueError,TypeError,KeyError,UnicodeError) as error:
                st.session_state['signal_error']=str(error)
                st.session_state.pop('signal_result',None)
        if st.session_state.get('signal_error'):
            st.error(st.session_state['signal_error'])
        if st.session_state.get('signal_result'):
            _result(st.session_state['signal_result'])
        else:
            st.info('先运行虚构实验，查看完整覆盖、缺失数据和失败案例；之后可导入自己的事前档案。')
        st.download_button('下载虚构实验模板',_json(demo_manifest()),'fictional-signal-experiment.json',mime='application/json',key='signal_template')
    with current:
        st.info('此页按披露日期计算当前评分，不视为严格历史回放。历史实验还要求档案、规则和判据在决策日前确定。')
        options=['虚构财务样本','本地财务 JSON']+(['自选公司的保存版本'] if store is not None else [])
        source=st.selectbox('评分数据来源',options,key='signal_score_source')
        raw_upload=st.file_uploader('财务 JSON（最多 2 MB）',type=['json'],key='signal_finance_upload') if source=='本地财务 JSON' else None
        selected_version=None
        if source=='自选公司的保存版本':
            watches=store.watches()[:50]
            if watches:
                symbol=st.selectbox('公司',[w['symbol'] for w in watches],key='signal_stock')
                versions=store.financial_versions(symbol)
                if versions:
                    chosen=st.selectbox('明确选择财务版本',[v['id'] for v in versions],key='signal_version')
                    selected_version=next(v for v in versions if v['id']==chosen)
                else:
                    st.info('该公司尚无保存的财务版本。')
            else:
                st.info('当前没有自选公司。')
        with st.form('signal_score_form'):
            as_of=st.date_input('财务数据截止日',value=datetime.now(ZoneInfo('Asia/Shanghai')).date(),key='signal_score_date')
            calculate=st.form_submit_button('计算透明评分')
        if calculate:
            try:
                payload=(demo_manifest()['snapshots'][0]['payload'] if source=='虚构财务样本' else
                         _read_upload(raw_upload) if source=='本地财务 JSON' else
                         selected_version['payload'] if selected_version else None)
                if not isinstance(payload,dict) or not isinstance(payload.get('financial_records'),list) or len(payload['financial_records'])>1000:
                    raise ValueError('请选择含最多 1000 条标准财务记录的输入')
                score=score_financials(payload,as_of=as_of)
                st.session_state['signal_current']={'score':score,'source':source,'version':selected_version['id'] if selected_version else None}
                st.session_state.pop('signal_current_error',None)
            except (ValueError,TypeError,KeyError,UnicodeError) as error:
                st.session_state['signal_current_error']=str(error)
                st.session_state.pop('signal_current',None)
        if st.session_state.get('signal_current_error'):
            st.error(st.session_state['signal_current_error'])
        saved=st.session_state.get('signal_current')
        if saved:
            if saved['source']=='虚构财务样本' or any(marker in str(saved['score'].get('provenance','')).lower() for marker in ('synthetic','fixture','demo')):
                st.warning('此评分来自虚构财务数据。')
            score=saved['score']
            st.caption(f'已计算来源：{saved["source"]} · 版本 {saved["version"] or "本地输入"} · 覆盖权重 {score["coverage_weight"]}%')
            st.metric('综合分（满分 100）',score['score'] if score['score'] is not None else '数据不足')
            _score_detail(score)
            st.download_button('下载评分与精确输入',_json(saved),'financial-research-score.json',mime='application/json',key='signal_score_export')
    with forward:
        from src.forward_research_ui import render_forward_research
        render_forward_research(store)
    with readiness:
        from src.forward_research_ui import render_readiness
        render_readiness(store)
    with policy:
        for text in LIMITATIONS: st.write('• '+text)
        st.write('日期级决策按当日开始处理，档案、样本池、判据和规则必须在前一日或更早确定；带时间戳的元数据统一换算为北京时间。')
        st.write('当前真实规则版本登记日为 2026-10-20。演示的 2025 年登记日期是明确的虚构元数据，不代表这些规则当时真实存在。')
        st.write('增长基线：营业收入同比与归母净利润同比均不低于 0。分档四档分值为 0/40/70/100；满足多少个递增阈值决定档位，加权后满分 100。')
        st.json(DEFAULT_RULES)
