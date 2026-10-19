function date(value) {
  const timestamp=Date.parse(value);
  if(!Number.isFinite(timestamp))return '时间未知';
  const local=new Date(timestamp+8*3600000),two=v=>String(v).padStart(2,'0');
  return local.getUTCFullYear()+'-'+two(local.getUTCMonth()+1)+'-'+two(local.getUTCDate())+' '+two(local.getUTCHours())+':'+two(local.getUTCMinutes());
}
function stage(value) { return ({initialized:'待开始',collecting_market:'采集财务资料',planning:'制定计划',replanning:'调整计划',deciding:'评估证据缺口',searching:'检索资料',reading:'阅读原文',evaluating:'评估证据',synthesizing:'综合分析',writing:'生成报告',completed:'已完成'})[value] || '处理中'; }
function blocks(markdown) {
  return String(markdown || '').split(/\n\s*\n/).filter(Boolean).map((text, i) => {
    let kind = 'paragraph';
    if (/^#{1,6}\s/.test(text)) { kind = 'heading'; text = text.replace(/^#{1,6}\s+/, ''); }
    else if (/^>/.test(text)) { kind = 'quote'; text = text.replace(/^>\s?/gm, ''); }
    // Rich-text node objects keep source strings as text; raw HTML is never executed.
    const nodes = text.split(/(\*\*[^*]+\*\*)/).filter(Boolean).map(t => /^\*\*/.test(t) ?
      {name:'strong',children:[{type:'text',text:t.slice(2,-2)}]} : {type:'text',text:t});
    return {id:i,kind,nodes};
  });
}
function money(record) {
  if (record.status !== 'ok' || record.value == null) return '待核对';
  // Presentation only. The raw value/unit remains visible; no financial derivation in JS.
  return String(record.value);
}
function amount(value){const parts=String(value==null?'—':value).split('.');return parts[0].replace(/\B(?=(\d{3})+(?!\d))/g,',')+(parts.length>1?'.'+parts.slice(1).join('.'):'');}
function basis(value){return ({cumulative:'年初至今累计',single_quarter:'单季度',instant:'期末时点',ttm:'过去十二个月'})[value]||'口径未知';}
function scope(value){return ({consolidated:'合并报表',parent_company:'母公司报表'})[value]||'范围未知';}
function unitLabel(unit,currency){return unit==='percent'?'%':unit==='multiple'?'倍':unit==='currency_unit'?({CNY:'元',USD:'美元',HKD:'港元',EUR:'欧元',JPY:'日元'})[currency]||'货币基本单位':unit||'单位未知';}
module.exports = {date, stage, blocks, money, amount, basis, scope, unitLabel};
