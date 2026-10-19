const api=require('../../utils/api');
Page({
  data:{demo:api.config.mode==='demo',items:[],adding:false,symbol:'',name:'',busy:false,error:''},
  onShow(){if(api.requireLogin())this.load();},
  async load(){try{const result=await api.call('/v1/watchlist');this.setData({items:result.items,error:''});}catch(error){this.setData({error:error.message});}},
  add(){this.setData({adding:!this.data.adding,error:''});},
  symbol(e){this.setData({symbol:e.detail.value});},name(e){this.setData({name:e.detail.value});},
  open(e){wx.navigateTo({url:'/pages/company/index?symbol='+encodeURIComponent(e.currentTarget.dataset.symbol)+'&name='+encodeURIComponent(e.currentTarget.dataset.name)});},
  async save(){if(this.data.busy)return;this.setData({busy:true,error:''});try{await api.call('/v1/watchlist','POST',{symbol:this.data.symbol,name:this.data.name});this.setData({adding:false,symbol:'',name:''});await this.load();}catch(error){this.setData({error:error.message});}finally{this.setData({busy:false});}},
  async remove(e){
    const symbol=e.currentTarget.dataset.symbol;
    wx.showModal({title:'移除自选公司',content:'仅移除自选关联，研究历史仍然保留。',success:async result=>{if(result.confirm){try{await api.call('/v1/watchlist/'+symbol,'DELETE');await this.load();}catch(error){this.setData({error:error.message});}}}});
  }
});
