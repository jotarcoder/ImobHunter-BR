# ImobHunter-BR

**Inteligência imobiliária local-first para prospecção de imóveis no Brasil.**

O ImobHunter-BR foi projetado para corretores, imobiliárias, construtores e captadores que precisam pesquisar, cruzar e organizar informações imobiliárias com o máximo possível de processamento realizado no computador do usuário.

## O que o projeto entrega
- Pesquisa por endereço, número e estrutura cadastral quando disponível.
- Número da matrícula no dossiê quando presente em fonte autorizada, com encaminhamento ao RI Digital para conferência quando não localizado.
- Reconciliação de registros e indicação de confiança/proveniência.
- Arquitetura local-first: processamento pesado, cache e dados de pesquisa permanecem no PC sempre que possível.
- Integrações por fontes públicas e autorizadas, sem bases vazadas e sem contornar autenticação ou CAPTCHA.
- Cobertura planejada para todo o Brasil, evoluindo fonte por fonte conforme disponibilidade e regras de cada órgão.
- Aplicativo desktop para Windows, Linux e macOS.

## Downloads
| Plataforma | Download |
|---|---|
| Windows | [Instalador .exe](https://pub-6bd1ab819504434691f4832d98de3cb6.r2.dev/ImobHunter-BR-Setup-Windows-0.1.16.exe) |
| Linux | [AppImage](https://pub-6bd1ab819504434691f4832d98de3cb6.r2.dev/ImobHunter-BR-Linux.AppImage) |
| macOS Intel | [.dmg](https://pub-6bd1ab819504434691f4832d98de3cb6.r2.dev/ImobHunter-BR-macOS-Intel.dmg) |
| macOS Apple Silicon | [.dmg](https://pub-6bd1ab819504434691f4832d98de3cb6.r2.dev/ImobHunter-BR-macOS-AppleSilicon.dmg) |

**[Central de releases](https://github.com/jotarcoder/ImobHunter-BR/releases/latest)**

## Landing page
A landing page pública e institucional apresenta o produto, fontes, políticas e downloads. Ela não executa as funções de pesquisa do aplicativo.

## Segurança e privacidade
O projeto segue uma regra central: não transferir processamento pesado e dados de pesquisa para o servidor sem necessidade. Credenciais e serviços remotos serão tratados separadamente.

Não fazem parte do projeto: bases vazadas, bypass de CAPTCHA, bypass de autenticação ou coleta indiscriminada de dados pessoais fora da finalidade e das permissões aplicáveis.

Consulte: docs/PRIVACY_POLICY.md, docs/TERMS_OF_USE.md e docs/DATA_SOURCE_POLICY.md.

## Desenvolvimento
Instalação: python -m pip install -e ".[dev,desktop]"
Testes: python -m compileall -q imobhunter tests && pytest && ruff check .
Execução desktop: python -m imobhunter

## Release
O pipeline gera quatro artefatos: Windows .exe, Linux .AppImage, macOS Intel .dmg e macOS Apple Silicon .dmg. Os binários são publicados como assets da release do GitHub e não são versionados no repositório.

### Integração autenticada CNPJ (Conecta gov.br)

A consulta autenticada é opcional e **enriquece somente CNPJs já encontrados pelo índice local autorizado**; ela não substitui uma base de estabelecimentos para descobrir empresas por endereço ou raio. Configure no ambiente de execução:

- `IMOBHUNTER_CNPJ_API_CLIENT_ID`
- `IMOBHUNTER_CNPJ_API_CLIENT_SECRET`
- `IMOBHUNTER_CNPJ_API_CPF_USUARIO`

O cliente consulta os serviços Básica, Empresa e QSA com token OAuth2, timeout curto e cache de token em memória. Sem as três variáveis, o comportamento anterior baseado em CSV/JSON permanece inalterado. Se a API falhar, o resultado local continua disponível e a falha é registrada nos atributos do resultado. **Não coloque segredos no repositório, no instalador desktop ou em arquivos distribuídos aos clientes.** O acesso depende de credenciais e autorização válidas do Conecta gov.br/SERPRO.
