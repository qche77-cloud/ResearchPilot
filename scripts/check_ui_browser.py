"""Optional Playwright acceptance against scripts/preview_ui.py (fictional data only).

Requires a development-only playwright install and Chromium. Not part of runtime.
"""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8503')
    parser.add_argument('--output', default='artifacts/ui-preview')
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, device_scale_factor=1)
        page = context.new_page()
        page.on('pageerror', lambda exc: errors.append(str(exc)))
        page.goto(args.url)
        page.locator('.rp-welcome').wait_for()
        page.get_by_role('button', name='开始研究', exact=True).wait_for()
        page.screenshot(path=str(out / 'home-desktop.png'), full_page=True)
        page.get_by_role('textbox', name='输入公司名称、代码和关注的问题').fill('界面验收草稿：核查现金流')
        page.get_by_role('button', name='个股与自选', exact=True).click()
        page.get_by_role('tab', name='行情概览', exact=True).wait_for()
        page.get_by_text('此页面的财务与行情为合成测试数据，不能用于投资判断。', exact=True).wait_for()
        page.screenshot(path=str(out / 'stock-desktop.png'), full_page=True)
        assert not page.get_by_test_id('stException').count()
        page.get_by_role('tab', name='财务分析', exact=True).click()
        page.get_by_text('离线合成示例 / 非真实财务数据 / 不写入真实研究数据', exact=True).wait_for()
        page.get_by_role('combobox', name='多期财务图表', exact=True).wait_for()
        page.get_by_role('button', name='下载财务分析与证据', exact=True).wait_for()
        page.wait_for_function("document.querySelector('[data-testid=stApp]')?.getAttribute('data-test-script-state') === 'notRunning'")
        page.locator('[data-testid="stVegaLiteChart"]:visible svg').first.wait_for()
        page.locator('[data-testid="stVegaLiteChart"]:visible').scroll_into_view_if_needed()
        page.screenshot(path=str(out / 'finance-desktop.png'), full_page=True)
        page.get_by_role('button', name='研究对话', exact=True).click()
        page.locator('.rp-welcome').wait_for()
        assert page.get_by_role('textbox', name='输入公司名称、代码和关注的问题').input_value() == '界面验收草稿：核查现金流'
        checks.append('desktop_home_draft_navigation')
        # Open only the explicit synthetic preview record, not a real task.
        page.get_by_role('button', name='离线界面演示：现金流如何检验增长质量？', exact=True).click()
        page.get_by_role('tab', name='研究报告', exact=True).wait_for()
        page.get_by_role('button', name='发送追问', exact=True).wait_for()
        page.screenshot(path=str(out / 'conversation-desktop.png'), full_page=True)
        page.get_by_role('tab', name='研究报告', exact=True).click()
        page.get_by_role('heading', name='研究摘要', exact=True).wait_for()
        page.screenshot(path=str(out / 'report-desktop.png'), full_page=True)
        page.get_by_role('tab', name='证据与来源', exact=True).click()
        assert not page.get_by_test_id('stException').count()
        page.get_by_role('tab', name='假设与验证', exact=True).click()
        page.get_by_text('研究过程检查', exact=True).wait_for()
        checks.append('desktop_stock_financial_report_evidence_reasoning_views')
        # Fresh browser sessions verify responsive layout, without retained sidebar state.
        for width, height, name in [(1024, 900, 'tablet'), (390, 844, 'mobile')]:
            responsive = browser.new_context(viewport={'width': width, 'height': height}, device_scale_factor=1)
            view = responsive.new_page()
            view.on('pageerror', lambda exc: errors.append(str(exc)))
            view.goto(args.url)
            view.locator('.rp-welcome').wait_for()
            view.get_by_role('button', name='开始研究', exact=True).wait_for()
            view.screenshot(path=str(out / f'home-{name}.png'), full_page=True)
            overflow = view.evaluate('document.documentElement.scrollWidth > window.innerWidth')
            assert not overflow, f'{name}: horizontal page overflow'
            assert not view.get_by_test_id('stException').count()
            checks.append(f'{name}_home_no_horizontal_overflow')
            if name == 'mobile':
                view.get_by_test_id('stExpandSidebarButton').click()
                view.get_by_role('button', name='个股与自选', exact=True).click()
                view.get_by_role('tab', name='财务分析', exact=True).wait_for()
                collapse = view.get_by_test_id('stSidebarCollapseButton')
                (collapse.locator('button') if collapse.locator('button').count() else collapse).click()
                view.get_by_role('tab', name='财务分析', exact=True).click()
                view.get_by_role('button', name='下载财务分析与证据', exact=True).wait_for()
                view.locator('[data-testid="stVegaLiteChart"]:visible svg').first.wait_for()
                assert not view.evaluate('document.documentElement.scrollWidth > window.innerWidth')
                view.locator('[data-testid="stVegaLiteChart"]:visible').scroll_into_view_if_needed()
                view.screenshot(path=str(out / 'finance-mobile.png'), full_page=True)
                assert not view.get_by_test_id('stException').count()
                checks.append('mobile_stock_financial_view_no_horizontal_overflow')
            responsive.close()
        assert not errors, errors
        context.close()
        browser.close()
    report = {'mode': 'isolated_synthetic_browser_preview', 'viewport_widths': [1440, 1024, 390],
              'checks': checks, 'page_errors': errors, 'screenshots': sorted(p.name for p in out.glob('*.png'))}
    (out / 'browser-checks.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
