// Device-flow relay for the radar's single GitHub App. No GitHub credential is
// stored here. The only supported browser origin is the radar itself.
const ORIGIN = 'https://terms.aifluxor.com';
const REPOSITORY_ID = '1442743892';
const GITHUB_APP_CLIENT_ID = 'Iv23li7T0QK7PzoDBPVq'; // Public app identifier, not a secret.
const headers = {
  'Access-Control-Allow-Origin': ORIGIN,
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'content-type',
  'Cache-Control': 'no-store',
  'Content-Type': 'application/json; charset=utf-8',
  'X-Content-Type-Options': 'nosniff',
  'Vary': 'Origin',
};
const reply = (body, status = 200) => new Response(JSON.stringify(body), {status, headers});

export default {
  async fetch(request) {
    if (request.headers.get('Origin') !== ORIGIN) return new Response('Forbidden', {status: 403});
    if (request.method === 'OPTIONS') return new Response(null, {status: 204, headers});
    if (request.method !== 'POST') return reply({error: 'method_not_allowed'}, 405);
    const path = new URL(request.url).pathname;
    if (path !== '/start' && path !== '/poll') return reply({error: 'not_found'}, 404);
    const params = new URLSearchParams({client_id: GITHUB_APP_CLIENT_ID});
    if (path === '/poll') {
      if (Number(request.headers.get('Content-Length') || '0') > 1024) return reply({error:'bad_request'},400);
      let payload;
      try { payload = await request.json(); } catch { return reply({error:'bad_request'},400); }
      if (typeof payload.device_code !== 'string' || !/^[a-zA-Z0-9_-]{20,200}$/.test(payload.device_code)) return reply({error:'bad_request'},400);
      params.set('device_code', payload.device_code);
      params.set('grant_type', 'urn:ietf:params:oauth:grant-type:device_code');
      params.set('repository_id', REPOSITORY_ID);
    }
    try {
      const response = await fetch('https://github.com' + (path === '/start' ? '/login/device/code' : '/login/oauth/access_token'), {
        method: 'POST', headers: {'Accept':'application/json','Content-Type':'application/x-www-form-urlencoded'}, body: params,
      });
      const data = await response.json();
      if (!response.ok) return reply({error:'github_unavailable'},502);
      if (path === '/start') return reply({device_code:data.device_code,user_code:data.user_code,verification_uri:data.verification_uri,expires_in:data.expires_in,interval:data.interval,error:data.error});
      // Do not expose or persist a long-lived refresh token.
      return reply({access_token:data.access_token,expires_in:data.expires_in,error:data.error,interval:data.interval});
    } catch {
      return reply({error:'github_unavailable'},502);
    }
  },
};
