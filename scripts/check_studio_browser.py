"""Repeatable Playwright acceptance on preview_studio.py; never use real research.

Run with a local isolated preview on 8510 and development-only Playwright installed.
"""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8510')
    parser.add_argument('--output', default='artifacts/studio-preview')
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport=dict(width=1440, height=1000), accept_downloads=True)
        page = context.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(args.url)
        frame = page.frame_locator('iframe')
        frame.locator('.home').wait_for()
        assert frame.locator('#preview-badge').is_visible(), 'Refuse screenshots of production research'
        frame.locator('#home-draft').fill('界面验收草稿：核查现金流')
        page.screenshot(path=str(out / 'home-desktop.png'))
        frame.get_by_role('button', name='自选档案', exact=True).click()
        frame.locator('.stock-card').first.wait_for()
        frame.get_by_role('button', name='研究空间', exact=True).click()
        frame.locator('#home-draft').wait_for()
        assert frame.locator('#home-draft').input_value() == '界面验收草稿：核查现金流'
        checks.append('home_draft_survives_navigation')
        frame.locator('.history-item').filter(has_text='离线演示公司 A').click()
        frame.locator('.report-title').wait_for()
        assert frame.locator('.canvas').is_visible() and frame.locator('.inspector').is_visible()
        assert frame.locator('.report-section').count() == 4
        frame.locator('#chat-draft').fill('草稿：请找反面证据')
        # A background poll must not reset the draft, text cursor or document position.
        frame.locator('#document-scroll').evaluate('(n)=>n.scrollTo({top:180,behavior:"instant"})')
        before = frame.locator('#document-scroll').evaluate('(n)=>n.scrollTop')
        page.wait_for_timeout(4600)
        assert frame.locator('#chat-draft').input_value() == '草稿：请找反面证据'
        assert abs(frame.locator('#document-scroll').evaluate('(n)=>n.scrollTop') - before) < 2
        checks.append('poll_preserves_draft_and_report_scroll')
        frame.locator('#document-scroll').evaluate('(n)=>n.scrollTo({top:0,behavior:"instant"})')
        page.screenshot(path=str(out / 'research-desktop.png'))
        frame.locator('.report-section .citation').filter(has_text='E2').first.click()
        frame.locator('#evidence-E2.focused').wait_for()
        assert '营运资金' in frame.locator('#evidence-E2').inner_text()
        assert frame.locator('.report-title').is_visible()
        page.screenshot(path=str(out / 'evidence-desktop.png'))
        checks.append('report_citation_opens_matching_saved_evidence')
        frame.locator('#report-version').select_option('demo-version-01')
        assert frame.locator('.report-section').count() == 2
        assert frame.locator('.evidence-card').count() == 2
        assert frame.locator('#evidence-E3').count() == 0
        checks.append('old_version_never_uses_new_evidence')
        frame.get_by_role('button', name='对话', exact=True).click()
        frame.locator('.message-version').last.click()
        assert frame.locator('#report-version').input_value() == 'demo-version-02'
        assert frame.locator('.report-section').count() == 4
        frame.locator('.message .citation').filter(has_text='E3').click()
        frame.locator('#evidence-E3.focused').wait_for()
        checks.append('message_report_and_citation_are_version_scoped')
        frame.get_by_role('button', name='过程', exact=True).click()
        assert frame.locator('.hypothesis').count() == 1
        assert '发现反例' in frame.locator('.hypothesis').inner_text()
        checks.append('hypotheses_and_uncertainty_visible')
        # The splitter supports keyboard users, too.
        separator = frame.get_by_role('separator')
        width = frame.locator('.inspector').bounding_box()['width']
        separator.focus()
        separator.press('ArrowLeft')
        assert frame.locator('.inspector').bounding_box()['width'] > width
        checks.append('resizable_workspace_keyboard_control')
        frame.get_by_role('button', name='对话', exact=True).click()
        assert frame.locator('#chat-draft').input_value() == '草稿：请找反面证据'
        # Report export must export the selected snapshot rather than the latest.
        frame.locator('#report-version').select_option('demo-version-01')
        with page.expect_download() as download_info:
            frame.get_by_role('button', name='下载当前版本报告', exact=True).click()
        text = Path(download_info.value.path()).read_text(encoding='utf-8')
        assert '[E3]' not in text and '2026-04-01' in text and '[E2]' in text
        checks.append('download_matches_selected_version')
        page.reload()
        frame.locator('.home').wait_for()
        frame.locator('.history-item').filter(has_text='离线演示公司 A').click()
        frame.locator('#report-version').wait_for()
        assert frame.locator('#report-version').input_value() == 'demo-version-01'
        assert frame.locator('#chat-draft').input_value() == '草稿：请找反面证据'
        checks.append('session_drafts_and_selected_version_survive_refresh')
        frame.locator('#chat-draft').press('Control+k')
        frame.locator('#palette[open]').wait_for()
        frame.locator('#palette-query').fill('产业链')
        assert frame.locator('.palette-result').count() == 1
        frame.locator('#palette-query').press('Enter')
        frame.locator('.report-title').filter(has_text='产业链').wait_for()
        checks.append('keyboard_task_search_and_navigation')
        frame.get_by_role('button', name='财务筛选', exact=True).click()
        frame.locator('#screen-form').wait_for()
        frame.locator('#screen-date').fill('2026-10-14')
        frame.locator('#screen-revenue').fill('0')
        frame.locator('#screen-profit').fill('0')
        frame.get_by_role('button', name='执行筛选', exact=True).click()
        frame.get_by_role('heading', name='1 / 2 家满足条件', exact=True).wait_for()
        assert frame.locator('[data-factor="revenue_yoy"]').first.inner_text() == '27.27%'
        assert frame.locator('[data-factor="revenue_yoy"]').first.get_attribute('title').startswith('27.2727')
        frame.locator('[data-factor="revenue_yoy"]').first.click()
        assert frame.locator('.input-card').count() == 2
        assert '披露' in frame.locator('.input-card').first.inner_text()
        assert '7000000' in frame.locator('.input-card').first.inner_text()
        frame.locator('.lineage details > summary').click()
        assert 'published_at' in frame.locator('.lineage pre').inner_text()
        frame.locator('.lineage details > summary').click()
        frame.locator('#main').evaluate('(n)=>n.scrollTo({top:0,behavior:"instant"})')
        page.screenshot(path=str(out / 'screening-desktop.png'))
        checks.append('deterministic_screen_and_original_input_lineage')
        jsframe = next(f for f in page.frames if '/component/' in f.url)
        assert jsframe.evaluate("safeURL('javascript:alert(1)') === null && safeURL('data:text/html,x') === null")
        rendered = jsframe.evaluate("markdown('<img src=x onerror=alert(1)> [bad](javascript:alert)')")
        assert '<img' not in rendered and 'href="javascript:' not in rendered
        checks.append('unsafe_html_and_link_schemes_rejected')
        frame.get_by_role('button', name='完整数据工具', exact=True).click()
        page.get_by_role('button', name='← 返回 Studio', exact=True).wait_for()
        assert page.get_by_role('tab', name='财务分析', exact=True).count() == 1
        assert not page.get_by_test_id('stException').count()
        page.get_by_role('button', name='← 返回 Studio', exact=True).click()
        frame.locator('.research').wait_for()
        checks.append('legacy_financial_and_review_tools_remain_accessible')
        # Independent contexts exercise responsive reading, citation and draft paths.
        for width, height, name in [(1024, 900, 'tablet'), (390, 844, 'mobile')]:
            responsive = browser.new_context(viewport=dict(width=width, height=height))
            view = responsive.new_page()
            view.on('pageerror', lambda e: errors.append(str(e)))
            view.goto(args.url)
            rf = view.frame_locator('iframe')
            rf.locator('.home').wait_for()
            view.screenshot(path=str(out / f'home-{name}.png'))
            rjs = next(f for f in view.frames if '/component/' in f.url)
            assert not rjs.evaluate('document.documentElement.scrollWidth > innerWidth')
            if name == 'mobile':
                rf.get_by_role('button', name='打开任务列表', exact=True).click()
            rf.locator('.history-item').filter(has_text='离线演示公司 A').click()
            rf.locator('.report-title').wait_for()
            rf.locator('.report-section .citation').first.click()
            rf.locator('.evidence-card.focused').wait_for()
            assert not rjs.evaluate('document.documentElement.scrollWidth > innerWidth')
            view.screenshot(path=str(out / f'evidence-{name}.png'))
            if name == 'mobile':
                rf.get_by_role('button', name='报告', exact=True).click()
                rf.locator('.report-title').wait_for(state='visible')
                view.screenshot(path=str(out / 'report-mobile.png'))
                rf.get_by_role('button', name='助手', exact=True).click()
                rf.get_by_role('button', name='对话', exact=True).click()
                rf.locator('#chat-draft').fill('手机追问草稿')
                rf.get_by_role('button', name='财务筛选', exact=True).click()
                rf.locator('#screen-form').wait_for()
                assert not rjs.evaluate('document.documentElement.scrollWidth > innerWidth')
                rf.get_by_role('button', name='研究空间', exact=True).click()
                rf.locator('#chat-draft').wait_for()
                assert rf.locator('#chat-draft').input_value() == '手机追问草稿'
            assert not view.get_by_test_id('stException').count()
            checks.append(f'{name}_report_evidence_no_overflow_and_navigation')
            responsive.close()
        assert not errors, errors
        context.close()
        browser.close()
    report = dict(mode='isolated_synthetic_studio_preview', viewport_widths=[1440, 1024, 390],
                  checks=checks, page_errors=errors, screenshots=sorted(p.name for p in out.glob('*.png')))
    (out / 'browser-checks.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
