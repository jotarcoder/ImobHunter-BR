# Recife/PE e Porto Alegre/RS — fontes municipais com uso verificável

Integração local-first. Esta mudança **não** inclui os CSVs de cidadãos, KMZ, PITEMX,
bancos SQLite, tokens, segredos ou instaladores no repositório. Nenhuma publicação R2.

## Porto Alegre — ArcGIS REST DMWEB e SMF

Origem municipal: `https://gis-smamus.portoalegre.rs.gov.br/server/rest/services/`.

- `01_PUBLICACOES/dmweb_lotes_fiscais/MapServer/0`: polígonos de lotes
  com `id_lotes`, setor, `qtd` (quarteirão) e bairro.
  A descrição da prefeitura estima extração da Fazenda em **19/12/2024**;
  não afirmar cadastro atualizado automaticamente.
- `.../MapServer/3`: **tabela**, não polígono; atributos urbanísticos vinculados
  por `id_lotes` aos lotes da camada 0.
- `.../MapServer/4`: **tabela** de `parcel_area`, `zone_percent`,
  `concat_zone_percent` e `zoned_parcel_percent`; ligação pelo mesmo `id_lotes`.
- `.../MapServer/5`: **tabela** com `json_front` por `id_lotes`.
  O programa registra apenas disponibilidade de informação; não replica o JSON
  bruto de até 80 mil caracteres.
- `POA___Consultas_MIL1/MapServer/98`: polígonos oficiais SMF para fallback.
  `NUMBLOCO` é uma **chave para vincular lote fiscal ao cadastro da SMF**,
  não é número de IPTU, SQL, número sequencial de lote ou `id_lotes` DMWEB.
  `QUARTEIRAO` é quarteirão, não automaticamente quadra de loteamento.
  O campo `MATRICULA` representa o identificador de **servidor municipal editor**
  e nunca deve alimentar a matrícula imobiliária.

A consulta por endereço geocodificado retorna somente **candidatos espaciais**,
sem afirmar correspondência predial individual. A união das tabelas 3/4/5 só
ocorre para IDs **numéricos e iguais** de `id_lotes` da camada 0. Erros nas
tabelas relacionadas não anulam a geometria já encontrada. O endpoint publica
a geometria em TM-POA na camada 0 e em Web Mercator na SMF; o cliente pede
`outSR=4326` para desenho no mapa (sem assumir coordenadas brutas projetadas).

Os arquivos de exportação `.kmz` e `.pitemx` fornecidos pelo usuário são
**apontadores** para o MapServer: o KMZ contém um NetworkLink e o PITEMX
contém uma URL do serviço. Não armazenam a base completa dos lotes.
Usar a API pública em vez de interpretar essas referências como shapefiles.

## Recife — dados abertos de IPTU 2025/2026

Fonte: `https://dados.recife.pe.gov.br/dataset/imposto-predial-e-territorial-urbano-iptu`
e metadados municipais com licença declarada ODbL; avaliar atribuição e as
condições da ODbL para distribuição de bases derivadas.

CSV do usuário (ambos UTF-8 e delimitados por ponto e vírgula):
- Exercício **2025**: 427.419 linhas originais, 425.192 com rua e número numérico indexáveis.
- Exercício **2026**: 422.910 linhas originais, 420.901 com rua e número numérico indexáveis.

Os dois arquivos foram realmente processados localmente em um SQLite
**descartável de QA** nesta etapa, com 846.093 linhas pesquisáveis.
Não fazem parte do pacote/versão de produção por serem bases municipais
anuais com informações pessoais e fiscais.

O aplicativo permite importar na aba **Configurações** um ou mais CSVs
municipais autorizados. O processamento é streaming e atômico: recria índice
local em `~/.imobhunter/recife/iptu_publico.sqlite3`; não usa nuvem, Workers,
licenças ou R2. Em uma pesquisa com rua e número exatos, consulta o exercício
mais recente instalado e retorna até 30 candidatos, com diagnóstico de
ambiguidade. Não associa inscrição a imóvel a partir de nome ou número
de contribuinte, nem presume unicidade quando há apartamentos.

**Somente campos permitidos no SQLite:** ano fiscal, logradouro, número,
complemento, bairro, cidade implícita Recife/PE, área de terreno, área construída,
coordenadas válidas, tipo de uso, CEP e código do logradouro. A aplicação **não
copia** número de contribuinte, CPF/CNPJ mesmo mascarado, proprietário, valor
venal, valor cobrado de IPTU, débitos nem identificadores individuais. As
coordenadas são pontos publicados, nunca poligonais. O SQL/IPTU fica vazio.

## Critérios de aceite e publicação

1. `pytest` para CSV inválido, seleção anual, preservação atômica e sigilo;
   testes ArcGIS com `MockTransport` para tabelas 3/4/5, fallback SMF e SQL vazio.
2. `ruff`, `compileall`, smoke do mapa Qt e testes anteriores aprovados.
3. Homologação manual do importador Windows usando os arquivos reais do usuário
   antes de distribuir instaladores Windows, Linux e macOS.
4. Sem publicação no R2 antes da homologação dos quatro pacotes.
