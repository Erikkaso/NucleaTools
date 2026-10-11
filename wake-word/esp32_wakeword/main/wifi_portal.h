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
<label for="base_url">Endereco da NucleaInterface</label>
<input id="base_url" type="url" required maxlength="192" placeholder="http://192.168.1.100:5000">
<button id="save" type="submit">Conectar e salvar</button>
</form>
<p id="status" role="status" aria-live="polite"></p>
</main>
<script>
const form=document.getElementById('config'),ssid=document.getElementById('ssid');
const password=document.getElementById('password'),url=document.getElementById('base_url');
const networks=document.getElementById('networks'),status=document.getElementById('status');
const save=document.getElementById('save'),scan=document.getElementById('scan');
let waiting=false,submitting=false;
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
  if(initial){ssid.value=data.ssid;url.value=data.base_url;status.textContent=data.message}
  if(data.busy)waiting=true;
  if(waiting&&!submitting){
   status.textContent=data.message;
   save.disabled=data.busy;
   if(!data.busy){waiting=false;if(data.connected)password.value=''}
  }
 }catch(error){if(waiting){status.textContent='Conexao com o portal interrompida. Reconecte a Nuclea-Config e recarregue a pagina.';waiting=false;save.disabled=false}}
 finally{setTimeout(()=>poll(),1500)}
}
form.onsubmit=async(event)=>{
 event.preventDefault();save.disabled=true;waiting=true;submitting=true;
 status.textContent='Testando conexao...';
 try{
  const response=await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({ssid:ssid.value,password:password.value,base_url:url.value.trim()})});
  if(!response.ok)throw new Error(await response.text());
 }catch(error){status.textContent=error.message;waiting=false;save.disabled=false}
 finally{submitting=false}
};
poll(true);refresh();
</script>
</html>)PORTAL";
