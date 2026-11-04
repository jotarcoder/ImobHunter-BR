# Base do IPTU São Paulo 2025 — importação local Parquet

A base `iptu_2025.parquet` não é um arquivo de texto: o ícone do Bloco de Notas
é apenas a associação do Windows. O formato do arquivo enviado foi verificado:
**3.806.436 linhas, 34 colunas** em Parquet, inclusive SQL, rua, número,
complemento, área de terreno/construída e ano de exercício.

## Configurações

1. Abra **Configurações → IPTU municipal → Selecionar**.
2. O seletor agora inclui **Dados IPTU (*.csv *.json *.parquet)**.
3. Selecione o arquivo original `iptu_2025.parquet`, sem renomeá-lo.
4. A interface permanece responsiva enquanto o importador lê os dados em
   lotes de 5.000 e prepara o índice SQLite local.
5. Ao concluir, o caminho salvo aponta para
   `~/.imobhunter/sp_iptu/iptu_sp.sqlite3`. O arquivo original continua
   exatamente onde o usuário o colocou; os dados não são enviados à nuvem.
6. Nas pesquisas por rua e **número**, o adaptador municipal encontra
   registros no SQLite por índice sem varrer milhões de linhas em memória.
   A busca por quadra+lote é possível, mas pode retornar diversos setores
   quando o setor não é informado, portanto não é identificação única.

Os campos *setor/quadra/lote* são **derivados do SQL quando o identificador
possui comprimento mínimo adequado**, não uma camada de polígonos oficiais.
A origem é indicada como arquivo local e não comprova propriedade, matrícula
ou situação atual de débitos. O GeoSampa continua independente e funcional.

## Cuidados de empacotamento

O importador precisa do motor opcional `pyarrow`; o extra `desktop` inclui
essa dependência e o CI utiliza o extra `dev` para testar um Parquet de amostra.
Antes de publicar nova versão **devem ser verificados os quatro builds nativos**
(incluindo a arquitetura arm64 de PyArrow no instalador Apple Silicon), uso de
disco do SQLite real, retenção do estado anterior e antivírus Windows.
Não publicar instaladores por causa deste PR antes de validação completa.
