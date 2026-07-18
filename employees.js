/* Colaboradores (dados reais via API) e painel operacional para Admin/RH/Tesouraria. */
let cachedEmployees=[];
const DEPARTMENTS=['Tecnologia','Produto','Dados e IA','Segurança','Pessoas & Cultura','Finanças','Operações','Administração','Financeiro','Tesouraria'];

function formatDate(value){if(!value)return '—';const [y,m,d]=value.split('-');return `${d}/${m}/${y}`}
function calculateAge(birthDate){if(!birthDate)return null;const [y,m,d]=birthDate.split('-').map(Number);const today=new Date();let age=today.getFullYear()-y;if(today.getMonth()+1<m||(today.getMonth()+1===m&&today.getDate()<d))age--;return age}

function employeesPage(){return `<div class="main-page"><div class="page-top"><div><h2>Colaboradores</h2><p>Gerencie o cadastro do seu time.</p></div><div class="action-row">${['Admin','RH'].includes(sessionUser?.role)?'<button class="secondary" data-action="exportEmployeesCsv">Exportar CSV</button>':''}<button class="primary" data-action="openModal" data-args='["employee"]'>+ Novo colaborador</button></div></div><div class="card table-card"><div class="table-head"><div class="filters"><input id="searchEmployees" placeholder="⌕  Buscar por nome ou matrícula" data-oninput="renderEmployeeRows"><select id="filterDepartment" data-onchange="loadEmployees"><option value="">Todos os departamentos</option>${DEPARTMENTS.map(d=>`<option>${d}</option>`).join('')}</select><select id="filterStatus" data-onchange="loadEmployees"><option value="">Ativos e inativos</option><option>Ativo</option><option>Inativo</option></select></div><span id="employeeCount" class="count-label"></span></div><table><thead><tr><th>COLABORADOR</th><th>CARGO</th><th>DEPARTAMENTO</th><th>STATUS</th><th>SALÁRIO</th><th></th></tr></thead><tbody id="employeeRows"><tr><td colspan="6" class="empty">Carregando…</td></tr></tbody></table></div></div>`}

async function loadEmployees(){
  const holder=$('#employeeRows');
  if(!holder)return;
  const params=new URLSearchParams();
  const department=$('#filterDepartment')?.value;
  const status=$('#filterStatus')?.value;
  if(department)params.set('department',department);
  if(status)params.set('status',status);
  try{const {users}=await api(`/api/users${params.toString()?'?'+params.toString():''}`);cachedEmployees=users;renderEmployeeRows($('#searchEmployees')?.value||'')}
  catch(error){holder.innerHTML=`<tr><td colspan="6" class="empty">${apiEscape(error.message)}</td></tr>`}
}

function renderEmployeeRows(query=''){
  const holder=$('#employeeRows');
  if(!holder)return;
  const term=query.toLowerCase();
  const data=cachedEmployees.filter(employee=>(employee.name+employee.enrollment).toLowerCase().includes(term));
  const count=$('#employeeCount');
  if(count)count.textContent=`${data.length} exibido(s)`;
  holder.innerHTML=data.map(employee=>`<tr><td><div class="employee-cell">${avatar(employee)}<div>${apiEscape(employee.name)}<small class="detail-sub">${employee.enrollment}</small></div></div></td><td>${apiEscape(employee.jobTitle)}</td><td>${apiEscape(employee.department)}</td><td><span class="badge ${employee.status==='Ativo'?'ok':'no'}">${employee.status}</span></td><td>${money(employee.salary)}</td><td><button class="link-button" data-action="openEmployeeDetail" data-args='${dataArgs([employee.id])}'>Ver perfil →</button></td></tr>`).join('')||'<tr><td colspan="6" class="empty">Nenhum colaborador encontrado.</td></tr>'
}

async function exportEmployeesCsv(){
  try{
    const token=localStorage.getItem('orbitaAccessToken');
    const response=await fetch('/api/employees/export',{headers:token?{Authorization:`Bearer ${token}`}:{}});
    if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(data.error||'Falha ao exportar')}
    const blob=await response.blob();
    const url=URL.createObjectURL(blob);
    const link=document.createElement('a');
    link.href=url;link.download='colaboradores.csv';
    document.body.appendChild(link);link.click();link.remove();
    URL.revokeObjectURL(url);
    toast('Exportação concluída.','success');
  }catch(error){toast(error.message,'error')}
}

function openSalaryModalFor(id){closeModal();openSalaryModal(id)}

function openEditEmployeeModal(id){
  const employee=cachedEmployees.find(item=>item.id===id);
  if(!employee)return;
  $('#modalRoot').innerHTML=`<div class="modal-backdrop"><div class="modal"><h2>Editar colaborador</h2><p>${employee.enrollment}</p><form id="editEmployeeForm"><div class="form-grid"><label>Nome completo<input name="name" value="${apiEscape(employee.name)}" required></label><label>Cargo<input name="jobTitle" value="${apiEscape(employee.jobTitle)}" required></label><label>Departamento<select name="department">${DEPARTMENTS.map(d=>`<option ${d===employee.department?'selected':''}>${d}</option>`).join('')}</select></label><label>Data de nascimento<input name="birthDate" type="date" value="${employee.birthDate||''}"></label></div><label>Endereço completo<input name="address" value="${apiEscape(employee.address)}" required></label><label>Nome da mãe<input name="motherName" value="${apiEscape(employee.motherName)}" required></label><label>Horário contratual<input name="schedule" value="${apiEscape(employee.schedule||'')}" placeholder="Ex.: 08:00 – 17:00"></label><div class="form-actions"><button type="button" class="secondary" data-action="closeModal">Cancelar</button><button class="primary">Salvar</button></div></form></div></div>`;
  $('#editEmployeeForm').onsubmit=async event=>{
    event.preventDefault();
    try{
      await api(`/api/employees/${id}`,{method:'PATCH',body:JSON.stringify(Object.fromEntries(new FormData(event.target)))});
      toast('Dados atualizados.','success');
      closeModal();
      loadEmployees();
    }catch(error){toast(error.message,'error')}
  };
}

async function toggleEmployeeStatus(id,newStatus){
  try{
    await api(`/api/employees/${id}/status`,{method:'POST',body:JSON.stringify({status:newStatus})});
    toast(newStatus==='Inativo'?'Colaborador desligado.':'Colaborador reativado.','success');
    closeModal();
    loadEmployees();
  }catch(error){toast(error.message,'error')}
}

function openPhotoModalFor(id){
  $('#modalRoot').innerHTML=`<div class="modal-backdrop"><div class="modal"><h2>Foto de perfil</h2><form id="photoForm"><label>Selecionar imagem<input name="photo" type="file" accept="image/*" required></label><div class="form-actions"><button type="button" class="secondary" data-action="closeModal">Cancelar</button><button class="primary">Salvar</button></div></form></div></div>`;
  $('#photoForm').onsubmit=async event=>{
    event.preventDefault();
    try{
      const photo=await readImage(event.target.photo);
      if(!photo)return;
      await api(`/api/employees/${id}/photo`,{method:'POST',body:JSON.stringify({photo})});
      toast('Foto atualizada.','success');
      closeModal();
      loadEmployees();
    }catch(error){toast(error.message,'error')}
  };
}

function openAddBenefitModal(employeeId){
  $('#modalRoot').innerHTML=`<div class="modal-backdrop"><div class="modal"><h2>Adicionar benefício</h2><form id="benefitForm"><label>Nome<input name="name" required placeholder="Ex.: Vale-refeição"></label><label>Valor mensal<input name="value" type="number" min="0" step="0.01" required></label><div class="form-actions"><button type="button" class="secondary" data-action="closeModal">Cancelar</button><button class="primary">Adicionar</button></div></form></div></div>`;
  $('#benefitForm').onsubmit=async event=>{
    event.preventDefault();
    try{
      const formData=Object.fromEntries(new FormData(event.target));
      await api('/api/benefits',{method:'POST',body:JSON.stringify({...formData,employeeId})});
      toast('Benefício adicionado.','success');
      openEmployeeDetail(employeeId);
    }catch(error){toast(error.message,'error')}
  };
}
async function removeBenefit(benefitId,employeeId){
  try{
    await api(`/api/benefits/${benefitId}`,{method:'DELETE'});
    toast('Benefício removido.','success');
    openEmployeeDetail(employeeId);
  }catch(error){toast(error.message,'error')}
}

async function openEmployeeTimeModal(id){
  const employee=cachedEmployees.find(item=>item.id===id)||{name:'colaborador'};
  const isAdmin=['Admin','RH'].includes(sessionUser?.role);
  $('#modalRoot').innerHTML=`<div class="modal-backdrop"><div class="modal"><h2>Jornada de ${apiEscape(employee.name)}</h2><div id="employeeTimeHistory" class="empty">Carregando…</div>${isAdmin?`<form id="timeCorrectForm" class="mt-12"><strong>Registrar correção</strong><div class="form-grid mt-8"><label>Tipo<select name="type"><option>Entrada</option><option>Início do intervalo</option><option>Fim do intervalo</option><option>Saída</option></select></label><label>Horário<input name="at" type="time" required></label></div><label>Data<input name="date" type="date" required></label><div class="form-actions"><button class="secondary">Registrar</button></div></form>`:''}<div class="form-actions"><button class="primary" data-action="closeModal">Fechar</button></div></div></div>`;
  const holder=$('#employeeTimeHistory');
  try{
    const data=await api(`/api/users/${id}/time`);
    holder.className='';
    holder.innerHTML=`<p class="muted-text text-sm">Banco de horas: <strong>${data.bank}</strong></p>`+(data.days.map(day=>`<div class="request-row"><div class="request-info"><strong>${formatDate(day.date)}</strong><span>${Math.floor(day.workedMinutes/60)}h${String(day.workedMinutes%60).padStart(2,'0')} trabalhadas · ${day.events.length} registro(s)</span></div></div>`).join('')||'<p class="muted-text text-sm">Nenhum registro de ponto.</p>');
  }catch(error){holder.innerHTML=`<p class="muted-text">${apiEscape(error.message)}</p>`}
  const form=$('#timeCorrectForm');
  if(form)form.onsubmit=async event=>{
    event.preventDefault();
    try{
      await api(`/api/employees/${id}/time/correct`,{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(event.target)))});
      toast('Registro adicionado.','success');
      openEmployeeTimeModal(id);
    }catch(error){toast(error.message,'error')}
  };
}

async function openEmployeeDetail(id){
  const employee=cachedEmployees.find(item=>item.id===id);
  if(!employee)return;
  const isAdmin=['Admin','RH'].includes(sessionUser?.role);
  let benefits=[];
  if(isAdmin){try{const data=await api(`/api/users/${id}/benefits`);benefits=data.benefits}catch(error){}}
  const age=calculateAge(employee.birthDate);
  $('#modalRoot').innerHTML=`<div class="modal-backdrop"><div class="modal">
    <h2>${apiEscape(employee.name)}</h2>
    <p>${employee.enrollment} · ${apiEscape(employee.jobTitle)} · <span class="badge ${employee.status==='Ativo'?'ok':'no'}">${employee.status}</span></p>
    <div class="card flat-card mt-15">
      <div class="employee-cell">${avatar(employee)}<div><strong>${apiEscape(employee.department)}</strong><small class="detail-sub">${apiEscape(employee.email)}</small></div></div>
      ${isAdmin?`<button class="link-button mt-8" data-action="openPhotoModalFor" data-args='${dataArgs([employee.id])}'>Trocar foto</button>`:''}
    </div>
    <div class="card flat-card mt-12">
      <strong>Salário vigente</strong><h2 class="mt-8">${money(employee.salary)}</h2>
      ${['Admin','RH','Manager'].includes(sessionUser?.role)?`<button class="secondary" data-action="openSalaryModalFor" data-args='${dataArgs([employee.id])}'>Solicitar alteração</button>`:''}
    </div>
    <div class="card flat-card mt-12">
      <strong>Detalhes</strong>
      <p class="muted-text text-sm mt-8">Admissão: ${formatDate(employee.admissionDate)} · Nascimento: ${formatDate(employee.birthDate)}${age!==null?` (${age} anos)`:''}<br>Saldo de férias: ${employee.vacationBalance} dias · Jornada: ${apiEscape(employee.schedule||'—')}</p>
      ${isAdmin?`<button class="link-button" data-action="openEmployeeTimeModal" data-args='${dataArgs([employee.id])}'>Ver jornada e ponto →</button>`:''}
    </div>
    ${isAdmin?`<div class="card flat-card mt-12">
      <div class="card-title"><strong>Benefícios</strong><button class="link-button" data-action="openAddBenefitModal" data-args='${dataArgs([employee.id])}'>+ Adicionar</button></div>
      ${benefits.map(b=>`<div class="request-row"><div class="request-info"><strong>${apiEscape(b.name)}</strong><span>${money(b.value)}/mês</span></div><button class="link-button" data-action="removeBenefit" data-args='${dataArgs([b.id,employee.id])}'>Remover</button></div>`).join('')||'<p class="muted-text text-sm">Nenhum benefício cadastrado.</p>'}
    </div>`:''}
    <div class="form-actions">
      ${isAdmin?`<button class="secondary" data-action="openEditEmployeeModal" data-args='${dataArgs([employee.id])}'>Editar</button>`:''}
      ${isAdmin?`<button class="secondary" data-action="toggleEmployeeStatus" data-args='${dataArgs([employee.id,employee.status==='Ativo'?'Inativo':'Ativo'])}'>${employee.status==='Ativo'?'Desligar':'Reativar'}</button>`:''}
      <button class="primary" data-action="closeModal">Fechar</button>
    </div>
  </div></div>`;
}

function organogramPage(){return `<div class="main-page"><div class="page-top"><div><h2>Organograma</h2><p>Estrutura hierárquica dos times.</p></div></div><div id="orgChart" class="card empty">Carregando…</div></div>`}
async function loadOrgChart(){
  const holder=$('#orgChart');
  if(!holder)return;
  try{
    const {users}=await api('/api/users');
    const byManager={};
    users.forEach(u=>{const key=u.managerId||'__root__';(byManager[key]=byManager[key]||[]).push(u)});
    const renderNode=user=>{
      const children=byManager[user.id]||[];
      return `<li><div class="org-node">${avatar(user)}<div><strong>${apiEscape(user.name)}</strong><small class="detail-sub">${apiEscape(user.jobTitle)} · ${apiEscape(user.department)}</small></div></div>${children.length?`<ul>${children.map(renderNode).join('')}</ul>`:''}</li>`;
    };
    const roots=byManager['__root__']||[];
    holder.className='card';
    holder.innerHTML=roots.length?`<ul class="org-tree">${roots.map(renderNode).join('')}</ul>`:'<p class="muted-text">Nenhum colaborador cadastrado.</p>';
  }catch(error){holder.innerHTML=`<div class="empty">${apiEscape(error.message)}</div>`}
}

function operationalDashboard(){return `<div class="main-page"><div class="page-top"><div><h2>Visão geral</h2><p>Acompanhe o que acontece na Orbita hoje.</p></div>${['Admin','RH'].includes(sessionUser?.role)?'<button class="primary" data-action="openModal" data-args=\'["employee"]\'>+ Novo colaborador</button>':''}</div><section id="fullDashboardStats" class="stats"><div class="stat"><div class="stat-top">Carregando…</div><h3>—</h3></div></section><section class="dashboard-grid"><div class="card"><div class="card-title"><h3>Últimas solicitações</h3><button class="link-button" data-action="go" data-args='["requests"]'>Ver todas</button></div><div id="dashboardRecentRequests" class="empty">Carregando…</div></div><div class="card"><div class="card-title"><h3>Ações rápidas</h3></div><div class="quick-actions">${['Admin','RH'].includes(sessionUser?.role)?'<button class="quick-action" data-action="openModal" data-args=\'["employee"]\'><span>＋</span>Adicionar colaborador</button>':''}<button class="quick-action" data-action="openRequestModal"><span>✓</span>Nova solicitação</button><button class="quick-action" data-action="go" data-args='["time"]'><span>◷</span>Consultar jornada</button></div></div></section><section class="dashboard-grid mt-20"><div class="card"><div class="card-title"><h3>Aniversariantes do mês</h3></div><div id="dashboardBirthdays" class="empty">Carregando…</div></div><div class="card"><div class="card-title"><h3>Evolução do quadro</h3></div><div id="dashboardHeadcount" class="empty">Carregando…</div></div></section></div>`}

function renderBirthdays(users){
  const holder=$('#dashboardBirthdays');
  if(!holder)return;
  const currentMonth=new Date().getMonth()+1;
  const birthdays=users.filter(u=>u.birthDate&&Number(u.birthDate.split('-')[1])===currentMonth).sort((a,b)=>Number(a.birthDate.split('-')[2])-Number(b.birthDate.split('-')[2]));
  holder.className=birthdays.length?'':'empty';
  holder.innerHTML=birthdays.map(u=>`<div class="request-row">${avatar(u)}<div class="request-info"><strong>${apiEscape(u.name)}</strong><span>Dia ${Number(u.birthDate.split('-')[2])}</span></div></div>`).join('')||'Nenhum aniversariante este mês.';
}

function renderHeadcountChart(users){
  const holder=$('#dashboardHeadcount');
  if(!holder)return;
  const withDates=users.filter(u=>u.admissionDate).sort((a,b)=>a.admissionDate.localeCompare(b.admissionDate));
  if(!withDates.length){holder.className='empty';holder.textContent='Sem dados de admissão suficientes.';return}
  const buckets={};
  withDates.forEach(u=>{const key=u.admissionDate.slice(0,7);buckets[key]=(buckets[key]||0)+1});
  let running=0;
  const points=Object.keys(buckets).sort().map(key=>{running+=buckets[key];return {key,total:running}});
  const max=points[points.length-1].total||1;
  holder.className='';
  holder.innerHTML=`<div class="headcount-chart">${points.map(p=>`<div class="headcount-bar" title="${p.key}: ${p.total} colaboradores"><span>${p.total}</span></div>`).join('')}</div><div class="headcount-labels">${points.map(p=>`<span>${p.key}</span>`).join('')}</div>`;
  holder.querySelectorAll('.headcount-bar').forEach((bar,i)=>{bar.style.height=`${Math.round(points[i].total/max*100)}%`});
}

async function loadFullDashboard(){
  const holder=$('#fullDashboardStats');
  if(!holder)return;
  const cards=[];
  try{
    const {users}=await api('/api/users');
    cards.push(['Total de colaboradores',users.length,'Cadastrados na Orbita']);
    renderBirthdays(users);
    renderHeadcountChart(users);
  }catch(error){}
  let salaryRequests=[],generalRequests=[];
  try{
    const [salary,general]=await Promise.all([api('/api/salary-requests'),api('/api/requests')]);
    salaryRequests=salary.requests;generalRequests=general.requests;
    const pending=salaryRequests.filter(r=>!['Aprovado','Rejeitado'].includes(r.status)).length+generalRequests.filter(r=>r.status==='Pendente').length;
    cards.push(['Pendências para aprovar',pending,'Requer sua atenção']);
  }catch(error){}
  try{const {schedule}=await api('/api/payroll/close-schedule');cards.push(['Fechamento da folha',schedule.status,schedule.competence])}catch(error){}
  holder.innerHTML=cards.map(([label,value,hint])=>`<div class="stat"><div class="stat-top">${label}</div><h3>${value}</h3><small>${hint}</small></div>`).join('')||'<div class="empty">Sem dados disponíveis para o seu perfil.</div>';

  const recentHolder=$('#dashboardRecentRequests');
  if(recentHolder){
    const recent=[
      ...generalRequests.slice(-3).map(r=>({name:r.employeeName,type:r.type,status:r.status})),
      ...salaryRequests.slice(-3).map(r=>({name:r.employeeName,type:'Alteração salarial',status:r.status})),
    ].slice(-5).reverse();
    recentHolder.className=recent.length?'':'empty';
    recentHolder.innerHTML=recent.map(r=>`<div class="request-row">${avatar({name:r.name,initials:initials(r.name)})}<div class="request-info"><strong>${apiEscape(r.name)}</strong><span>${apiEscape(r.type)}</span></div><span class="badge ${r.status==='Aprovado'?'ok':r.status==='Rejeitado'?'no':''}">${apiEscape(r.status)}</span></div>`).join('')||'Nenhuma solicitação registrada ainda.';
  }
}

pages.employees=employeesPage;
pages.dashboard=operationalDashboard;
pages.organograma=organogramPage;
meta.organograma=['PESSOAS','Organograma'];
document.addEventListener('page:show',event=>{const page=event.detail;setTimeout(()=>{if(page==='employees')loadEmployees();if(page==='dashboard')loadFullDashboard();if(page==='organograma')loadOrgChart()},0)});
