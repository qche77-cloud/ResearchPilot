"""Loopback browser acceptance using only the isolated fictional forward ledger."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, expect
from src.forward_ledger import replay_review


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8550')
    parser.add_argument('--output',default='artifacts/forward-ledger-browser')
    args=parser.parse_args()
    if urlparse(args.url).hostname not in {'127.0.0.1','localhost','::1'}:
        parser.error('Only the local isolated validation app is permitted')
    out=Path(args.output)
    out.mkdir(parents=True,exist_ok=True)
    checks,errors,external=[],[],[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context(viewport={'width':1440,'height':1050},accept_downloads=True,reduced_motion='reduce')
        def local(route):
            if urlparse(route.request.url).netloc!=urlparse(args.url).netloc:
                external.append(urlparse(route.request.url).hostname)
                route.abort()
            else: route.continue_()
        context.route('**/*',local)
        page=context.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(args.url)
        page.get_by_role('tab',name='前向研究',exact=True).click()
        panel=page.get_by_role('tabpanel',name='前向研究',exact=True)
        expect(panel.get_by_text('隔离演示：公司、财务数字与时钟均为虚构，数据在独立临时库中，不计入真实研究成绩。',exact=True)).to_be_visible()
        expect(panel.get_by_role('button',name='模拟新财报到来',exact=True)).to_be_disabled()
        checks.append('session_starts_with_explicit_fictional_data_and_clock_in_temporary_database')
        panel.get_by_role('button',name='保存前向登记',exact=True).click()
        expect(panel.get_by_text('前向登记已保存。原始版本、规则和判断已固定。',exact=True)).to_be_visible()
        expect(panel.get_by_test_id('stMetricValue').nth(0)).to_have_text('1')
        expect(panel.get_by_role('button',name='保存前向登记',exact=True)).to_have_count(0)
        checks.append('registration_persists_once_and_removes_demo_duplicate_submission')
        page.get_by_role('heading',name='研究信号验证',exact=True).scroll_into_view_if_needed()
        page.screenshot(path=str(out/'registration-desktop.png'))
        panel.get_by_role('button',name='检查并追加复盘',exact=True).click()
        expect(panel.get_by_text('所选复盘结果：等待决策日',exact=True)).to_be_visible()
        checks.append('before_decision_result_stays_unknown_instead_of_counting_as_failure')
        panel.get_by_role('button',name='模拟新财报到来',exact=True).click()
        expect(panel.get_by_text('当前模拟日期：2026-05-02',exact=True)).to_be_visible()
        expect(panel.get_by_test_id('stMetricValue').nth(1)).to_have_text('1')
        panel.get_by_role('button',name='检查并追加复盘',exact=True).click()
        expect(panel.get_by_text('所选复盘结果：财务判据满足',exact=True)).to_be_visible()
        with page.expect_download() as event:
            panel.get_by_role('button',name='下载所选复盘与重放输入',exact=True).click()
        first=json.loads(Path(event.value.path()).read_text(encoding='utf-8'))
        assert first['result']==replay_review(first['replay'])
        assert first['result']['label'] is True
        assert first['replay']['registration']['predictions']['manual'] is None
        checks.append('new_statement_is_explicitly_selected_and_default_manual_prediction_remains_unknown')
        panel.get_by_role('button',name='模拟财报修订',exact=True).click()
        expect(panel.get_by_text('当前模拟日期：2026-05-03',exact=True)).to_be_visible()
        expect(panel.get_by_role('combobox',name='明确选择本次复盘的数据版本',exact=True)).to_have_value('2026-05-03 · demo-forward-revised')
        panel.get_by_role('button',name='检查并追加复盘',exact=True).click()
        expect(panel.get_by_text('所选复盘结果：财务判据未满足',exact=True)).to_be_visible()
        expect(panel.get_by_test_id('stMetricValue').nth(2)).to_have_text('1')
        with page.expect_download() as event:
            panel.get_by_role('button',name='下载所选复盘与重放输入',exact=True).click()
        revised=json.loads(Path(event.value.path()).read_text(encoding='utf-8'))
        assert revised['result']==replay_review(revised['replay'])
        assert revised['result']['label'] is False
        assert len(revised['result']['previous_review_diff']['changed_financial_values'])==1
        checks.append('revision_appends_new_snapshot_and_preserves_one_exact_financial_value_change')
        panel.get_by_text('所选复盘结果：财务判据未满足',exact=True).scroll_into_view_if_needed()
        expect(page.get_by_test_id('stApp')).to_have_attribute('data-test-script-state','notRunning')
        page.screenshot(path=str(out/'revision-detail.png'))
        for title,label in [('首次已知结果',True),('最新复盘结果',False)]:
            panel.get_by_text(title,exact=True).click()
            expect(panel.get_by_text('统计口径：'+title,exact=True)).to_be_visible()
            expect(page.get_by_test_id('stApp')).to_have_attribute('data-test-script-state','notRunning')
            with page.expect_download() as event:
                panel.get_by_role('button',name='下载账本概览',exact=True).click()
            summary=json.loads(Path(event.value.path()).read_text(encoding='utf-8'))
            assert summary['rows'][0]['label'] is label,(title,summary['review_policy'],summary['rows'][0]['label'])
            assert summary['groups']['synthetic_fixture']['rule_baseline']['n']==1
            assert summary['groups']['synthetic_fixture']['with_manual']['n']==0
            assert summary['groups']['local_prospective']['count']==0
        checks.append('first_known_and_latest_outcomes_are_separate_with_identical_cohorts_and_no_real_scores')
        panel.get_by_role('button',name='检查并追加复盘',exact=True).click()
        with page.expect_download() as event:
            panel.get_by_role('button',name='下载所选复盘与重放输入',exact=True).click()
        repeated=json.loads(Path(event.value.path()).read_text(encoding='utf-8'))
        assert repeated['id']==revised['id'] and repeated['created_at']==revised['created_at']
        checks.append('review_retry_returns_same_saved_version_without_inflating_history')
        history=panel.get_by_test_id('stSelectbox').filter(has_text='选择已保存的复盘版本').get_by_role('combobox')
        history.click()
        page.get_by_role('option',name=first['id'],exact=True).click()
        expect(panel.get_by_text('所选复盘结果：财务判据满足',exact=True)).to_be_visible()
        panel.get_by_role('button',name='校验所选版本的重放',exact=True).click()
        expect(panel.get_by_text('重放一致：仅使用保存的输入，结果未受最新数据影响。',exact=True)).to_be_visible()
        checks.append('older_saved_result_replays_unchanged_after_financial_revision')
        page.get_by_role('heading',name='研究信号验证',exact=True).scroll_into_view_if_needed()
        page.screenshot(path=str(out/'review-desktop.png'))
        for width in [390,1024,1440]:
            page.set_viewport_size({'width':width,'height':920})
            panel.get_by_role('heading',name='把今天的判断留给未来验证',exact=True).scroll_into_view_if_needed()
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
            page.screenshot(path=str(out/f'forward-{width}.png'))
        checks.append('forward_workflow_has_no_document_horizontal_overflow_at_three_widths')
        page.get_by_role('tab',name='数据检查',exact=True).click()
        readiness=page.get_by_role('tabpanel',name='数据检查',exact=True)
        expect(readiness.get_by_text('连接本机电脑工作台的已保存资料',exact=True)).to_be_visible()
        expect(readiness.get_by_role('button',name='只读检查自选财务资料',exact=True)).to_have_count(0)
        checks.append('real_workbench_readonly_inspection_requires_explicit_connection')
        assert not page.get_by_test_id('stException').count()
        assert not errors,errors
        assert not external,external
        checks.append('no_streamlit_or_javascript_errors_and_no_external_browser_requests')
        browser.close()
    (out/'checks.json').write_text(json.dumps({'mode':'isolated_fictional_forward_ledger',
        'checks':checks,'page_errors':errors,'external_requests':external},ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'{len(checks)} offline forward browser checks passed')


if __name__=='__main__':
    main()
