"""Offline glass material acceptance on the isolated, fictional Studio preview."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, expect


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8554')
    parser.add_argument('--output',default='artifacts/glass-ui-2026-10-22/acceptance')
    args=parser.parse_args()
    if urlparse(args.url).hostname not in {'127.0.0.1','localhost','::1'}:
        parser.error('Only a loopback isolated Studio preview is permitted')
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    checks,errors,external=[],[],[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)

        def session(**kwargs):
            context=browser.new_context(viewport={'width':1440,'height':1000},**kwargs)
            def local(route):
                if urlparse(route.request.url).netloc!=urlparse(args.url).netloc:
                    external.append(urlparse(route.request.url).hostname);route.abort()
                else:route.continue_()
            context.route('**/*',local)
            return context

        def open_studio(context):
            page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(args.url)
            frame=page.frame_locator('iframe')
            expect(frame.locator('.home')).to_be_visible()
            expect(frame.locator('#preview-badge')).to_be_visible()
            js=next(f for f in page.frames if '/component/' in f.url)
            js.wait_for_function('StudioInteractions.activeCount() === 0')
            expect(page.get_by_test_id('stException')).to_have_count(0)
            return page,frame,js

        context=session()
        page,frame,js=open_studio(context)
        assert js.evaluate('document.documentElement.dataset.material')=='glass'
        assert frame.locator('[data-view="signals"]').count()==0
        checks.append('original_studio_navigation_and_layout_remain_the_primary_interface')
        surfaces=js.evaluate("""() => ['.rail','.library','.topbar'].map(s=>{
            const c=getComputedStyle(document.querySelector(s));
            return {selector:s,blur:c.backdropFilter,background:c.backgroundColor,radius:c.borderRadius,shadow:c.boxShadow};
        })""")
        assert all('blur(24px)' in s['blur'] and s['background'].startswith('rgba') and s['shadow']!='none' for s in surfaces),surfaces
        checks.append('navigation_uses_real_translucency_backdrop_blur_radii_and_specular_shadows')
        page.screenshot(path=str(out/'home-desktop.png'))
        new=frame.locator('.new-button');box=new.bounding_box()
        page.mouse.move(box['x']+12,box['y']+12)
        js.wait_for_function("document.querySelector('.new-button').style.getPropertyValue('--glass-x') !== ''")
        first=new.evaluate("n=>n.style.getPropertyValue('--glass-x')")
        page.mouse.move(box['x']+box['width']-14,box['y']+12)
        js.wait_for_function("x=>document.querySelector('.new-button').style.getPropertyValue('--glass-x') !== x",arg=first)
        page.screenshot(path=str(out/'control-reflection.png'))
        frame.locator('.home-heading h1').hover()
        expect(new).not_to_have_attribute('data-glass-active','true')
        checks.append('pointer_reflection_tracks_only_interactive_controls_and_cleans_up_on_leave')
        frame.locator('#home-draft').fill('玻璃外观验收草稿')
        toggle=frame.locator('#material-toggle')
        toggle.focus();toggle.press('Enter')
        expect(toggle).to_have_attribute('aria-pressed','true')
        assert js.evaluate('document.documentElement.dataset.material')=='solid'
        assert frame.locator('.topbar').evaluate('n=>getComputedStyle(n).backdropFilter')=='none'
        assert frame.locator('#home-draft').input_value()=='玻璃外观验收草稿'
        page.screenshot(path=str(out/'solid-desktop.png'))
        checks.append('keyboard_material_toggle_removes_blur_without_changing_the_research_draft')
        page.reload();expect(frame.locator('#home-draft')).to_be_visible()
        js=next(f for f in page.frames if '/component/' in f.url)
        expect(frame.locator('#material-toggle')).to_have_attribute('aria-pressed','true')
        assert frame.locator('#home-draft').input_value()=='玻璃外观验收草稿'
        frame.locator('#material-toggle').click()
        expect(frame.locator('#material-toggle')).to_have_attribute('aria-pressed','false')
        checks.append('material_preference_and_draft_survive_refresh_independently')
        frame.get_by_role('button',name='自选公司',exact=True).click()
        expect(frame.locator('.stock-card').first).to_be_visible()
        page.screenshot(path=str(out/'watchlist-desktop.png'))
        frame.locator('.history-item').filter(has_text='增长是否转化为现金流').click()
        expect(frame.locator('.report-title')).to_be_visible()
        js.wait_for_function('StudioInteractions.activeCount() === 0')
        paper=frame.locator('.paper').evaluate("n=>({background:getComputedStyle(n).backgroundColor,blur:getComputedStyle(n).backdropFilter})")
        assert paper['background']=='rgb(20, 34, 52)' and paper['blur']=='none',paper
        page.screenshot(path=str(out/'report-desktop.png'))
        # Measure foreground over the report's opaque background, not the mesh.
        contrast_ratio=frame.locator('.paper .markdown').first.evaluate("""node=>{
            function rgb(s){return s.match(/[\d.]+/g).slice(0,3).map(Number).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4})}
            const f=rgb(getComputedStyle(node).color),b=rgb(getComputedStyle(document.querySelector('.paper')).backgroundColor);
            const l=v=>v[0]*.2126+v[1]*.7152+v[2]*.0722;
            return (Math.max(l(f),l(b))+.05)/(Math.min(l(f),l(b))+.05);
        }""")
        assert contrast_ratio>=4.5,contrast_ratio
        checks.append('long_report_uses_opaque_unblurred_paper_with_body_text_contrast_at_least_4_5')
        frame.locator('.report-section .citation').filter(has_text='E2').first.click()
        expect(frame.locator('#evidence-E2.focused')).to_be_visible()
        page.screenshot(path=str(out/'evidence-desktop.png'))
        checks.append('glass_material_does_not_change_version_scoped_report_evidence')
        frame.get_by_role('button',name='搜索已有研究',exact=True).click()
        expect(frame.locator('#palette')).to_be_visible()
        assert 'blur(' in frame.locator('#palette').evaluate('n=>getComputedStyle(n).backdropFilter')
        page.screenshot(path=str(out/'search-glass.png'))
        frame.locator('#palette-query').press('Escape')
        expect(frame.locator('#palette')).not_to_be_visible()
        checks.append('search_dialog_has_glass_material_and_preserves_escape_and_focus_behaviour')
        for width in [1024,390,1440]:
            page.set_viewport_size({'width':width,'height':920})
            js.wait_for_function('w=>innerWidth<=w && innerWidth>w-30',arg=width)
            if width<=820:
                expect(frame.locator('.library')).not_to_be_visible()
            assert not js.evaluate('document.documentElement.scrollWidth>innerWidth'),width
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth'),width
            page.screenshot(path=str(out/f'report-{width}.png'))
        checks.append('glass_workspace_has_no_document_horizontal_overflow_at_three_widths')
        context.close()

        reduced=session(reduced_motion='reduce')
        rp,rf,rj=open_studio(reduced)
        rf.locator('.new-button').hover()
        assert not rf.locator('.new-button').get_attribute('data-glass-active')
        assert rj.evaluate('StudioInteractions.activeCount()')==0
        assert rf.locator('.new-button').evaluate('n=>getComputedStyle(n).transform')=='none'
        checks.append('reduced_motion_disables_reflection_tracking_and_existing_motion')
        reduced.close()

        for feature,value,label in [('prefers-reduced-transparency','reduce','system_reduced_transparency'),('prefers-contrast','more','system_increased_contrast'),('forced-colors','active','system_forced_colors')]:
            system=session()
            sp,sf,sj=open_studio(system)
            cdp=system.new_cdp_session(sp)
            cdp.send('Emulation.setEmulatedMedia',{'features':[{'name':feature,'value':value}]})
            sj.wait_for_function("document.documentElement.dataset.material==='solid'")
            expect(sf.locator('#material-toggle')).to_be_disabled()
            assert sf.locator('.topbar').evaluate('n=>getComputedStyle(n).backdropFilter')=='none'
            if feature!='forced-colors':
                assert sf.locator('.library').evaluate('n=>!getComputedStyle(n).backgroundColor.startsWith("rgba")')
            checks.append(label+'_forces_readable_solid_material_live')
            system.close()

        def inject_glass(context,script):
            def inject(route):
                response=route.fetch()
                route.fulfill(response=response,body=script+'\n'+response.text())
            context.route('**/glass.js*',inject)

        blocked=session()
        inject_glass(blocked,"""
            window.__glassBlockedStorageTest=true;
            Object.defineProperty(window,'localStorage',{get(){throw new DOMException('Storage unavailable','SecurityError')}});
        """)
        bp,bf,bj=open_studio(blocked)
        assert bj.evaluate('window.__glassBlockedStorageTest') is True
        bf.locator('#material-toggle').click()
        expect(bf.locator('#material-toggle')).to_have_attribute('aria-pressed','true')
        checks.append('blocked_local_storage_keeps_a_working_in_memory_material_toggle')
        blocked.close()

        unsupported=session()
        inject_glass(unsupported,"""
            window.__glassUnsupportedTest=true;
            const supports=CSS.supports.bind(CSS);
            CSS.supports=(...args)=>String(args[0]).includes('backdrop-filter')?false:supports(...args);
        """)
        up,uf,uj=open_studio(unsupported)
        assert uj.evaluate('document.documentElement.dataset.material')=='solid',uj.evaluate("({url:location.pathname,injected:window.__glassUnsupportedTest,supports:CSS.supports('backdrop-filter','blur(1px)'),material:document.documentElement.dataset.material})")
        assert uf.locator('.topbar').evaluate('n=>getComputedStyle(n).backdropFilter')=='none'
        expect(uf.locator('#material-toggle')).to_be_disabled()
        checks.append('simulated_unsupported_backdrop_filter_uses_solid_fallback')
        unsupported.close()

        touch=session(has_touch=True,is_mobile=True)
        tp,tf,tj=open_studio(touch)
        tp.set_viewport_size({'width':390,'height':844})
        tj.wait_for_function('innerWidth<=390 && innerWidth>360')
        bounds=tf.locator('#material-toggle').bounding_box()
        assert bounds['width']>=44 and bounds['height']>=44,bounds
        tf.locator('#material-toggle').tap()
        expect(tf.locator('#material-toggle')).to_have_attribute('aria-pressed','true')
        tf.get_by_role('button',name='打开任务列表',exact=True).tap()
        expect(tf.locator('.library')).to_have_class('library open')
        assert not tj.evaluate('document.documentElement.scrollWidth>innerWidth')
        checks.append('touch_material_control_has_44px_target_and_mobile_navigation_remains_usable')
        touch.close()
        assert not errors,errors
        assert not external,external
        checks.append('no_javascript_errors_or_external_browser_requests')
        browser.close()
    result={'mode':'isolated_fictional_glass_acceptance','checks':checks,'report_text_contrast':round(contrast_ratio,2),
            'surfaces':surfaces,'page_errors':errors,'external_requests':external}
    (out/'checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'{len(checks)} glass browser checks passed; report text contrast {contrast_ratio:.2f}:1')


if __name__=='__main__':main()
