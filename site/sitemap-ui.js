// Public read-only report plus optional direct GitHub configuration management.
(() => {
  let shown = 50, managed = null;
  const byId = id => document.getElementById(id);
  const encode = value => encodeURIComponent(value);
  const fmt = value => { const d = new Date(value); return isNaN(d) ? '时间未知' : d.toLocaleString('zh-CN', {timeZone:'Asia/Taipei', hour12:false}); };
  function external(url, text) { return '<a href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">'+esc(text)+' ↗</a>'; }
  function render() {
    if (!data) return;
    const rows = Array.isArray(data.sitemap_pages) ? data.sitemap_pages : [];
    const sites = Array.isArray(data.competitors) ? data.competitors : [];
    const states = new Map((data.sources || []).filter(s => s.id.startsWith('sitemap:')).map(s => [s.id.slice(8), s]));
    const selected = byId('pageSite').value;
    byId('pageSite').innerHTML = '<option value="">所有同行</option>' + sites.map(s => '<option value="'+esc(s.id)+'">'+esc(s.id)+'</option>').join('');
    byId('pageSite').value = selected;
    const q = byId('pageSearch').value.trim().toLowerCase();
    const filtered = rows.filter(r => (!selected || r.site === selected) && (!q || (String(r.candidate||'')+' '+String(r.url||'')).toLowerCase().includes(q)));
    byId('pageBadge').textContent = '本次新发现 '+(data.sitemap_new_count ?? '—')+' 条';
    byId('pageRows').innerHTML = filtered.length ? filtered.slice(0,shown).map(r => {
      const term = String(r.candidate||'').trim();
      const u = safeUrl(r.url), sitemap = safeUrl(r.sitemap);
      const trend = date => 'https://trends.google.com/trends/explore?date='+encode(date)+'&q='+encode(term);
      const search = 'https://www.google.com/search?q='+encode(term);
      return '<tr><td><span class="term">'+esc(term || '无法从网址提取')+'</span><span class="subterm">未经需求验证</span></td><td>'+esc(r.site)+'<span class="subterm">'+esc(fmt(r.first_seen))+'</span>'+(sitemap?external(sitemap,'内容清单'):'')+'</td><td class="page-url">'+(u?external(u,u):'链接不可用')+'</td><td><div class="candidate-links">'+(term?[external(trend('now 7-d'),'趋势 7 天'),external(trend('today 1-m'),'30 天'),external(trend('today 3-m'),'90 天'),external(search,'Google 搜索')].join(''):'请打开原始网址人工提取')+'</div></td></tr>';
    }).join('') : '<tr><td colspan="4" class="empty">'+(data.version >= 2 ? '目前没有符合条件的新增网址。新监控的网站需先建立对照，等下次采集才能判断新增。' : '新版采集尚未发布，请等首次更新。')+'</td></tr>';
    byId('pageFoot').textContent = '显示 '+Math.min(filtered.length,shown)+' / '+filtered.length+' 条 · 首次发现时间不等于网页发布时间 · 候选词和搜索需求均需人工验证'+(data.sitemap_truncated?' · 记录较多，仅保留最近 5,000 条':'');
    byId('morePages').hidden = filtered.length <= shown;
    byId('competitorBadge').textContent = sites.length ? sites.length+' 个监控项' : '等待新版采集';
    byId('competitorRows').innerHTML = sites.length ? sites.map(s => {
      const status = states.get(s.id) || {}, u = safeUrl(s.index);
      const labels = {ok:'正常',baseline:'建立对照',partial:'部分建立对照',error:'采集失败',disabled:'已暂停'};
      const title = status.message || (status.status === 'baseline' ? '首次记录，等待下一次对比' : '');
      return '<tr><td><span class="term">'+esc(s.id)+'</span></td><td class="page-url">'+(u?external(u,u):'地址不可用')+'</td><td><span class="pill '+(status.status==='error'?'failed':status.status==='baseline'||status.status==='partial'?'warning':'ok')+'" title="'+esc(title)+'">'+esc(labels[status.status]||'未知')+'</span>'+(title?'<span class="subterm" title="'+esc(title)+'">'+esc(title)+'</span>':'')+'</td><td>'+esc(status.count ?? '—')+' 条</td></tr>';
    }).join('') : '<tr><td colspan="4" class="empty">新版采集完成后会显示当前名单。</td></tr>';
  }
  const originalDisplay = display;
  display = function(){ originalDisplay(); render(); };
  byId('pageSearch').addEventListener('input', () => {shown=50;render();});
  byId('pageSite').addEventListener('change', () => {shown=50;render();});
  byId('morePages').addEventListener('click', () => {shown+=50;render();});
  const endpoint = 'https://api.github.com/repos/seekitx/new-term-radar-free-data/contents/free-config.json';
  const setStatus = text => { byId('managerStatus').textContent=text; };
  function validAddress(address){
    let url;try{url=new URL(address);}catch{throw Error('请输入完整的 Sitemap 地址。');}
    if(url.protocol!=='https:'||url.username||url.password||!url.hostname.includes('.')||/^(localhost|127\.|10\.|192\.168\.|169\.254\.|0\.|\[)/i.test(url.hostname))throw Error('请使用公开网站的 HTTPS 地址。');
    return url.href;
  }
  function headers() {
    const token = byId('ghToken').value.trim();
    if (!token) throw Error('请先填写 GitHub 个人访问令牌。');
    return {'Accept':'application/vnd.github+json','Authorization':'Bearer '+token,'X-GitHub-Api-Version':'2022-11-28'};
  }
  async function readConfig(){
    const response=await fetch(endpoint+'?ref=main',{headers:headers(),cache:'no-store'});
    if(!response.ok)throw Error('读取名单失败（HTTP '+response.status+'），请检查令牌和仓库权限。');
    const file=await response.json();
    const bytes=Uint8Array.from(atob(file.content.replace(/\s/g,'')),c=>c.charCodeAt(0));
    const config=JSON.parse(new TextDecoder().decode(bytes));
    if(!config.sitemaps || Array.isArray(config.sitemaps)) throw Error('名单格式异常，未修改。');
    return {config,sha:file.sha};
  }
  async function save(change, message){
    setStatus('正在读取最新名单…');
    const current=await readConfig();
    change(current.config.sitemaps);
    const bytes=new TextEncoder().encode(JSON.stringify(current.config,null,2)+'\n');
    let binary=''; for(const byte of bytes)binary+=String.fromCharCode(byte);
    setStatus('正在保存…');
    const response=await fetch(endpoint,{method:'PUT',headers:{...headers(),'Content-Type':'application/json'},body:JSON.stringify({message,content:btoa(binary),sha:current.sha,branch:'main'})});
    if(!response.ok)throw Error('保存失败（HTTP '+response.status+'）。名单可能被同时修改，请重新读取后再试。');
    managed=current.config.sitemaps;
    renderManager();
    setStatus('已保存到 GitHub，下一次自动采集时生效。新增或调整范围后会先建立对照。');
  }
  function renderManager(){
    const target=byId('managedList');target.textContent='';
    Object.entries(managed || {}).forEach(([id,entry])=>{
      const row=document.createElement('div');row.style.cssText='padding:10px 0;border-bottom:1px solid #edf1ec;display:flex;gap:8px;align-items:center;flex-wrap:wrap';
      const title=document.createElement('span');title.textContent=id+' · '+(entry.enabled===false?'已暂停':'监控中');title.style.flex='1';row.append(title);
      const edit=document.createElement('button');edit.className='btn';edit.textContent='修改地址';edit.onclick=()=>{try{const address=prompt('填写该同行的 Sitemap 地址：',entry.index || '');if(address===null)return;const index=validAddress(address.trim());const pattern=prompt('填写内容子清单筛选规则；留空则自动选择：',entry.shards || '');if(pattern===null)return;if(pattern.length>200)throw Error('筛选规则过长，请控制在 200 字以内。');save(sites=>{if(!sites[id])throw Error('该同行已不存在，请重新读取。');sites[id].index=index;if(pattern.trim())sites[id].shards=pattern.trim();else delete sites[id].shards;},'更新同行监控地址').catch(e=>setStatus(e.message));}catch(e){setStatus(e.message);}};row.append(edit);
      const toggle=document.createElement('button');toggle.className='btn';toggle.textContent=entry.enabled===false?'启用':'暂停';toggle.onclick=()=>save(sites=>{if(!sites[id])throw Error('该同行已不存在，请重新读取。');sites[id].enabled=sites[id].enabled===false;},'更新同行监控状态').catch(e=>setStatus(e.message));row.append(toggle);
      const del=document.createElement('button');del.className='btn danger';del.textContent='移除';del.onclick=()=>{if(confirm('确定从每日监控中移除 '+id+'？已发现的近期明细仍会保留到保存期限结束。'))save(sites=>{if(!sites[id])throw Error('该同行已不存在，请重新读取。');delete sites[id];},'移除同行监控').catch(e=>setStatus(e.message));};row.append(del);target.append(row);
    });
  }
  byId('manageLoad').onclick=async()=>{try{setStatus('正在读取…');const r=await readConfig();managed=r.config.sitemaps;renderManager();setStatus('名单已读取，可以添加、暂停或移除同行。');}catch(e){setStatus(e.message);}};
  byId('manageAdd').onclick=async()=>{try{
    const id=byId('newSiteName').value.trim(), address=byId('newSiteUrl').value.trim(), pattern=byId('newSitePattern').value.trim();
    if(!/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,59}$/.test(id))throw Error('请填写正确的同行名称，只能使用英文字母、数字、点、短横线和下划线。');
    const url=validAddress(address);
    if(pattern.length>200)throw Error('筛选规则过长，请控制在 200 字以内。');
    await save(sites=>{if(Object.hasOwn(sites,id))throw Error('同行名称已经存在，请换一个名称。');sites[id]={index:url,pause:3,...(pattern?{shards:pattern}:{})};},'添加同行监控');
    byId('newSiteName').value='';byId('newSiteUrl').value='';byId('newSitePattern').value='';
  }catch(e){setStatus(e.message);}};
  if(data)render();
})();
