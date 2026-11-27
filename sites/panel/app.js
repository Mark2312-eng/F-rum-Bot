const API="https://f-rum-bot.onrender.com";
const $=id=>document.getElementById(id);
let dashboardData=null, moderationData=null, peopleData=null, refreshing=false, refreshTimer=null, peopleLoading=false;
function esc(v){return String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function date(v){const d=new Date(v);return Number.isNaN(d.getTime())?"—":d.toLocaleString("ru-RU");}
async function request(path,options={}){const headers={...(options.headers||{})};if(options.body)headers["Content-Type"]="application/json";const r=await fetch(API+path,{...options,credentials:"include",headers});if(!r.ok){let detail="";try{detail=(await r.json()).error||"";}catch{}throw new Error(detail||(r.status===401?"Сначала войдите через Telegram.":r.status===403?"У этого аккаунта нет доступа.":"Ошибка сервера ("+r.status+")."));}return r.status===204?null:r.json();}
function table(headers,rows){return rows.length?'<div class="table-wrap"><table><thead><tr>'+headers.map(x=>'<th>'+x+'</th>').join('')+'</tr></thead><tbody>'+rows.join('')+'</tbody></table></div>':'<p class="empty">Пока нет данных.</p>';}
function updateSearch(){const q=$("table-search").value.trim().toLocaleLowerCase("ru");document.querySelectorAll(".table-wrap tbody tr").forEach(row=>{row.hidden=!!q&&!row.textContent.toLocaleLowerCase("ru").includes(q);});}
function toast(message,type="success"){const node=$("toast");node.textContent=message;node.dataset.type=type;node.hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>{node.hidden=true;},3200);}
function renderDashboard(d,m,b){dashboardData=d;moderationData=m;$("login-view").hidden=true;$("dashboard").hidden=false;
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
$("blacklist-audit-count").textContent=(b.events||[]).length;$("blacklist-audit-table").innerHTML=table(["Пользователь","Действие","Кто изменил","Причина","Дата"],(b.events||[]).map(x=>'<tr><td>'+esc(x.target_id)+'</td><td>'+esc(({add:"Добавлен",update:"Обновлена запись",remove:"Удалён"})[x.action]||x.action)+'</td><td>'+esc(x.actor_id)+'</td><td class="reason-cell">'+esc(x.reason||"—")+'</td><td>'+esc(date(x.created_at))+'</td></tr>'));$("updated-at").textContent="ОБНОВЛЕНО · "+new Date().toLocaleTimeString("ru-RU",{hour:"2-digit",minute:"2-digit"});$("dashboard-error").textContent="";updateSearch();}
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
    const historyButton='<button class="button button-quiet member-history" data-chat-id="'+esc(x.chat_id)+'" data-user-id="'+esc(x.user_id)+'" type="button">История</button>';
    return '<tr><td>'+esc(x.display_name||x.username||x.user_id)+(x.username?' <span class="muted-cell">@'+esc(x.username)+'</span>':'')+'<div class="muted-cell">ID '+esc(x.user_id)+' · '+esc(x.chat_title||"")+'</div></td><td>'+esc(x.message_count)+' сообщений<div class="muted-cell">С нами с '+esc(date(x.first_seen_at))+'</div></td><td>'+esc(x.warning_count)+'</td><td>'+esc(x.role_title||"Участник")+' <span class="muted-cell">приоритет '+esc(x.priority)+'</span></td><td><div class="role-actions">'+historyButton+selector+actions+'</div></td></tr>';
  })); 
}
async function loadMemberHistory(chatId,userId,filters={}){
  const node=$("member-history");
  node.hidden=false;
  node.innerHTML='<p class="empty"><span class="spinner"></span> Загружаем историю участника…</p>';
  node.scrollIntoView({behavior:"smooth",block:"nearest"});
  const params=new URLSearchParams();
  if(filters.category)params.set("category",filters.category);
  if(filters.actor_id)params.set("actor_id",filters.actor_id);
  try{
    const suffix=params.toString()?"?"+params.toString():"";
    const data=await request("/api/members/"+encodeURIComponent(chatId)+"/"+encodeURIComponent(userId)+"/history"+suffix);
    const m=data.member;
    node.innerHTML='<div class="member-history-head"><div><b>'+esc(m.display_name||m.username||m.user_id)+'</b><small>'+esc(m.chat_title||m.chat_id)+' · ID '+esc(m.user_id)+(m.username?' · @'+esc(m.username):'')+'</small></div><button class="button button-quiet" id="close-member-history" type="button">Скрыть</button></div><div class="member-history-stats"><span>Сообщения <b>'+esc(m.message_count)+'</b></span><span>Предупреждения <b>'+esc(m.warning_count)+'</b></span><span>Роль <b>'+esc(m.role_title)+' · '+esc(m.priority)+'</b></span><span>В группе с <b>'+esc(date(m.first_seen_at))+'</b></span></div><div class="member-history-filters"><label>Тип события<select id="member-history-category"><option value="">Все события</option><option value="moderation">Модерация</option><option value="roles">Изменения ролей</option></select></label><label>Модератор (Telegram ID)<input id="member-history-actor" type="number" min="1" inputmode="numeric" placeholder="Любой модератор"></label><button class="button button-secondary" id="member-history-apply" type="button">Применить</button></div>'+table(["Тип","Действие","Модератор","Детали","Дата"],data.events.map(e=>'<tr><td>'+esc(e.category==="roles"?"Роли":"Модерация")+'</td><td>'+esc(e.action)+'</td><td>'+esc(e.actor_id??"Автоматически")+'</td><td>'+esc(e.details||"—")+'</td><td>'+esc(date(e.created_at))+'</td></tr>'))+(data.events.length?'':'<p class="empty">По выбранным фильтрам записей нет.</p>');
    $("member-history-category").value=filters.category||"";
    $("member-history-actor").value=filters.actor_id||"";
    $("close-member-history").addEventListener("click",()=>{node.hidden=true;node.innerHTML="";});
    $("member-history-apply").addEventListener("click",()=>{
      loadMemberHistory(chatId,userId,{
        category:$("member-history-category").value,
        actor_id:$("member-history-actor").value.trim()
      });
    });
    $("member-history-actor").addEventListener("keydown",event=>{
      if(event.key==="Enter")$("member-history-apply").click();
    });
  }catch(error){node.innerHTML='<p class="notice">'+esc(error.message)+'</p>';}
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

async function loadDashboard(){if(refreshing||$("dashboard").hidden)return;refreshing=true;$("refresh").disabled=true;$("refresh").textContent="Обновление…";try{const [d,m,b]=await Promise.all([request("/api/dashboard"),request("/api/moderation"),request("/api/blacklist/history")]);renderDashboard(d,m,b);await loadPeople();await loadSupportQueue();}catch(e){$("dashboard-error").textContent=e.message;if(e.message.includes("Сначала войдите"))stopAutoRefresh();}finally{refreshing=false;$("refresh").disabled=false;$("refresh").textContent="↻ Обновить";}}
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
  const history=event.target.closest(".member-history");
  if(history){loadMemberHistory(history.dataset.chatId,history.dataset.userId);return;}
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

let supportQueueData=[];
let selectedSupportTicket=null;
async function loadSupportQueue(){
  const node=$("support-queue");if(!node)return;
  try{
    const data=await request("/api/support/staff/tickets");
    supportQueueData=data.tickets||[];
    $("support-count").textContent=supportQueueData.filter(x=>x.status!=="closed").length;
    renderSupportQueue();
  }catch(error){node.innerHTML='<p class="empty">'+esc(error.message)+'</p>';}
}
function renderSupportQueue(){
  const filter=$("support-filter")?.value||"active";
  const rows=supportQueueData.filter(ticket=>filter==="all"||(filter==="closed"?ticket.status==="closed":ticket.status!=="closed"));
  $("support-queue").innerHTML=rows.length?rows.map(ticket=>'<button class="support-queue-item '+(String(ticket.id)===String(selectedSupportTicket)?'active':'')+'" data-support-id="'+esc(ticket.id)+'" type="button"><span><b>#'+esc(ticket.id)+' · '+esc(ticket.subject)+'</b><small>'+esc(ticket.username?'@'+ticket.username:'ID '+ticket.user_id)+' · '+esc(ticket.status)+'</small><em>'+esc(ticket.last_message||'')+'</em></span><i>›</i></button>').join(""):'<p class="empty">Обращений в этой категории нет.</p>';
}
async function openSupportTicket(id){
  selectedSupportTicket=String(id);renderSupportQueue();
  const node=$("support-conversation");node.innerHTML='<p class="empty">Загружаем переписку…</p>';
  try{
    const data=await request("/api/support/staff/tickets/"+encodeURIComponent(id));
    node.innerHTML='<div class="support-conversation-head"><div><b>Обращение #'+esc(data.ticket.id)+' · '+esc(data.ticket.subject)+'</b><small>Пользователь: '+esc(data.ticket.username?'@'+data.ticket.username:data.ticket.user_id)+' · '+esc(data.ticket.status)+' · '+(data.ticket.assigned_to?'Ответственный: '+esc(data.ticket.assigned_to):'Не назначено')+'</small></div><div class="support-head-actions">'+(data.ticket.status!=="closed"?(data.ticket.assigned_to?'':'<button class="button button-quiet" id="support-assign-ticket" type="button">Взять себе</button>')+'<button class="button button-quiet" id="support-close-ticket" type="button">Закрыть</button>':'<span class="status good">Закрыто</span>')+'</div></div><div class="support-conversation-messages">'+data.messages.map(message=>'<article class="support-chat-message '+(message.author_role==="staff"?"staff":"user")+'"><small>'+(message.author_role==="staff"?"Сотрудник #"+esc(message.author_id):"Пользователь")+' · '+esc(date(message.created_at))+'</small><p>'+esc(message.body)+'</p></article>').join("")+'</div>'+(data.ticket.status!=="closed"?'<form id="support-staff-reply"><textarea name="message" maxlength="2000" rows="3" required placeholder="Ответ пользователю…"></textarea><button class="button button-secondary" type="submit">Отправить ответ</button></form>':'<p class="empty">Обращение закрыто.</p>');
    $("support-assign-ticket")?.addEventListener("click",async()=>{
      try{await request("/api/support/staff/tickets/"+encodeURIComponent(id)+"/assign",{method:"POST"});toast("Обращение назначено вам.");await openSupportTicket(id);await loadSupportQueue();}
      catch(error){toast(error.message,"error");}
    });
    $("support-staff-reply")?.addEventListener("submit",async event=>{
      event.preventDefault();const form=event.currentTarget;const message=form.elements.message.value.trim();if(!message)return;
      const button=form.querySelector("button");button.disabled=true;
      try{await request("/api/support/staff/tickets/"+encodeURIComponent(id)+"/messages",{method:"POST",body:JSON.stringify({message})});toast("Ответ отправлен пользователю.");await openSupportTicket(id);await loadSupportQueue();}
      catch(error){toast(error.message,"error");button.disabled=false;}
    });
    $("support-close-ticket")?.addEventListener("click",async()=>{
      try{await request("/api/support/staff/tickets/"+encodeURIComponent(id)+"/close",{method:"POST"});toast("Обращение закрыто.");await loadSupportQueue();await openSupportTicket(id);}
      catch(error){toast(error.message,"error");}
    });
  }catch(error){node.innerHTML='<p class="empty">'+esc(error.message)+'</p>';}
}
$("support-queue")?.addEventListener("click",event=>{const button=event.target.closest("[data-support-id]");if(button)openSupportTicket(button.dataset.supportId);});
$("support-filter")?.addEventListener("change",renderSupportQueue);
$("support-reload")?.addEventListener("click",loadSupportQueue);

init();