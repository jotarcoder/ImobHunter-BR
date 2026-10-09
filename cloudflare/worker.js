const CORS = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS", "Access-Control-Allow-Headers": "Content-Type,Authorization", "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" };
const json = (data, status=200) => new Response(JSON.stringify(data), {status, headers:CORS});
const hex = (bytes) => [...bytes].map(b=>b.toString(16).padStart(2,"0")).join("").toUpperCase();
const randomHex = (n=32) => { const b=new Uint8Array(n); crypto.getRandomValues(b); return hex(b); };
const hashKey = async (key) => hex(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(key.trim().toUpperCase()))));
const isoNow = () => new Date().toISOString();
const addMonths = (date, months) => { const d=new Date(date); d.setUTCMonth(d.getUTCMonth()+months); return d.toISOString(); };
async function audit(env, actor, action, userId, detail={}) { await env.DB.prepare("INSERT INTO audit_log(actor,action,user_id,detail,created_at) VALUES(?,?,?,?,?)").bind(actor,action,userId||null,JSON.stringify(detail),isoNow()).run(); }
function admin(request, env) { return Boolean(env.ADMIN_TOKEN) && request.headers.get("Authorization")==="Bearer "+env.ADMIN_TOKEN; }
async function body(request) { try { return await request.json(); } catch { return {}; } }
function adminPage() { return `<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ImobHunter · Administração</title><style>
:root{color-scheme:dark;--bg:#07111b;--panel:#0d1b28;--line:#1d3548;--green:#35ff77;--muted:#8ba1b3}*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at top,#10283a,var(--bg) 60%);color:#eef6fb;font:15px system-ui,Segoe UI,sans-serif}main{max-width:1200px;margin:auto;padding:32px 20px}h1{margin:0;font-size:28px}p{color:var(--muted)}.row{display:flex;gap:10px;flex-wrap:wrap}.panel{background:#0d1b28;border:1px solid var(--line);border-radius:16px;padding:18px;margin:18px 0}input,select,button{border:1px solid #29445a;background:#081521;color:#f5f9fb;padding:11px 12px;border-radius:9px;font:inherit}input,select{min-width:160px;flex:1}button{cursor:pointer;font-weight:700}button.primary{background:var(--green);color:#04110a;border-color:var(--green)}button.danger{border-color:#a84848;color:#ff9b9b}table{border-collapse:collapse;width:100%;min-width:780px}th,td{text-align:left;padding:12px;border-bottom:1px solid var(--line);vertical-align:top}th{color:#9cb1c0;font-size:12px;text-transform:uppercase}.scroll{overflow:auto}.tag{display:inline-block;padding:4px 8px;border:1px solid var(--line);border-radius:99px;font-size:12px}.hidden{display:none}.note{white-space:pre-wrap;overflow-wrap:anywhere;color:var(--green)}small{color:var(--muted)}@media(max-width:600px){main{padding:18px 12px}}</style><main><header><h1>ImobHunter <span style="color:var(--green)">/ Admin</span></h1><p>Controle de clientes, chaves e planos · acesso restrito</p></header>
<section class="panel" id="login"><h2>Acesso administrativo</h2><p>Use o token administrativo configurado como segredo do Worker. Ele não fica gravado no sistema.</p><div class="row"><input id="token" type="password" placeholder="Token administrativo" autocomplete="current-password"><button class="primary" onclick="connect()">Entrar</button></div></section>
<div id="app" class="hidden"><section class="panel"><h2>Novo cliente / emitir chave</h2><div class="row"><input id="name" placeholder="Nome do cliente"><input id="email" type="email" placeholder="E-mail (opcional)"><select id="plan"><option value="monthly">Mensal · R$ 3.000</option><option value="annual">Anual · R$ 20.000</option></select><button class="primary" onclick="createClient()">Criar cliente e gerar chave</button></div><p><small>A chave completa só é mostrada nesta emissão. Guarde-a com segurança e entregue ao cliente após confirmar o pagamento.</small></p><div id="newkey" class="note"></div></section>
<section class="panel"><div class="row" style="align-items:center;justify-content:space-between"><h2>Clientes e licenças</h2><button onclick="loadClients()">Atualizar lista</button></div><div class="scroll"><table><thead><tr><th>ID / Cliente</th><th>Plano</th><th>Status</th><th>Validade</th><th>Ações</th></tr></thead><tbody id="clients"></tbody></table></div></section>
<section class="panel"><h2>Auditoria recente</h2><div class="scroll"><table><thead><tr><th>Data</th><th>Admin</th><th>Ação</th><th>ID usuário</th><th>Detalhes</th></tr></thead><tbody id="audit"></tbody></table></div></section></div><p id="msg" role="status"></p></main>
<script>let token=sessionStorage.getItem('ih_admin_token')||'';const el=id=>document.getElementById(id);async function api(path,method='GET',data){const r=await fetch(path,{method,headers:{'Authorization':'Bearer '+token,'Content-Type':'application/json'},body:data?JSON.stringify(data):undefined});const j=await r.json();if(!r.ok)throw Error(j.error||'Falha HTTP '+r.status);return j}function say(s){el('msg').textContent=s}async function connect(){token=el('token').value.trim();try{await loadClients();sessionStorage.setItem('ih_admin_token',token);el('login').classList.add('hidden');el('app').classList.remove('hidden');say('Acesso autorizado.')}catch(e){say('Não foi possível entrar: '+e.message)}}async function loadClients(){const j=await api('/api/admin/clients');el('clients').innerHTML=j.clients.map(c=>'<tr><td><b>'+esc(c.name)+'</b><br><small>'+esc(c.user_id)+'</small><br><small>'+esc(c.email||'')+'</small></td><td>'+esc(c.plan_label)+'</td><td><span class="tag">'+esc(c.status)+'</span></td><td>'+esc(c.expires_at||'—')+'</td><td><div class="row"><button onclick="toggleClient(\''+c.user_id+'\',\''+(c.status==='active'?'deactivate':'activate')+'\')">'+(c.status==='active'?'Desativar':'Ativar')+'</button><button onclick="renewKey(\''+c.user_id+'\')">Trocar chave</button><button onclick="changePlan(\''+c.user_id+'\')">Plano</button><button class="danger" onclick="deleteClient(\''+c.user_id+'\')">Excluir</button></div></td></tr>').join('')||'<tr><td colspan="5">Nenhum cliente cadastrado.</td></tr>';const a=await api('/api/admin/audit');el('audit').innerHTML=a.events.map(e=>'<tr><td>'+esc(e.created_at)+'</td><td>'+esc(e.actor)+'</td><td>'+esc(e.action)+'</td><td>'+esc(e.user_id||'—')+'</td><td>'+esc(e.detail||'')+'</td></tr>').join('')}function esc(v){return String(v??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}async function createClient(){try{const j=await api('/api/admin/clients','POST',{name:el('name').value,email:el('email').value,plan:el('plan').value});el('newkey').textContent='ID DO USUÁRIO: '+j.user_id+'\nCHAVE HEXADECIMAL (exibida uma única vez): '+j.activation_key+'\nPlano: '+j.plan_label+'\nValidade: '+j.expires_at+'\nCopie e guarde agora.';el('name').value='';el('email').value='';await loadClients();say('Cliente criado. A licença ainda precisa ser ativada pelo painel.')}catch(e){say(e.message)}}async function toggleClient(id,action){try{await api('/api/admin/clients/'+encodeURIComponent(id)+'/'+action,'POST',{});await loadClients();say('Status atualizado.')}catch(e){say(e.message)}}async function renewKey(id){if(!confirm('Revogar a chave atual e emitir outra?'))return;try{const j=await api('/api/admin/clients/'+encodeURIComponent(id)+'/rotate-key','POST',{});alert('NOVA CHAVE (copie agora):\n'+j.activation_key);await loadClients()}catch(e){say(e.message)}}async function changePlan(id){const plan=prompt('Digite monthly ou annual');if(!['monthly','annual'].includes(plan))return;try{await api('/api/admin/clients/'+encodeURIComponent(id)+'/plan','PATCH',{plan});await loadClients();say('Plano alterado.')}catch(e){say(e.message)}}async function deleteClient(id){if(!confirm('Excluir/arquivar este cliente e revogar o acesso?'))return;try{await api('/api/admin/clients/'+encodeURIComponent(id),'DELETE');await loadClients();say('Cliente arquivado e licença revogada.')}catch(e){say(e.message)}}if(token){el('token').value=token;connect()}</script></html>`; }
export default {
 async fetch(request, env) {
  if(request.method==="OPTIONS") return new Response(null,{status:204,headers:CORS});
  const url=new URL(request.url), path=url.pathname;
  if(path==="/health") return json({ok:true,service:"imobhunter-license",time:isoNow()});
  if(path==="/admin") return new Response(adminPage(),{headers:{"Content-Type":"text/html; charset=utf-8","Cache-Control":"no-store","Content-Security-Policy":"default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"}});
  if(path==="/api/license/activate" && request.method==="POST"){
   const b=await body(request), userId=String(b.user_id||"").trim(), key=String(b.activation_key||"").trim().toUpperCase();
   if(!/^[0-9a-f-]{36}$/i.test(userId)||!/^[0-9A-F]{64}$/.test(key)) return json({ok:false,error:"ID de usuário ou chave inválidos."},400);
   const digest=await hashKey(key), row=await env.DB.prepare("SELECT user_id,status,plan,expires_at,deleted_at FROM licenses WHERE user_id=? AND key_hash=?").bind(userId,digest).first();
   if(!row||row.deleted_at||row.status!=="active"||!row.expires_at||Date.parse(row.expires_at)<=Date.now()) return json({ok:false,authorized:false,error:"Licença não autorizada. Entre em contato com +55 (11) 99903-7737 para obter a ativação."},403);
   await env.DB.prepare("UPDATE licenses SET last_seen_at=? WHERE user_id=?").bind(isoNow(),userId).run();
   return json({ok:true,authorized:true,user_id:userId,plan:row.plan,expires_at:row.expires_at,checked_at:isoNow()});
  }
  if(path.startsWith("/api/admin/")){
   if(!admin(request,env)) return json({error:"Acesso administrativo não autorizado."},401);
   const actor="admin-token";
   if(path==="/api/admin/clients"&&request.method==="GET"){
    const rows=await env.DB.prepare("SELECT user_id,name,email,plan,status,expires_at,created_at FROM licenses WHERE deleted_at IS NULL ORDER BY created_at DESC").all();
    return json({clients:(rows.results||[]).map(r=>({...r,plan_label:r.plan==="annual"?"Anual · R$ 20.000":"Mensal · R$ 3.000"}))});
   }
   if(path==="/api/admin/clients"&&request.method==="POST"){
    const b=await body(request), name=String(b.name||"").trim(), email=String(b.email||"").trim(), plan=b.plan==="annual"?"annual":"monthly";
    if(name.length<2||name.length>160||email.length>254) return json({error:"Informe um nome válido e e-mail de até 254 caracteres."},400);
    const userId=crypto.randomUUID(), key=randomHex(32), now=isoNow(), expires=addMonths(now,plan==="annual"?12:1), digest=await hashKey(key);
    await env.DB.prepare("INSERT INTO licenses(user_id,name,email,plan,status,key_hash,created_at,updated_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?)").bind(userId,name,email||null,plan,"pending",digest,now,now,expires).run();
    await audit(env,actor,"client_created",userId,{plan,expires_at:expires});
    return json({user_id:userId,activation_key:key,plan_label:plan==="annual"?"Anual · R$ 20.000":"Mensal · R$ 3.000",expires_at:expires,status:"pending"},201);
   }
   if(path==="/api/admin/audit"&&request.method==="GET"){
    const r=await env.DB.prepare("SELECT actor,action,user_id,detail,created_at FROM audit_log ORDER BY id DESC LIMIT 100").all();return json({events:r.results||[]});
   }
   const m=path.match(/^\/api\/admin\/clients\/([0-9a-f-]+)(?:\/(activate|deactivate|rotate-key|plan))?$/i);
   if(m){const id=m[1], action=m[2];
    const existing=await env.DB.prepare("SELECT user_id,status,deleted_at,plan FROM licenses WHERE user_id=?").bind(id).first();
    if(!existing) return json({error:"Cliente não encontrado."},404);
    if(request.method==="DELETE"&&!action){await env.DB.prepare("UPDATE licenses SET status='revoked',deleted_at=?,updated_at=? WHERE user_id=?").bind(isoNow(),isoNow(),id).run();await audit(env,actor,"client_archived",id,{});return json({ok:true});}
    if(request.method==="POST"&&action==="activate"){
     if(existing.deleted_at) return json({error:"Cliente arquivado. Crie novo cadastro para reativar."},409);
     await env.DB.prepare("UPDATE licenses SET status='active',updated_at=? WHERE user_id=?").bind(isoNow(),id).run();await audit(env,actor,"license_activated",id,{});return json({ok:true,status:"active"});
    }
    if(request.method==="POST"&&action==="deactivate"){
     await env.DB.prepare("UPDATE licenses SET status='suspended',updated_at=? WHERE user_id=?").bind(isoNow(),id).run();await audit(env,actor,"license_suspended",id,{});return json({ok:true,status:"suspended"});
    }
    if(request.method==="POST"&&action==="rotate-key"){
     if(existing.deleted_at) return json({error:"Cliente arquivado."},409);
     const key=randomHex(32), digest=await hashKey(key);await env.DB.prepare("UPDATE licenses SET key_hash=?,status='pending',updated_at=? WHERE user_id=?").bind(digest,isoNow(),id).run();await audit(env,actor,"key_rotated",id,{});return json({ok:true,activation_key:key,status:"pending"});
    }
    if(request.method==="PATCH"&&action==="plan"){
     const b=await body(request);if(!["monthly","annual"].includes(b.plan))return json({error:"Plano inválido."},400);
     const expires=addMonths(isoNow(),b.plan==="annual"?12:1);await env.DB.prepare("UPDATE licenses SET plan=?,expires_at=?,updated_at=? WHERE user_id=?").bind(b.plan,expires,isoNow(),id).run();await audit(env,actor,"plan_changed",id,{plan:b.plan,expires_at:expires});return json({ok:true,plan:b.plan,expires_at:expires});
    }
   }
   return json({error:"Rota administrativa não encontrada."},404);
  }
  return json({error:"Não encontrado."},404);
 }
};