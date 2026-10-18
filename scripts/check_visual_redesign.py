"""Visual/readability acceptance on temporary fictional data only."""
import argparse
import json
from pathlib import Path
import uuid
from playwright.sync_api import sync_playwright, expect


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8530')
    parser.add_argument('--output',default='artifacts/visual-redesign')
    args=parser.parse_args();out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    checks=[];errors=[];readability=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        for width,name in [(1440,'desktop'),(1024,'tablet'),(390,'mobile')]:
            context=browser.new_context(viewport=dict(width=width,height=1100),reduced_motion='reduce')
            page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(args.url+'?acceptance_token=visual-'+uuid.uuid4().hex)
            f=page.frame_locator('iframe');f.locator('.home').wait_for()
            assert f.locator('#preview-badge').is_visible(),'Screenshots require fictional preview'
            js=next(fr for fr in page.frames if '/component/' in fr.url)
            js.wait_for_function('(width)=>innerWidth<=width',arg=width)
            assert not js.evaluate('document.documentElement.scrollWidth>innerWidth')
            assert js.evaluate("getComputedStyle(document.documentElement).colorScheme==='dark'")
            assert f.locator('.workspace-strip strong').first.inner_text()==str(js.evaluate('data.history_count'))
            metrics=f.locator('.home-heading p').evaluate('''n=>{
              const s=getComputedStyle(n),b=getComputedStyle(document.getElementById('main'));
              const rgb=t=>t.match(/[\d.]+/g).slice(0,3).map(Number);
              const lum=c=>c.map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
              const a=lum(rgb(s.color)),z=lum(rgb(b.backgroundColor));
              return {font_size:parseFloat(s.fontSize),contrast:(Math.max(a,z)+.05)/(Math.min(a,z)+.05)};
            }''')
            assert metrics['font_size']>=13 and metrics['contrast']>=4.5,metrics
            readability.append(dict(viewport=width,home_description=metrics))
            page.screenshot(path=str(out/f'home-{name}.png'))
            f.locator('.template').first.click()
            assert f.locator('#home-draft').input_value()=='研究一家公司的现金流质量'
            if width>660:
                f.get_by_role('button',name='搜索已有研究',exact=True).click()
                expect(f.locator('#palette')).to_be_visible()
                f.locator('#palette-query').press('Escape')
            if f.locator('.resume-card').is_visible():
                resume_id=f.locator('.resume-card [data-run]').get_attribute('data-run')
                f.locator('.resume-card [data-run]').click()
                js.wait_for_function('(id)=>data.run?.id===id',arg=resume_id)
                f.locator('.taskbar').wait_for()
            checks.append(f'{name}_home_readability_template_and_search')
            f.get_by_role('button',name='自选公司',exact=True).click()
            f.locator('[data-company="002837"]').click()
            f.locator('.chart-point').first.wait_for()
            assert not js.evaluate('document.documentElement.scrollWidth>innerWidth')
            assert f.locator('.finance-summary').inner_text()
            page.screenshot(path=str(out/f'company-{name}.png'))
            f.get_by_role('button',name='同业比较',exact=True).click()
            f.locator('#peer-compare').wait_for()
            assert not js.evaluate('document.documentElement.scrollWidth>innerWidth')
            page.screenshot(path=str(out/f'comparison-form-{name}.png'))
            checks.append(f'{name}_company_finance_and_forms_no_overflow')
            # Open a report through the actual task list. Mobile uses its drawer.
            if width<=820:
                f.get_by_role('button',name='打开任务列表',exact=True).click()
            f.locator('.history-item').filter(has_text='增长是否转化为现金流').click()
            f.locator('.report-title').wait_for()
            assert float(f.locator('.paper .markdown').first.evaluate('n=>getComputedStyle(n).fontSize').rstrip('px'))>=15
            assert not js.evaluate('document.documentElement.scrollWidth>innerWidth')
            page.screenshot(path=str(out/f'report-{name}.png'))
            checks.append(f'{name}_report_readability_and_navigation')
            assert not page.get_by_test_id('stException').count()
            context.close()
        browser.close()
    assert not errors,errors
    (out/'browser-checks.json').write_text(json.dumps(dict(mode='fictional_preview_readability_and_visual_acceptance',checks=checks,readability=readability,page_errors=errors),ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'{len(checks)} visual/readability checks passed')


if __name__=='__main__':main()
