const api=require('../../utils/api');
const fmt=require('../../utils/format');
Page({
  data:{demo:api.config.mode==='demo',run:null,report:null,tab:'report',versionIndex:0,versions:[],error:'',busy:false,largeText:false,outlineOpen:false,sourceFocus:''},
  onLoad(query){this.runId=query.id;},
  onShow(){this.visible=true;this.epoch=(this.epoch||0)+1;this.setData({largeText:wx.getStorageSync('rp_mini_reading_large')==='1'});if(api.requireLogin())this.load();},
  onHide(){this.visible=false;this.epoch++;clearTimeout(this.timer);},
  onUnload(){this.onHide();},
  async load(){
    const epoch=this.epoch;
    if(this.loadingEpoch===epoch)return;
    this.loadingEpoch=epoch;clearTimeout(this.timer);
    try{
      const run=await api.call('/v1/runs/'+encodeURIComponent(this.runId));
      if(!this.visible||epoch!==this.epoch)return;
      const previous=this.selectedVersion;
      const versions=run.versions.map((v,i)=>Object.assign({},v,{label:'版本 '+(i+1)+' · '+fmt.date(v.as_of)}));
      const index=Math.max(0,previous?versions.findIndex(v=>v.id===previous):versions.length-1);
      this.setData({run:Object.assign({},run,{stageLabel:fmt.stage(run.stage),time:fmt.date(run.updated_at),events:run.events.map((e,i)=>Object.assign({},e,{position:i+1}))}),versions,versionIndex:index,error:''});
      if(versions.length){this.selectedVersion=versions[index].id;await this.loadReport();}
    }catch(error){if(this.visible&&epoch===this.epoch)this.setData({error:error.message});}
    finally{if(this.loadingEpoch===epoch)this.loadingEpoch=null;if(this.visible&&epoch===this.epoch&&this.data.run&&this.data.run.active)this.timer=setTimeout(()=>this.load(),3000);}
  },
  async loadReport(){
    const version=this.selectedVersion,epoch=this.epoch;
    if(this.data.report && this.data.report.id===version)return;
    try{
      const report=await api.call('/v1/runs/'+encodeURIComponent(this.runId)+'/reports/'+encodeURIComponent(version));
      if(!this.visible||epoch!==this.epoch||version!==this.selectedVersion)return;
      report.sections=report.sections.map((s,i)=>Object.assign({},s,{sectionIndex:i,blocks:fmt.blocks(s.content),citations:Array.from(new Set((s.content.match(/\[(E\d+)\]/g)||[]).map(e=>e.slice(1,-1))))}));
      this.setData({report});
    }catch(error){if(this.visible&&epoch===this.epoch)this.setData({error:error.message});}
  },
  version(e){const index=Number(e.detail.value);this.selectedVersion=this.data.versions[index].id;this.setData({versionIndex:index,report:null});this.loadReport();},
  tab(e){this.setData({tab:e.currentTarget.dataset.tab});},
  reading(){const largeText=!this.data.largeText;wx.setStorageSync('rp_mini_reading_large',largeText?'1':'0');this.setData({largeText});},
  outline(){this.setData({outlineOpen:true});},
  closeOutline(){this.setData({outlineOpen:false});},
  stop(){},
  section(e){this.setData({outlineOpen:false,tab:'report'});const go=()=>wx.pageScrollTo({selector:'#report-section-'+e.currentTarget.dataset.index,offsetTop:-20,duration:180});if(wx.nextTick)wx.nextTick(go);else go();},
  citation(e){const eid=e.currentTarget.dataset.eid;if(!this.data.report.cards.some(c=>c.eid===eid)){wx.showToast({title:'此版本未保存该引用',icon:'none'});return;}this.setData({tab:'sources',sourceFocus:eid});const go=()=>wx.pageScrollTo({selector:'#source-'+eid,offsetTop:-20,duration:180});if(wx.nextTick)wx.nextTick(go);else go();},
  source(e){api.source(e.currentTarget.dataset.url);},
  async command(e){
    if(this.data.busy)return;this.setData({busy:true,error:''});
    try{await api.call('/v1/runs/'+encodeURIComponent(this.runId)+'/commands','POST',{kind:e.currentTarget.dataset.kind});clearTimeout(this.timer);await this.load();}
    catch(error){this.setData({error:error.message});}
    finally{this.setData({busy:false});}
  }
});
