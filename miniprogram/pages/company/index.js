const api=require('../../utils/api');
const fmt=require('../../utils/format');
Page({
  data:{demo:api.config.mode==='demo',name:'',company:null,records:[],metricCards:[],periods:[],groups:[],scopeIndex:0,periodIndex:0,selectedPeriod:'',trend:[],trendLabel:'',inspected:null,error:'',busy:false},
  onLoad(q){this.symbol=q.symbol;this.setData({name:q.name||q.symbol});},
  onShow(){if(api.requireLogin())this.load();},
  async load(){try{const company=await api.call('/v1/companies/'+encodeURIComponent(this.symbol));this.setData({company,error:''});this.arrange();}catch(error){this.setData({error:error.message});}},
  arrange(){
    const company=this.data.company;if(!company)return;
    const all=company.analysis.records.filter(r=>r.status==='ok').map(r=>Object.assign({},r,{display_value:fmt.amount(r.value),display_unit:fmt.unitLabel(r.unit,r.currency)}));
    const keys=Array.from(new Set(all.map(r=>[r.currency,r.basis,r.scope].join('|'))));
    const groups=keys.map(key=>{const parts=key.split('|');return {key,label:parts[0]+' · '+fmt.basis(parts[1])+' · '+fmt.scope(parts[2])};});
    const scopeIndex=this.data.scopeIndex<groups.length?this.data.scopeIndex:0,chosen=keys[scopeIndex];
    const scoped=all.filter(r=>[r.currency,r.basis,r.scope].join('|')===chosen),periods=Array.from(new Set(scoped.map(r=>r.period_end))).sort().reverse();
    const selectedPeriod=periods.includes(this.data.selectedPeriod)?this.data.selectedPeriod:periods[0]||'';
    const records=scoped.filter(r=>r.period_end===selectedPeriod);
    const metricCards=['revenue','attributable_net_profit','net_profit','operating_cash_flow','gross_margin','cost_of_revenue'].map(m=>records.find(r=>r.metric===m)).filter(Boolean).slice(0,4);
    const points=(company.charts.revenue||[]).filter(p=>[p.currency,p.basis,p.scope].join('|')===chosen&&p.period.slice(0,4)===selectedPeriod.slice(0,4)&&Number.isFinite(Number(p.value))).sort((a,b)=>a.period.localeCompare(b.period));
    const sameUnit=points.filter(p=>p.unit===points[0].unit),largest=Math.max(1,...sameUnit.map(p=>Math.abs(Number(p.value))));
    const trend=sameUnit.map(p=>Object.assign({},p,{display_value:fmt.amount(p.value),width:Math.max(0,Number(p.value)/largest*100)}));
    this.setData({records,metricCards,periods,groups,scopeIndex,periodIndex:Math.max(0,periods.indexOf(selectedPeriod)),selectedPeriod,trend,trendLabel:trend.length?fmt.basis(trend[0].basis)+' · '+trend[0].currency+' '+fmt.unitLabel(trend[0].unit,trend[0].currency):''});
  },
  period(e){this.setData({selectedPeriod:this.data.periods[Number(e.detail.value)]});this.arrange();},
  scope(e){this.setData({scopeIndex:Number(e.detail.value),selectedPeriod:''});this.arrange();},
  inspect(e){const record=this.data.company.analysis.records.find(r=>r.id===e.currentTarget.dataset.id);if(!record)return;const raw=record.raw||{};this.setData({inspected:Object.assign({},record,{display_value:fmt.amount(record.value),display_unit:fmt.unitLabel(record.unit,record.currency),basisLabel:fmt.basis(record.basis),scopeLabel:fmt.scope(record.scope),raw_value:raw.value==null?(raw.item_value==null?'未保留':String(raw.item_value)):String(raw.value),fetchedLabel:fmt.date(record.fetched_at)})});},
  close(){this.setData({inspected:null});},stop(){},
  source(e){api.source(e.currentTarget.dataset.url);},
  async research(){if(this.data.busy)return;this.setData({busy:true,error:''});this.requestKey=this.requestKey||api.key();try{const run=await api.call('/v1/runs','POST',{topic:'研究'+this.symbol+'：收入、利润与经营现金流是否一致？',symbol:this.symbol,budget:2},this.requestKey);wx.navigateTo({url:'/pages/task/index?id='+encodeURIComponent(run.id)});}catch(error){this.setData({error:error.message});}finally{this.setData({busy:false});}}
});
