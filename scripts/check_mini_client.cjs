/* Native controller tests with explicit wx transport stubs, not a WeChat VM. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {createRequire}=require('node:module');
const {execFileSync}=require('node:child_process');
const base=path.resolve(__dirname,'../miniprogram'),checks=[];
const storage=new Map(),requests=[],navigations=[],scheduled=[],scrolls=[];
let transport;
global.wx={getStorageSync:k=>storage.get(k),setStorageSync:(k,v)=>storage.set(k,v),removeStorageSync:k=>storage.delete(k),
 request(options){requests.push(options);transport(options);},navigateTo:o=>navigations.push(o.url),switchTab:o=>navigations.push(o.url),
 login:o=>o.success({code:'offline-wx-code'}),showToast(){},setClipboardData(){},showModal:o=>o.success({confirm:true}),nextTick:fn=>fn(),pageScrollTo:o=>scrolls.push(o.selector)};
function controller(relative){
 let definition;
 const filename=path.join(base,relative);
 vm.runInNewContext(fs.readFileSync(filename,'utf8'),{require:createRequire(filename),Page:p=>definition=p,wx:global.wx,
   setTimeout:(fn,ms)=>{scheduled.push({fn,ms});return scheduled.length;},clearTimeout(){}},{filename});
 const page={...definition,data:JSON.parse(JSON.stringify(definition.data))};
 page.setData=values=>Object.assign(page.data,values);
 return page;
}
async function main(){
 const app=JSON.parse(fs.readFileSync(path.join(base,'app.json'),'utf8'));
 for(const page of app.pages){
   assert(fs.existsSync(path.join(base,page+'.js')));assert(fs.existsSync(path.join(base,page+'.wxml')));
   execFileSync(process.execPath,['--check',path.join(base,page+'.js')]);
   const definition=controller(page+'.js');
   for(const match of fs.readFileSync(path.join(base,page+'.wxml'),'utf8').matchAll(/(?:bind|catch)(?:tap|input|change)="([^"]+)"/g))assert.equal(typeof definition[match[1]],'function',page+' '+match[1]);
 }
 checks.push('six_native_pages_parse_and_handlers_resolve');
 execFileSync(process.execPath,['--check',path.resolve(__dirname,'../mobile-preview/mobile.js')]);
 const api=require(path.join(base,'utils/api')),config=require(path.join(base,'config')),fmt=require(path.join(base,'utils/format'));
 transport=o=>o.success({statusCode:200,data:{token:'offline-session-token-0000000000000000000',mode:'demo'}});
 await api.login();assert(api.token());assert.equal(requests.at(-1).url,'http://127.0.0.1:8540/v1/auth/demo');checks.push('explicit_demo_login_uses_demo_endpoint');
 transport=o=>o.success({statusCode:401,data:{error:{message:'expired'}}});
 await assert.rejects(api.call('/v1/me'),/expired/);assert.equal(api.token(),'');checks.push('unauthorized_response_clears_session');
 config.mode='wechat';config.apiBase='http://unsafe.example';const before=requests.length;
 await assert.rejects(api.call('/v1/me'),/HTTPS/);assert.equal(requests.length,before);checks.push('wechat_mode_rejects_insecure_transport');
 config.apiBase='https://api.example.invalid';transport=o=>o.success({statusCode:200,data:{token:'offline-session-token-0000000000000000000',mode:'wechat'}});
 await api.login('offline-invitation');assert.equal(requests.at(-1).data.code,'offline-wx-code');assert.equal(requests.at(-1).data.invitation,'offline-invitation');checks.push('wechat_login_sends_code_only_to_backend');
 config.mode='demo';config.apiBase='http://127.0.0.1:8540';
 const home=controller('pages/home/index.js');home.data.topic='离线问题';home.data.requestKey='persistent-request-key-0001';
 let pending;transport=o=>{pending=o;};const count=requests.length;
 const first=home.submit();await home.submit();assert.equal(requests.length,count+1);
 const requestId=pending.header['Idempotency-Key'];pending.fail();await first;
 assert.equal(home.data.requestKey,requestId);assert.equal(home.data.submitting,false);
 const retry=home.submit();assert.equal(pending.header['Idempotency-Key'],requestId);pending.success({statusCode:202,data:{id:'offline-run'}});await retry;
 assert(navigations.at(-1).includes('offline-run'));checks.push('submit_blocks_double_tap_and_reuses_key_after_network_failure');
 const task=controller('pages/task/index.js');task.onLoad({id:'slow-run'});task.onShow();const slow=pending;task.onHide();
 slow.success({statusCode:200,data:{id:'slow-run',active:true,versions:[]}});await new Promise(resolve=>setImmediate(resolve));
 assert.equal(task.data.run,null);assert.equal(scheduled.length,0);checks.push('hidden_page_ignores_late_response_and_stops_polling');
 const blocks=fmt.blocks('**原始文字**\n\n<script>doNotExecute()</script>');assert.equal(blocks[0].nodes[0].name,'strong');assert.equal(blocks[1].nodes[0].type,'text');checks.push('markdown_treats_raw_html_as_text');
 assert.equal(fmt.date('2026-10-19T15:49:00Z'),'2026-10-19 23:49');checks.push('timestamps_display_in_asia_shanghai');
 home.data.runs=[{id:'one',topic:'Cash FLOW',active:true,completed:false},{id:'two',topic:'其他研究',active:false,completed:true}];
 home.search({detail:{value:'flow'}});assert.equal(home.data.visibleRuns.length,1);assert.equal(home.data.runs.length,2);
 home.selectFilter({currentTarget:{dataset:{filter:'completed'}}});assert.equal(home.data.visibleRuns.length,0);
 checks.push('native_search_and_status_filters_do_not_modify_history');
 home.data.requestKey='retry-after-closing-0001';home.data.topic='原问题';home.newResearch();home.close();home.newResearch();assert.equal(home.data.requestKey,'retry-after-closing-0001');checks.push('native_sheet_reopen_preserves_idempotency_key');
 task.data.report={cards:[{eid:'E1'}]};task.outline();task.section({currentTarget:{dataset:{index:1}}});assert.equal(scrolls.at(-1),'#report-section-1');assert.equal(task.data.outlineOpen,false);
 task.citation({currentTarget:{dataset:{eid:'E1'}}});assert.equal(task.data.sourceFocus,'E1');assert.equal(scrolls.at(-1),'#source-E1');
 task.reading();assert.equal(storage.get('rp_mini_reading_large'),'1');checks.push('native_outline_citation_and_reading_preferences_work');
 const company=controller('pages/company/index.js');
 const record=(id,currency,period,value,metric='revenue')=>({id,currency,period_end:period,value,metric,label:metric,status:'ok',basis:'cumulative',scope:'consolidated',unit:'元',raw_unit:'元',raw:{value},source_url:'https://example.invalid/fixture'});
 company.data.company={analysis:{records:[record('a','CNY','2025-12-31','100'),record('b','USD','2025-12-31','999'),record('c','CNY','2024-12-31','80'),record('d','CNY','2025-12-31','-5','net_profit')]},charts:{revenue:[{record_id:'a',currency:'CNY',scope:'consolidated',basis:'cumulative',unit:'元',period:'2025-12-31',value:'100'},{record_id:'b',currency:'USD',scope:'consolidated',basis:'cumulative',unit:'元',period:'2025-12-31',value:'999'},{record_id:'c',currency:'CNY',scope:'consolidated',basis:'cumulative',unit:'元',period:'2024-12-31',value:'80'}]}};
 company.arrange();assert.equal(company.data.records.length,2);assert.equal(company.data.trend.length,1);assert.equal(company.data.trend[0].record_id,'a');
 company.period({detail:{value:'1'}});assert.equal(company.data.records[0].id,'c');company.inspect({currentTarget:{dataset:{id:'c'}}});assert.equal(company.data.inspected.raw_value,'80');assert.equal(company.data.inspected.source_url,'https://example.invalid/fixture');
 checks.push('native_finance_period_scope_and_source_detail_preserve_record_identity');
 assert.equal(fmt.amount('12345678901234567890.012300'),'12,345,678,901,234,567,890.012300');assert.equal(fmt.amount('-1000.00'),'-1,000.00');checks.push('financial_display_keeps_exact_decimal_strings');
 assert.equal(fmt.unitLabel('currency_unit','CNY'),'元');assert.equal(fmt.unitLabel('currency_unit','USD'),'美元');assert.equal(fmt.unitLabel('percent','CNY'),'%');assert.equal(fmt.unitLabel('multiple','CNY'),'倍');assert.equal(fmt.unitLabel('currency_unit','XYZ'),'货币基本单位');checks.push('canonical_units_have_currency_aware_labels_without_changing_values');
 fs.mkdirSync(path.resolve(__dirname,'../artifacts'),{recursive:true});
 fs.writeFileSync(path.resolve(__dirname,'../artifacts/miniprogram-client-checks.json'),JSON.stringify({mode:'native_controller_stubs_not_wechat_runtime',checks},null,2));
 process.stdout.write(checks.length+' native controller checks passed; not a WeChat compiler or device acceptance\n');
}
main().catch(error=>{process.stderr.write(error.stack+'\n');process.exitCode=1;});
