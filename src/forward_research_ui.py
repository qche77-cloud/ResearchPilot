"""Prospective research UI: explicit local saves and session-only fictional demo."""
from datetime import date, timedelta
import json
import uuid
import streamlit as st

from src.forward_demo import ForwardDemo
from src.forward_ledger import ForwardLedger, replay_review
from src.research_readiness import ReadOnlyWorkbench, audit_version, audit_workbench
from src.research_signals import DEFAULT_RULES, day, digest

STATUS = {'awaiting_decision':'等待决策日','not_due':'未到复盘日','review_due':'到期未复盘',
          'waiting_for_data':'等待可比数据','criterion_met':'财务判据满足','criterion_not_met':'财务判据未满足'}
METHODS = {'baseline':'增长基线','rules':'财务综合规则','manual':'人工登记判断'}


def _json(value):
    return json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)


@st.fragment
def _download(label,value,filename,key):
    # Streamlit 1.41-compatible isolation: downloading must not rerun the ledger.
    st.download_button(label,_json(value),filename,mime='application/json',key=key)


def _local_reader(store,key):
    if store is not None:
        return ReadOnlyWorkbench(store.path)
    if st.checkbox('连接本机电脑工作台的已保存资料',key=key):
        from src.workbench import DEFAULT_PATH
        return ReadOnlyWorkbench(DEFAULT_PATH)
    st.info('连接后只读取已有财务版本。保存登记或复盘时，才会写入本机的新账本表。')
    return None


def _criterion(target,review,rules):
    return {'review_on':str(review),'criteria':[
        dict(metric='revenue',measure='yoy',operator='>=',threshold='0',period_end=str(target),
             currency=rules['currency'],scope=rules['scope'],basis=rules['basis']),
        dict(metric='net_profit',measure='value',operator='>',threshold='0',period_end=str(target),
             currency=rules['currency'],scope=rules['scope'],basis=rules['basis'])]}


def render_forward_research(store=None):
    st.subheader('把今天的判断留给未来验证')
    st.caption('先检查并固定已有财务版本，再登记未来决策日和目标财报期。保存时间由本机记录，复盘追加保存，原判断保留。')
    mode=st.radio('账本空间',['隔离演示','本机工作台'],horizontal=True,key='forward_space')
    demo=None
    if mode=='隔离演示':
        if 'forward_demo_context' not in st.session_state:
            st.session_state['forward_demo_context']=ForwardDemo()
        demo=st.session_state['forward_demo_context']
        reader=ReadOnlyWorkbench(demo.store.path)
        ledger=demo.ledger
        st.warning('隔离演示：公司、财务数字与时钟均为虚构，数据在独立临时库中，不计入真实研究成绩。')
        st.caption('当前模拟日期：'+str(day(ledger.now())))
    else:
        reader=_local_reader(store,'forward_connect')
        if reader is None: return
        ledger=ForwardLedger(reader)
        st.caption('本机今日：'+str(day(ledger.now()))+' · 真实登记不接受补填过去日期。')
    namespace='forward_'+digest(str(reader.path))[:12]
    try:
        registrations=ledger.registrations()
        watches=reader.watches()
    except (ValueError,RuntimeError) as error:
        st.error(str(error))
        return
    if demo:
        a,b,c=st.columns(3)
        if a.button('模拟新财报到来',disabled=not bool(registrations),key=namespace+'_advance'):
            demo.advance()
            st.session_state[namespace+'_cutoff']=day(ledger.now())
            st.session_state[namespace+'_outcome']='demo-forward-outcome'
            st.rerun()
        if b.button('模拟财报修订',disabled=not bool(registrations),key=namespace+'_revise'):
            demo.revise()
            st.session_state[namespace+'_cutoff']=day(ledger.now())
            st.session_state[namespace+'_outcome']='demo-forward-revised'
            st.rerun()
        if c.button('重置演示',key=namespace+'_reset'):
            st.session_state.pop('forward_demo_context',None)
            st.rerun()
    if not watches:
        st.info('先在电脑工作台加入自选公司并保存已核对口径的财务版本。')
    elif not (demo and registrations):
        with st.expander('登记一项未来研究',expanded=True):
            names={w['symbol']:w['name'] for w in watches}
            symbol=st.selectbox('研究公司',list(names),format_func=lambda s:names[s]+' · '+s,key=namespace+'_symbol')
            versions=reader.financial_versions(symbol)
            if not versions:
                st.info('该公司还没有独立保存的财务版本，请先在电脑端导入。')
            else:
                records={r['id']:r for r in versions}
                version=st.selectbox('登记使用的财务版本',list(records),
                    format_func=lambda k:records[k]['created'][:10]+' · '+k,key=namespace+'_version')
                selected=records[version]
                columns=st.columns(3)
                currency=columns[0].selectbox('登记币种',['CNY','HKD','USD','EUR'],key=namespace+'_currency')
                scope=columns[1].selectbox('登记范围',['consolidated','parent_company'],
                    format_func=lambda v:'合并报表' if v=='consolidated' else '母公司报表',key=namespace+'_scope')
                basis=columns[2].selectbox('登记期间口径',['cumulative','single_quarter'],
                    format_func=lambda v:'年初至今累计' if v=='cumulative' else '单季度',key=namespace+'_basis')
                rules=dict(DEFAULT_RULES,currency=currency,scope=scope,basis=basis)
                today=day(ledger.now())
                decision=st.date_input('未来决策日',value=date(2025,5,5) if demo else today+timedelta(days=1),key=namespace+'_decision')
                default_target=date(2025,12,31) if demo else date(decision.year+(decision.month==12 and decision.day==31),12,31)
                target=st.date_input('目标财报期末',value=default_target,key=namespace+'_target')
                review=st.date_input('计划复盘日',value=date(2026,5,1) if demo else default_target+timedelta(days=120),key=namespace+'_review')
                st.caption('验证条件：目标期营业收入同比不低于 0，且同范围净利润大于 0。两项均满足才标记满足。')
                try:
                    preview=ledger.preview(symbol,version,decision_on=decision,rules=rules)
                    score=preview['score']
                    st.caption('本次评分：'+str(score['score'] if score['score'] is not None else '数据不足')+' · 因子覆盖权重 '+score['coverage_weight']+'%')
                    if score['status']!='complete':
                        st.info('因子不完整，综合规则暂不判断。仍可记录有明确证据的人工判断，缺口将保留。')
                    judgment=st.selectbox('你的事前判断',['暂不判断','预期满足','预期未满足'],key=namespace+'_judgment')
                    prediction={'暂不判断':None,'预期满足':True,'预期未满足':False}[judgment]
                    note=st.text_area('判断依据与待核查问题',max_chars=4000,key=namespace+'_note')
                    evidence=st.multiselect('关联财务证据',list(score['inputs']),max_selections=20,
                        format_func=lambda k:score['inputs'][k]['label']+' · '+score['inputs'][k]['period_end']+' · '+k,
                        key=namespace+'_evidence')
                    if st.button('保存前向登记',type='primary',key=namespace+'_save'):
                        args={'symbol':symbol,'dataset_id':version,'expected_payload_hash':preview['payload_hash'],
                              'decision_on':str(decision),'criterion':_criterion(target,review,rules),'prediction':prediction,
                              'note':note,'evidence_ids':evidence,'rules':rules}
                        fingerprint=digest(args)
                        saved=st.session_state.get(namespace+'_request')
                        if not saved or saved['fingerprint']!=fingerprint:
                            saved={'fingerprint':fingerprint,'key':uuid.uuid4().hex}
                            st.session_state[namespace+'_request']=saved
                        record=ledger.register(**args,request_key=saved['key'])
                        st.session_state[namespace+'_saved']=record['id']
                        st.rerun()
                except ValueError as error:
                    st.warning(str(error))
    if st.session_state.get(namespace+'_saved'):
        st.success('前向登记已保存。原始版本、规则和判断已固定。')
    try:
        registrations=ledger.registrations()
        policy=st.radio('统计使用的复盘结果',['首次已知结果','最新复盘结果'],horizontal=True,key=namespace+'_policy')
        st.caption('统计口径：'+policy)
        report=ledger.summary(review_policy='first_known' if policy=='首次已知结果' else 'latest')
        cols=st.columns(3)
        cols[0].metric('账本登记',report['count'])
        cols[1].metric('到期未复盘',report['due_count'])
        cols[2].metric('发现结果修订',report['revised_count'])
        if report['rows']:
            st.dataframe([{'代码':r['symbol'],'登记日':r['created_at'][:10],'决策日':r['decision_on'],
                '复盘日':r['review_on'],'状态':STATUS[r['status']],'冻结分数':r['score'],
                '覆盖权重':r['coverage_weight'],'结果有修订':'是' if r['result_revised'] else '否'} for r in report['rows']],hide_index=True,use_container_width=True)
        else:
            st.info('尚无前向登记。可以先在隔离演示中走完登记、到期检查和财报修订流程。')
        group=report['groups']['synthetic_fixture' if demo else 'local_prospective']
        with st.expander('同批样本比较与覆盖'):
            st.caption('当前口径：'+policy+'。只比较同一批有判断且有已知结果的样本，未到期或缺数据不算失败。')
            for title,cohort in [('规则与增长基线',group['rule_baseline']),('加入人工判断',group['with_manual'])]:
                st.write(title+' · 共同样本 '+str(cohort['n']))
                st.dataframe([{'方法':METHODS[k],'样本':v['n'],'正确率':v['accuracy'],'真阳性':v['tp'],
                               '真阴性':v['tn'],'假阳性':v['fp'],'假阴性':v['fn']} for k,v in cohort['metrics'].items()],hide_index=True,use_container_width=True)
        _download('下载账本概览',report,'forward-research-summary.json',namespace+'_summary_download')
        if registrations:
            by_id={r['id']:r for r in registrations}
            chosen=st.selectbox('查看登记与复盘',[r['id'] for r in registrations],
                format_func=lambda k:by_id[k]['symbol']+' · '+by_id[k]['decision_on']+' · '+k[-8:],key=namespace+'_entry')
            registration=by_id[chosen]
            origin='人工登记' if registration['predictions']['manual'] is not None else '尚未登记人工判断'
            st.caption('原始登记时间：'+registration['created_at']+' · '+origin+' · 数据版本 '+registration['dataset_id'])
            with st.expander('冻结的判断、规则和来源'):
                st.json({'criterion':registration['criterion'],'judgment':registration['manual_judgment'],
                         'predictions':registration['predictions'],'rules':registration['rules'],
                         'payload_hash':registration['payload_hash'],'inputs':registration['score']['inputs']})
            outcome_versions=reader.financial_versions(registration['symbol'])
            outcomes={r['id']:r for r in outcome_versions}
            outcome=st.selectbox('明确选择本次复盘的数据版本',['']+list(outcomes),
                format_func=lambda k:'不指定新版本，仅检查到期状态' if not k else outcomes[k]['created'][:10]+' · '+k,key=namespace+'_outcome')
            cutoff=st.date_input('本次复盘截止日',value=day(ledger.now()),max_value=day(ledger.now()),key=namespace+'_cutoff')
            if st.button('检查并追加复盘',key=namespace+'_check'):
                saved_review=ledger.review(chosen,outcome_dataset_id=outcome or None,as_of=cutoff)
                st.session_state[namespace+'_history']=saved_review['id']
                st.session_state[namespace+'_review_saved']=True
                st.rerun()
            if st.session_state.get(namespace+'_review_saved'):
                st.success('复盘已追加保存，原登记与旧复盘未被覆盖。')
            history=ledger.reviews(chosen)
            if history:
                st.dataframe([{'保存时间':r['created_at'],'截止日':r['as_of'],'数据版本':r['dataset_id'] or '未选择',
                               '结果':STATUS[r['result']['status']]} for r in history],hide_index=True,use_container_width=True)
                selected_review=st.selectbox('选择已保存的复盘版本',[r['id'] for r in history],key=namespace+'_history')
                saved=next(r for r in history if r['id']==selected_review)
                result=saved['result']
                st.info('所选复盘结果：'+STATUS[result['status']])
                difference=result.get('previous_review_diff')
                if difference:
                    st.caption('对比上次复盘：同期间修订 '+str(len(difference['changed_financial_values']))+' 条，新期间记录 '+str(len(difference['new_financial_records']))+' 条。')
                    changes=difference['changed_financial_values']
                    if changes:
                        from src.financial_analysis import METRICS
                        st.dataframe([{'指标':METRICS.get(c['after']['metric'],c['after']['metric']),
                            '财报期':c['after']['period_end'],'修订前':c['before']['value'],'修订后':c['after']['value'],
                            '币种':c['after']['currency'],
                            '单位':({'CNY':'元','HKD':'港元','USD':'美元','EUR':'欧元'}.get(c['after']['currency'],'原币单位')
                                    if c['after']['unit']=='currency_unit' else '%' if c['after']['unit']=='percent' else c['after']['unit']),
                            '来源':c['after']['source_url']} for c in changes],hide_index=True,use_container_width=True)
                with st.expander('判据观测与数据变化'):
                    st.json(result)
                if st.button('校验所选版本的重放',key=namespace+'_replay'):
                    if result==replay_review(saved['replay']):
                        st.success('重放一致：仅使用保存的输入，结果未受最新数据影响。')
                _download('下载所选复盘与重放输入',saved,'forward-review.json',namespace+'_review_download')
    except ValueError as error:
        st.error(str(error))


def render_readiness(store=None):
    st.subheader('保存资料是否足够开展验证')
    st.caption('检查已保存的日期、来源、财务口径和因子覆盖。这里不抓取新数据，也不修改已有版本。')
    reader=_local_reader(store,'readiness_connect')
    if reader is None: return
    key='readiness_'+digest(str(reader.path))[:12]
    try:
        if st.button('只读检查自选财务资料',key=key+'_run'):
            from datetime import datetime
            from zoneinfo import ZoneInfo
            st.session_state[key+'_result']=audit_workbench(reader.path,as_of=datetime.now(ZoneInfo('Asia/Shanghai')).date())
        report=st.session_state.get(key+'_result')
        if not report: return
        cols=st.columns(3)
        cols[0].metric('已检查公司',report['company_count'])
        cols[1].metric('可开始前向登记',report['forward_ready'])
        cols[2].metric('缺少独立版本',len(report['missing_versions']))
        st.caption('检查日期：'+report['as_of']+'。资料变化后请重新检查。可登记只表示满足输入契约，不认证来源或投资有效性。')
        st.dataframe([{'代码':r['symbol'],'财报期':r['period_end'],'保存日':str(r['saved_at'])[:10],
                       '可用记录':r['usable_records'],'待核对记录':r['blocked_records'],
                       '覆盖权重':r['score']['coverage_weight'] if r['score'] else '0',
                       '可登记':'是' if r['forward_ready'] else '否',
                       '需处理':'；'.join(p['message'] for p in r['issues'])} for r in report['reports']],hide_index=True,use_container_width=True)
        if report['missing_versions']:
            st.info('尚无独立财务版本：'+'、'.join(report['missing_versions'])+'。可在电脑端核对原始财报后导入。')
        _download('下载本机资料检查报告',report,'research-input-readiness.json',key+'_download')
    except (ValueError,RuntimeError) as error:
        st.error(str(error))
