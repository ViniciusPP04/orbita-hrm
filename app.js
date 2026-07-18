/* Casca da aplicação: roteador, helpers compartilhados, tema e relógio. Dados vêm sempre da API. */
const $=s=>document.querySelector(s);
const initials=n=>n.split(' ').map(x=>x[0]).slice(0,2).join('').toUpperCase();
function avatar(e){return e&&e.photo?`<img class="person-avatar" src="${apiEscape(e.photo)}" alt="">`:`<div class="person-avatar">${e&&e.initials||initials(e&&e.name||'')}</div>`}
function placeholder(title,description){return `<div class="main-page"><div class="page-top"><div><h2>${title}</h2><p>${description}</p></div></div><div class="card empty"><h3>${title} em preparação</h3><p>Este módulo está previsto para a próxima etapa do MVP.</p></div></div>`}
const pages={dashboard:()=>placeholder('Painel','Carregando…'),employees:()=>placeholder('Colaboradores','Carregando…'),requests:()=>placeholder('Aprovações','Carregando…'),time:()=>placeholder('Jornada & ponto','Carregando…'),payroll:()=>placeholder('Folha de pagamento','Processamento por competência, eventos e holerites.'),documents:()=>placeholder('Documentos','Repositório seguro de documentos dos colaboradores.')};
const meta={dashboard:['PAINEL','Visão geral'],employees:['PESSOAS','Colaboradores'],requests:['FLUXOS','Aprovações'],time:['JORNADA','Jornada & ponto'],payroll:['REMUNERAÇÃO','Folha de pagamento'],documents:['ARQUIVOS','Documentos']};
function go(page){$('#pageContent').innerHTML=pages[page]();const[kicker,title]=meta[page]||['',''];$('#pageKicker').textContent=kicker;$('#pageTitle').textContent=title;document.querySelectorAll('.nav-item[data-page]').forEach(b=>b.classList.toggle('active',b.dataset.page===page));$('#sidebar')?.classList.remove('open');document.dispatchEvent(new CustomEvent('page:show',{detail:page}))}
function closeModal(){$('#modalRoot').innerHTML=''}
function updateClock(){const el=$('#clock');if(el)el.textContent=new Date().toLocaleTimeString('pt-BR')}
function toast(message,type='info'){
  let root=document.getElementById('toastRoot');
  if(!root){root=document.createElement('div');root.id='toastRoot';root.className='toast-root';document.body.appendChild(root)}
  const item=document.createElement('div');
  item.className=`toast ${type}`;
  item.textContent=message;
  root.appendChild(item);
  requestAnimationFrame(()=>item.classList.add('show'));
  setTimeout(()=>{item.classList.remove('show');setTimeout(()=>item.remove(),250)},4500);
}

/* CSP bloqueia atributos de evento inline (onclick, oninput etc.) no HTML gerado
   dinamicamente, pois script-src é 'self' sem unsafe-inline. HTML gerado usa
   data-action/data-args (clique) e data-oninput (digitação); este delegator despacha. */
const dataArgs=arr=>apiEscape(JSON.stringify(arr));
document.addEventListener('click',event=>{
  const backdrop=event.target.closest('.modal-backdrop');
  if(backdrop&&event.target===backdrop){closeModal();return}
  const target=event.target.closest('[data-action]');
  if(!target)return;
  const action=window[target.dataset.action];
  if(typeof action!=='function')return;
  const args=target.dataset.args?JSON.parse(target.dataset.args):[];
  action(...args);
});
document.addEventListener('input',event=>{
  const target=event.target.closest('[data-oninput]');
  if(!target)return;
  const handler=window[target.dataset.oninput];
  if(typeof handler==='function')handler(target.value);
});
document.addEventListener('change',event=>{
  const target=event.target.closest('[data-onchange]');
  if(!target)return;
  const handler=window[target.dataset.onchange];
  if(typeof handler==='function')handler(target.value,target);
});
document.addEventListener('keydown',event=>{
  if(event.key==='Escape'&&$('.modal-backdrop'))closeModal();
});

document.addEventListener('DOMContentLoaded',()=>{
  if(localStorage.getItem('orbitaTheme')==='dark')document.body.classList.add('dark');
  document.querySelectorAll('.nav-item[data-page]').forEach(b=>b.onclick=()=>go(b.dataset.page));
  $('#themeToggle').onclick=()=>{document.body.classList.toggle('dark');localStorage.setItem('orbitaTheme',document.body.classList.contains('dark')?'dark':'light')};
  $('#menuButton').onclick=()=>$('.sidebar').classList.toggle('open');
  setInterval(updateClock,1000);
  let lastFocusedElement=null;
  new MutationObserver(()=>{
    const modal=$('.modal');
    if(modal){
      lastFocusedElement=document.activeElement;
      modal.setAttribute('tabindex','-1');
      modal.focus();
    }else if(lastFocusedElement){
      lastFocusedElement.focus();
      lastFocusedElement=null;
    }
  }).observe($('#modalRoot'),{childList:true});
});
