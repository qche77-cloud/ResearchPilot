const config = require('../config');
const storageKey = 'rp_mini_session_v1';
function token() { return wx.getStorageSync(storageKey) || ''; }
function clear() { wx.removeStorageSync(storageKey); }
function call(path, method = 'GET', data, requestKey) {
  return new Promise((resolve, reject) => {
    if (config.mode === 'wechat' && !/^https:\/\//.test(config.apiBase)) {
      reject(new Error('正式模式必须配置 HTTPS API 地址')); return;
    }
    const header = {'Content-Type': 'application/json'};
    if (token()) header.Authorization = 'Bearer ' + token();
    if (requestKey) header['Idempotency-Key'] = requestKey;
    wx.request({url: config.apiBase.replace(/\/$/, '') + path, method, data, header, timeout: 20000,
      success(response) {
        if (response.statusCode >= 200 && response.statusCode < 300) resolve(response.data);
        else {
          if (response.statusCode === 401) clear();
          const error = new Error(response.data && response.data.error ? response.data.error.message : '服务暂不可用');
          error.status = response.statusCode; reject(error);
        }
      },
      fail() { reject(new Error('暂时无法连接服务，请检查网络后重试')); }
    });
  });
}
function saveLogin(result) {
  if (!result.token || result.mode !== config.mode) throw new Error('服务端模式与小程序配置不一致');
  wx.setStorageSync(storageKey, result.token);
  return result;
}
async function login(invitation = '') {
  if (config.mode === 'demo') return saveLogin(await call('/v1/auth/demo', 'POST', {identity: config.demoIdentity || 'A'}));
  const code = await new Promise((resolve, reject) => wx.login({success(r) { r.code ? resolve(r.code) : reject(new Error('未获得微信登录凭证')); }, fail() { reject(new Error('微信登录暂不可用')); }}));
  return saveLogin(await call('/v1/auth/wechat', 'POST', {code, invitation}));
}
function requireLogin() {
  if (token()) return true;
  wx.navigateTo({url: '/pages/login/index'}); return false;
}
function key() { return 'mini_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2); }
function source(url) {
  if (!/^https?:\/\//i.test(url || '')) { wx.showToast({title: '此证据没有可用来源链接', icon: 'none'}); return; }
  wx.setClipboardData({data: url});
}
module.exports = {call, login, token, clear, requireLogin, key, source, config};
