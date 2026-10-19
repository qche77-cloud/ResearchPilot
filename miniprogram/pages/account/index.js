const api=require('../../utils/api');
Page({
  data:{demo:api.config.mode==='demo',me:null,error:'',largeText:false},
  onShow(){this.setData({largeText:wx.getStorageSync('rp_mini_reading_large')==='1'});if(api.requireLogin())this.load();},
  reading(){const largeText=!this.data.largeText;wx.setStorageSync('rp_mini_reading_large',largeText?'1':'0');this.setData({largeText});},
  async load(){try{this.setData({me:await api.call('/v1/me'),error:''});}catch(error){this.setData({error:error.message});}},
  async logout(){try{await api.call('/v1/auth/logout','POST');}catch(error){this.setData({error:error.message});return;}api.clear();wx.navigateTo({url:'/pages/login/index'});}
});
