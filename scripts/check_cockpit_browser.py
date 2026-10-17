"""End-to-end writable cockpit acceptance in TemporaryDirectory fixtures only."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import time
from playwright.sync_api import sync_playwright
from src.financial_ui import example_dataset


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8520')
    parser.add_argument('--output',default='artifacts/cockpit-browser')
    args=parser.parse_args();out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    checks=[];errors=[];stamp=str(time.time_ns())[-8:]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context(viewport=dict(width=1440,height=1100),accept_downloads=True)
        page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
        url=args.url+'?acceptance_token='+stamp
        page.goto(url);f=page.frame_locator('iframe');f.locator('.home').wait_for()
        js=next(fr for fr in page.frames if '/component/' in fr.url)
        assert js.evaluate('data.preview && data.fixture_writes'), 'Refuse writes/screenshots outside isolated fixture'
        f.get_by_role('button',name='自选公司',exact=True).click()
        f.locator('.stock-card').filter(has_text='公司 A').get_by_role('button',name='查看公司研究',exact=False).click()
        f.locator('.chart-point').first.wait_for();js.wait_for_function('StudioInteractions.activeCount()===0')
        assert f.locator('.chart-point').count()==8
        page.screenshot(path=str(out/'finance-desktop.png'))
        f.locator('.chart-point').last.click();f.locator('#finance-lineage').wait_for()
        assert '7000000' in f.locator('#finance-lineage').inner_text()
        assert '披露' in f.locator('#finance-lineage').inner_text()
        page.screenshot(path=str(out/'chart-lineage.png'))
        checks.append('multi_period_chart_and_original_record_lineage')
        f.locator('#chart-basis').select_option('single_quarter')
        f.locator('.chart-point').last.click()
        assert '2300000' in f.locator('#finance-lineage').inner_text()
        assert f.locator('#finance-lineage .input-card').count()>=3
        checks.append('single_quarter_chart_has_cumulative_input_lineage')
        f.locator('#finance-asof').fill('2025-04-29')
        f.get_by_role('button',name='应用日期与版本',exact=True).click()
        f.get_by_text('当前口径没有可绘制的数据',exact=True).wait_for()
        f.locator('#finance-asof').fill('2026-10-14');f.get_by_role('button',name='应用日期与版本',exact=True).click()
        f.locator('.chart-point').first.wait_for()
        checks.append('disclosure_cutoff_blocks_future_financial_records')
        # Save a financial fixture as user-supplied data in the temporary DB.
        supplied=example_dataset();supplied['provenance']='offline_browser_acceptance_user_supplied'
        for row in supplied['financial_records']:
            if row['metric']=='revenue' and row['period_end']=='2025-12-31':row['value']='900'
        f.locator('#finance-upload').set_input_files(dict(name='provided-financial-fixture.json',mimeType='application/json',buffer=json.dumps(supplied).encode()))
        f.get_by_role('button',name='保存为新财务版本',exact=True).click()
        js.wait_for_function("data.company.versions.length>=2 && data.company.dataset_id!=='fictional-input-002837'")
        original='fictional-input-002837';latest=js.evaluate('data.company.dataset_id')
        f.locator('#finance-version').select_option(original);f.get_by_role('button',name='应用日期与版本',exact=True).click()
        js.wait_for_function("data.company.dataset_id==='fictional-input-002837'")
        f.locator('#chart-basis').select_option('cumulative');f.locator('.chart-point').last.click()
        assert '7000000' in f.locator('#finance-lineage').inner_text()
        f.locator('#finance-version').select_option(latest);f.get_by_role('button',name='应用日期与版本',exact=True).click()
        js.wait_for_function("data.company.dataset_id!=='fictional-input-002837'")
        checks.append('financial_import_creates_version_and_old_inputs_remain_available')
        with page.expect_download() as info:f.get_by_role('button',name='导出财务数据与计算结果',exact=False).click()
        exported=json.loads(Path(info.value.path()).read_text(encoding='utf-8'))
        assert any(r.get('value')=='9000000' for r in exported['inputs'].values())
        checks.append('financial_export_contains_exact_inputs_and_computations')
        f.locator('#valuation-cap').fill('55000000');f.locator('#valuation-date').fill('2026-10-14');f.locator('#valuation-source').fill('https://example.invalid/browser-supplied-market')
        f.get_by_role('button',name='计算估值',exact=True).click()
        js.wait_for_function('data.company.valuation !== null')
        assert js.evaluate("data.company.valuation.results.some(r=>r.kind==='pe'&&r.status==='ok'&&r.value==='100')")
        checks.append('pe_valuation_uses_valid_disclosed_attributable_profit')
        f.get_by_role('button',name='研究时间轴',exact=True).click()
        assert f.locator('.research-version').count()>=2
        assert f.locator('.diff-strip').count()>=1
        f.get_by_text('查看与上一份报告的差异',exact=True).first.click()
        f.get_by_text('报告原文逐行变化',exact=True).first.wait_for()
        js.wait_for_function('StudioInteractions.activeCount()===0');page.screenshot(path=str(out/'timeline-desktop.png'))
        checks.append('company_timeline_exposes_report_and_hypothesis_changes')
        f.get_by_role('button',name='研究档案',exact=True).click();f.locator('#profile-focus').fill('现金流质量-'+stamp)
        f.get_by_role('button',name='投资复盘',exact=True).click();f.get_by_role('button',name='研究档案',exact=True).click()
        assert f.locator('#profile-focus').input_value()=='现金流质量-'+stamp
        f.get_by_role('button',name='保存研究档案',exact=True).click();js.wait_for_function('(s)=>data.company.profile.focus===s',arg='现金流质量-'+stamp)
        f.locator('#company-preferences-text').fill('优先交易所公告-'+stamp);f.get_by_role('button',name='保存长期偏好',exact=True).click()
        js.wait_for_function('(s)=>data.company.preferences===s',arg='优先交易所公告-'+stamp)
        checks.append('company_drafts_profile_and_long_term_preferences_save')
        f.get_by_role('button',name='投资复盘',exact=True).click();f.locator('#thesis-content').fill('现金流兑现假设-'+stamp)
        f.locator('#thesis-catalyst').fill('回款改善');f.locator('#thesis-invalidation').fill('经营现金流持续恶化')
        f.get_by_role('button',name='保存投资观点',exact=True).click()
        form=f.locator('.review-form').filter(has_text='现金流兑现假设-'+stamp);form.wait_for()
        form.locator('textarea[name=review]').fill('保留反例，待核查回款。');form.locator('select[name=status]').select_option(label='得到支持')
        form.get_by_role('button',name='保存本次复盘',exact=True).click()
        js.wait_for_function('(s)=>data.company.theses.some(t=>t.thesis===s&&t.history.length===1)',arg='现金流兑现假设-'+stamp)
        form.locator('details > summary').click();assert '保留反例' in form.locator('details').inner_text()
        page.screenshot(path=str(out/'review-desktop.png'))
        checks.append('investment_thesis_review_and_previous_versions_saved')
        f.get_by_role('button',name='财务筛选',exact=True).click();f.locator('#screen-form').wait_for()
        f.locator('#screen-date').fill('2026-10-14');f.locator('#screen-revenue').fill('0');f.locator('#screen-profit').fill('0')
        f.get_by_role('button',name='执行筛选',exact=True).click();f.get_by_role('heading',name='1 / 2 家满足条件',exact=True).wait_for()
        original_screen=js.evaluate('data.screening.id');first_execution=js.evaluate('data.screening.execution_id')
        f.locator('#preset-name').fill('增长与兑现-'+stamp);f.get_by_role('button',name='保存方案',exact=True).click()
        f.locator('[data-screen-preset]').filter(has_text='增长与兑现-'+stamp).wait_for()
        f.locator('[data-screen-preset]').filter(has_text='增长与兑现-'+stamp).click()
        js.wait_for_function('(id)=>data.executions.some(e=>e.id!==id)',arg=''+first_execution)
        assert js.evaluate('data.screening.id')==original_screen
        checks.append('saved_screening_preset_reruns_with_fixed_criteria')
        # Import changed values, then compare latest-pool run with exact replay.
        f.get_by_role('button',name='自选公司',exact=True).click();f.locator('.stock-card').filter(has_text='公司 A').get_by_role('button',name='查看公司研究',exact=False).click()
        f.get_by_role('button',name='财务分析',exact=True).click()
        supplied2=deepcopy(supplied)
        for row in supplied2['financial_records']:
            if row['metric']=='revenue' and row['period_end']=='2025-12-31':row['value']='1000'
        f.locator('#finance-upload').set_input_files(dict(name='updated-fixture.json',mimeType='application/json',buffer=json.dumps(supplied2).encode()))
        f.get_by_role('button',name='保存为新财务版本',exact=True).click();js.wait_for_function('data.company.versions.length>=3')
        f.get_by_role('button',name='财务筛选',exact=True).click();f.get_by_role('button',name='执行筛选',exact=True).click()
        js.wait_for_function('(id)=>data.screening.id!==id',arg=original_screen)
        f.locator('.screen-presets details > summary').click()
        f.locator('[data-replay-screen="'+first_execution+'"]').click();js.wait_for_function('(id)=>data.screening.id===id',arg=original_screen)
        js.wait_for_function('StudioInteractions.activeCount()===0');page.screenshot(path=str(out/'screening-history.png'))
        checks.append('historical_screen_replay_ignores_new_financial_import')
        page.reload();f.locator('.home').wait_for();f.get_by_role('button',name='财务筛选',exact=True).click()
        f.locator('[data-screen-preset]').filter(has_text='增长与兑现-'+stamp).wait_for()
        assert f.locator('[data-screen-preset]').filter(has_text='增长与兑现-'+stamp).count()==1
        checks.append('preset_history_survives_browser_session_reload')
        assert not page.get_by_test_id('stException').count()
        for width,height,name in [(1024,1000,'tablet'),(390,844,'mobile')]:
            small=browser.new_context(viewport=dict(width=width,height=height));view=small.new_page();view.on('pageerror',lambda e:errors.append(str(e)))
            view.goto(url);sf=view.frame_locator('iframe');sf.locator('.home').wait_for()
            sf.get_by_role('button',name='自选公司',exact=True).click();sf.locator('.stock-card').filter(has_text='公司 A').get_by_role('button',name='查看公司研究',exact=False).click()
            sf.locator('.chart-point').first.wait_for();sjs=next(fr for fr in view.frames if '/component/' in fr.url);sjs.wait_for_function('StudioInteractions.activeCount()===0')
            assert not sjs.evaluate('document.documentElement.scrollWidth>innerWidth')
            view.screenshot(path=str(out/('finance-'+name+'.png')))
            sf.get_by_role('button',name='研究时间轴',exact=True).click();assert not sjs.evaluate('document.documentElement.scrollWidth>innerWidth')
            sf.get_by_role('button',name='投资复盘',exact=True).click();assert not sjs.evaluate('document.documentElement.scrollWidth>innerWidth')
            checks.append(name+'_finance_timeline_review_no_overflow');small.close()
        assert not errors,errors;context.close();browser.close()
    result=dict(mode='isolated_writable_cockpit_fixture',checks=checks,page_errors=errors,paid_commands=0,screenshots=sorted(p.name for p in out.glob('*.png')))
    (out/'browser-checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
