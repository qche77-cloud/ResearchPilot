"""Fictional browser acceptance. PDF decoding covered by original-PDF evaluation."""
import argparse
import json
from pathlib import Path
import uuid
from playwright.sync_api import sync_playwright, expect
from scripts.preview_peer_research import FIXTURE_BYTES


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8527')
    parser.add_argument('--output',default='artifacts/peer-research-browser')
    args=parser.parse_args();out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    checks=[];errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context(viewport=dict(width=1440,height=1100),accept_downloads=True)
        page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(args.url+'?acceptance_token='+uuid.uuid4().hex)
        f=page.frame_locator('iframe');f.locator('.home').wait_for()
        assert f.locator('#preview-badge').is_visible()
        f.get_by_role('button',name='自选公司',exact=True).click()
        f.locator('[data-company="002837"]').click()
        f.get_by_role('button',name='财报导入',exact=True).click()
        f.locator('#report-pdf').set_input_files(dict(name='fictional.pdf',mimeType='application/pdf',buffer=FIXTURE_BYTES))
        f.locator('#pdf-period').fill('2025-12-31');f.locator('#pdf-published').fill('2026-04-01');f.locator('#pdf-source').fill('https://example.invalid/fictional.pdf')
        f.get_by_role('button',name='提取候选数值',exact=True).click()
        f.locator('#pdf-confirm').wait_for()
        expect(f.locator('[data-pdf-candidate]')).to_have_count(4)
        f.locator('.pdf-candidates details').first.locator('summary').click()
        expect(f.locator('.pdf-candidates')).to_contain_text('营业收入 12000000.00')
        page.screenshot(path=str(out/'import-desktop.png'))
        checks.append('pdf_proposals_periods_page_and_original_excerpt_visible')
        for checkbox in f.locator('[data-pdf-candidate]').all(): checkbox.check()
        f.locator('#pdf-confirmed').check()
        f.get_by_role('button',name='确认并保存新版本',exact=True).click()
        f.get_by_role('button',name='下载原始 PDF',exact=True).wait_for()
        expect(f.locator('#pdf-confirm')).to_have_count(0)
        with page.expect_download() as download:
            f.get_by_role('button',name='下载原始 PDF',exact=True).click()
        assert Path(download.value.path()).read_bytes()==FIXTURE_BYTES
        checks.append('explicit_confirmation_saves_version_and_exact_source_bytes')
        f.get_by_role('button',name='同业比较',exact=True).click()
        f.locator('#peer-name').fill('虚构公司比较组')
        f.locator('#peer-symbols').fill('002837 600000 600001')
        f.get_by_role('button',name='保存比较组',exact=True).click()
        f.locator('#peer-group-id option').nth(1).wait_for(state='attached')
        f.locator('#peer-group-id').select_option(index=1)
        f.locator('#peer-period').fill('2025-12-31');f.locator('#peer-cutoff').fill('2026-10-18')
        f.get_by_role('button',name='比较并保存结果',exact=True).click()
        f.locator('[data-peer-export]').wait_for()
        expect(f.locator('#company-content')).to_contain_text('比较组中位数')
        expect(f.locator('.peer-lead')).to_contain_text('营收增长，归母净利润未增长')
        with page.expect_download() as download:
            f.locator('[data-peer-export]').click()
        report=json.loads(Path(download.value.path()).read_text(encoding='utf-8'))
        assert len(report['rows'])==3 and len(report['bindings'])==2
        assert next(row for row in report['rows'] if row['symbol']=='600001')['reason']=='缺少已保存的财务数据'
        assert report['parameters']['period_end']=='2025-12-31'
        assert all(factor['period_end']=='2025-12-31' for row in report['rows'] for factor in row['factors'])
        assert all(b.is_disabled() for b in f.locator('[data-peer-research]').all())
        f.locator('[data-peer-export]').evaluate("n=>n.closest('section').scrollIntoView({block:'start',behavior:'instant'})")
        page.screenshot(path=str(out/'peers-desktop.png'))
        checks.append('same_period_comparison_missing_coverage_and_versioned_export')
        checks.append('research_questions_visible_paid_actions_disabled_in_preview')
        # A new session reopens immutable results from the temporary database.
        run_id=report['run_id'];page.reload();f.locator('.home').wait_for()
        f.get_by_role('button',name='自选公司',exact=True).click();f.locator('[data-company="002837"]').click()
        f.get_by_role('button',name='同业比较',exact=True).click()
        f.locator('#peer-history').select_option(run_id)
        f.locator('[data-peer-export]').wait_for()
        checks.append('saved_comparison_reopens_after_browser_reload')
        for width,label in [(1024,'tablet'),(390,'mobile')]:
            page.set_viewport_size(dict(width=width,height=1000))
            js=next(frame for frame in page.frames if '/component/' in frame.url)
            js.wait_for_function('(width)=>innerWidth<=width',arg=width)
            js.wait_for_function('StudioInteractions.activeCount()===0')
            js.wait_for_function("innerWidth>820||(getComputedStyle(document.getElementById('library')).visibility==='hidden' && Number(getComputedStyle(document.getElementById('library')).opacity)===0)")
            assert not js.evaluate('document.documentElement.scrollWidth > innerWidth')
            f.locator('[data-peer-export]').evaluate("n=>n.closest('section').scrollIntoView({block:'start',behavior:'instant'})")
            page.screenshot(path=str(out/f'peers-{label}.png'))
            f.get_by_role('button',name='财报导入',exact=True).click()
            f.locator('#pdf-prepare').wait_for()
            assert not js.evaluate('document.documentElement.scrollWidth > innerWidth')
            page.screenshot(path=str(out/f'import-{label}.png'))
            f.get_by_role('button',name='同业比较',exact=True).click()
            checks.append(f'{label}_import_and_comparison_no_page_overflow')
        assert not errors,errors
        assert not page.get_by_test_id('stException').count()
        browser.close()
    result=dict(mode='synthetic_temporary_db_and_mock_pdf_extraction',pdf_parser_acceptance='see peer-research-original-pdfs.json',checks=checks,page_errors=errors)
    (out/'browser-checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'{len(checks)} browser checks passed')


if __name__=='__main__':main()
