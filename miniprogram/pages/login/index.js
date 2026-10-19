const api = require('../../utils/api');
Page({
  data: {demo:api.config.mode === 'demo', invitation:'',busy:false,error:''},
  invitation(e) { this.setData({invitation:e.detail.value}); },
  async login() {
    if (this.data.busy) return;
    this.setData({busy:true,error:''});
    try { await api.login(this.data.invitation.trim()); wx.switchTab({url:'/pages/home/index'}); }
    catch (error) { this.setData({error:error.message}); }
    finally { this.setData({busy:false}); }
  }
});
