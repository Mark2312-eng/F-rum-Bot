const API="https://f-rum-bot.onrender.com";
const $=id=>document.getElementById(id);
let dashboardData=null, moderationData=null, peopleData=null, refreshing=false, refreshTimer=null, peopleLoading=false;
function esc(v){return String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function date(v){const d=new Date(v);return Number.isNaN(d.getTime())?"—":d.toLocaleString("ru-RU");}
async function request(path,options={}){const headers={...(options.headers||{})};if(options.body)headers["Content-Type"]="application/json";const r=await fetch(API+path,{...options,credentials:"include",headers});if(!r.ok){let detail="";try{detail=(await r.json()).error||"";}catch{}throw new Error(detail||(r.status===401?"Сначала войдите через Telegram.":r.status===403?"У этого аккаунта нет доступа.":"Ошибка сервера ("+r.status+")."));}return r.status===204?null:r.json();}
function table(headers,rows){return rows.length?'<div class="table-wrap"><table><thead><tr>'+headers.map(x=>'<th>'+x+'</th>').join('')+'</tr></thead><tbody>'+rows.join('')+'</tbody></table></div>':'<p class="empty">Пока нет данных.</p>';}
function updateSearch(){const q=$("table-search").value.trim().toLocaleLowerCase("ru");document.querySelectorAll(".table-wrap tbody tr").forEach(row=>{row.hidden=!!q&&!row.textContent.toLocaleLowerCase("ru").includes(q);});}
function toast(message,type="success"){const node=$("toast");node.textContent=message;node.dataset.type=type;node.hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>{node.hidden=true;},3200);}
function renderDashboard(d,m){dashboardData=d;moderationData=m;$("login-view").hidden=true;$("dashboard").hidden=false;
const s=m.summary||{};
$("stats").innerHTML=[["Группы",d.chats.length],["Открытые жалобы",s.open_reports||0],["Участники",s.members_count||0],["Действия за 7 дней",s.events_week||0]].map(([k,v])=>'<article><span>'+k+'</span><b>'+esc(v)+'</b></article>').join("");
$("groups-count").textContent=d.chats.length;$("tests-count").textContent=d.tests.length;$("results-count").textContent=d.results.length;
$("chats").innerHTML=table(["Группа","ID","Режим"],d.chats.map(x=>'<tr><td>'+esc(x.title||"Без названия")+'</td><td>'+esc(x.chat_id)+'</td><td>'+esc(x.moderation_mode)+'</td></tr>'));
$("tests-table").innerHTML=table(["Тест","Группа","Роль","Попытки","Сдано"],d.tests.map(x=>'<tr><td>#'+esc(x.id)+' · '+esc(x.title)+'</td><td>'+esc(x.chat_id)+'</td><td>'+esc(x.role_key)+'</td><td>'+esc(x.attempts)+'</td><td>'+esc(x.passed_count)+'</td></tr>'));
$("results-table").innerHTML=table(["Тест","Пользователь","Результат","Статус","Дата"],d.results.map(x=>'<tr><td>'+esc(x.test_title)+'</td><td>'+esc(x.user_id)+'</td><td>'+esc(x.score_percent)+'%</td><td><span class="status '+(x.passed?"good":"bad")+'">'+(x.passed?"Сдан":"Не сдан")+'</span></td><td>'+esc(date(x.created_at))+'</td></tr>'));
$("reports-count").textContent=m.reports.length;$("members-count").textContent=m.members.length;$("events-count").textContent=m.events.length;
$("reports-table").innerHTML=table(["№","Группа","Отправитель","На пользователя","Причина","Дата","Действие"],m.reports.map(x=>'<tr><td>#'+esc(x.id)+'</td><td>'+esc(x.chat_title||x.chat_id)+'</td><td>'+esc(x.reporter_id)+'</td><td>'+esc(x.target_id)+'</td><td class="reason-cell">'+esc(x.reason)+'</td><td>'+esc(date(x.created_at))+'</td><td><button class="button button-secondary close-report" data-report-id="'+esc(x.id)+'" type="button">Закрыть</button></td></tr>'));
$("members-table").innerHTML=table(["Участник","Группа","Роль","Сообщения","Предупреждения","Впервые замечен"],m.members.map(x=>'<tr><td>'+esc(x.display_name||x.username||x.user_id)+(x.username?' <span class="muted-cell">@'+esc(x.username)+'</span>':'')+'<div class="muted-cell">ID '+esc(x.user_id)+'</div></td><td>'+esc(x.chat_title||x.chat_id)+'</td><td>'+esc(x.role_title||"Участник")+'</td><td>'+esc(x.message_count)+'</td><td>'+esc(x.warning_count)+'</td><td>'+esc(date(x.first_seen_at))+'</td></tr>'));
$("events-table").innerHTML=table(["Группа","Действие","Модератор","Участник","Детали","Дата"],m.events.map(x=>'<tr><td>'+esc(x.chat_title||x.chat_id)+'</td><td>'+esc(x.action)+'</td><td>'+esc(x.actor_id??"Автоматически")+'</td><td>'+esc(x.target_id??"—")+'</td><td>'+esc(x.details)+'</td><td>'+esc(date(x.created_at))+'</td></tr>'));
$("updated-at").textContent="ОБНОВЛЕНО · "+new Date().toLocaleTimeString("ru-RU",{hour:"2-digit",minute:"2-digit"});$("dashboard-error").textContent="";updateSearch();}

function renderPeople(data){
  peopleData=data;
  const chatSelect=$("people-chat");
  const previous=chatSelect.value;
  chatSelect.innerHTML='<option value="">Все группы · только просмотр</option>'+data.chats.map(c=>'<option value="'+esc(c.chat_id)+'">'+esc(c.title||c.chat_id)+'</option>').join("");
  chatSelect.value=data.selected_chat_id?String(data.selected_chat_id):(previous&&data.chats.some(c=>String(c.chat_id)===previous)?previous:"");
  $("people-count").textContent=data.members.length+" записей";
  $("role-catalog").innerHTML=data.roles.length?'<span class="catalog-label">РОЛИ ГРУППЫ</span>'+data.roles.map(r=>'<span class="role-chip">'+esc(r.title)+' <b>'+esc(r.priority)+'</b>'+(r.is_system?' · системная':'')+'</span>').join(""):'<span class="catalog-label">Выберите группу, чтобы увидеть доступные роли</span>';
  $("people-table").innerHTML=table(["Участник","Активность","Предупреждения","Текущая роль","Назначение"],data.members.map(x=>{
    const canEdit=!!data.selected_chat_id;
    const selector=canEdit?'<select class="role-select" aria-label="Новая роль для '+esc(x.user_id)+'"><option value="">Выберите роль</option>'+data.roles.map(r=>'<option value="'+esc(r.role_key)+'">'+esc(r.title)+' · '+esc(r.priority)+'</option>').join("")+'</select>':'<span class="muted-cell">Только просмотр</span>';
    const actions=canEdit?'<button class="button button-secondary assign-member-role" data-user-id="'+esc(x.user_id)+'" type="button">Назначить</button>'+(x.role_key?'<button class="button button-quiet remove-member-role" data-user-id="'+esc(x.user_id)+'" type="button">Снять</button>':''):'—';
    return '<tr><td>'+esc(x.display_name||x.username||x.user_id)+(x.username?' <span class="muted-cell">@'+esc(x.username)+'</span>':'')+'<div class="muted-cell">ID '+esc(x.user_id)+' · '+esc(x.chat_title||"")+'</div></td><td>'+esc(x.message_count)+' сообщений<div class="muted-cell">С нами с '+esc(date(x.first_seen_at))+'</div></td><td>'+esc(x.warning_count)+'</td><td>'+esc(x.role_title||"Участник")+' <span class="muted-cell">приоритет '+esc(x.priority)+'</span></td><td><div class="role-actions">'+selector+actions+'</div></td></tr>';
  })); 
}
async function loadPeople(){
  if(peopleLoading)return;
  peopleLoading=true;
  const chatId=$("people-chat").value;
  const q=$("people-search").value.trim();
  const params=new URLSearchParams();
  if(chatId)params.set("chat_id",chatId);
  if(q)params.set("q",q);
  $("people-table").innerHTML='<p class="empty"><span class="spinner"></span> Загружаем участников…</p>';
  try{const data=await request("/api/people"+(params.toString()?"?"+params.toString():""));renderPeople(data);}
  catch(e){$("people-table").innerHTML='<p class="notice">'+esc(e.message)+'</p>';}
  finally{peopleLoading=false;}
}

async function loadDashboard(){if(refreshing||$("dashboard").hidden)return;refreshing=true;$("refresh").disabled=true;$("refresh").textContent="Обновление…";try{const [d,m]=await Promise.all([request("/api/dashboard"),request("/api/moderation")]);renderDashboard(d,m);await loadPeople();}catch(e){$("dashboard-error").textContent=e.message;if(e.message.includes("Сначала войдите"))stopAutoRefresh();}finally{refreshing=false;$("refresh").disabled=false;$("refresh").textContent="↻ Обновить";}}
function startAutoRefresh(){stopAutoRefresh();refreshTimer=setInterval(()=>{if(!document.hidden)loadDashboard();},60000);}
function stopAutoRefresh(){if(refreshTimer){clearInterval(refreshTimer);refreshTimer=null;}}
function exportCsv(){const tables=[...document.querySelectorAll(".table-wrap table")];if(!tables.length){toast("Нет данных для экспорта.","error");return;}const lines=[];for(const t of tables){const title=t.closest(".block")?.querySelector("h2")?.textContent||"Раздел";lines.push([title]);for(const row of t.querySelectorAll("tr")){if(row.hidden)continue;const cells=[...row.querySelectorAll("th,td")].map(cell=>{let value=cell.innerText.replace(/\s+/g," ").trim();if(/^[=+@-]/.test(value))value="'"+value;return '"'+value.replace(/"/g,'""')+'"';});lines.push(cells);}lines.push([]);}const csv="\uFEFF"+lines.map(row=>row.join(";")).join("\r\n");const blob=new Blob([csv],{type:"text/csv;charset=utf-8"});const url=URL.createObjectURL(blob);const a=document.createElement("a");a.href=url;a.download="vise-russia-panel-"+new Date().toISOString().slice(0,10)+".csv";document.body.append(a);a.click();a.remove();URL.revokeObjectURL(url);toast("Экспорт CSV подготовлен.");}
window.onTelegramAuth=async user=>{try{$("message").textContent="Проверяем Telegram-аккаунт…";await request("/api/auth/telegram",{method:"POST",body:JSON.stringify(user)});$("dashboard").hidden=false;await loadDashboard();startAutoRefresh();}catch(e){$("message").textContent=e.message;}};
async function init(){try{const me=await request("/api/me");if(me.authenticated){$("login-view").hidden=true;$("dashboard").hidden=false;await loadDashboard();startAutoRefresh();return;}const cfg=await request("/api/config");if(!cfg.bot_username){$("login-widget").innerHTML='<p class="notice">Вход пока не настроен. Проверьте PANEL_BOT_USERNAME и домен Telegram Login в BotFather.</p>';return;}const s=document.createElement("script");s.async=true;s.src="https://telegram.org/js/telegram-widget.js?22";s.dataset.telegramLogin=cfg.bot_username;s.dataset.size="large";s.dataset.radius="8";s.dataset.userpic="false";s.dataset.onauth="onTelegramAuth(user)";$("login-widget").replaceChildren(s);}catch(e){$("login-widget").innerHTML='<p class="notice">Не удалось загрузить авторизацию. Обновите страницу через минуту.</p>';$("message").textContent=e.message;}}
$("logout").addEventListener("click",async()=>{try{stopAutoRefresh();await request("/api/logout",{method:"POST"});location.reload();}catch(e){$("dashboard-error").textContent=e.message;}});
$("refresh").addEventListener("click",loadDashboard);$("export-csv").addEventListener("click",exportCsv);$("table-search").addEventListener("input",updateSearch);
$("reports-table").addEventListener("click",async event=>{const button=event.target.closest(".close-report");if(!button)return;const id=button.dataset.reportId;if(!id)return;button.disabled=true;button.textContent="Закрываем…";try{await request("/api/reports/"+encodeURIComponent(id)+"/close",{method:"POST"});toast("Жалоба #"+id+" закрыта.");await loadDashboard();}catch(e){$("dashboard-error").textContent=e.message;button.disabled=false;button.textContent="Закрыть";}});

$("people-chat").addEventListener("change",loadPeople);
$("people-find").addEventListener("click",loadPeople);
$("people-search").addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();loadPeople();}});
$("people-table").addEventListener("click",async event=>{
  const assign=event.target.closest(".assign-member-role");
  const remove=event.target.closest(".remove-member-role");
  const button=assign||remove;if(!button)return;
  const userId=button.dataset.userId,chatId=$("people-chat").value;
  if(!chatId){toast("Сначала выберите группу.","error");return;}
  const row=button.closest("tr");
  const roleKey=assign?row.querySelector(".role-select")?.value:"";
  if(assign&&!roleKey){toast("Выберите роль для назначения.","error");return;}
  button.disabled=true;button.textContent=assign?"Назначаем…":"Снимаем…";
  try{
    await request(assign?"/api/members/role":"/api/members/role/remove",{method:"POST",body:JSON.stringify({chat_id:chatId,user_id:userId,...(assign?{role_key:roleKey}:{})})});
    toast(assign?"Роль назначена.":"Роль снята.");
    await loadDashboard();
  }catch(e){toast(e.message,"error");button.disabled=false;button.textContent=assign?"Назначить":"Снять";}
});

document.querySelectorAll(".dash-nav a").forEach(link=>link.addEventListener("click",()=>{document.querySelectorAll(".dash-nav a").forEach(x=>x.classList.remove("active"));link.classList.add("active");}));
document.addEventListener("keydown",event=>{if(event.key==="/"&&!event.ctrlKey&&!event.metaKey&&!event.altKey&&!["INPUT","TEXTAREA"].includes(document.activeElement.tagName)){event.preventDefault();$("table-search").focus();}if(event.key==="Escape"&&document.activeElement===$("table-search")){$("table-search").value="";updateSearch();}});
document.addEventListener("visibilitychange",()=>{if(!document.hidden&&!$("dashboard").hidden)loadDashboard();});
init();