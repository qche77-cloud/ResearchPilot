"""Validated Studio intents for PDF import and immutable peer comparisons."""
import base64
import binascii
from datetime import date
from src.financial_import import prepare_import, confirmed_payload
from src.peer_research import compare_peers

ACTIONS={'pdf_prepare','pdf_confirm','pdf_download','save_peer_group','compare_peers','open_peer_run','research_peer_lead'}


def workspace_view(store,session,symbol):
    ready=all(callable(getattr(store,k,None)) for k in ('financial_documents','save_pdf_import','peer_groups','peer_run'))
    if not ready:
        return {'ready':False}
    proposal=session.get('studio_pdf_proposal')
    row=store.peer_run(session['studio_peer_run']) if session.get('studio_peer_run') else None
    return dict(ready=True,documents=store.financial_documents(symbol),groups=store.peer_groups(),
                proposal={k:v for k,v in proposal.items() if k!='pages'} if proposal and proposal['symbol']==symbol else None,
                comparison=dict(row['result'],run_id=row['id'],group_id=row['group_id'],bindings=row['bindings']) if row else None,
                history=store.peer_history(symbol),download=session.get('studio_pdf_download') if session.get('studio_pdf_download',{}).get('symbol')==symbol else None)


def handle(event,service,session):
    action=event['action'];store=service.store;symbol=event.get('symbol')
    if symbol!=session.get('studio_company'):
        raise ValueError('公司已切换，请重新操作')
    if not callable(getattr(store,'save_pdf_import',None)):
        raise ValueError('请使用更新后的服务打开财报导入与同业比较')
    if getattr(service,'_studio_preview',False) and not getattr(service,'_studio_fixture_writes',False) and action in {'pdf_confirm','save_peer_group','compare_peers'}:
        raise ValueError('当前预览只读')
    if action=='pdf_prepare':
        encoded=event.get('content')
        if not isinstance(encoded,str) or len(encoded)>16*1024*1024:
            raise ValueError('请选择不超过 12 MB 的 PDF')
        try:
            content=base64.b64decode(encoded,validate=True)
        except (ValueError,binascii.Error) as exc:
            raise ValueError('PDF 编码无效') from exc
        proposal=prepare_import(content,symbol=symbol,period_end=event.get('period_end'),published_at=event.get('published_at'),
                                source_url=event.get('source_url',''),filename=event.get('filename','report.pdf'),
                                extractor=getattr(service,'_pdf_parser_fixture',None) if getattr(service,'_studio_preview',False) else None)
        # Record latest actual dataset, not a selected historical display version.
        latest=store.financial_dataset(symbol)
        session['studio_pdf_base']=latest['id'] if latest else None
        session['studio_pdf_proposal']=proposal
        session['studio_pdf_bytes']=content
        session['studio_notice']='已提取候选数值，核对原文后勾选保存'
    elif action=='pdf_confirm':
        proposal=session.get('studio_pdf_proposal')
        if not proposal or proposal['symbol']!=symbol or proposal['id']!=event.get('proposal_id'):
            raise ValueError('PDF 预览已变化，请重新提取')
        payload=confirmed_payload(proposal,event.get('selections'),unit=event.get('unit'),currency=event.get('currency'),
                                  scope=event.get('scope'),basis=event.get('basis'),confirmed=event.get('confirmed'))
        dataset=store.save_pdf_import(payload,session['studio_pdf_bytes'],session.get('studio_pdf_base'))
        session['studio_dataset']=dataset
        session.pop('studio_pdf_proposal',None);session.pop('studio_pdf_bytes',None)
        session['studio_notice']='已保存原始 PDF 和确认的财务数据，生成新版本'
    elif action=='pdf_download':
        doc=store.financial_document(symbol,event.get('sha256'))
        if not doc: raise ValueError('此公司未保存该原始文件')
        session['studio_pdf_download']=dict(id=event['id'],symbol=symbol,sha256=doc['sha256'],content=base64.b64encode(doc['content']).decode())
    elif action=='save_peer_group':
        session['studio_peer_group']=store.save_peer_group(event.get('name'),event.get('symbols'))
        session['studio_notice']='比较组已保存；成员由你选择，不自动认定为同行'
    elif action=='compare_peers':
        group=next((g for g in store.peer_groups() if g['id']==event.get('group_id')),None)
        if not group or symbol not in group['symbols']:
            raise ValueError('请选择包含当前公司的比较组')
        payloads={};bindings={}
        for member in group['symbols']:
            data=store.financial_dataset(member)
            if data:
                payloads[member]=data['payload'];bindings[member]=data['id']
        result=compare_peers(payloads,symbols=group['symbols'],**{k:event.get(k) for k in ('period_end','as_of','basis','currency','scope')})
        session['studio_peer_run']=store.save_peer_run(group['id'],bindings,result)
        session['studio_notice']='比较已完成，结果与各公司数据版本已保存'
    elif action=='open_peer_run':
        row=store.peer_run(event.get('run_id'))
        if not row or symbol not in row['result']['parameters']['symbols']:
            raise ValueError('此比较记录不包含当前公司')
        session['studio_peer_run']=row['id']
    elif action=='research_peer_lead':
        if getattr(service,'_studio_preview',False):
            raise ValueError('隔离预览不调用模型')
        row=store.peer_run(event.get('run_id'))
        lead=next((l for l in row['result']['leads'] if l['id']==event.get('lead_id') and l['symbol']==symbol),None) if row else None
        if not lead: raise ValueError('研究线索与公司或比较版本不匹配')
        dataset=store.financial_version(symbol,row['bindings'].get(symbol))
        if not dataset: raise ValueError('原财务版本缺失，不能替换为最新版本')
        from src.studio_bridge import start_run
        cutoff=row['result']['parameters']['as_of']
        start_run(service,session,f'研究 {symbol}：{lead["title"]}。{lead["question"]}',event.get('budget',2),symbol,
                  financial_context=(dataset['payload'],dataset['id'],cutoff),peer_context=(row,lead))
