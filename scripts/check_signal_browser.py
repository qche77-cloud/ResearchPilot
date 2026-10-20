"""Browser acceptance of the no-provider signal_validation_app on loopback."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, expect
from src.research_signals import evaluate_experiment


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8550')
    parser.add_argument('--output',default='artifacts/research-signals-browser')
    parser.add_argument('--studio-url',help='Optional isolated preview_studio instance')
    args=parser.parse_args()
    if urlparse(args.url).hostname not in {'127.0.0.1','localhost','::1'}:
        parser.error('Only the local no-provider validation app is permitted')
    if args.studio_url and urlparse(args.studio_url).hostname not in {'127.0.0.1','localhost','::1'}:
        parser.error('Studio acceptance also requires loopback')
    out=Path(args.output)
    out.mkdir(parents=True,exist_ok=True)
    checks,errors,external=[],[],[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context(viewport={'width':1440,'height':1050},accept_downloads=True,reduced_motion='reduce')
        def local(route):
            allowed={urlparse(args.url).netloc}|({urlparse(args.studio_url).netloc} if args.studio_url else set())
            if urlparse(route.request.url).netloc not in allowed:
                external.append(urlparse(route.request.url).hostname)
                route.abort()
            else:
                route.continue_()
        context.route('**/*',local)
        page=context.new_page()
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(args.url)
        expect(page.get_by_role('heading',name='研究信号验证',exact=True)).to_be_visible()
        page.get_by_role('button',name='运行离线验证',exact=True).click()
        expect(page.get_by_text('当前全部公司、数字和登记判断均为虚构。这里没有运行模型，示例成绩不代表 Agent 实际能力或收益。',exact=True)).to_be_visible()
        expect(page.get_by_test_id('stMetricValue').nth(0)).to_have_text('5')
        expect(page.get_by_test_id('stMetricValue').nth(1)).to_have_text('4')
        expect(page.get_by_test_id('stMetricValue').nth(2)).to_have_text('4')
        checks.append('explicit_fictional_experiment_runs_with_shared_cohort_counts')
        page.get_by_test_id('stDataFrame').first.locator('canvas').first.wait_for(state='visible')
        page.screenshot(path=str(out/'validation-desktop.png'))
        page.get_by_text('加入登记研究判断',exact=True).click()
        expect(page.get_by_text('综合分 100 / 100 · 覆盖权重 100%',exact=True)).to_be_visible()
        checks.append('registered_judgment_comparison_remains_explicitly_separate_from_actual_model_calls')
        with page.expect_download() as event:
            page.get_by_role('button',name='下载完整验证结果与重放输入',exact=True).click()
        downloaded=event.value
        result=json.loads(Path(downloaded.path()).read_text(encoding='utf-8'))
        assert result['provenance']=='synthetic_offline_fixture'
        replayed=evaluate_experiment(**result['replay'])
        if result!=replayed:
            differences=[]
            def compare(left,right,path='result'):
                if type(left)!=type(right): differences.append(path+':type')
                elif isinstance(left,dict):
                    for key in sorted(set(left)|set(right)):
                        if key not in left or key not in right: differences.append(path+'.'+key+':missing')
                        else: compare(left[key],right[key],path+'.'+key)
                elif isinstance(left,list):
                    if len(left)!=len(right): differences.append(path+':length')
                    else:
                        for i,(a,b) in enumerate(zip(left,right)): compare(a,b,f'{path}[{i}]')
                elif left!=right: differences.append(path+':value')
            compare(result,replayed)
            raise AssertionError(differences[:12])
        checks.append('download_contains_exact_replayable_inputs_rules_and_financial_evidence')
        select=page.get_by_test_id('stSelectbox').filter(has_text='查看样本证据').get_by_role('combobox')
        select.click()
        page.get_by_role('option',name='fictional-4',exact=True).click()
        expect(page.get_by_text('综合分 数据不足 / 100 · 覆盖权重 70%',exact=True)).to_be_visible()
        checks.append('missing_cash_inputs_never_become_zero_or_a_complete_score')
        date_input=page.get_by_test_id('stDateInput').filter(has_text='验证截止日').locator('input')
        date_input.fill('2025-06-01')
        date_input.press('Tab')
        page.get_by_role('button',name='运行离线验证',exact=True).click()
        expect(page.get_by_test_id('stMetricValue').nth(1)).to_have_text('0')
        expect(page.get_by_text('没有同时具备判断和已知结果的共同样本，暂不计算比较成绩。',exact=True)).to_be_visible()
        checks.append('not_due_results_remain_unknown_and_do_not_enter_accuracy_denominator')
        page.get_by_role('tab',name='当前财务评分',exact=True).click()
        page.get_by_role('button',name='计算透明评分',exact=True).click()
        expect(page.get_by_text('此评分来自虚构财务数据。',exact=True)).to_be_visible()
        expect(page.get_by_test_id('stMetricValue').filter(has_text='100')).to_be_visible()
        page.screenshot(path=str(out/'score-desktop.png'))
        checks.append('current_score_has_a_separate_readonly_workflow_and_exact_source_details')
        for width in [390,1024]:
            page.set_viewport_size({'width':width,'height':920})
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
            page.screenshot(path=str(out/f'score-{width}.png'))
        checks.append('mobile_and_tablet_have_no_document_horizontal_overflow')
        if args.studio_url:
            integrated=context.new_page()
            integrated.on('pageerror',lambda e:errors.append(str(e)))
            integrated.goto(args.studio_url)
            frame=integrated.frame_locator('iframe')
            expect(frame.locator('#preview-badge')).to_be_visible()
            before=frame.locator('.history-item').count()
            frame.get_by_role('button',name='研究信号验证',exact=True).click()
            expect(integrated.get_by_role('heading',name='研究信号验证',exact=True)).to_be_visible()
            integrated.get_by_role('button',name='运行离线验证',exact=True).click()
            expect(integrated.get_by_test_id('stMetricValue').nth(0)).to_have_text('5')
            checks.append('studio_navigation_opens_the_same_offline_validation_logic')
            integrated.get_by_role('button',name='← 返回研究页面',exact=True).click()
            expect(frame.locator('.home')).to_be_visible()
            assert frame.locator('.history-item').count()==before
            checks.append('return_to_studio_preserves_existing_research_history')
        assert not errors,errors
        assert not external,external
        checks.append('browser_has_no_javascript_errors_or_external_requests')
        browser.close()
    (out/'checks.json').write_text(json.dumps({'mode':'isolated_fictional_signal_validation',
        'checks':checks,'page_errors':errors,'external_requests':external},ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'{len(checks)} offline signal browser checks passed')


if __name__=='__main__':
    main()
