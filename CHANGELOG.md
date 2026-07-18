# Changelog

Todas as mudanças relevantes deste projeto serão registradas aqui.

## [Unreleased]

### Changed (rebranding)

- Nova identidade visual do produto ("Orbita HRM", fornecedor Orbita): paleta grafite + âmbar (era navy + azul) e novo logo — um ícone de órbita (ponto central com anel elíptico e satélite) em SVG inline, substituindo a marca de letra única. Renomeados também: banco de dados (`orbita_hrm.db`), variável de ambiente do segredo (`ORBITA_HRM_SECRET`), domínio dos e-mails de demonstração (`@orbita.com`) e as chaves de `localStorage` (prefixo `orbita*`). Sem mudança de comportamento — é só identidade.

### Added (gestão de pessoas, documentos, ponto, férias, folha e auditoria)

- Colaboradores: edição de cadastro, desligar/reativar, troca de foto, filtros por departamento/status, exportação de CSV, benefícios por colaborador (adicionar/remover) e organograma (árvore por gestor).
- Dashboard operacional (Admin/RH/Tesouraria) com últimas solicitações, ações rápidas, aniversariantes do mês e evolução do quadro (gráfico de barras).
- Documentos: upload real de arquivo (armazenado como base64 no SQLite), download autenticado e assinatura ("marcar como assinado" — sem e-signature real, decisão de escopo).
- Ponto: histórico dia a dia com banco de horas calculado a partir dos registros reais, disponível também para o papel Funcionário (antes só via um resumo estático sem histórico nem botão de registrar ponto).
- Aprovações: campo de dias ao solicitar férias (valida contra o saldo do colaborador) e motivo obrigatório ao recusar qualquer solicitação, registrado e exibido no histórico.
- Folha de pagamento: holerite imprimível (`window.print()`, sem geração de PDF no servidor — decisão de escopo) e histórico de fechamentos, disponíveis para todos os papéis (antes só Admin/RH/Tesouraria viam o agendamento de fechamento).
- Portal do colaborador ("Meu espaço"): saldo de férias e lista de benefícios pessoais.
- Log de auditoria na Administração (Admin), listando as últimas 200 ações registradas no sistema.

### Fixed (segurança/RBAC)

- Campo "Cargo" no cadastro/edição de colaborador gravava diretamente na coluna `role`, a mesma usada em todo o controle de acesso (`require(conn, "Admin", "RH", ...)`). Editar o cargo de um colaborador silenciosamente corrompia seu nível de permissão (e a navegação já rendered no front, via `limitedRole()`), deixando-o sem nenhum papel reconhecido pelo backend. O cadastro de colaborador tinha o mesmo problema: o `<select>` "Cargo" enviava valores como "Product Manager" diretamente como `role`. Corrigido separando `job_title` (cargo, texto livre, exibido na UI) de `role` (papel de RBAC, fixo em `Funcionário` na criação e nunca editável pelo formulário de edição).
- Item de navegação "Aprovações" ficava oculto para o papel `Funcionário`, removendo a única forma de o próprio colaborador abrir o formulário de nova solicitação — ele não conseguia pedir férias, ajuste de ponto ou hora extra pela UI. O backend já escopava corretamente as solicitações por `employee_id` para esse papel; faltava só exibir a navegação.

### Added

- Rate limiting no login: 5 tentativas falhas por e-mail em 5 minutos bloqueiam novas tentativas (HTTP 429) até o contador expirar; resposta correta é surfaçada como alerta na tela de login.
- Novo endpoint `POST /api/auth/logout`: revoga o token no servidor (lista de revogação em memória, com limpeza automática de tokens já expirados) em vez de só limpar o `localStorage` no cliente.
- Validação de formato de e-mail e CPF no cadastro de colaborador (`POST /api/employees`), além da validação HTML5 nativa do formulário.
- Modais fecham com Esc e devolvem o foco ao elemento que os abriu, via `MutationObserver` genérico em `#modalRoot` — não precisou tocar em cada função que abre um modal.
- Cobertura de testes para os endpoints que não tinham nenhum teste: documentos, ponto, notificações, `/api/portal`, `/api/admin/overview`, agendamento de fechamento de folha, além da nova validação e do rate limiting/logout.
- `tests/test_static_checks.py`: guarda-corpo leve (regex, sem dependência nova) que falha o build se algum `onclick="..."`/`style="..."` inline for reintroduzido, ou se uma página nova for registrada em `pages` sem uma entrada correspondente em `meta` — as duas classes de bug reais encontradas na sessão anterior de testes manuais em navegador.
- Sistema de toasts (`toast()` em `app.js`) substituindo todo `alert()`/`prompt()` nativo do navegador — não trava mais a página e segue o tema claro/escuro do app.
- Modal de busca de colaborador (antes era um `prompt()` bloqueante seguido de um modal de resultado separado; agora é um único modal com busca e resultado inline).
- Card "Últimas solicitações" no dashboard operacional, com dados reais (últimas solicitações salariais e genéricas), preenchendo o espaço vazio deixado pela remoção do conteúdo fake do dashboard original.
- Ícone consistente nos estados vazios (`.empty::before`) em toda a aplicação.

### Fixed (melhorias estéticas)

- Contraste quebrado nos botões de "Ações rápidas" no tema escuro: cor de texto fixa não era sobrescrita pelas variáveis do modo escuro, deixando o texto quase ilegível.
- Campo de busca de Colaboradores cortava o placeholder ("Buscar por nome ou matríc…"); largura aumentada.
- Cabeçalho de página (título + botões de ação) espremia os botões ao lado do título em telas estreitas; agora empilha verticalmente abaixo de 620px.

## [0.2.0] - 2026-07-15

### Added

- Persistência real em SQLite (`db.py`) substituindo o estado em memória do servidor: colaboradores, documentos, ponto, solicitações e agendamento de folha sobrevivem a reinícios.
- Senhas com hash PBKDF2-HMAC-SHA256 (salt por usuário) no lugar da comparação em texto puro; segredo do JWT gerado e persistido localmente em vez de hardcoded no código-fonte.
- Novo endpoint `/api/requests` (ponto, férias, horas extras, alteração cadastral) com aprovação por RH/Admin/Manager, substituindo o fluxo que só existia como estado fake no front-end.
- Usuário de demonstração com papel `RH` (`rh@orbita.com`) — papel usado em várias rotas mas antes inatingível via login demo.
- Suíte de testes automatizados (`unittest`, stdlib apenas) cobrindo autenticação, RBAC, criação de colaborador e os fluxos de aprovação.
- `Dockerfile`, `.dockerignore` e workflow de CI (GitHub Actions) rodando a suíte de testes.

### Fixed

- Front-end consolidado numa única fonte de verdade: a página "Colaboradores" e os indicadores do dashboard liam um array local desatualizado em vez dos dados reais da API — colaboradores cadastrados agora aparecem de forma consistente em toda a aplicação.
- Menu "Aprovações" deixou de ficar oculto para os papéis `Manager` e `CFO`, que precisam aprovar reajustes salariais.
- Menu "Colaboradores" agora fica restrito a `Admin`/`RH`, evitando que a Tesouraria visse um item de navegação que a API sempre rejeitou com 403.
- Carregamento de dados de cada página (dashboard, colaboradores, documentos, admin, aprovações) agora dispara imediatamente após login e após qualquer navegação programática, não apenas em cliques diretos no menu.

### Removed

- `payroll.js`, cuja versão local de folha/aprovações já era inteiramente substituída pelas páginas reais conectadas à API.
- `payroll.css`, cuja única regra (`.approval-steps`) só era usada pelo `payroll.js` removido.

### Fixed (verificação em navegador real)

- CSP (`script-src 'self'`, sem `unsafe-inline`) bloqueava silenciosamente todo `onclick="..."`/`oninput="..."` escrito em HTML gerado dinamicamente — praticamente nenhum botão fora da barra lateral funcionava. Substituído por um delegator central em `app.js` baseado em `data-action`/`data-args`/`data-oninput`.
- Mesma causa-raiz em `style-src`: todo `style="..."` inline também era bloqueado (avatares sem cor de fundo, grids com número errado de colunas). Substituído por classes utilitárias em `styles.css` (`.mt-8`, `.stats-3`, `.muted-text` etc.).
- `meta.admin` nunca era definido após a consolidação do front-end — a página "Administração" abria com o breadcrumb da página anterior travado e as estatísticas presas em "Carregando…" para sempre, porque a exceção interrompia `go()` antes do evento `page:show` disparar.
- `go()` agora tolera uma entrada ausente em `meta` em vez de lançar uma exceção que interrompe o resto da navegação.

## [0.1.0] - 2026-07-15

### Added

- MVP Orbita HRM com gestão de colaboradores, jornada, folha, documentos e aprovações.
- API local mock com autenticação JWT assinada e fluxo SSO demonstrativo.
- Área administrativa, personalização visual e controle de acesso por papéis.
- Artefatos de segurança e processo de reporte responsável.
