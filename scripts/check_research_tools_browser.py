"""Real browser acceptance for isolated fictional research tools, never production."""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import uuid
from playwright.sync_api import sync_playwright
from scripts.test_research_tools import research_fixture


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8524')
    parser.add_argument('--output',default='artifacts/research-tools-browser')
    args=parser.parse_args()
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    checks,errors=[],[]
    url=args.url+'?acceptance_token='+uuid.uuid4().hex
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000},accept_downloads=True)
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(url)
        frame=page.frame_locator('iframe');frame.locator('.home').wait_for()
        js=next(f for f in page.frames if '/component/' in f.url)
        def idle():js.wait_for_function('pendingEvent===null')
        assert frame.locator('#preview-badge').is_visible(),'Refuse non-fictional preview'
        frame.get_by_role('button',name='自选公司',exact=True).click()
        frame.locator('[data-company="002837"]').click()
        frame.locator('#finance-asof').fill('2026-04-01')
        frame.get_by_role('button',name='应用日期与版本',exact=True).click()
        idle()
        frame.get_by_role('button',name='财务检查',exact=True).click()
        frame.locator('.research-signal.triggered').first.wait_for()
        assert frame.locator('.research-signal.triggered').count()==7
        checks.append('seven_financial_signals_and_explicit_scope')
        compatibility=js.evaluate("() => {const saved=data;try{data={...data,company:{...data.company,research:undefined}};return StudioResearchTools.diagnostics()+StudioResearchTools.tracking();}finally{data=saved;}}")
        assert '暂不可用' in compatibility and '已有投资观点' in compatibility
        checks.append('older_backend_packets_keep_manual_review_accessible')
        assert frame.get_by_role('img',name='利润变化瀑布图',exact=True).is_visible()
        frame.get_by_role('button',name='收入变化贡献 80',exact=True).press('Enter')
        frame.locator('.research-lineage').wait_for()
        assert frame.locator('.research-lineage .input-card').count()==3
        assert '披露 2026-03-30' in frame.locator('.research-lineage').inner_text()
        checks.append('waterfall_keyboard_selection_resolves_exact_inputs')
        with page.expect_download() as download:
            frame.get_by_role('button',name='下载分析结果与原始数据',exact=True).click()
        evidence=json.loads(Path(download.value.path()).read_text(encoding='utf-8'))
        b=evidence['research']['profit_bridge']
        assert b['reconciled'] and b['change']=='-40'
        assert sum(Decimal(s['value']) for s in b['steps'][:-1])==Decimal(b['steps'][-1]['value'])
        assert set(b['input_ids'])<=set(evidence['inputs'])
        checks.append('downloaded_profit_ledger_reconciles_and_has_source_inputs')
        frame.locator('#main').evaluate('(n)=>n.scrollTo({top:0,behavior:"instant"})')
        page.screenshot(path=str(out/'financial-detective-desktop.png'))
        frame.get_by_role('heading',name='利润变化分解',exact=True).scroll_into_view_if_needed()
        page.screenshot(path=str(out/'profit-bridge-desktop.png'))
        frame.locator('#research-options select[name="currency"]').select_option('USD')
        frame.get_by_role('button',name='应用分析条件',exact=True).click()
        idle()
        frame.get_by_role('heading',name='暂不能完成利润分解',exact=True).wait_for()
        assert frame.locator('.research-signal.unavailable').count()==7
        checks.append('missing_currency_stays_unavailable_without_synthetic_values')
        frame.locator('#research-options select[name="currency"]').select_option('CNY')
        frame.get_by_role('button',name='应用分析条件',exact=True).click()
        idle()
        frame.get_by_role('button',name='投资复盘',exact=True).click()
        form=frame.locator('.thesis-test-form').first
        form.locator('[name="threshold"]').fill('15')
        form.locator('[name="period_end"]').fill('2025-12-31')
        form.locator('[name="review_on"]').fill('2026-04-01')
        js.evaluate("renderMain(true,'none')")
        assert form.locator('[name="threshold"]').input_value()=='15'
        checks.append('criterion_draft_survives_packet_rerender')
        form.get_by_role('button',name='保存验证条件',exact=True).click()
        try:
            frame.get_by_role('button',name='用当前数据检查条件',exact=True).wait_for(timeout=10000)
        except Exception:
            page.screenshot(path=str(out/'save-criterion-failure.png'))
            print('Criterion save notice:',frame.locator('#notice').inner_text())
            print('Criterion fields:',form.locator('input').evaluate_all('(nodes)=>nodes.map(n=>[n.name,n.value,n.validationMessage])'))
            raise
        frame.get_by_role('button',name='用当前数据检查条件',exact=True).click()
        frame.locator('.thesis-test-result').filter(has_text='财务条件已满足').wait_for()
        assert frame.locator('.review-form select[name="status"]').input_value()=='观察中'
        checks.append('criterion_met_and_manual_investment_status_preserved')
        frame.locator('.thesis-test-result').scroll_into_view_if_needed()
        page.screenshot(path=str(out/'thesis-tracking-desktop.png'))
        frame.get_by_role('button',name='财务分析',exact=True).click()
        payload=research_fixture()
        next(r for r in payload['financial_records'] if r['metric']=='revenue' and r['period_end']=='2025-12-31')['value']='1050'
        frame.locator('#finance-upload').set_input_files({'name':'fictional-revision.json','mimeType':'application/json','buffer':json.dumps(payload).encode()})
        frame.get_by_role('button',name='保存为新财务版本',exact=True).click()
        js.wait_for_function("data.company.dataset_id !== 'fictional-research-v1'")
        idle()
        frame.get_by_role('button',name='投资复盘',exact=True).click()
        frame.get_by_role('button',name='用当前数据检查条件',exact=True).click()
        frame.locator('.thesis-test-result').filter(has_text='财务条件未满足').wait_for()
        assert '有修订' in frame.locator('.thesis-test-result').inner_text()
        with page.expect_download() as download:
            frame.get_by_role('button',name='下载验证条件与检查记录',exact=True).click()
        history=json.loads(Path(download.value.path()).read_text(encoding='utf-8'))
        assert len(history['runs'])==2 and len(history['versions'])==1
        assert history['runs'][0]['payload']['status']=='criterion_not_met'
        assert history['runs'][1]['payload']['status']=='criterion_met'
        checks.append('revised_financials_change_criterion_and_keep_previous_evidence')
        frame.get_by_role('button',name='财务分析',exact=True).click()
        frame.locator('#finance-asof').fill('2026-03-01')
        frame.get_by_role('button',name='应用日期与版本',exact=True).click()
        idle()
        frame.get_by_role('button',name='投资复盘',exact=True).click()
        frame.get_by_role('button',name='用当前数据检查条件',exact=True).click()
        frame.locator('.thesis-test-result').filter(has_text='未到复盘日期').wait_for()
        assert '无可比数据' in frame.locator('.thesis-test-result').inner_text()
        checks.append('before_deadline_and_disclosure_no_premature_judgment')
        js=next(f for f in page.frames if '/component/' in f.url)
        assert js.evaluate('!document.querySelector(".thesis-test-result img")')
        for width,height,name in [(390,844,'mobile'),(1024,900,'tablet')]:
            mobile=browser.new_page(viewport={'width':width,'height':height})
            mobile.on('pageerror',lambda error:errors.append(str(error)))
            mobile.goto(url)
            mf=mobile.frame_locator('iframe');mf.locator('.home').wait_for()
            mf.get_by_role('button',name='自选公司',exact=True).click()
            mf.locator('[data-company="002837"]').click()
            mf.get_by_role('button',name='财务检查',exact=True).click()
            mf.locator('.research-signal').first.wait_for()
            mj=next(f for f in mobile.frames if '/component/' in f.url)
            assert not mj.evaluate('document.documentElement.scrollWidth>innerWidth')
            mobile.screenshot(path=str(out/f'financial-detective-{name}.png'))
            mf.get_by_role('button',name='投资复盘',exact=True).click()
            mf.locator('.thesis-test').first.wait_for()
            assert not mj.evaluate('document.documentElement.scrollWidth>innerWidth')
            checks.append(name+'_diagnostics_and_tracking_no_page_overflow')
            mobile.close()
        browser.close()
    report={'fixture':'synthetic_offline_fixture','checks':checks,'passed':len(checks),'page_errors':errors}
    (out/'browser-checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    assert not errors,errors
    print(f'{len(checks)} research tools browser checks passed; {out}')


if __name__=='__main__':main()
