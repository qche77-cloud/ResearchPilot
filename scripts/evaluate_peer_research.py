"""Offline real table replay; optionally hash-check original local PDF files."""
import argparse
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
from src.financial_import import propose_rows, confirmed_payload, extract_pdf
from src.peer_research import compare_peers

ROOT=Path(__file__).resolve().parents[1]


def evaluate(pdf_dir=None):
    fixtures=json.loads((ROOT/'evals/financial_reports_real.json').read_text(encoding='utf-8'))['reports']
    payloads={};checks=[]
    for report in fixtures:
        pages=report['pages']
        if pdf_dir:
            content=(Path(pdf_dir)/(report['symbol']+'.pdf')).read_bytes()
            assert hashlib.sha256(content).hexdigest()==report['document_sha256']
            extracted=extract_pdf(content)
            pages=[p for p in extracted if p['page'] in {p['page'] for p in pages}]
        candidates=propose_rows(pages,'2024-12-31')
        for golden in report['expected']:
            matches=[c for c in candidates if c['metric']==golden['metric'] and c['period_end']==golden['period_end']]
            assert len(matches)==1 and matches[0]['value']==golden['value'],(report['symbol'],golden)
            checks.append(dict(symbol=report['symbol'],metric=golden['metric'],period_end=golden['period_end'],passed=True,page=matches[0]['page']))
        proposal=dict(report,id=report['document_sha256'],candidates=candidates,filename=report['symbol']+'.pdf',
                      fetched_at='2026-10-18T00:00:00Z',page_count=report['page_count'])
        payloads[report['symbol']]=confirmed_payload(proposal,[c['id'] for c in candidates],unit='元',currency='CNY',scope='consolidated',basis='cumulative',confirmed=True)
    result=compare_peers(payloads,symbols=sorted(payloads),period_end='2024-12-31',as_of='2025-04-16')
    golden_yoy={'603288':('9.53','12.75'),'603027':('-4.16','-3.07'),'600872':('7.39','-47.37')}
    for row in result['rows']:
        for i,key in enumerate(('revenue_yoy','attributable_profit_yoy')):
            factor=next(f for f in row['factors'] if f['key']==key)
            assert Decimal(factor['value']).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)==Decimal(golden_yoy[row['symbol']][i])
    assert any(l['symbol']=='600872' and l['kind']=='revenue_profit_divergence' for l in result['leads'])
    return dict(mode='original_pdf_hash_checked' if pdf_dir else 'offline_real_table_excerpt_replay',reports=3,
                checked_values=len(checks),passed_values=len(checks),reported_yoy_matches=6,checks=checks,
                comparison=result,limitations='3 个历史年报样本，不能外推通用提取准确率；确认动作在此为已逐项核对的固定验收输入，不是自动批准用户财报。')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf-dir')
    parser.add_argument('--output',default='artifacts/peer-research-evaluation.json')
    args=parser.parse_args();report=evaluate(args.pdf_dir)
    Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"{report['reports']} reports; {report['passed_values']}/{report['checked_values']} values; 6/6 YoY checks")
