# Contribuindo com o Orbita HRM

Obrigado pelo interesse! Este é um projeto stdlib-only (Python puro no backend, JS puro no frontend, sem build step) — mantenha essa filosofia em qualquer contribuição.

## Rodando o projeto localmente

```powershell
python server.py
```

Abra `http://localhost:4173`. Veja o [README](README.md) para logins de demonstração e o [docs/COMO-FUNCIONA.md](docs/COMO-FUNCIONA.md) para entender a arquitetura antes de mexer no código.

## Testes

```powershell
python -m unittest discover -s tests -v
```

Toda mudança em código deve manter a suíte passando. Se adicionar uma funcionalidade, adicione o teste correspondente em `tests/`.

## Antes de abrir um Pull Request

1. Rode a suíte de testes.
2. Atualize `CHANGELOG.md` (seção `[Unreleased]`) descrevendo a mudança.
3. Não adicione dependências externas de runtime (Python stdlib e JS puro apenas) — dependências de desenvolvimento/CI (lint, testes) podem ser discutidas em separado.
4. Não commite segredos, tokens, ou dados pessoais reais — o ambiente é exclusivamente local/demonstrativo.
5. Siga o padrão de commits existente no histórico (mensagem objetiva na primeira linha, contexto no corpo quando necessário).

## Reportando vulnerabilidades

Não abra uma issue pública para vulnerabilidades de segurança. Siga o processo descrito em [SECURITY.md](SECURITY.md).

## Dúvidas de arquitetura

Consulte [docs/COMO-FUNCIONA.md](docs/COMO-FUNCIONA.md) — cobre o modelo de dados, autenticação/autorização, os principais fluxos e os padrões específicos deste projeto (como o delegator de eventos usado por causa da CSP).
