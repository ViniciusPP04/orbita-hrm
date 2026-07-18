# Orbita HRM — MVP local

Protótipo funcional de uma plataforma de gestão de RH, com API local persistida em SQLite e sem dependências externas de runtime.

Para entender a arquitetura, o modelo de dados e os principais fluxos da aplicação, veja [docs/COMO-FUNCIONA.md](docs/COMO-FUNCIONA.md).

Versão atual: **0.3.0**. Fornecedor: **Orbita**.

## Executar

No PowerShell, dentro desta pasta:

```powershell
python server.py
```

Depois, abra `http://localhost:4173` no navegador. A aplicação agora precisa ser executada por esse servidor local para que autenticação, SSO e API funcionem.

No primeiro start, o servidor cria automaticamente `orbita_hrm.db` (banco SQLite, ignorado pelo git) e popula os dados de demonstração. Reinicie o servidor à vontade — os dados persistem entre execuções.

Por padrão, o segredo usado para assinar tokens é gerado uma vez e guardado em `.secret_key` (também ignorado pelo git). Para definir o seu, exporte `ORBITA_HRM_SECRET` antes de iniciar o servidor.

## Login de demonstração

Use a senha `123456` com `admin@orbita.com`, `manager@orbita.com`, `cfo@orbita.com`, `rh@orbita.com`, `treasury@orbita.com` ou `employee@orbita.com`. O botão SSO simula um login OIDC como administrador. Colaboradores cadastrados pela tela de Admin/RH também recebem a senha inicial `123456`.

## Testes

```powershell
python -m unittest discover -s tests -v
```

## Docker

```powershell
docker build -t orbita-hrm .
docker run -p 4173:4173 -v orbita_hrm_data:/app orbita-hrm
```

O volume mantém `orbita_hrm.db` entre execuções do container.

## Escopo entregue

- Dashboard com indicadores reais (colaboradores, pendências, fechamento de folha), últimas solicitações, aniversariantes do mês e evolução do quadro
- Listagem, busca e filtros (departamento/status) de colaboradores, sempre a partir da mesma base de dados usada pela API, com exportação para CSV
- Cadastro, edição e desligamento/reativação de colaborador, com matrícula sequencial `MAT-00000X`, foto e organograma (árvore por gestor)
- Benefícios por colaborador (adicionar/remover)
- Documentos com upload de arquivo real, download autenticado e assinatura ("marcar como assinado")
- Solicitações de ponto, férias (com dias e desconto automático do saldo), horas extras e alteração cadastral, com aprovação por RH/Admin/Manager e motivo obrigatório em toda recusa
- Ponto com histórico dia a dia e banco de horas calculado a partir dos registros reais, disponível para todos os papéis
- Consulta de folha com holerite imprimível e histórico de fechamentos, disponíveis para todos os papéis
- Visualização de salário e solicitação de reajuste por colaborador
- Reajuste salarial com confirmação sequencial obrigatória de Gerente e CFO
- Log de auditoria (Admin) com as últimas 200 ações registradas no sistema
- API protegida por JWT assinado (segredo não versionado) e cabeçalhos HTTP de segurança
- Senhas armazenadas com hash (PBKDF2-HMAC-SHA256, salt por usuário) — nunca em texto puro
- Papel de permissão (`role`) e cargo exibido (`jobTitle`) são campos distintos: editar o cargo de alguém nunca altera o nível de acesso dela
- Rate limiting no login (5 tentativas por e-mail a cada 5 minutos)
- Logout revoga o token no servidor, além de limpar a sessão local
- Validação de formato de e-mail e CPF no cadastro de colaborador
- Modais fecham com Esc e devolvem o foco ao elemento que os abriu
- Persistência real em SQLite (`db.py`): sobrevive a reinícios do servidor
- SSO demonstrativo e área administrativa exclusiva de Admin
- Endpoint administrativo `GET /api/users` (Admin/RH) com dados mock de CPF, CTPS, endereço, matrícula e nome da mãe
- Alternância de tema claro/escuro (preferência de UI, guardada em `localStorage`)
- Suíte de testes automatizados (`unittest`, sem dependências externas) cobrindo autenticação, RBAC, todos os endpoints da API e checagens estáticas anti-regressão de CSP
- Dockerfile e workflow de CI (GitHub Actions)

Cálculos trabalhistas reais (CLT, INSS, IRRF) e integrações de identidade com um provedor real permanecem como próximos incrementos — fora do escopo deste MVP.

## Segurança e elegibilidade

Consulte [SECURITY.md](SECURITY.md), [o banco de advisories](docs/SECURITY-ADVISORIES.md) e [a aderência ao checklist CVE](docs/CVE-ELIGIBILITY.md). O ambiente é exclusivamente local e não deve receber dados pessoais reais.
