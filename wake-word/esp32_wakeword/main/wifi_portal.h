#pragma once

inline constexpr char kWifiPortalHtml[] = R"PORTAL(<!doctype html>
<html lang="pt-BR">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nuclea - Wi-Fi</title>
<style>
*{box-sizing:border-box}body{margin:0;font:16px system-ui,sans-serif;background:#f4f6f7;color:#19282b}
header{background:#173d35;color:white;padding:20px 24px}header h1{font-size:22px;margin:0}
main{max-width:520px;margin:32px auto;padding:0 24px}label{display:block;margin:20px 0 8px}
input,select,button{font:inherit;width:100%;padding:12px;border:1px solid #aebfc3;border-radius:4px}
input,select{background:white;color:#19282b}button{margin-top:16px;cursor:pointer;background:#176a4a;color:white;border:0}
input{min-width:0}button.secondary{background:#e1e9ed;color:#19282b}button:disabled{opacity:.6;cursor:wait}
.url-row{display:flex;gap:8px;align-items:stretch}.url-row input{flex:1;width:0}
.url-row button{width:auto;margin:0;flex-shrink:0}input:read-only{background:#eaf0ed}
#status{padding:16px 0;line-height:1.5;color:#354f59;overflow-wrap:anywhere}
</style>
<header><h1>Nuclea Wi-Fi</h1></header>
<main>
<form id="config">
<label for="networks">Redes disponiveis</label>
<select id="networks"><option value="">Selecione uma rede</option></select>
<button type="button" class="secondary" id="scan">Atualizar redes</button>
<label for="ssid">Nome da rede</label><input id="ssid" required autocomplete="off">
<label for="password">Senha do Wi-Fi</label><input id="password" type="password" maxlength="64" autocomplete="new-password">
<label for="base_url">Endereco do gateway</label>
<div class="url-row">
<input id="base_url" type="url" required maxlength="192" readonly value="https://voice-gateway.200-129-37-25.sslip.io">
<button type="button" class="secondary" id="edit_url" aria-label="Editar endereco do gateway" title="Editar endereco">&#9998; Editar</button>
</div>
<label for="auth_key">Chave de acesso do n8n</label>
<div class="url-row">
<input id="auth_key" type="password" minlength="32" maxlength="128" readonly autocomplete="new-password" placeholder="Chave preservada; escolha Editar para trocar">
<button type="button" class="secondary" id="edit_key" aria-label="Editar chave de acesso" title="Editar chave">&#9998; Editar</button>
</div>
<p id="auth_status" role="status"></p>
<button id="save" type="submit">Conectar e salvar</button>
</form>
<p id="status" role="status" aria-live="polite"></p>
</main>
<script>
const form=document.getElementById('config'),ssid=document.getElementById('ssid');
const password=document.getElementById('password'),url=document.getElementById('base_url');
const networks=document.getElementById('networks'),status=document.getElementById('status');
const save=document.getElementById('save'),scan=document.getElementById('scan');
const editUrl=document.getElementById('edit_url');
const authKey=document.getElementById('auth_key'),authStatus=document.getElementById('auth_status');
let waiting=false,submitting=false,urlInitialized=false,urlEditing=false,keyEditing=false;
editUrl.onclick=()=>{urlEditing=true;url.readOnly=false;url.focus()};
document.getElementById('edit_key').onclick=()=>{keyEditing=true;authKey.readOnly=false;authKey.focus()};
networks.onchange=()=>{if(networks.value)ssid.value=networks.value};
async function refresh(){
 scan.disabled=true;
 try{
  const response=await fetch('/api/networks',{cache:'no-store'});
  if(!response.ok)throw new Error(await response.text());
  const names=await response.json();
  networks.replaceChildren(new Option('Selecione uma rede',''));
  for(const name of new Set(names))networks.add(new Option(name,name));
 }catch(error){status.textContent=error.message}
 finally{scan.disabled=false}
}
scan.onclick=refresh;
async function poll(initial=false){
 try{
  const response=await fetch('/api/status',{cache:'no-store'});
  if(!response.ok)throw new Error('Nao foi possivel consultar o ESP.');
  const data=await response.json();
  authStatus.textContent=data.auth_configured?'Chave salva.':'Nenhuma chave salva.';
  if(initial){ssid.value=data.ssid;status.textContent=data.message}
  if(!urlInitialized&&!urlEditing){url.value=data.base_url||url.defaultValue;urlInitialized=true}
  if(data.busy)waiting=true;
  if(waiting&&!submitting){
   status.textContent=data.message;
   save.disabled=data.busy;
   if(!data.busy){waiting=false;if(data.connected){
    password.value='';authKey.value='';authKey.readOnly=true;url.readOnly=true;
    keyEditing=false;urlEditing=false;urlInitialized=false;
   }}
  }
 }catch(error){if(waiting){status.textContent='Conexao com o portal interrompida. Reconecte a Nuclea-Config e recarregue a pagina.';waiting=false;save.disabled=false}}
 finally{setTimeout(()=>poll(),1500)}
}
form.onsubmit=async(event)=>{
 event.preventDefault();save.disabled=true;waiting=true;submitting=true;
 status.textContent='Testando conexao...';
 try{
  const config={ssid:ssid.value,password:password.value};
  if(urlEditing)config.base_url=url.value.trim();
  if(keyEditing)config.auth_key=authKey.value;
  const response=await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify(config)});
  if(!response.ok)throw new Error(await response.text());
 }catch(error){status.textContent=error.message;waiting=false;save.disabled=false}
 finally{submitting=false}
};
poll(true);refresh();
</script>
</html>)PORTAL";
