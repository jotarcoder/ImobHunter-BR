# Etapa 2 — mapa cadastral nativo e navegável

O mapa agora é uma aba do dossiê da **Prospecção**, e não uma janela modal ou
um conjunto fixo de nove imagens. Os dados cadastrais existentes, incluindo
SQL/IPTU, quadra, lote e área, continuam vindo dos adaptadores de fontes
municipais; o mapa **não altera os retornos das consultas nem os cadastros**.

## Funcionamento

1. Realize uma pesquisa normal de endereço ou quadra/lote.
2. Se a fonte entregar geometria GeoJSON válida (Polygon/MultiPolygon em
   WGS84), a aba **Mapa cadastral** será aberta com os polígonos recebidos.
   Se entregar apenas latitude/longitude, a aba fica disponível para
   visualizar o **ponto**, sem fingir que existe um limite cadastral.
3. Arraste para navegar; use a roda, **+** ou **−** para alterar o zoom
   geográfico. Os mosaicos de ruas são buscados sob demanda (no máximo 36
   por viewport, com até três requisições simultâneas) e são cacheados
   localmente em ~/.imobhunter/map-tiles.
4. Use **Enquadrar lotes**, **Centralizar imóvel** ou clique num
   polígono/marcador. Os detalhes exibem os identificadores efetivamente
   fornecidos pela fonte, área e procedência. **Copiar dados** envia o
   texto selecionado ao clipboard do sistema.

### Confiança da correspondência

- Verde: campo \`house_number_match=exact\` recebido da fonte.
- Verde: correspondência de **quadra e lote pedidos na busca** com os mesmos
  identificadores da fonte oficial, respeitando cidade e UF. Isso confirma
  apenas a igualdade cadastral, não o número predial nem titularidade.
- Verde-claro: \`geocoded_spatial_match\`, correspondência espacial a
  confirmar; **não significa confirmação do número predial**.
- Âmbar: \`geocoded_spatial_candidate\` / \`spatial_candidate_only\`.
- Cinza: \`neighboring_parcel\` ou \`parcel_relation=neighbor_candidate\`.
- Geometria sem correspondência cadastrada: não é indicada como alvo,
  nem associada automaticamente ao endereço consultado.

O SQL/IPTU é exibido somente quando a fonte preencher
\`iptu_registration_number\` ou \`sql\`. Um \`property_id\` genérico da
camada WFS **não é convertido em inscrição municipal**.

### Origem e limites

A base de ruas vem de © OpenStreetMap contributors. **OSM não fornece
limites cadastrais oficiais neste recurso.** Geometrias de lotes vêm apenas
do GeoJSON efetivamente retornado pelo adaptador municipal escolhido pela
pesquisa. O GeoSampa é restrito à **cidade de São Paulo**, sem consulta
indevida para municípios como Bertioga, Santos ou Praia Grande.

Sem retorno de geometria não há desenho inventado de lote ou quadra.
O mapa rejeita coordenadas fora do intervalo WGS84 e não desenha camadas
projetadas sem conversão autorizada. Polígonos administrativos de **quadra
inteira** só podem ser mostrados quando uma fonte oficial disponibilizar
essa geometria; não são derivados do contorno de lotes.

O download de ruas usa HTTP no QThreadPool, sem bloquear a interface. Em
falha de rede, os polígonos locais continuam clicáveis, mesmo com a base
de ruas sem mosaicos. A navegação não exige WebEngine/CDN, e a aba de
Inteligência de Mercado permanece independente.

## Validação

Execute na branch do PR:

- \`python -m compileall -q imobhunter tests scripts\`
- \`pytest\`
- \`ruff check .\`

Quando o ambiente tiver o extra \`desktop\`, rode
\`QT_QPA_PLATFORM=offscreen pytest tests/test_cadastral_map_desktop.py\`,
além de conferir visualmente no Windows e Linux com uma pesquisa cadastral
real. Isso **não comprova** disponibilidade ou correção de serviços
municipais externos: validar o mapa e validar o endpoint são verificações
independentes.

**Nunca publicar instaladores no Cloudflare R2 até a aprovação dos testes
e autorização explícita de release.**
