/* Local, dependency-free Streamlit component. Only explicit intents reach Python. */
'use strict';
const icons={book:'M4 4h6c2 0 2 2 2 2s0-2 2-2h6v15h-6c-2 0-2 1-2 1s0-1-2-1H4z M12 6v14',grid:'M4 4h6v6H4z M14 4h6v6h-6z M4 14h6v6H4z M14 14h6v6h-6z',sliders:'M4 7h8 M16 7h4 M4 17h3 M11 17h9 M12 4v6 M7 14v6',settings:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1z',plus:'M12 5v14 M5 12h14',search:'M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14 M15 15l6 6',menu:'M4 6h16 M4 12h16 M4 18h16',arrow:'M5 12h14 M13 6l6 6-6 6',file:'M6 3h8l4 4v14H6z M14 3v5h4 M9 12h6 M9 16h6',spark:'M12 3l2 6 6 3-6 2-2 7-2-7-6-2 6-3z',download:'M12 3v12 M7 10l5 5 5-5 M4 16v5h16v-5',link:'M10 14l4-4 M9 16l-2 2a4 4 0 0 1-5-5l5-5a4 4 0 0 1 6 0 M15 8l2-2a4 4 0 0 1 5 5l-5 5a4 4 0 0 1-6 0',check:'M5 12l4 4 10-10',pause:'M8 5v14 M16 5v14',play:'M7 4l13 8-13 8z',clock:'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M12 7v5l4 2',chart:'M4 20h17 M5 16l5-5 4 3 6-9',shield:'M12 3l8 3v6c0 5-8 9-8 9s-8-4-8-9V6z M8 12l3 3 5-6',send:'M3 3l18 9-18 9 4-9z M7 12h14',external:'M14 3h7v7 M21 3l-11 11 M10 4H4v16h16v-6',close:'M6 6l12 12 M18 6L6 18'};
const svg=name=>`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${icons[name]||icons.file}"/></svg>`;
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeURL=value=>{try{const u=new URL(value);return ['https:','http:'].includes(u.protocol)?u.href:null;}catch{return null;}};
const labelStatus=value=>({completed:'已完成',failed:'执行失败',running:'待恢复',pending:'待恢复'}[value]||'待恢复');
const dateText=value=>String(value||'日期未知').slice(0,10).replaceAll('-','.');
// Display rounding only. Python calculations and exported decimal strings stay exact.
const formatFactor=value=>Number.isFinite(Number(value))?Number(value).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2}):String(value);
const readStatusText=value=>({success:'正文已读取',fallback:'仅有搜索摘要',failed:'读取失败',error:'读取失败'}[value]||'读取状态未记录');
const relationText=value=>({supports:'与原文一致',supported:'与原文一致',contradicts:'与原文冲突',contradicted:'与原文冲突',mixed:'原文存在分歧',unknown:'尚未确认',unresolved:'引用无法对应'}[value]||'尚未确认');
const uncertaintyText=value=>({high:'高',medium:'中',low:'低'}[value]||value||'未知');
const executionStatusText=value=>({running:'正在执行',completed:'已完成',success:'已完成',ok:'已完成',failed:'执行失败',error:'执行失败',interrupted:'已中断',pending:'等待处理',cancelled:'已取消'}[value]||'状态未记录');
const dateSourceText=value=>({none:'未记录',metadata:'页面元数据',structured_data:'页面标注',body:'正文',url:'来源链接',search_result:'搜索结果',synthetic_fixture:'演示资料'}[value]||(/[\u4e00-\u9fff]/.test(value||'')?value:'其他日期记录'));
const confidenceText=value=>({high:'高',medium:'中',low:'低',none:'未知',unknown:'未知'}[value]||(/[\u4e00-\u9fff]/.test(value||'')?value:'未知'));
const criterionStatusText=value=>({not_due:'未到复盘日期',waiting_for_data:'等待财报数据',criterion_met:'财务条件已满足',criterion_not_met:'财务条件未满足'}[value]||'尚未检查');
const moneyUnitText=value=>({CNY:'元',USD:'美元',HKD:'港元',EUR:'欧元'}[value]||'金额单位待核对');
const empty=(title,text,wide=false)=>`<div class="empty${wide?' wide':''}">${svg('file')}<h3>${esc(title)}</h3><p>${esc(text)}</p></div>`;
const $=selector=>document.querySelector(selector);
let data=null,lastSignature='',currentRun=null,version=null,inspector='chat',focusedEvidence=null,mobileInspector=false,pendingEvent=null,paletteIndex=0;
const interactions=window.StudioInteractions;
interactions.setEvidenceProvider(button=>(data?.run?.versions?.[button.dataset.citeVersion]?.cards||[]).find(card=>card.eid===button.dataset.cite));
const drafts=new Map();
function getSaved(key,fallback=''){try{return sessionStorage.getItem('rp-studio-'+key)??fallback;}catch{return drafts.get(key)??fallback;}}
function save(key,value){drafts.set(key,value);try{sessionStorage.setItem('rp-studio-'+key,value);}catch{/* In-memory draft fallback for privacy browsers. */}}
function snapshot(){return data?.run?.versions?.[version]||{sections:[],cards:[],findings:[]};}
function inline(text,citationVersion=version){
  const pattern=/(`[^`\n]+`|\*\*[^*\n]+\*\*|\[[^\]\n]+\]\([^\s)]+\)|\[E\d+\])/g;
  let out='',at=0;
  for(const match of String(text).matchAll(pattern)){
    out+=esc(String(text).slice(at,match.index));const token=match[0];
    if(token.startsWith('`'))out+=`<code>${esc(token.slice(1,-1))}</code>`;
    else if(token.startsWith('**'))out+=`<strong>${inline(token.slice(2,-2),citationVersion)}</strong>`;
    else if(/^\[E\d+\]$/.test(token)){
      const eid=token.slice(1,-1),found=(data.run?.versions?.[citationVersion]?.cards||[]).some(c=>c.eid===eid);
      out+=`<button class="citation${found?'':' missing'}" data-cite="${esc(eid)}" data-cite-version="${esc(citationVersion||'')}" title="${found?'查看此版本的原始证据':'此版本缺少引用证据'}">${esc(eid)}</button>`;
    }else{
      const parts=token.match(/^\[([^\]]+)\]\(([^)]+)\)$/),url=safeURL(parts?.[2]);
      out+=url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(parts[1])}</a>`:esc(token);
    }
    at=match.index+token.length;
  }
  return out+esc(String(text).slice(at));
}
function markdown(text,citationVersion=version){
  const renderInline=text=>inline(text,citationVersion);
  const lines=String(text||'').replaceAll('\r','').split('\n');let out='',i=0;
  while(i<lines.length){
    const line=lines[i];
    if(!line.trim()){i++;continue;}
    if(/^```/.test(line)){let code=[];i++;while(i<lines.length&&!/^```/.test(lines[i]))code.push(lines[i++]);i++;out+=`<pre><code>${esc(code.join('\n'))}</code></pre>`;continue;}
    if(/^\s*\|/.test(line)&&i+1<lines.length&&/^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lines[i+1])){
      const cells=l=>l.trim().replace(/^\||\|$/g,'').split('|');
      out+='<table><thead><tr>'+cells(line).map(c=>`<th>${renderInline(c.trim())}</th>`).join('')+'</tr></thead><tbody>';i+=2;
      while(i<lines.length&&/^\s*\|/.test(lines[i]))out+='<tr>'+cells(lines[i++]).map(c=>`<td>${renderInline(c.trim())}</td>`).join('')+'</tr>';
      out+='</tbody></table>';continue;
    }
    if(/^#{1,6}\s/.test(line)){out+=`<h4>${renderInline(line.replace(/^#{1,6}\s/,''))}</h4>`;i++;continue;}
    if(/^>\s?/.test(line)){out+=`<blockquote>${renderInline(line.replace(/^>\s?/,''))}</blockquote>`;i++;continue;}
    if(/^\s*([-*]|\d+\.)\s/.test(line)){
      const ordered=/^\s*\d+\./.test(line),tag=ordered?'ol':'ul';out+=`<${tag}>`;
      while(i<lines.length&&/^\s*([-*]|\d+\.)\s/.test(lines[i]))out+=`<li>${renderInline(lines[i++].replace(/^\s*([-*]|\d+\.)\s/,''))}</li>`;
      out+=`</${tag}>`;continue;
    }
    let paragraph=[line];i++;
    while(i<lines.length&&lines[i].trim()&&!/^(#{1,6}\s|>|```|\s*([-*]|\d+\.)\s|\s*\|)/.test(lines[i]))paragraph.push(lines[i++]);
    out+=`<p>${paragraph.map(renderInline).join('<br>')}</p>`;
  }
  return `<div class="markdown">${out}</div>`;
}
function post(type,extra={}){window.parent.postMessage({isStreamlitMessage:true,type,...extra},'*');}
function resize(){let height=900;try{height=Math.max(500,window.parent.innerHeight);}catch{height=Math.max(500,window.innerHeight);}post('streamlit:setFrameHeight',{height});}
function notify(message){const node=$('#notice');node.textContent=String(message).replaceAll('判据','验证条件').replaceAll('财务输入','财务数据');node.hidden=false;clearTimeout(notify.timer);notify.timer=setTimeout(()=>node.hidden=true,6000);}
function emit(action,extra={}){
  if(pendingEvent){notify('正在处理上一条请求，请稍候');return;}
  const id=Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);
  pendingEvent={id,action,...extra};post('streamlit:setComponentValue',{value:pendingEvent,dataType:'json'});
  interactions.busy(true);
  clearTimeout(emit.timer);emit.timer=setTimeout(()=>{pendingEvent=null;interactions.busy(false);notify('暂未收到服务响应，请检查本地连接后重试');},25000);
}
function renderHistory(){
  $('#history-count').textContent=data.history_count;
  $('#history').innerHTML=data.history.length?data.history.map(r=>`<button class="history-item${data.run?.id===r.id?' selected':''}" data-run="${esc(r.id)}"><b>${esc(r.topic)}</b><small><i class="status-dot ${esc(relationText(r.status))}"></i>${labelStatus(r.status)}<span>·</span>${dateText(r.updated_at)}</small></button>`).join(''):empty('还没有研究记录','从一个值得核查的问题开始。');
  document.querySelectorAll('.rail-item[data-view]').forEach(b=>b.classList.toggle('selected',b.dataset.view===data.view||(b.dataset.view==='watchlist'&&data.view==='company')));
  $('#workspace-name').textContent={research:'研究空间',watchlist:'自选公司',screening:'财务筛选',company:'公司研究'}[data.view]||'研究空间';
  $('#preview-badge').hidden=!data.preview;
}
function home(){
  const today=new Date(),recent=data.history.slice(0,4);
  return `<div class="home"><div class="home-heading"><div><div class="eyebrow">研究工作台</div><h1>把问题研究清楚，把依据留完整。</h1><p>查找资料、对照证据，保存每次研究的报告和判断。</p></div><div class="home-date"><b>${String(today.getDate()).padStart(2,'0')}</b>${today.getFullYear()} / ${String(today.getMonth()+1).padStart(2,'0')}</div></div>
  <div class="launch"><section class="briefing"><div class="briefing-top"><h2>开始一项研究</h2><span>公司 · 行业 · 投资观点</span></div><textarea id="home-draft" aria-label="研究问题" placeholder="你想弄清楚什么？&#10;&#10;例如：收入增长背后，利润与现金流是否同步兑现？" maxlength="6000">${esc(getSaved('home'))}</textarea><div class="briefing-foot"><label>搜索次数上限 <input id="budget" type="number" min="2" max="16" value="${esc(getSaved('budget','2'))}" aria-label="搜索次数上限"></label><button class="button primary" data-action="start" ${data.preview?'disabled':''}>开始研究 ${svg('arrow')}</button></div></section>
  <section class="discipline"><div class="eyebrow">研究方法</div><h2>形成判断前，<br>也看看反面证据。</h2><p>先核对事实，再形成判断。<br>把尚未确定的问题记录下来。</p><div class="loop"><span>问题</span><i>→</i><span>证据</span><i>→</i><span>判断</span></div></section></div>
  <div class="block-heading"><h2>选一个切入点</h2><span>只填入问题，确认后开始</span></div><div class="templates">
  ${[['chart','经营质量','从利润与现金流的差异，拆解增长。','研究一家公司的现金流质量'],['file','公告变化','对照历史判断，关注真正新增的信息。','核查近期公告中的风险'],['shield','观点核查','主动寻找反例，检验判断的边界。','寻找推翻投资观点的证据']].map(([icon,title,desc,prompt])=>`<button class="template" data-prompt="${esc(prompt)}"><span class="template-icon">${svg(icon)}</span><span class="arrow">↗</span><h3>${title}</h3><p>${desc}</p></button>`).join('')}</div>
  <div class="block-heading"><h2>最近的研究</h2><button class="button quiet" data-action="palette">查看全部 ${svg('arrow')}</button></div><div class="recent-table">${recent.length?recent.map(r=>`<button class="recent-row" data-run="${esc(r.id)}"><b>${esc(r.topic)}</b><span class="tag ${r.status==='completed'?'green':''}">${labelStatus(r.status)}</span><small>${dateText(r.updated_at)}</small><span style="color:#a4abb7">↗</span></button>`).join(''):empty('你的第一份研究档案','研究报告、对话和来源会共同保存在这里。')}</div>
  <div class="footer-note">${data.preview?'当前为隔离的离线演示，所有公司、数值与资料均为虚构。':'研究与数据保存在本地 · 创建研究和发送追问可能使用已配置的模型 / 搜索 API'}</div></div>`;
}
function paper(){
  const run=data.run,s=snapshot(),sections=s.sections||[],vs=Object.keys(run.versions);
  return `<div class="canvas"><div class="canvas-toolbar"><div class="canvas-toolbar-label">${svg('file')}研究报告 <span class="tag">${sections.length} 章节</span></div><div><select id="report-version" aria-label="报告版本">${vs.map((v,i)=>`<option value="${esc(v)}" ${v===version?'selected':''}>版本 ${String(i+1).padStart(2,'0')} · ${dateText(run.versions[v].as_of)}</option>`).join('')||'<option>尚未生成报告</option>'}</select><button class="icon-button" data-action="download-report" aria-label="下载当前版本报告" ${sections.length?'':'disabled'}>${svg('download')}</button></div></div>
  <div class="document-scroll" id="document-scroll"><article class="paper"><div class="paper-kicker"><span>ResearchPilot / 研究报告</span><span>${data.preview?'虚构数据演示':'本地研究'}</span></div><h2 class="report-title">${esc(run.topic)}</h2><div class="paper-byline"><span>报告时间 ${dateText(s.as_of||run.updated_at)}</span><span>版本 ${esc(version?.slice(0,8)||'等待生成')}</span><span>${(s.cards||[]).length} 条引用证据</span></div>
  ${sections.length?`<nav class="toc" aria-label="报告目录">${sections.map((sec,i)=>`<button data-section="${i}"><b>${String(i+1).padStart(2,'0')}</b>${esc(sec.title)}</button>`).join('')}</nav>${sections.map((sec,i)=>`<section class="report-section" id="section-${i}"><h3><span class="section-number">${String(i+1).padStart(2,'0')}</span>${esc(sec.title)}</h3>${markdown(sec.content)}</section>`).join('')}`:empty(run.active?'研究正在推进':'报告尚未生成',run.active?'报告会随后台研究更新。右侧可以查看计划与执行记录。':'可查看历史对话，或恢复任务继续研究。',true)}
  <div class="paper-disclaimer">${data.preview?'离线合成演示，不能用于投资判断。<br>':''}引用可点击查看此报告版本对应的原文摘录。原文引用可供核对，但资料是否足以支持结论仍需判断。${version==='legacy'?'<br>这份历史报告未保存引用对应关系，暂时无法确认原文。':''}</div></article></div></div>`;
}
function chat(){
  const run=data.run;
  return `<div class="inspector-scroll" id="chat-scroll"><div class="assistant-intro"><div class="assistant-icon">${svg('spark')}</div><div><b>研究助手</b><small>围绕同一个问题，持续核查。</small></div></div>${(run.messages||[]).map((m,i)=>`<div class="message ${m.role==='user'?'user':'assistant'}"><div class="message-label"><span>${m.role==='user'?'你':'RESEARCHPILOT'}</span>${m.report_version?'<span>已关联报告</span>':''}</div><div class="message-content">${markdown(m.display_summary||m.content,m.report_version||null)}</div>${m.report_version&&run.versions[m.report_version]?`<button class="message-version" data-version="${esc(m.report_version)}">${svg('file')}打开这条回答对应的报告 <span style="margin-left:auto">↗</span></button>`:''}${m.provenance_note||m.citation_check?`<div class="message-note">${esc(m.provenance_note||m.citation_check)}</div>`:''}${m.original_content?`<details class="process-disclosure"><summary>查看原回答</summary>${markdown(m.original_content,m.report_version||null)}</details>`:''}</div>`).join('')||empty('研究对话','新的消息会出现在这里。')}
  ${data.pending.filter(c=>c.kind==='chat').map(c=>`<div class="subtle-box">待处理消息：${esc(c.content)}</div>`).join('')}
  <div><button class="suggestion" data-followup="哪些证据可能推翻当前结论？">寻找反例</button><button class="suggestion" data-followup="请指出报告中的证据缺口和需要补查的问题。">核查证据缺口</button></div></div>
  <div class="composer"><div class="composer-box"><textarea id="chat-draft" aria-label="继续追问" maxlength="6000" placeholder="追问一条结论，或让助手继续核查…">${esc(getSaved('draft-'+run.id))}</textarea><div class="composer-bottom"><span>Ctrl / ⌘ + Enter 发送</span><button data-action="chat" aria-label="发送追问" ${data.preview?'disabled':''}>${svg('send')}</button></div></div><div class="composer-tip">${data.preview?'离线预览 · 禁用模型和任务命令':'草稿保留在当前浏览器会话 · 追问可能调用模型'}</div></div>`;
}
function evidence(){
  const s=snapshot(),cards=s.cards||[],found=cards.find(c=>c.eid===focusedEvidence);
  return `<div class="inspector-scroll" id="evidence-scroll"><div class="evidence-summary"><span>此报告版本的引用资料</span><span>${cards.length} 条</span></div>${focusedEvidence&&!found?`<div class="subtle-box">引用 ${esc(focusedEvidence)} 在此报告中未保存对应资料，暂时无法确认来源。</div>`:''}
  ${cards.map(c=>{const url=safeURL(c.url);return `<article class="evidence-card${c.eid===focusedEvidence?' focused':''}" id="evidence-${esc(c.eid)}"><div class="evidence-title"><span class="tag purple">${esc(c.eid)}</span><div><b>${esc(c.title)}</b><small>来源日期 ${esc(c.date||'未知')} · ${esc(readStatusText(c.read_status))}</small></div></div><div class="evidence-text">${c.listing_page?'<div class="tag amber">滚动列表页 · 不能认定为公告发布日期</div>':''}<div>${esc(c.excerpt_kind)}</div>${(c.excerpts||[]).map(q=>`<blockquote>${esc(q)}</blockquote>`).join('')||'<p>没有保存可核对的采集文本。</p>'}${(s.findings||[]).filter(f=>(f.evidence_ids||[]).includes(c.eid)).map(f=>`<p><span class="tag">${f.kind==='inference'?'模型推断':f.kind==='gap'?'待验证':'模型归纳'}</span> ${esc(f.text)}</p>`).join('')}<details><summary>完整采集文本</summary><div class="full-text">${esc(c.text||'未保存')}</div></details><details><summary>日期依据与口径</summary><p>日期来源：${esc(dateSourceText(c.date_source))}<br>日期可信度：${esc(confidenceText(c.date_confidence))}<br>财报期：${esc(c.report_period||'尚未核对')}</p></details></div>${url?`<a class="evidence-link" href="${esc(url)}" target="_blank" rel="noopener noreferrer">打开原始来源 ${svg('external')}</a>`:'<div class="evidence-link">原始链接不可用</div>'}</article>`;}).join('')||empty('此报告未保存引用资料','可以查看已采集的来源，但暂时无法确认它们与报告中引用的对应关系。')}
  ${data.run.sources.length?`<details class="process-disclosure"><summary>全部采集来源 · ${data.run.sources.length} 条</summary>${data.run.sources.map(c=>{const url=safeURL(c.url);return `<div class="subtle-box">${esc(c.title)}<br>来源日期：${esc(c.date||'未知')}${url?`<br><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">原始来源 ↗</a>`:''}</div>`;}).join('')}</details>`:''}<p class="source-label">摘录来自保存的资料。请结合原文核对结论，并以原始公告确认日期。</p></div>`;
}
function claimPanel(s){
  const check=s.verification;
  if(!check?.claims)return '<div class="subtle-box claim-checks">此报告版本未保存逐条结论验证。</div>';
  const summary=check.claim_summary||{},claims=check.claims||[];
  return `<section class="claim-checks"><h3 class="process-heading">此版本的结论验证</h3><div class="subtle-box">原文匹配 ${esc(summary.supported||0)} · 直接冲突 ${esc((summary.contradicted||0)+(summary.mixed||0))} · 证据不足 ${esc(summary.insufficient_evidence||0)}<p>原文匹配表示来源中有相同陈述，结论是否成立、资料是否可靠仍需核对。</p></div>${claims.map(c=>`<details class="process-disclosure claim-check" data-claim-status="${esc(c.status)}"><summary>${esc(c.label)} · ${esc(c.text)}</summary>${markdown(c.raw)}${c.references.map(r=>`<div class="subtle-box">${inline('['+r.evidence_id+']')} ${esc(r.title||'引用不存在')}<p>来源日期：${esc(r.published_at||'未知')} · 读取：${esc(readStatusText(r.read_status))} · ${esc(relationText(r.status))}</p>${r.excerpts.map(q=>`<blockquote>${esc(q.text)}</blockquote><small>原文位置 ${esc(q.start)}–${esc(q.end)} · ${esc(relationText(q.relation))}</small>`).join('')}</div>`).join('')||'<p>未关联引用，仍待验证。</p>'}</details>`).join('')}<button class="button" data-action="download-claims">下载此版本验证记录</button></section>`;
}
function processPanel(){
  const run=data.run,s=snapshot(),old=version!==Object.keys(run.versions).at(-1),hs=s.hypotheses||(old?[]:run.hypotheses),summary=run.trace_summary;
  const judgment={open:'待验证',direction_supported:'方向支持',contradicted_by_data:'发现反例'};
  return `<div class="inspector-scroll" id="process-scroll"><div class="evidence-summary"><span>研究假设与核查结果</span><span>${hs.length} 个假设</span></div>${hs.map(h=>`<article class="hypothesis"><span class="tag ${h.judgment==='contradicted_by_data'?'amber':'purple'}">${esc(judgment[h.judgment]||h.judgment)}</span><h3>${esc(h.content)}</h3><p>不确定性：${esc(uncertaintyText(h.uncertainty))}</p>${h.criterion?`<p>验证依据：${esc(h.criterion)}</p>`:''}${['supporting','contrary'].map((side,i)=>h[side]?.length?`<details><summary>${i?'反面':'支持'}证据 · ${h[side].length}</summary><pre class="full-text">${esc(JSON.stringify(h[side],null,2))}</pre></details>`:'').join('')}${h.questions?.length?`<ul>${h.questions.map(q=>`<li>${esc(q)}</li>`).join('')}</ul>`:''}</article>`).join('')||empty('尚无研究假设记录',old?'此历史版本没有保存假设，不能用当前判断回填。':'研究过程生成的假设与反例会显示在这里。')}
  ${data.worker?`<div class="worker-panel"><b>${data.worker.locked?'此任务正在执行':'此任务当前未执行'}</b><br>待处理操作 ${data.pending.length} 条<details><summary>执行与恢复记录</summary>${data.worker.attempts.map(t=>`<div class="worker-attempt">${esc(executionStatusText(t.status))} · ${esc(t.started)}<small>结束 ${esc(t.finished||'尚未结束；若长时间没有进展，可尝试恢复任务')} · ${esc(t.error_type||'')}</small></div>`).join('')||'尚无执行记录。'}</details></div>`:''}<h3 class="process-heading">${old?'当前任务执行记录（与历史报告独立）':'研究执行进度'}</h3><div class="timeline">${(run.plan||[]).map(p=>`<div class="timeline-item"><b>${esc(p.title)}</b><p>${esc(p.description)}</p></div>`).join('')||'<div class="timeline-item"><b>等待生成研究计划</b><p>计划生成后，可在这里查看研究步骤。</p></div>'}</div>
  ${claimPanel(s)}
  ${run.critic?`<div class="subtle-box"><b>当前任务的引用与数值检查：${run.critic.passed?'通过':'未通过'}</b><p>此处检查引用和部分数值冲突，不能证明所有结论正确。上方显示所选报告版本的逐条核查结果。</p><details><summary>查看当前任务检查明细</summary><pre>${esc(JSON.stringify(run.critic,null,2))}</pre></details></div>`:''}
  ${run.gaps?.length?`<details class="process-disclosure"><summary>待补查的证据缺口 · ${run.gaps.length}</summary>${run.gaps.map(g=>`<div class="subtle-box">${esc(g.task)}<br>${esc(g.issue)}</div>`).join('')}</details>`:''}
  ${summary?`<h3 class="process-heading">调用与成本</h3><div class="subtle-box">模型 ${esc(summary.model_calls)} 次 · 工具记录 ${esc(summary.tool_calls)} 条<br>已记录 Token ${esc(summary.known_total_tokens)} · 用量未记录 ${esc(summary.unknown_usage_calls)} 次<br>${summary.total_model_cost_usd==null?'完整费用未知；已知部分 USD '+esc(summary.known_cost_subtotal_usd):'模型 Token 估算 USD '+esc(summary.total_model_cost_usd)}<br>搜索等工具费用不包含在此估算中。</div>`:'<div class="subtle-box">此任务未保存完整的调用用量，无法计算历史费用。</div>'}
  <div class="timeline">${(run.trace||[]).slice(-15).map(t=>`<div class="timeline-item"><b>${esc(t.operation||t.kind)} <span class="tag">${esc(executionStatusText(t.status))}</span></b><p>${esc(t.model||t.stage||'')} · ${esc(t.elapsed_ms??'未知')} ms</p></div>`).join('')}</div>
  ${(run.revisions||[]).length?`<details class="process-disclosure"><summary>自主计划调整</summary><pre class="full-text">${esc(JSON.stringify(run.revisions,null,2))}</pre></details>`:''}
  ${(s.evidence_graph||run.graph)?.nodes?.length?`<details class="process-disclosure"><summary>结论—假设—证据关系</summary><button class="button" data-action="download-graph">下载关系图</button><pre class="full-text">${esc(JSON.stringify(s.evidence_graph||(old?{}:run.graph),null,2))}</pre></details>`:''}
  ${run.diff?`<details class="process-disclosure"><summary>与上次研究的变化</summary><pre class="full-text">${esc(JSON.stringify(run.diff,null,2))}</pre><button class="button" data-action="download-diff">下载结构化差异</button></details>`:''}
  ${run.baseline?`<button class="message-version" data-run="${esc(run.baseline.run_id)}">${svg('clock')}打开上次研究 ${dateText(run.baseline.as_of)}</button>`:''}</div>`;
}
function research(){
  const run=data.run;
  return `<div class="research${mobileInspector?' mobile-inspector':''}"><div class="taskbar"><div class="taskbar-copy"><h1 title="${esc(run.topic)}">${esc(run.topic)}</h1><div class="taskbar-meta"><span class="tag ${run.active?'purple':run.completed?'green':'amber'}">${run.active?svg('spark'):run.completed?svg('check'):svg('clock')}${esc(run.status)}</span><span>搜索 ${esc(run.searches)} / ${esc(run.budget)}</span><span>${run.sources.length} 条来源</span><span>更新 ${dateText(run.updated_at)}</span></div></div><div class="taskbar-actions">${run.active?`<button class="button" data-command="pause" ${data.preview?'disabled':''}>${svg('pause')}暂停</button>`:!run.completed?`<button class="button" data-command="resume" ${data.preview?'disabled':''}>${svg('play')}恢复</button>`:''}<button class="button" data-command="budget" ${data.preview?'disabled':''}>${svg('plus')}增加搜索次数</button>${run.stock_symbol?`<button class="button quiet" data-command="update" ${run.active||data.preview?'disabled':''}>更新研究</button>`:''}<div class="mobile-focus"><button class="button ${!mobileInspector?'selected':''}" data-focus="report">报告</button><button class="button ${mobileInspector?'selected':''}" data-focus="inspector">助手</button></div></div></div>${run.error?`<div class="task-alert">执行异常：${esc(run.error)}</div>`:''}${!run.active&&!run.completed?'<div class="task-alert">当前任务未在执行。若其他窗口仍显示运行中，请确认任务已经停止后再恢复。</div>':''}<div class="research-body">${paper()}<div class="resize-handle" id="resize-handle" role="separator" aria-label="调整报告与助手宽度" aria-orientation="vertical" tabindex="0"></div><aside class="inspector"><div class="inspector-head"><div class="inspector-tabs">${[['chat','对话'],['evidence','证据'],['process','过程']].map(([id,title])=>`<button class="inspector-tab${inspector===id?' selected':''}" data-inspector="${id}">${title}</button>`).join('')}</div><span style="font-size:8px;color:#b0b5bf">研究助手</span></div><div class="inspector-content">${inspector==='chat'?chat():inspector==='evidence'?evidence():processPanel()}</div></aside></div></div>`;
}
function watchlist(){
  return `<div class="data-workspace"><div class="data-heading"><div><div class="eyebrow">公司研究</div><h1>自选公司</h1><p>集中查看自选公司的研究、财务数据和投资观点。</p></div><button class="button" data-view="workbench">${svg('settings')}管理自选与数据</button></div><div class="stock-grid">${data.watches.map(w=>`<article class="stock-card"><small>${esc(w.symbol)} · 公司档案</small><h2>${esc(w.name||w.symbol)}</h2><span class="tag">本地自选</span><p class="source-label">加入 ${dateText(w.created)}</p><button class="button" data-action="stock-search" data-symbol="${esc(w.symbol)}">${svg('search')}查找研究档案</button></article>`).join('')||empty('自选列表还是空的','在数据工具中添加公司，然后保存有来源的财务数据。',true)}</div></div>`;
}
function screening(){
  const result=data.screening,criteria=data.criteria,rows=result?.rows||[],fields=['revenue_yoy','attributable_profit_yoy','gross_margin','net_margin','cash_conversion'];
  return `<div class="data-workspace"><div class="data-heading"><div><div class="eyebrow">按财务指标筛选</div><h1>财务指标筛选</h1><p>按所选日期筛选已保存的财务数据。点击指标查看公式、原始数据和来源。</p></div><button class="button" data-view="workbench">导入原始财务数据 ${svg('arrow')}</button></div>
  <form class="screen-filter" id="screen-form"><label>数据截止日<input id="screen-date" type="date" value="${esc(criteria.as_of)}" required></label><label>财务口径<select id="screen-basis"><option value="cumulative" ${criteria.basis!=='single_quarter'?'selected':''}>累计</option><option value="single_quarter" ${criteria.basis==='single_quarter'?'selected':''}>单季</option></select></label><label>币种<select id="screen-currency">${['CNY','USD','HKD','EUR'].map(c=>`<option ${c===(criteria.currency||'CNY')?'selected':''}>${c}</option>`).join('')}</select></label><label>报表范围<select id="screen-scope"><option value="consolidated" ${criteria.scope!=='parent_company'?'selected':''}>合并报表</option><option value="parent_company" ${criteria.scope==='parent_company'?'selected':''}>母公司</option></select></label><label>营收同比 ≥ %<input id="screen-revenue" type="number" step="any" value="${esc(criteria.minimums?.revenue_yoy??'')}" placeholder="不限"></label><label>归母利润同比 ≥ %<input id="screen-profit" type="number" step="any" value="${esc(criteria.minimums?.attributable_profit_yoy??'')}" placeholder="不限"></label><button class="button primary" type="submit">执行筛选</button></form>
  <div class="block-heading"><h2>${result?.matched_count??0} / ${result?.stock_count??0} 家满足条件</h2><button class="button quiet" data-action="download-screen">${svg('download')}导出筛选依据</button></div>${result?.missing_symbols?.length?`<div class="subtle-box">${result.missing_symbols.length} 家自选缺少本地财务输入：${result.missing_symbols.map(esc).join('、')}。请导入有来源的数据。</div>`:''}
  ${StudioCockpit.screeningExtras()}<div class="screen-table">${rows.length?`<table><thead><tr><th>公司</th><th>财报期</th><th>营收同比</th><th>归母利润同比</th><th>毛利率</th><th>净利率</th><th>现金兑现率（近12个月）</th><th>结果</th></tr></thead><tbody>${rows.map((r,i)=>`<tr><td>${esc(r.symbol)}</td><td>${esc(r.quality.period_end||'未知')}</td>${fields.map(key=>{const f=r.quality.factors.find(f=>f.key===key);return `<td><button class="factor-value ${f?.status==='ok'?'':'unavailable'}" data-factor="${key}" data-row="${i}" title="${esc(f?.value??f?.reason??'不可计算')}">${f?.status==='ok'?esc(formatFactor(f.value))+(f.unit==='percent'?'%':'×'):'—'}</button></td>`;}).join('')}<td><span class="tag ${r.matched?'green':'amber'}" title="${esc(r.reasons.join('；'))}">${r.matched?'符合':'未满足'}</span></td></tr>`).join('')}</tbody></table>`:empty('没有可筛选的本地财务数据','筛选不会自动抓取数据；在数据工具中导入后再试。',true)}</div><div id="factor-lineage"></div><p class="footer-note">表格显示两位小数，导出保留计算精度。仅覆盖本地自选池，最多 50 家；缺失指标不补零。筛选不调用模型，结果仅表示满足所设条件，不代表投资建议。</p></div>`;
}
function renderMain(preserve=true,reason='none'){
  interactions.beforeRender();
  const positions={};if(preserve)document.querySelectorAll('[id$="-scroll"]').forEach(n=>positions[n.id]=n.scrollTop);
  const focused=document.activeElement,focusId=focused?.id,start=focused?.selectionStart,end=focused?.selectionEnd;
  $('#main').innerHTML=data.view==='watchlist'?StudioCockpit.library():data.view==='company'?StudioCockpit.render():data.view==='screening'?screening():data.run?research():home();
  for(const [id,top] of Object.entries(positions)){const node=document.getElementById(id);if(node)node.scrollTo({top,behavior:'instant'});}
  const target=focusId&&document.getElementById(focusId);if(target){target.focus({preventScroll:true});if(target.setSelectionRange&&start!=null&&target.type!=='number')target.setSelectionRange(start,end);}
  wireResize();
  interactions.transition(reason);
}
function selectVersion(v){if(!data.run.versions[v])return;version=v;save('version-'+data.run.id,v);focusedEvidence=null;renderMain(false,'version');}
function paletteResults(){const q=$('#palette-query').value.toLowerCase(),rows=data.history.filter(r=>r.topic.toLowerCase().includes(q));paletteIndex=Math.min(paletteIndex,Math.max(0,rows.length-1));$('#palette-results').innerHTML=rows.length?rows.map((r,i)=>`<button class="palette-result${i===paletteIndex?' selected':''}" data-run="${esc(r.id)}"><span>${esc(r.topic)}</span><small>${labelStatus(r.status)} · ${dateText(r.updated_at)}</small></button>`).join(''):empty('没有匹配的研究','尝试公司代码或研究主题。');}
function openPalette(q=''){interactions.beforeRender();const dialog=$('#palette');$('#palette-query').value=q;paletteIndex=0;paletteResults();if(!dialog.open){dialog.showModal();interactions.openPalette();}$('#palette-query').focus();}
function download(name,content,type='text/markdown'){const url=URL.createObjectURL(new Blob([content],{type:type+';charset=utf-8'})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function factorLineage(row,key){
  const r=data.screening.rows[row],f=r.quality.factors.find(f=>f.key===key);if(!f)return;
  const records=[],visited=new Set();
  function follow(id){if(visited.has(id))return;visited.add(id);const input=r.quality.inputs[id]||{id,status:'输入未保存'};records.push(input);for(const child of input.input_ids||[])follow(child);}
  f.input_ids.forEach(follow);
  const basisLabel={cumulative:'年初至今累计',single_quarter:'单季',ttm:'滚动 12 个月'},scopeLabel={consolidated:'合并报表',parent_company:'母公司'};
  $('#factor-lineage').innerHTML=`<article class="lineage"><div class="block-heading"><h3>${esc(r.symbol)} · ${esc(f.label)}的计算依据</h3><button class="icon-button" data-action="close-lineage" aria-label="关闭计算依据">${svg('close')}</button></div><div class="lineage-formula"><span>公式</span><b>${esc(f.formula||'缺少可比输入，无法计算')}</b></div><p class="source-label">截止日 ${esc(r.quality.as_of)} · ${esc(f.currency)} · ${esc(scopeLabel[f.scope]||f.scope)} · ${esc(basisLabel[f.basis]||f.basis)}</p>${f.reason?`<p class="source-label">不可计算原因：${esc(f.reason)}</p>`:''}<div class="input-grid">${records.map(input=>{const url=safeURL(input.source_url);return `<div class="input-card"><div class="input-period">${esc(input.period_end||'期间未知')} <span>${esc(input.label||input.metric||'缺失输入')}</span></div><strong>${esc(input.value??'不可用')} <small>${esc(input.currency||'')}</small></strong><p>${esc(basisLabel[input.basis]||input.basis||'口径未知')} · ${esc(scopeLabel[input.scope]||input.scope||'范围未知')}<br>原始值 ${esc(input.raw?.value??input.value??'未知')} ${esc(input.raw?.unit||input.raw_unit||input.unit||'单位未知')}<br>披露 ${esc(input.published_at||'未知')} · 可用 ${esc(input.available_at||input.published_at||'未知')}</p>${url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">原始数据来源 ↗</a>`:'<span class="source-label">此派生步骤的原始依据见输入记录</span>'}</div>`;}).join('')||'<p class="source-label">没有可用的原始输入，不能补零或生成虚构计算。</p>'}</div><details class="process-disclosure"><summary>查看记录编号与完整数据 · ${records.length} 条</summary><pre>${esc(JSON.stringify(records,null,2))}</pre></details></article>`;
}

function wireResize(){const h=$('#resize-handle');if(!h)return;let origin,startWidth;h.addEventListener('pointerdown',e=>{origin=e.clientX;startWidth=$('.inspector').getBoundingClientRect().width;h.setPointerCapture(e.pointerId);});h.addEventListener('pointermove',e=>{if(!h.hasPointerCapture(e.pointerId))return;const max=Math.min(550,$('.research-body').clientWidth-310);document.documentElement.style.setProperty('--side',Math.max(280,Math.min(max,startWidth+origin-e.clientX))+'px');});h.addEventListener('pointerup',e=>{h.releasePointerCapture(e.pointerId);save('panel-width',String($('.inspector').getBoundingClientRect().width));});h.addEventListener('keydown',e=>{if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();const width=$('.inspector').getBoundingClientRect().width;document.documentElement.style.setProperty('--side',Math.max(280,Math.min(550,width+(e.key==='ArrowLeft'?20:-20)))+'px');}});}
document.addEventListener('click',e=>{
  const b=e.target.closest('button,a');if(!b||b.disabled)return;
  if(b.dataset.run){$('#palette').close();$('#library').classList.remove('open');emit('open',{run_id:b.dataset.run});return;}
  if(b.dataset.view){$('#library').classList.remove('open');emit('navigate',{view:b.dataset.view});return;}
  if(b.dataset.prompt){$('#home-draft').value=b.dataset.prompt;save('home',b.dataset.prompt);$('#home-draft').focus();return;}
  if(b.dataset.followup){$('#chat-draft').value=b.dataset.followup;save('draft-'+data.run.id,b.dataset.followup);$('#chat-draft').focus();return;}
  if(b.dataset.section){document.getElementById('section-'+b.dataset.section)?.scrollIntoView({behavior:'smooth',block:'start'});return;}
  if(b.dataset.cite){if(!b.dataset.citeVersion){notify('这条回答未关联可核对的报告版本，无法重建引用来源');return;}version=b.dataset.citeVersion;save('version-'+data.run.id,version);inspector='evidence';focusedEvidence=b.dataset.cite;if(window.innerWidth<=660)mobileInspector=true;renderMain(true,'panel');const card=document.getElementById('evidence-'+focusedEvidence);card?.scrollIntoView({behavior:'smooth',block:'nearest'});interactions.spotlight(card);return;}
  if(b.dataset.inspector){inspector=b.dataset.inspector;renderMain(true,'panel');return;}
  if(b.dataset.focus){mobileInspector=b.dataset.focus==='inspector';renderMain(true,'panel');return;}
  if(b.dataset.version){selectVersion(b.dataset.version);return;}
  if(b.dataset.command){emit(b.dataset.command,{run_id:data.run.id});return;}
  if(b.dataset.factor){factorLineage(Number(b.dataset.row),b.dataset.factor);interactions.showLineage();return;}
  switch(b.dataset.action){
    case 'new':case 'home':emit('new');break;
    case 'menu':$('#library').classList.toggle('open');break;
    case 'palette':openPalette();break;
    case 'close-palette':$('#palette').close();break;
    case 'stock-search':openPalette(b.dataset.symbol);break;
    case 'start':{const topic=$('#home-draft').value.trim(),budget=Number($('#budget').value);if(!topic){$('#home-draft').focus();notify('先写下你想核查的问题');return;}if(!Number.isInteger(budget)||budget<2||budget>16){notify('搜索次数上限范围为 2–16 次');return;}emit('start',{topic,budget});break;}
    case 'chat':{const content=$('#chat-draft').value.trim();if(content)emit('chat',{run_id:data.run.id,content});break;}
    case 'download-report':download('research-'+version+'.md','# '+data.run.topic+'\n\n'+snapshot().sections.map(s=>'## '+s.title+'\n\n'+s.content).join('\n\n')+'\n\n报告时间：'+snapshot().as_of);break;
    case 'download-graph':download('evidence-graph.json',JSON.stringify(snapshot().evidence_graph||(version===Object.keys(data.run.versions).at(-1)?data.run.graph:{}),null,2),'application/json');break;
    case 'download-claims':download('claim-verification-'+version+'.json',JSON.stringify(snapshot().verification||{},null,2),'application/json');break;
    case 'download-diff':download('research-diff.json',JSON.stringify(data.run.diff,null,2),'application/json');break;
    case 'close-lineage':$('#factor-lineage').innerHTML='';break;
    case 'download-screen':download('financial-screening.json',JSON.stringify(data.screening,null,2),'application/json');break;
  }
});
document.addEventListener('input',e=>{if(e.target.id==='home-draft')save('home',e.target.value);if(e.target.id==='budget')save('budget',e.target.value);if(e.target.id==='chat-draft')save('draft-'+data.run.id,e.target.value);if(e.target.id==='palette-query'){paletteIndex=0;paletteResults();}});
document.addEventListener('change',e=>{if(e.target.id==='report-version')selectVersion(e.target.value);});
document.addEventListener('submit',e=>{if(e.target.id!=='screen-form')return;e.preventDefault();const minimums={};for(const [id,key] of [['screen-revenue','revenue_yoy'],['screen-profit','attributable_profit_yoy']]){const value=document.getElementById(id).value;if(value!=='')minimums[key]=Number(value);}emit('screen',{as_of:$('#screen-date').value,minimums,basis:$('#screen-basis').value,currency:$('#screen-currency').value,scope:$('#screen-scope').value});});
document.addEventListener('keydown',e=>{
  const typing=['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName);
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();openPalette();}
  if((e.ctrlKey||e.metaKey)&&e.key==='Enter'&&e.target.id==='chat-draft'&&!data.preview){e.preventDefault();document.querySelector('[data-action="chat"]').click();}
  if(!typing&&!$('#palette').open&&e.key.toLowerCase()==='n')emit('new');
  if($('#palette').open&&['ArrowDown','ArrowUp','Enter'].includes(e.key)){e.preventDefault();const rows=$('#palette-results').querySelectorAll('.palette-result');if(!rows.length)return;if(e.key==='Enter')rows[paletteIndex]?.click();else{paletteIndex=(paletteIndex+(e.key==='ArrowDown'?1:-1)+rows.length)%rows.length;paletteResults();rows[paletteIndex]?.scrollIntoView({block:'nearest'});}}
});
window.addEventListener('message',event=>{
  if(event.source!==window.parent||event.data.type!=='streamlit:render')return;
  const next=event.data.args.data;if(!next)return;
  if(pendingEvent&&next.ack===pendingEvent.id){const action=pendingEvent.action;if(!next.notice?.startsWith('操作未执行')){if(action==='chat')save('draft-'+pendingEvent.run_id,'');if(action==='start')save('home','');StudioCockpit.ack(pendingEvent);}pendingEvent=null;interactions.busy(false);clearTimeout(emit.timer);if(next.notice)notify(next.notice);}
  const signature=JSON.stringify(next);if(signature===lastSignature){resize();return;}lastSignature=signature;
  const oldView=data?.view,oldLatest=Object.keys(data?.run?.versions||{}).at(-1),changed=currentRun!==next.run?.id;
  if(!changed&&version===oldLatest)version=Object.keys(next.run?.versions||{}).at(-1);
  data=next;
  if(changed){currentRun=data.run?.id;version=getSaved('version-'+currentRun,Object.keys(data.run?.versions||{}).at(-1));inspector='chat';focusedEvidence=null;mobileInspector=false;}
  if(data.run&&!data.run.versions[version])version=Object.keys(data.run.versions).at(-1);
  renderHistory();renderMain(!changed&&oldView===data.view,changed||oldView!==data.view?'page':'none');resize();
});
for(const node of document.querySelectorAll('[data-icon]'))node.innerHTML=svg(node.dataset.icon);
const width=Number(getSaved('panel-width'));if(width>=280&&width<=550)document.documentElement.style.setProperty('--side',width+'px');
window.addEventListener('resize',resize);post('streamlit:componentReady',{apiVersion:1});resize();
