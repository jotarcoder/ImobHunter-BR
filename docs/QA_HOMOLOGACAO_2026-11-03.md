# Homologação técnica — ImobHunter-BR
**Data-base:** 03/11/2026  
**Commit auditado:** `521876e07bc96fcb2f3dfab80074578b43cb1669` (`main`)  
**Escopo:** testes de regressão, fontes cadastrais reais, interface/mapeamento, dossiês/exportações, configurações, inteligência de mercado, licenças e critérios de futura distribuição.  
**Regra:** **NÃO publicar no Cloudflare R2**, NÃO gerar instaladores, NÃO disparar release, NÃO editar credenciais nem alterar produção.

## Legenda de homologação
- **Aprovado (automatizado):** validação determinística da lógica ou do fluxo local; não comprova serviço externo em produção.
- **Retorno real confirmado:** consulta ao endpoint municipal via adaptador, com dados e/ou geometria obtidos ao vivo.
- **Parcial:** fonte responde, mas não oferece todos os atributos ou a correspondência exata solicitada.
- **Bloqueado:** fonte retornou erro externo e exige reavaliação, não um dado inventado.
- **Pendente manual:** requer sistema operacional nativo, instalação, credenciais autorizadas ou inspeção visual.

## 1. Ponto de partida: CI atual da main
- CI: https://github.com/jotarcoder/ImobHunter-BR/actions/runs/41681488491
- `compileall`: sucesso.
- `pytest`: **328 passaram; 10 pulados; 2 avisos** no runner Python sem Qt desktop.
- `ruff check .`: sucesso.
- Diagnóstico real municipal: executado e reportado; o step é `continue-on-error`, portanto **CI verde não significa que todas as APIs municipais funcionam**.
- PR #164 (Caxias): código consolidado, ainda sem homologação de resposta real. PR #165 (Juiz): inscrição e geometria confirmadas para dois endereços.

## 2. Matriz de fontes reais — amostra por endereço
Base: relatório do mesmo CI (18 casos; não equivale a cobertura cadastral de todos os logradouros).

| Município | Evidência observada | Situação |
| --- | --- | --- |
| São Paulo capital/SP | 1 registro com SQL/identificador e polígono | Retorno real confirmado no caso testado |
| Praia Grande/SP | 40 polígonos; inscrição não retornada | Parcial |
| Rio de Janeiro/RJ | 20 polígonos; inscrição não retornada | Parcial |
| Belo Horizonte/MG | 40 registros com identificadores e polígonos | Retorno da camada confirmado; verificar semântica fiscal por município |
| Santos/SP | 40 polígonos; inscrição não retornada | Parcial |
| Bertioga/SP | Certificado TLS não validado (`CERTIFICATE_VERIFY_FAILED`) | Bloqueado; **não** desabilitar TLS |
| Brasília/DF | 40 registros com identificadores e polígonos | Retorno da camada confirmado; não chamar genericamente de SQL/SP |
| Goiânia/GO | 40 polígonos; inscrição não retornada | Parcial |
| Blumenau/SC | 38 polígonos; inscrição não retornada | Parcial |
| Joinville/SC | Av. Aluísio Pires Condeixa 2550: inscrição, quadra/lote e polígono | Retorno real confirmado |
| São Bento do Sul/SC | Rua Benjamin Constant 118: inscrição/quadra/lote/polígono | Retorno real confirmado |
| São Bento do Sul/SC | Rua Jorge Lacerda 75: 2 lotes com inscrição/quadra/lote/polígono | Retorno real confirmado; endereço com múltiplos lotes |
| Caxias do Sul/RS | Rua Alfredo Chaves 1333: `ConnectTimeout` | **Não homologado ao vivo** |
| Juiz de Fora/MG | Av. Brasil 2680: inscrição, área e polígono; sem quadra/lote | Parcial |
| Juiz de Fora/MG | Av. Brasil 1512: inscrição, área e polígono; sem quadra/lote | Parcial |
| Recife/PE | `ConnectTimeout` | Bloqueado |
| Porto Alegre/RS | Av. Ipiranga 6681: 40 polígonos sem SQL individual confirmado | Parcial; polígonos da região não provam o lote exato |
| Porto Alegre/RS | Praça Marechal Deodoro 101: 40 polígonos sem SQL individual confirmado | Parcial; idem |

**Total:** 8 cenários com SQL/inscrição reportados, 7 com registros sem esse identificador e 3 erros externos. Os 8 não são equivalentes em semântica; cada um usa atributos e regras municipais específicos. Não inferir IPTU de campo de lote nem proprietário de registro cadastral.

## 3. Fluxos de desktop e aplicação
O CI padrão instala a opção `dev`, não a opção `desktop`, por isso **10 testes opcionais ficaram pulados**. Esta auditoria adiciona workflow de **QA Linux offscreen com PySide6 fixado** para executar novamente toda a suíte, inclusive testes de janelas reais de Qt, e repetir o smoke de mapas em um segundo processo.

| Área | Cobertura de teste prevista nesta rodada | O que ainda não comprova |
| --- | --- | --- |
| Mapa cadastral | polígonos oficiais, lotes vizinhos, seleção, zoom, destaque, janela em Qt | experiência visual em Windows/macOS reais |
| Dossiê e exportações | consolidação, proveniência, JSON/CSV, reimportação local | aparência final de todas as exportações no desktop |
| Configurações municipais | links específicos, testes de conexão, persistência, importação CSV/GeoJSON/Excel e isolamento por município | disponibilidade de todas as fontes externas |
| Inteligência de mercado | raio, CNPJ geocodificado, filtros, importações, CSV | faturamento real de bases oficiais quando não publicado |
| Licenças | chave, UUID, resposta autorizada/negada, falhas de rede, proteção local | ativação real/reabertura usando chave paga válida e Worker de produção |
| Site/servidor | healthcheck e landing, políticas e qualidade web estática | verificação de navegador real, Cloudflare WAF e WhatsApp em produção |
| Instalação | contratos/arquivos de build por teste estático | instalação, assinatura e execução dos 4 pacotes |

### Evidência do QA desktop (sem build)
Workflow `.github/workflows/qa-homologacao.yml` do PR desta auditoria. O status de sua execução deve ser consultado no GitHub Actions antes de concluir a homologação Qt. O workflow instala dependências desktop, executa `compileall`, todos os testes Python com Qt, Ruff e um segundo smoke de mapa/Qt em processo independente. **Não contém AWS CLI, R2, build de instalador nem etapa de publicação.**

## 4. Pendências antes da futura versão
1. **Fontes externas bloqueadas:** Caxias (timeout), Recife (timeout), Bertioga (TLS). Registrar offline, testar novamente com certificado válido/documentação oficial; sem `verify=False`, sem bypass de autenticação.
2. **Inscrições incompletas:** Santos, Praia Grande, RJ, Goiânia, Blumenau, Porto Alegre; alguns serviços só fornecem geometria; Juiz de Fora fornece inscrição/geom., mas quadra e lote vazios nos endereços testados.
3. **Correspondência exata:** não classificar lote vizinho como inscrição individual nem usar polígono da região como prova da porta solicitada.
4. **Homologação manual:** Windows, Linux AppImage, macOS Intel e Apple Silicon; testar licença ativada, reabertura, atualização, exportação e interface por sistema. Esta rodada não compila esses pacotes.
5. **Produção:** teste real de fluxo de ativação em Cloudflare Worker/D1 e teste manual do site/downloads exigem credenciais e/ou revisão humana autorizada; não alterar dados reais.
6. **Distribuição:** congelar versão **somente depois** de novas modificações, QA completa, quatro pacotes verificados e autorização explícita de publicação no R2.

## 5. Referências e não-objetivos
- GitHub Actions CI de referência: https://github.com/jotarcoder/ImobHunter-BR/actions/runs/41681488491
- Fonte de evidência municipal: `scripts/live_municipal_cadastral_evidence.py`.
- Qt e mapas: `tests/test_cadastral_map_desktop.py`, `tests/test_cadastral_map.py`.
- Fontes e importações: `tests/test_custom_municipal_sources.py`, `tests/test_municipal_endpoints_stage3.py`.
- Inteligência/exports: `tests/test_market_intelligence.py`, `tests/test_market_export.py`, `tests/test_export.py`.
- Licenciamento: `tests/test_licensing.py`.
- **Não realizado:** rebuild, publicação de release, deploy em produção ou upload Cloudflare R2.
