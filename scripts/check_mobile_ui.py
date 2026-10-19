"""Isolated fictional UI acceptance. Starts and removes its own demo process.

Never connects to a running user instance, loads .env or calls research APIs.
Requires optional Playwright + installed Chromium; not a WeChat device test.
"""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def isolated_demo():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    with tempfile.TemporaryFile() as log:
        env = {k: v for k, v in os.environ.items() if not any(
            part in k.upper() for part in ('API_KEY', 'APP_SECRET', 'ACCESS_TOKEN'))}
        process = subprocess.Popen([sys.executable, '-m', 'scripts.serve_miniprogram',
                                    '--demo', '--port', str(port)], cwd=ROOT, env=env,
                                   stdout=log, stderr=log)
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError('Isolated demo failed to start; no user service was changed')
                try:
                    with urlopen(url + '/health', timeout=1) as response:
                        assert json.load(response)['mode'] == 'demo'
                    break
                except (URLError, TimeoutError):
                    time.sleep(.1)
            else:
                raise RuntimeError('Isolated demo start timed out')
            yield url
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def acceptance(url, out):
    checks, errors, external = [], [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 390, 'height': 844}, reduced_motion='reduce')

        def local_only(route):
            if urlparse(route.request.url).netloc != urlparse(url).netloc:
                external.append(urlparse(route.request.url).hostname)
                route.abort()
            else:
                route.continue_()

        context.route('**/*', local_only)
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(url + '/preview/')
        page.get_by_role('button', name='进入体验 A', exact=False).click()
        expect(page.get_by_role('heading', name='研究工作台', exact=True)).to_be_visible()
        page.screenshot(path=str(out / 'home-390.png'), full_page=True)
        page.screenshot(path=str(out / 'home-viewport.png'))
        for width, height in ((360, 800), (390, 560), (430, 932)):
            page.set_viewport_size({'width': width, 'height': height})
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
            box = page.locator('[data-new]').bounding_box()
            assert box['height'] >= 44 and box['width'] >= 44
        checks.append('360_390_430_widths_and_short_viewport_have_no_overflow_and_touchable_primary_action')
        page.set_viewport_size({'width': 390, 'height': 560})
        page.locator('[data-new]').click()
        expect(page.get_by_role('dialog')).to_be_visible()
        assert page.locator('#app').evaluate('(e) => e.inert')
        page.wait_for_function("document.activeElement?.getAttribute('role') === 'dialog'")
        page.keyboard.press('Shift+Tab')
        assert page.locator('#create-form [type=submit]').evaluate('(e) => e === document.activeElement')
        page.keyboard.press('Tab')
        assert page.locator('[data-close]').evaluate('(e) => e === document.activeElement')
        checks.append('sheet_traps_keyboard_focus_and_makes_background_inert')
        page.locator('#topic').fill('虚构交互验收：现金流为何低于利润？')
        page.screenshot(path=str(out / 'new-research-short.png'), full_page=True)
        page.keyboard.press('Escape')
        expect(page.get_by_role('dialog')).to_have_count(0)
        page.wait_for_function('!history.state.sheet')
        assert not page.locator('#app').evaluate('(e) => e.inert')
        page.locator('[data-new]').click()
        expect(page.locator('#topic')).to_have_value('虚构交互验收：现金流为何低于利润？')
        page.go_back()
        expect(page.get_by_role('dialog')).to_have_count(0)
        expect(page.get_by_role('heading', name='研究工作台', exact=True)).to_be_visible()
        checks.append('escape_and_browser_back_close_sheet_preserving_research_draft')

        attempts = []

        def fail_once(route):
            if route.request.method == 'POST':
                attempts.append(route.request.headers.get('idempotency-key'))
                if len(attempts) == 1:
                    route.abort('failed')
                    return
            route.continue_()

        page.route('**/v1/runs', fail_once)
        page.locator('[data-new]').click()
        page.locator('#create-form [type=submit]').click()
        expect(page.locator('#sheet-error')).to_be_visible()
        page.locator('[data-close]').click()
        expect(page.get_by_role('dialog')).to_have_count(0)
        page.wait_for_function('!history.state.sheet')
        page.locator('[data-new]').click()
        page.locator('#create-form [type=submit]').click()
        expect(page.get_by_role('heading', name='虚构交互验收：现金流为何低于利润？', exact=True)).to_be_visible()
        assert len(attempts) == 2 and attempts[0] and attempts[0] == attempts[1]
        page.unroute('**/v1/runs', fail_once)
        checks.append('failed_submission_reopens_and_retries_same_idempotency_key_once')

        page.locator('nav [data-nav=home]').click()
        page.locator('#research-query').fill('no-such-fictional-research')
        expect(page.locator('#history-list .empty')).to_be_visible()
        assert page.locator('[data-run]').count() == 0
        page.locator('#research-query').fill('')
        page.locator('[data-filter=active]').click()
        expect(page.locator('#history-list .empty')).to_be_visible()
        page.locator('[data-filter=completed]').click()
        assert page.locator('[data-run]').count() == 2
        page.locator('[data-filter=all]').click()
        checks.append('search_and_status_filters_show_empty_state_and_restore_unmodified_history')
        page.evaluate('scrollTo(0, 240)')
        saved = page.evaluate('scrollY')
        assert saved > 0
        page.locator('nav [data-nav=account]').click()
        expect(page.get_by_role('heading', name='我的研究空间', exact=True)).to_be_visible()
        page.locator('nav [data-nav=home]').click()
        page.wait_for_function('(y) => Math.abs(scrollY-y)<2', arg=saved)
        checks.append('navigation_restores_research_list_scroll_position')

        page.set_viewport_size({'width': 390, 'height': 844})
        page.locator('[data-run]').first.click()
        expect(page.locator('#version')).to_be_visible()
        page.locator('[data-outline]').click()
        expect(page.get_by_role('dialog', name='报告目录')).to_be_visible()
        page.locator('[data-section="1"]').click()
        expect(page.get_by_role('dialog')).to_have_count(0)
        page.wait_for_function('!history.state.sheet')
        page.wait_for_function("scrollY > 0 && document.getElementById('report-section-1').getBoundingClientRect().top < innerHeight-110")
        checks.append('report_outline_scrolls_to_selected_section_below_sticky_header')
        page.locator('[data-reading]').click()
        assert page.locator('body').evaluate("e => e.classList.contains('reading-large')")
        page.reload()
        expect(page.locator('#version')).to_be_visible()
        assert page.locator('body').evaluate("e => e.classList.contains('reading-large')")
        page.locator('[data-reading]').click()
        expect(page.locator('#toast')).to_be_hidden(timeout=5000)
        page.screenshot(path=str(out / 'report-390.png'), full_page=True)
        page.screenshot(path=str(out / 'report-viewport.png'))
        checks.append('large_reading_preference_survives_reload')
        page.locator('[data-citation="E1"]').first.click()
        expect(page.locator('#source-E1')).to_have_class('source-card selected')
        expect(page.locator('[data-tab=sources]')).to_have_attribute('aria-selected', 'true')
        page.screenshot(path=str(out / 'sources-390.png'), full_page=True)
        checks.append('inline_citation_opens_and_highlights_version_bound_evidence')
        page.locator('[data-tab=report]').click()
        options = page.locator('#version option').evaluate_all('(es) => es.map(e => e.value)')
        page.locator('#version').select_option(options[0])
        expect(page.get_by_text('反面证据与后续核查', exact=True)).not_to_be_visible()
        page.locator('#version').select_option(options[1])
        expect(page.get_by_text('反面证据与后续核查', exact=True)).to_be_visible()
        checks.append('old_report_version_does_not_show_new_sections')

        held = []
        old_path = '**/reports/' + options[0]
        page.route(old_path, lambda route: held.append(route))
        with page.expect_request(old_path):
            page.locator('#version').select_option(options[0])
        page.locator('#version').select_option(options[1])
        expect(page.get_by_text('反面证据与后续核查', exact=True)).to_be_visible()
        assert len(held) == 1
        late = context.request.get(held[0].request.url, headers=held[0].request.headers).json()
        held[0].fulfill(json=late)
        page.unroute(old_path)
        # A same-origin marker queues after the fulfilled stale response callback.
        page.evaluate('() => new Promise(resolve => setTimeout(resolve, 100))')
        expect(page.locator('#version')).to_have_value(options[1])
        expect(page.get_by_text('反面证据与后续核查', exact=True)).to_be_visible()
        checks.append('late_old_version_response_cannot_overwrite_new_selection')

        latest_path = '**/reports/' + options[1]

        def unsafe_text(route):
            data = context.request.get(route.request.url, headers=route.request.headers).json()
            data['sections'][0]['content'] = '<img src=x onerror="window.fixtureExecuted=1"><script>window.fixtureExecuted=2</script>'
            route.fulfill(json=data)

        page.route(latest_path, unsafe_text)
        page.reload()
        expect(page.locator('#reading-panel')).to_contain_text('<img src=x')
        assert page.evaluate('window.fixtureExecuted === undefined')
        assert page.locator('#reading-panel img, #reading-panel script').count() == 0
        page.unroute(latest_path, unsafe_text)
        checks.append('raw_report_html_remains_text_and_cannot_execute')

        page.locator('nav [data-nav=watches]').click()
        page.locator('[data-company="000001"]').click()
        expect(page.get_by_role('heading', name='已保存财务', exact=True)).to_be_visible()
        expect(page.locator('.metric-unit').first).to_contain_text('CNY 元')
        assert 'currency_unit' not in page.locator('#app').inner_text()
        page.screenshot(path=str(out / 'company-390.png'), full_page=True)
        page.screenshot(path=str(out / 'company-viewport.png'))
        assert page.locator('.metric-card').count() == 4
        chart_id = page.locator('[data-chart-point]').first.get_attribute('data-chart-point')
        page.locator('[data-chart-point]').first.click()
        point_period = page.locator('.chart-inspect .muted').first.inner_text()
        expect(page.locator('#finance-period')).to_have_value(point_period)
        page.locator('.chart-inspect [data-record]').click()
        expect(page.get_by_role('dialog')).to_contain_text(chart_id)
        expect(page.get_by_role('dialog')).to_contain_text('源值与单位')
        expect(page.get_by_role('dialog')).to_contain_text('来源披露日期')
        expect(page.get_by_role('dialog')).to_contain_text('采集时间')
        page.screenshot(path=str(out / 'financial-source-390.png'), full_page=True)
        page.keyboard.press('Escape')
        expect(page.get_by_role('dialog')).to_have_count(0)
        page.wait_for_function('!history.state.sheet')
        checks.append('chart_period_selection_and_source_sheet_keep_exact_record_identity_and_units')
        periods = page.locator('#finance-period option').evaluate_all('(es) => es.map(e => e.value)')
        page.locator('#finance-period').select_option(periods[0])
        expect(page.locator('.chart-inspect')).to_contain_text(periods[0])
        checks.append('reporting_period_selector_updates_chart_inspector')

        page.locator('nav [data-nav=account]').click()
        expect(page.get_by_role('heading', name='我的研究空间', exact=True)).to_be_visible()
        expect(page.locator('#toast')).to_be_hidden()
        page.screenshot(path=str(out / 'account-390.png'), full_page=True)
        page.emulate_media(reduced_motion='reduce')
        assert page.locator('#app').evaluate("e => getComputedStyle(e).animationName === 'none'")
        checks.append('page_changes_clear_toasts_and_reduced_motion_disables_page_animation')
        assert not errors, errors
        assert not external, external
        checks.append('all_browser_requests_are_local_and_no_javascript_errors_occur')
        browser.close()
    return {'mode': 'isolated_fictional_browser_not_wechat_device_acceptance', 'checks': checks,
            'page_errors': errors, 'external_requests': external, 'paid_api_calls': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='artifacts/mobile-ui-2026-10-20/acceptance')
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    with isolated_demo() as url:
        result = acceptance(url, out)
    (out / 'checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{len(result["checks"])} UI interaction checks passed; isolated fictional data; no paid APIs')


if __name__ == '__main__':
    main()
