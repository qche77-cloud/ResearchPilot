"""Loopback browser acceptance of the explicitly fictional mobile companion."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8540')
    parser.add_argument('--output', default='artifacts/miniprogram-browser')
    parser.add_argument('--lan-demo', action='store_true', help='Explicitly test a private LAN demo and insecure-context fallbacks')
    args = parser.parse_args()
    if urlparse(args.url).hostname not in {'127.0.0.1', 'localhost', '::1'}:
        from scripts.serve_miniprogram import private_lan_host
        if not args.lan_demo or not private_lan_host(urlparse(args.url).hostname or ''):
            parser.error('Acceptance requires loopback, or --lan-demo and an explicit private IPv4')
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width':390,'height':844}, reduced_motion='reduce', permissions=['clipboard-read','clipboard-write'])
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        response = context.request.get(args.url + '/health')
        assert response.json()['mode'] == 'demo', 'Only fictional demonstrations may be mutated or captured'
        if args.lan_demo:
            assert response.json().get('lan_demo') is True
            page.add_init_script("Object.defineProperty(crypto,'randomUUID',{value:undefined,configurable:true});Object.defineProperty(navigator,'clipboard',{value:undefined,configurable:true});")
        page.goto(args.url + '/preview/')
        if args.lan_demo:
            assert page.evaluate('isSecureContext') is False
        page.get_by_role('button', name='进入体验 A', exact=False).click()
        expect(page.get_by_role('heading', name='研究工作台', exact=True)).to_be_visible()
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        page.screenshot(path=str(out/'home-390.png'), full_page=True)
        checks.append('login_and_home_have_explicit_demo_label_and_no_horizontal_overflow')
        page.locator('[data-run]').first.click()
        expect(page.get_by_text('反面证据与后续核查', exact=True)).to_be_visible()
        assert page.locator('#version option').count() == 2
        page.locator('#version').select_option(index=0)
        expect(page.get_by_text('反面证据与后续核查', exact=True)).not_to_be_visible()
        page.locator('#version').select_option(index=1)
        expect(page.get_by_text('反面证据与后续核查', exact=True)).to_be_visible()
        page.screenshot(path=str(out/'report-390.png'), full_page=True)
        checks.append('report_version_switch_reads_the_selected_immutable_snapshot')
        page.locator('[data-tab="sources"]').click()
        expect(page.get_by_text('虚构公司年度报告（演示夹具）', exact=True)).to_be_visible()
        page.get_by_role('button', name='复制原始来源链接 ↗', exact=True).click()
        expect(page.get_by_role('status')).to_have_text('来源链接已复制')
        expect(page.get_by_role('status')).to_be_hidden(timeout=5000)
        page.screenshot(path=str(out/'sources-390.png'), full_page=True)
        checks.append('evidence_contains_original_excerpt_date_and_copyable_source')
        page.locator('[data-tab="process"]').click()
        expect(page.get_by_text('未调用模型、搜索或行情服务', exact=True)).to_be_visible()
        checks.append('process_view_discloses_no_real_tool_calls')
        page.locator('nav').get_by_role('button', name='研究', exact=True).click()
        page.get_by_role('button', name='＋ 新建研究', exact=True).click()
        page.get_by_label('你希望核查什么？', exact=True).fill('离线演示：现金流为何低于净利润？')
        page.get_by_role('button', name='生成离线演示报告', exact=True).click()
        expect(page.get_by_role('heading', name='离线演示：现金流为何低于净利润？', exact=True)).to_be_visible()
        expect(page.get_by_text('反面证据与后续核查', exact=True)).to_be_visible()
        checks.append('research_form_submits_real_api_request_and_opens_fictional_saved_report')
        page.locator('nav').get_by_role('button', name='自选', exact=True).click()
        page.get_by_role('button', name='＋ 添加公司', exact=True).click()
        page.get_by_label('六位 A 股代码', exact=True).fill('000002')
        page.get_by_label('显示名称', exact=True).fill('仅 A 的隔离演示公司')
        page.get_by_role('button', name='保存自选', exact=True).click()
        expect(page.get_by_role('heading', name='仅 A 的隔离演示公司', exact=True)).to_be_visible()
        checks.append('watchlist_can_save_a_valid_company_without_market_fetch')
        page.locator('[data-company="000001"]').click()
        expect(page.get_by_role('heading', name='已保存财务', exact=True)).to_be_visible()
        expect(page.locator('.metric-unit').first).to_contain_text('CNY')
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        page.screenshot(path=str(out/'company-390.png'), full_page=True)
        checks.append('company_financials_show_record_values_reporting_period_currency_and_unit')
        page.get_by_role('button', name='研究这家公司', exact=True).click()
        expect(page.get_by_role('heading', name='研究000001：收入、利润与经营现金流是否一致？', exact=True)).to_be_visible()
        checks.append('company_research_is_bound_to_the_selected_symbol')
        page.locator('nav').get_by_role('button', name='我的', exact=True).click()
        expect(page.get_by_role('heading', name='我的研究空间', exact=True)).to_be_visible()
        page.screenshot(path=str(out/'account-390.png'), full_page=True)
        page.get_by_role('button', name='退出登录', exact=True).click()
        expect(page.get_by_role('button', name='进入体验 A', exact=False)).to_be_visible()
        checks.append('logout_revokes_session_and_returns_to_login')
        page.get_by_role('button', name='进入体验 B', exact=False).click()
        expect(page.get_by_role('heading', name='研究工作台', exact=True)).to_be_visible()
        assert page.locator('[data-run]').count() == 1
        page.locator('nav').get_by_role('button', name='自选', exact=True).click()
        expect(page.get_by_role('heading', name='仅 A 的隔离演示公司', exact=True)).not_to_be_visible()
        checks.append('second_account_cannot_see_first_accounts_research_or_watchlist')
        page.locator('nav').get_by_role('button', name='研究', exact=True).click()
        page.set_viewport_size({'width':430,'height':932})
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        page.screenshot(path=str(out/'home-430.png'), full_page=True)
        checks.append('second_mobile_width_has_no_horizontal_overflow')
        assert not errors, errors
        browser.close()
    result = dict(mode='fictional_browser_preview_not_wechat_device_acceptance', lan_demo=args.lan_demo, checks=checks, page_errors=errors)
    (out/'checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{len(checks)} browser checks passed; no WeChat device acceptance claimed')


if __name__ == '__main__':
    main()
