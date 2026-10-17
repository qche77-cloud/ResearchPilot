"""Browser acceptance only for scripts/preview_claims.py fictional records."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8522')
    parser.add_argument('--output', default='artifacts/claim-browser')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000}, accept_downloads=True)
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(args.url)
        frame = page.frame_locator('iframe')
        frame.locator('.home').wait_for()
        assert frame.locator('#preview-badge').is_visible(), 'Only fictional preview allowed'
        frame.locator('.history-item').filter(has_text='逐条结论验证验收').click()
        frame.get_by_role('button', name='过程', exact=True).click()
        frame.locator('.claim-check').first.wait_for()
        js = next(f for f in page.frames if '/component/' in f.url)
        versions = js.evaluate('Object.keys(data.run.versions)')
        assert frame.locator('[data-claim-status="supported"]').count() == 1
        assert frame.locator('[data-claim-status="contradicted"]').count() == 1
        assert frame.locator('[data-claim-status="insufficient_evidence"]').count() == 1
        checks.append('current_version_three_distinct_verdicts')
        conflict = frame.locator('[data-claim-status="contradicted"]')
        conflict.locator('summary').click()
        assert '净利润同比下降20%' in conflict.inner_text()
        assert '原文位置' in conflict.inner_text()
        page.screenshot(path=str(output / 'claims-desktop.png'))
        checks.append('conflicting_excerpt_and_original_offsets_visible')
        conflict.locator('.citation').last.click()
        frame.locator('#evidence-E2.focused').wait_for()
        assert '净利润同比下降20%' in frame.locator('#evidence-E2').inner_text()
        checks.append('claim_citation_opens_same_version_document')
        frame.get_by_role('button', name='过程', exact=True).click()
        with page.expect_download() as download:
            frame.get_by_role('button', name='下载此版本验证记录', exact=True).click()
        record = json.loads(Path(download.value.path()).read_text(encoding='utf-8'))
        assert record['claim_summary']['contradicted'] == 1
        assert record['semantic_support'] == 'unknown'
        checks.append('download_contains_current_verdicts_and_semantic_limit')
        frame.locator('#report-version').select_option(versions[1])
        assert frame.locator('[data-claim-status="supported"]').count() == 2
        assert frame.locator('[data-claim-status="contradicted"]').count() == 0
        checks.append('historical_verification_uses_historical_evidence')
        with page.expect_download() as download:
            frame.get_by_role('button', name='下载此版本验证记录', exact=True).click()
        assert json.loads(Path(download.value.path()).read_text(encoding='utf-8'))['claim_summary']['supported'] == 2
        checks.append('historical_export_matches_selected_version')
        frame.locator('#report-version').select_option('legacy-unchecked')
        assert '此报告版本未保存逐条结论验证' in frame.locator('.claim-checks').inner_text()
        assert frame.locator('.claim-check').count() == 0
        checks.append('legacy_version_never_inherits_latest_verdicts')
        malicious = js.evaluate("claimPanel({verification:{claims:[{status:'unknown',label:'<img src=x>',text:'<script>bad</script>',raw:'<img src=x onerror=alert(1)>',references:[]}],claim_summary:{}}})")
        assert '<img' not in malicious and '<script>' not in malicious
        checks.append('claim_text_and_raw_markup_are_escaped')
        mobile = browser.new_page(viewport={'width': 390, 'height': 844})
        mobile.on('pageerror', lambda error: errors.append(str(error)))
        mobile.goto(args.url)
        mf = mobile.frame_locator('iframe')
        mf.locator('.home').wait_for()
        mf.get_by_role('button', name='打开任务列表', exact=True).click()
        mf.locator('.history-item').filter(has_text='逐条结论验证验收').click()
        mf.get_by_role('button', name='助手', exact=True).click()
        mf.get_by_role('button', name='过程', exact=True).click()
        mf.locator('.claim-check').first.wait_for(state='visible')
        mf.locator('[data-claim-status="contradicted"] summary').click()
        mj = next(f for f in mobile.frames if '/component/' in f.url)
        assert not mj.evaluate('document.documentElement.scrollWidth > innerWidth')
        mobile.screenshot(path=str(output / 'claims-mobile.png'))
        checks.append('mobile_claims_readable_without_horizontal_overflow')
        browser.close()
    result = {'fixture': 'synthetic_offline_fixture', 'checks': checks, 'passed': len(checks), 'browser_errors': errors}
    (output / 'browser-checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    assert not errors, errors
    print(f'{len(checks)} claim browser checks passed; {output}')


if __name__ == '__main__':
    main()
