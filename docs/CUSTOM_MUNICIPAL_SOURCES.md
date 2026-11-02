# Fontes municipais adicionadas pelo usuário

## Configurações > Fontes cadastrais municipais > Minhas fontes municipais

É possível cadastrar uma fonte **sem alterar o código** do ImobHunter-BR:

1. Clique em **+ Adicionar fonte municipal**.
2. Informe **nome da fonte, município e UF**.
3. Informe o **link HTTPS** (se existir). Escolha o tipo ou deixe o aplicativo
   inferir pelo link: WFS, ArcGIS REST ou website informativo.
4. Salve. A fonte aparece na lista com **Testar fonte**, **Importar arquivo**
   e **Remover fonte**. Uma fonte sem link tem as opções de importar/remover.
5. As próximas consultas incluem **somente** as fontes adicionadas que
   correspondem exatamente ao **município e UF** da pesquisa.
6. Ao reiniciar, a lista e as cópias dos arquivos permanecem salvas no
   computador em **~/.imobhunter/municipal_sources/**. Nenhuma informação é
   enviada para Cloudflare R2, GitHub ou para servidores de prefeituras pela
   opção de importar.

## Tipos de link e teste

- **WFS:** o teste consulta GetCapabilities. Nas pesquisas com endereço,
  o adaptador reutiliza a descoberta de camadas de lotes municipais e
  GetFeature/GeoJSON, com limites e diagnósticos.
- **ArcGIS REST:** o teste lê os metadados JSON da camada. Na pesquisa usa
  o endpoint informado, necessariamente finalizado em /FeatureServer/N
  ou /MapServer/N. A localização é estimada por geocodificação, e os
  polígonos são candidatos até confirmação por fonte cadastral.
- **Website:** pode ser salvo e testado, mas **não é tratado como API**.
  Um HTTP 200 não significa que o município disponibilize inscrição, SQL,
  áreas, proprietário ou camadas de lote.

A verificação exige **HTTPS com hostname público**, bloqueia credenciais
embutidas, IPs literais, rede local, redirecionamentos automáticos e
endereços HTTP. TLS permanece ativo. O usuário é responsável por cadastrar
links cujo acesso e uso de dados são autorizados. O programa não cria
endpoints de consulta que a prefeitura não disponibiliza.

## Importar arquivo cadastral da prefeitura

Clique em **Importar arquivo** ao lado da localidade salva. O sistema aceita:

- CSV (separado por vírgula, ponto e vírgula ou tabulação; UTF-8 ou cp1252);
- XLSX (Excel; somente valores calculados na primeira planilha);
- JSON de lista, data/items/records;
- GeoJSON FeatureCollection com propriedades e geometria WGS84.

Cada importação é copiada para a pasta **privada do ImobHunter** e validada
antes de substituir a cópia anterior. Limites: arquivo até **80 MB** e
50 mil linhas. Remover fonte apaga apenas a cópia gerenciada, **nunca o
arquivo original da prefeitura**.

Campos reconhecidos incluem logradouro, numero, endereco, quadra,
lote, municipio, uf, sql, inscricao_imobiliaria, cib,
area_m2, area_terreno, latitude e longitude. Outros campos
permanecem preservados no dossiê como propriedades originais. Linhas com
cidade/UF explicitamente divergentes são ignoradas; registro sem cidade/UF
pode herdar **apenas para contextualização** a localidade atribuída à
fonte. Não são fabricados SQL, geometria cadastral ou nome de proprietário.

O mapa utiliza **somente geometrias GeoJSON WGS84 válidas**; coordenadas
projetadas sem referência não são transformadas arbitrariamente.

### Limitações da consulta

- Arquivos são filtrados por **endereço e número** ou **quadra+lote** ou
  **CIB**. Números de imóveis vizinhos não são confundidos.
- Para fonte remota, a pesquisa automática por endereço requer a API
  WFS ou ArcGIS acessível e uma geocodificação disponível. Se o endpoint
  estiver offline, uma falha é registrada sem apagar resultados locais.
- Sites informativos não são consultados como cadastro, ainda que o botão
  **Testar fonte** confirme que o site responde.
- Um arquivo ou API personalizado **não substitui** o GeoSampa de São Paulo
  capital nem altera os adaptadores municipais oficiais embutidos.
  O registro é independente e a origem permanece identificada.

### Verificação / fluxo

Executar compileall, pytest, Ruff e o smoke Qt offscreen. Os testes cobrem
criação, persistência, exclusão, importação CSV/XLSX/GeoJSON, roteamento
por município/UF e testes de conexão sem rede. O teste visual dos
instaladores em Windows/Linux ainda é exigido para homologação de release.
**Não publicar R2 nesta etapa.**

## Versão Qt homologada no CI

O extra desktop fixa PySide6 em 6.8.3. No runner Linux de 02/11/2026, a
instalação anterior de PySide6 6.12.0 produziu falhas nativas intermitentes
após a execução dos testes de interface; com PySide6 6.8.3, o conjunto
completo de testes Qt concluiu três vezes em processos Python independentes,
com código de saída zero. A validação automatizada verifica essa mesma
versão usada pela instalação desktop. A validação visual em Windows/Linux
instalados continua pendente e não autoriza publicação automática no R2.
