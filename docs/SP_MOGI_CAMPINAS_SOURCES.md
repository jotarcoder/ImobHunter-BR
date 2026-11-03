# SP — fontes públicas Mogi das Cruzes e Campinas (03/11/2026)

## Objetivo
Investigar fonte oficial que permita relacionar **logradouro + número** com **inscrição imobiliária/SQL, setor, quadra, lote e geometria**. Não confundir um mapa de quadras ou busca por inscrição preexistente com a API inversa de endereço.

## Mogi das Cruzes (DDD 11)
- GeoMogi: https://geomogi.mogidascruzes.sp.gov.br/mapa
- Portal de dados abertos CKAN: https://dados.mogidascruzes.sp.gov.br/
- O GeoMogi público oferece busca por **inscrição de lote**, **setor/quadra**, **logradouro** e **unidade fiscal**, e mostra informações de lotes. Essas telas não demonstram, sozinhas, uma API pública por endereço e número com inscrição.
- Documentação pública municipal anterior mostra o Sistema de Recuperação de Informações do Cadastro Imobiliário com setor/quadra/lote, mas não comprova endpoint vigente.
- O CKAN anuncia bases de dados abertos sob CC-BY; o diagnóstico consulta somente os títulos e formatos dos conjuntos, não registros individuais.

## Campinas (DDD 19)
- Metadados oficiais: https://campinas.sp.gov.br/sites/metadadosgeoespaciais
- Página do serviço: https://portal-adm.campinas.sp.gov.br/servico/consultar-metadados-espaciais
- A consulta pública de metadados é gratuita, mas parte das camadas está disponível gradualmente; o fornecimento de certos SHPs exige requerimento com login.
- Não foi comprovada inscrição individual pesquisável por endereço via endpoint público.

## Investigação técnica / gate
- Script `scripts/probe_sp_mogi_campinas.py`: lê apenas HTML/JavaScript públicos, rotas técnicas não sensíveis e metadados CKAN de até 5 pesquisas de 8 resultados. Limites de resposta e fontes no próprio domínio; não usa credenciais, CAPTCHA, SQL por proximidade ou dados de contribuintes.
- Workflow `.github/workflows/sp-mogi-campinas-probe.yml`: ação de descoberta, sem compilação, publicação ou R2.
- [ ] Identificar camadas públicas de endereço/numeração predial e lote com vínculo oficial.
- [ ] Confirmar pelo menos um endereço real, inscrições e geometria quando publicados.
- [ ] Escrever adaptador isolado e testes de regressão, incluir fonte nas Configurações.
- [ ] Incorporar à main apenas código aprovado e fonte fiscal somente após retorno real.
- [x] Não gerar instaladores ou publicar no R2.

**Observação:** consultar uma inscrição já conhecida não é o mesmo que descobrir SQL pelo endereço pesquisado.

## Resultado inicial da busca pública do CKAN

A descoberta real em 03/11/2026 encontrou no CKAN municipal:
- **CADASTRO IMOBILIÁRIO**: conjunto público com 6 recursos CSV, localizado tanto por pesquisa de cadastro quanto de quadras.
- **LISTA DE LOGRADOUROS - VISÃO FINANÇAS**: conjunto público em CSV.
- **LOGRADOUROS MOGI DAS CRUZES - SP - DNE CORREIOS**: cadastro separado de logradouros.

A presença dos conjuntos não comprova os campos. A próxima execução inspeciona somente **metadados de publicação e cabeçalhos de até três CSVs por conjunto**, com leitura parcial, sem capturar linhas ou dados de cidadãos. Verificar qualidade e autorização antes de qualquer vínculo fiscal.

Evidência da descoberta inicial: https://github.com/jotarcoder/ImobHunter-BR/actions/runs/41709239199

### Conferência de esquema cadastral por ano
Os primeiros CSVs da base são arquivos de IPTU/ITBI de **2016–2018**, com `cadastro_id`, `logradouro`, `nro_imov_qda`, `bairro` e campos financeiros. **Isso não comprova SQL atual e não autoriza exibir valores tributários.**

O registro específico de **CADASTRO IMOBILIÁRIO** não declara licença própria no CKAN (`license_id` vazio), embora o portal apresente uma orientação genérica de reutilização. É necessário verificar a licença aplicável antes de incorporar automaticamente os arquivos ao produto comercial. A descoberta não baixa nem persiste dados de contribuinte.

A próxima sondagem seleciona os **cabeçalhos mais recentes das famílias `pmmc_imobiliario_*`, `pmmc_iptu_*` e `iptu_itbi_*`** para confirmar se há endereçamento, quadra/lote e inscrição individual.
