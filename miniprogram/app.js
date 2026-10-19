const config = require('./config');
App({
  globalData: {config},
  onLaunch() {
    if (!['demo', 'wechat'].includes(config.mode) ||
        (config.mode === 'wechat' && !/^https:\/\//.test(config.apiBase))) {
      this.globalData.configurationError = '正式模式必须配置 HTTPS API 地址';
    }
  }
});
