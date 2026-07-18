# Como funciona o Orbita HRM

Este documento explica a arquitetura, o modelo de dados e os principais fluxos da aplicação, para quem for dar manutenção ou continuar o desenvolvimento. Para instruções de instalação/execução, veja o [README](../README.md).

## Visão geral

Orbita HRM é um MVP de gestão de RH: cadastro de colaboradores, ponto, férias, documentos, folha de pagamento e aprovações, com controle de acesso por papel. É um projeto **100% stdlib** — sem frameworks, sem `npm`, sem dependências externas de runtime — para servir como referência de uma aplicação web completa construída só com Python (`http.server`) e JavaScript puro no navegador.

## Arquitetura

```
navegador  <-- HTML/CSS/JS puro, sem build step -->  server.py  <-- SQLite -->  orbita_hrm.db
```

- **Backend**: `server.py`, um `ThreadingHTTPServer` (`http.server` da stdlib) que serve os arquivos estáticos e responde às rotas `/api/*` com JSON.
- **Persistência**: `db.py`, camada de acesso ao SQLite (`orbita_hrm.db`, criado automaticamente no primeiro start, ignorado pelo git).
- **Frontend**: HTML/CSS/JS servidos como arquivos estáticos pelo próprio `server.py`. Sem React/Vue/bundler — o roteamento de "páginas" é feito trocando o `innerHTML` de uma `<div>` central.
- **Sem build step**: qualquer edição em `.js`/`.css`/`.html` é refletida direto ao recarregar a página (não há transpilação nem bundling).

### Por que não há dependências externas

Decisão de projeto deliberada: o objetivo é que qualquer pessoa consiga rodar (`python server.py`) e ler o código-fonte inteiro sem precisar entender um framework. Isso tem custos assumidos (sem JSX, sem CSS-in-JS, template strings HTML concatenadas manualmente) mas mantém o projeto auditável de ponta a ponta.

## Estrutura de arquivos

```
server.py         Rotas HTTP (GET/POST/PATCH/DELETE), regras de autorização, JWT
db.py             Schema SQLite, seed de dados de demonstração, hash de senha
index.html         Casca da SPA: login, sidebar, header, <div id="pageContent">
app.js             Roteador de páginas (go()), tema, relógio, sistema de toast,
                   delegator de eventos (data-action/data-oninput/data-onchange)
api.js             Cliente HTTP (api()), sessão, login/logout, documentos (upload/
                   download/assinatura), cadastro de colaborador, Administração (stats)
employees.js       Página Colaboradores (CRUD, filtros, CSV, benefícios, foto,
                   histórico de ponto por colaborador), Organograma, dashboard
                   operacional (Admin/RH/Tesouraria)
functional.js      Ponto ("Meu ponto"), Folha ("Folha de pagamento", holerite,
                   histórico de fechamentos), Aprovações, busca, notificações
portal.js          Visão restrita ("Meu espaço") para Funcionário/Manager/CFO,
                   documentos por pessoa
fixes.js           Administração (config, log de auditoria), branding, SSO
styles.css         Estilos principais + media queries responsivas
branding.css / functional.css / portal.css   Estilos por módulo
tests/             Suíte unittest (test_db.py, test_server.py, test_static_checks.py)
docs/              Este documento + advisories de segurança
```

Cada arquivo `.js` define funções globais (sem módulos ES/`import`) que ficam disponíveis para todos os outros, na ordem em que são carregados pelo `<script>` no `index.html`: `app.js → api.js → employees.js → functional.js → fixes.js → portal.js`. Essa ordem importa: arquivos carregados depois podem sobrescrever `pages.xxx` definido por um arquivo anterior (é assim que `portal.js` troca o dashboard/folha/ponto "completos" pela versão restrita quando o papel é Funcionário/Manager/CFO).

## Modelo de dados (SQLite)

| Tabela | Para quê |
|---|---|
| `users` | Colaboradores: dados cadastrais, `role` (permissão), `job_title` (cargo exibido), salário, saldo de férias, foto, jornada contratual |
| `documents` | Documentos por colaborador, com arquivo em base64 (`file_data`), versão, assinatura |
| `point_events` | Batidas de ponto (Entrada / Início do intervalo / Fim do intervalo / Saída) |
| `salary_requests` | Reajustes salariais, com fluxo de aprovação em duas etapas |
| `requests` | Solicitações genéricas (férias, ajuste de ponto, hora extra, alteração cadastral) |
| `payroll_schedule` | Linha única com o status do fechamento da competência atual |
| `payroll_history` | Histórico de fechamentos já programados |
| `notifications` | Notificações por usuário (ou globais, quando `user_id` é nulo) |
| `benefits` | Benefícios por colaborador (nome + valor mensal) |
| `audit_log` | Trilha de auditoria: quem fez o quê e quando |

### `role` vs `job_title` — não confundir

Esses dois campos parecem sinônimos mas **não são intercambiáveis**:

- **`role`** é o papel de permissão (RBAC): `Admin`, `RH`, `Manager`, `CFO`, `Tesouraria` ou `Funcionário`. É comparado literalmente em toda checagem de autorização no backend (`self.require(conn, "Admin", "RH")`) e no frontend (`limitedRole()`, visibilidade de itens de menu). Só é definido na criação do colaborador (sempre `Funcionário`, exceto para os usuários de seed) e nunca é alterado pelo formulário de edição.
- **`job_title`** é o cargo exibido na UI ("Engenheiro de Software Sênior", "Gerente de Pessoas & Cultura" etc.) — texto livre, editável, sem nenhum efeito em permissões.

Essa separação existe porque uma versão anterior da aplicação usava o mesmo campo para as duas coisas, e editar o "cargo" de alguém corrompia silenciosamente as permissões dela. Ao mexer em qualquer coisa relacionada a colaborador, **nunca reintroduza esse acoplamento**.

## Autenticação e autorização

- Login (`POST /api/auth/login`) valida e-mail/senha (hash PBKDF2-HMAC-SHA256, 200 mil iterações, salt por usuário) e devolve um token assinado (formato JWT: `header.payload.signature`, HMAC-SHA256).
- O segredo de assinatura é lido de `ORBITA_HRM_SECRET` ou gerado uma vez e persistido em `.secret_key` (fora do git).
- O token expira em 1h e é enviado em `Authorization: Bearer <token>` em toda chamada autenticada.
- `POST /api/auth/logout` revoga o token no servidor (lista de revogação em memória) além de limpar o `localStorage` no cliente.
- Rate limiting de login: 5 tentativas falhas por e-mail em 5 minutos bloqueiam novas tentativas (HTTP 429).
- Cada rota do backend decide sozinha quem pode acessá-la, chamando `self.require(conn, "Admin", "RH", ...)` (403 se o papel não bater) ou `self.current_user(conn)` (só exige estar autenticado, sem exigir papel específico).
- No frontend, a mesma lógica é replicada de forma best-effort (esconder itens de menu, esconder botões) — **isso é só UX, nunca segurança**: a autorização real sempre acontece no backend.

## O que cada papel vê

| Papel | Navegação | Observações |
|---|---|---|
| **Admin** | Tudo, incluindo Colaboradores, Organograma e Administração | Único papel com acesso à Administração (config, branding, SSO, log de auditoria) |
| **RH** | Tudo exceto Administração | Pode cadastrar/editar/desligar colaboradores, gerenciar documentos e benefícios |
| **Manager** | Visão restrita ("Meu espaço") + Aprovações | Aprova solicitações do próprio time e a 1ª etapa de reajustes salariais |
| **CFO** | Visão restrita ("Meu espaço") + Aprovações | Aprova a 2ª etapa (final) de reajustes salariais |
| **Tesouraria** | Dashboard/Folha "completos" (não é `limitedRole`) | Único papel que pode programar o fechamento da folha |
| **Funcionário** | Visão restrita ("Meu espaço") + Aprovações | Só vê e gerencia os próprios dados; pode solicitar férias/ajustes |

A função `limitedRole()` (em `portal.js`) define quem recebe a experiência "restrita" (`Meu espaço`, ponto/folha centrados só na própria pessoa): hoje são `Funcionário`, `Manager` e `CFO`. Ponto e Folha são as mesmas páginas para todo mundo (só mostram os dados de quem está logado); o que muda entre papéis é o Dashboard (visão agregada da empresa para Admin/RH/Tesouraria vs. "Meu espaço" para os demais) e a visibilidade de Colaboradores/Organograma/Administração.

## Principais fluxos

### Cadastro e ciclo de vida do colaborador

1. Admin/RH cadastra (`+ Novo colaborador`): campos obrigatórios validados (e-mail, CPF, CTPS, endereço, nome da mãe). Matrícula (`MAT-00000X`) e senha inicial (`123456`) são geradas automaticamente; papel é sempre `Funcionário`.
2. Editar (`Editar`) atualiza cadastro/cargo/departamento/jornada — nunca o papel de permissão.
3. Desligar/Reativar alterna `status` entre `Ativo`/`Inativo`. Colaborador inativo não consegue fazer login.
4. Foto, benefícios e histórico de ponto são geridos a partir do modal de perfil do colaborador.

### Ponto

- Cada clique em "Registrar entrada/intervalo/saída" grava um `point_events` com hora atual.
- O banco de horas é recalculado a cada consulta: soma, por dia, `(minutos trabalhados − 8h)`, considerando um par Entrada→Início do intervalo (ou Entrada→Saída) como período trabalhado.
- Admin/RH também podem lançar correções manuais de ponto para qualquer colaborador (`/api/employees/:id/time/correct`).

### Férias e outras solicitações (Aprovações)

- `+ Nova solicitação`: tipos são Ajuste de ponto, Solicitação de férias, Hora extra e Alteração cadastral. Férias exige quantidade de dias e é validada contra o saldo do colaborador (`vacation_balance`) já na criação.
- Aprovar/Recusar: aprovar uma solicitação de férias desconta os dias do saldo; recusar exige informar um motivo, que fica salvo (`decision_reason`) e visível no tooltip da tabela.
- Reajuste salarial é um fluxo separado (`salary_requests`), com duas etapas obrigatórias: Manager aprova primeiro, CFO aprova depois — só então o novo salário é aplicado.

### Documentos

- Upload (`+ Adicionar documento`, Admin/RH): o arquivo é lido no navegador (`FileReader`), convertido para base64 e enviado no corpo JSON; fica armazenado direto na coluna `file_data` do SQLite (sem um serviço de storage separado — decisão de escopo para um MVP local).
- Download: `GET /api/documents/:id/download` decodifica o base64 e devolve o arquivo com o `Content-Type`/`Content-Disposition` corretos.
- Assinatura: "marcar como assinado" (`signed`, `signed_by`, `signed_at`) — não é uma assinatura eletrônica com validade jurídica, é um registro de confirmação dentro do sistema (decisão de escopo).

### Folha de pagamento

- Cada colaborador vê sua própria competência (salário base, proventos, descontos estimados) e pode abrir o holerite (`Ver holerite`), uma página imprimível via `window.print()` — não há geração de PDF no servidor.
- Só a Tesouraria pode programar o fechamento da competência (`Programar fechamento`); isso grava uma entrada em `payroll_history`, visível a todos no "Histórico de fechamentos".

### Auditoria

- Praticamente toda ação de mutação (criar/editar/desligar colaborador, decidir solicitação, assinar documento, programar fechamento etc.) grava uma linha em `audit_log` via `write_audit()`.
- Só Admin acessa `GET /api/audit-log` (últimas 200 ações), exibido na página Administração.

## Padrões do frontend que vale conhecer

- **Sem `onclick="..."` inline**: a Content-Security-Policy (`script-src 'self'`) bloqueia atributos de evento inline. Todo elemento clicável usa `data-action="nomeDaFuncao" data-args='[...]'`, capturado por um único listener central em `app.js` que chama `window[nomeDaFuncao](...args)`. O mesmo padrão existe para `input` (`data-oninput`) e `change` (`data-onchange`). Há um teste estático (`tests/test_static_checks.py`) que falha o build se um `onclick=`/`style=` inline for reintroduzido.
- **`pages` e `meta`**: cada "página" da SPA é uma função em `pages.<nome>` que devolve uma string HTML, e uma entrada em `meta.<nome> = [kicker, título]` para o cabeçalho. `go(pagina)` troca o conteúdo e dispara o evento `page:show`, que cada arquivo escuta para carregar os dados daquela página via `fetch`.
- **Toasts em vez de `alert()`/`prompt()`**: `toast(mensagem, tipo)` em `app.js`.
- **CSP e estilos inline**: `style-src` também não permite `style="..."` no HTML. Ajustes visuais dinâmicos usam classes utilitárias (`.mt-20`, `.stats-3` etc.) ou, quando o valor é calculado em runtime (como a altura das barras do gráfico de headcount), `elemento.style.propriedade = valor` via JS — isso **não** é bloqueado pela CSP porque não é um atributo HTML, é uma chamada de API do DOM.

## Testes

```powershell
python -m unittest discover -s tests -v
```

- `test_db.py`: schema, seed, hash/verificação de senha.
- `test_server.py`: sobe um `ThreadingHTTPServer` numa porta efêmera contra um banco temporário e cobre autenticação, RBAC, e os principais fluxos de cada módulo.
- `test_static_checks.py`: checagens estáticas (regex) contra as duas classes de bug já encontradas nesta aplicação — atributos de evento/estilo inline bloqueados pela CSP, e páginas registradas em `pages` sem entrada correspondente em `meta`.

## Fora de escopo (deliberado)

- Cálculos trabalhistas reais (CLT, INSS, IRRF).
- Assinatura eletrônica com validade jurídica (hoje é só "marcar como assinado").
- Geração de PDF no servidor (holerite é uma página HTML imprimível).
- Roles/permissões totalmente customizáveis pelo cliente (o conjunto de papéis é fixo no código).
- Armazenamento de arquivo em serviço externo (documentos ficam como base64 no próprio SQLite).
