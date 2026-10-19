const api = require('../../utils/api');
const fmt = require('../../utils/format');
Page({
  data:{demo:api.config.mode==='demo',me:null,runs:[],visibleRuns:[],total:0,query:'',filter:'all',error:'',busy:false,creating:false,topic:'',budget:2,budgets:[2,3,4,5,6],requestKey:''},
  onShow() { if (api.requireLogin()) this.load(); },
  async load() {
    this.setData({busy:true,error:''});
    try {
      const [me, history] = await Promise.all([api.call('/v1/me'),api.call('/v1/runs')]);
      this.setData({me,total:history.total,runs:history.items.map(r=>Object.assign({},r,{time:fmt.date(r.updated_at)})),budgets:Array.from({length:me.max_searches-1},(_,i)=>i+2)});
      this.filterRuns();
    } catch(error) { this.setData({error:error.message}); }
    finally { this.setData({busy:false}); }
  },
  async more(){
    if(this.data.busy)return;this.setData({busy:true,error:''});
    try{const history=await api.call('/v1/runs?limit=20&offset='+this.data.runs.length);const ids=new Set(this.data.runs.map(r=>r.id));this.setData({total:history.total,runs:this.data.runs.concat(history.items.filter(r=>!ids.has(r.id)).map(r=>Object.assign({},r,{time:fmt.date(r.updated_at)})))});this.filterRuns();}
    catch(error){this.setData({error:error.message});}finally{this.setData({busy:false});}
  },
  open(e) { wx.navigateTo({url:'/pages/task/index?id='+encodeURIComponent(e.currentTarget.dataset.id)}); },
  filterRuns(){const query=this.data.query.toLowerCase(),filter=this.data.filter;this.setData({visibleRuns:this.data.runs.filter(r=>(!query||r.topic.toLowerCase().includes(query))&&(filter==='all'||filter==='active'&&r.active||filter==='completed'&&r.completed))});},
  search(e){this.setData({query:e.detail.value});this.filterRuns();},
  selectFilter(e){this.setData({filter:e.currentTarget.dataset.filter});this.filterRuns();},
  newResearch() { this.setData({creating:true,requestKey:this.data.requestKey||api.key(),error:''}); },
  quick(e){this.setData({creating:true,topic:e.currentTarget.dataset.topic,requestKey:api.key(),error:''});},
  close() { if(!this.data.submitting) this.setData({creating:false}); },
  stop() {},
  topic(e) { this.setData({topic:e.detail.value,requestKey:api.key()}); },
  budget(e) { this.setData({budget:this.data.budgets[Number(e.detail.value)],requestKey:api.key()}); },
  template(e) { this.setData({topic:e.currentTarget.dataset.topic,requestKey:api.key()}); },
  async submit() {
    if(this.data.submitting || !this.data.topic.trim()) return;
    this.setData({submitting:true,error:''});
    try {
      const run = await api.call('/v1/runs','POST',{topic:this.data.topic,budget:this.data.budget},this.data.requestKey);
      this.setData({creating:false,topic:'',requestKey:''}); wx.navigateTo({url:'/pages/task/index?id='+encodeURIComponent(run.id)});
    } catch(error) { this.setData({error:error.message}); }
    finally { this.setData({submitting:false}); }
  }
});
