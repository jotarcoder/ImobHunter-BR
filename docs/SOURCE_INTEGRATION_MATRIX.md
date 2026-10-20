# Matriz de fontes oficiais e modelos de integração — ImobHunter-BR

**Atualização:** 2026-10-20  
**Escopo:** inventário de adaptadores, municípios configurados, modelos de integração e limites de cada fonte. Este documento descreve o código identificado no repositório; não transforma conectores existentes em garantia de cobertura nacional nem substitui a evidência dos testes ao vivo.

## 1. Regra obrigatória de roteamento

1. **São Paulo capital (SP): GeoSampa, exclusivamente para o cadastro municipal da capital.** O adaptador exige município São Paulo e UF SP explícitos.
2. **Qualquer outro município:** consultar o conector oficial específico daquela prefeitura quando configurado; caso contrário, usar descoberta controlada de serviços cadastrais oficiais, como INDE, sem reutilizar GeoSampa.
3. **Não misturar identificadores:** SQL, inscrição imobiliária/IPTU, CIB, código de lote, quadra, índice cadastral e matrícula são campos diferentes. Só podem ser exibidos com o nome correspondente ao campo efetivamente retornado e à sua definição documentada.
4. **Geocodificação não é cadastro:** localizar um endereço por geocodificador não comprova que o lote foi encontrado. Geometria próxima é candidata espacial, não confirmação exata.
5. **Não inventar dados:** proprietário/titular, débitos, SQL, IPTU, área, matrícula e demais campos só aparecem quando a fonte consultada os fornece de forma autorizada.
6. **Falha ou campo ausente:** informar fonte, estado da consulta e limitação — por exemplo, não consultado, indisponível na fonte, requer autenticação, timeout ou nenhum resultado.
7. **Cobertura municipal não equivale à estadual:** uma integração de uma cidade não deve ser descrita como cobertura integral de sua UF.

## 2. Modelos de integração presentes no código

| Modelo | Adaptador/módulo | Finalidade e estado |
|---|---|---|
| WFS/OGC municipal direto | `OfficialMunicipalServicesAdapter`, `ogc_wfs.py` | Consulta direta a serviços oficiais documentados e configurados. A camada e os atributos variam por prefeitura. |
| ArcGIS REST municipal | `OfficialMunicipalServicesAdapter` | Consulta a FeatureServer/MapServer oficial quando a prefeitura publica camadas cadastrais. |
| Descoberta municipal por INDE | `NationalMunicipalCadastreAdapter`, `national_service_discovery.py`, `inde.py` | Descobre serviços/camadas candidatas no catálogo; descoberta e conectividade não garantem consulta cadastral útil. |
| GeoSampa dedicado | `GeoSampaAdapter` | Cadastro territorial da **capital São Paulo/SP somente**. |
| Geocodificação nacional | `NationalAddressGeocoderAdapter`, `national_geocoder.py` | Normalização/localização de endereço; não fornece titularidade nem substitui o cadastro municipal. |
| Endereços censitários | `CNEFEAdapter` | Referência de endereços do IBGE, quando disponível; não é prova de propriedade. |
| CNPJ local/API | `CNPJAdapter`, `cnpj_api.py` | Enriquecimento de estabelecimentos e pessoas jurídicas. Não prova propriedade imobiliária e não significa descoberta automática de empresas por raio. |
| Cadastro rural | `SNCRAdapter`, `SICARAdapter`, `SIGEFAdapter`, `CNIRAdapter` | Dados rurais/ambientais/georreferenciados, sujeitos à disponibilidade, autorização e autenticação de cada serviço. Não equivalem a matrícula registral. |
| SINTER/CIB | `SINTERAdapter` | Identificação cadastral quando dados oficiais acessíveis e autorizados estiverem disponíveis; acesso pode ser condicionado. |
| Meio ambiente e patrimônio | `ICMBioAdapter`, `IPHANAdapter` | Contexto ambiental, unidades de conservação e patrimônio; não determinam titularidade. |
| OpenStreetMap | `OSMAdapter` | Ruas, pontos e contexto geográfico, respeitando atribuição/licença; não define limites fiscais de lotes. |
| IPTU municipal configurável | `MunicipalIPTUAdapter` | Consulta municipal quando endpoint e acesso estiverem configurados. Autenticação/CAPTCHA não são contornados; não presumir cobertura nacional. |
| Serviços geoespaciais públicos | `PublicGeoservicesAdapter` | Acesso a serviços públicos geoespaciais configurados, preservando limitações da camada. |
| Fonte configurável / stub | `ConfigurableWFSAdapter`, `ConfiguredSourceStub` | Estrutura de configuração ou placeholder. **Não deve ser descrita como integração funcional sem endpoint, teste e resultado comprovados.** |

## 3. Municípios e territórios com conectores específicos identificados

A lista abaixo é de **conectores municipais/territoriais no código**, não de cobertura integral de estado. Os campos disponíveis dependem da camada e do retorno real de cada consulta.

| Localidade | Fonte oficial / modelo | Dados/identificadores documentados no conector | Limites que devem permanecer explícitos |
|---|---|---|---|
| São Paulo capital — SP | GeoSampa WFS; camada configurada `geoportal:lote_cidadao` | Lote/quadra, endereço, SQL/IPTU, área e geometria quando retornados pela camada. | Uso exclusivo na capital. A camada não confirma, por si só, proprietário nem débitos atuais. |
| Praia Grande — SP | WFS municipal `https://geoserver.praiagrande.sp.gov.br/ows` | Camadas cadastrais/territoriais publicadas pela prefeitura; geometria e atributos efetivamente retornados. | Não presumir que todo endereço retorne SQL, IPTU, área ou titularidade. |
| Santos — SP | GeoServer/WFS municipal `https://egov.santos.sp.gov.br/geoserver/wfs` | Camadas oficiais municipais identificadas em configuração. | Campos e correspondência de endereço dependem da camada e do retorno real. |
| Bertioga — SP | GeoServer/OWS municipal `https://geoportal.bertioga.sp.gov.br/geoserver/ows` | Camadas oficiais municipais identificadas em configuração. | Campos e cobertura devem ser confirmados por consulta; não herdar atributos de outra prefeitura. |
| Belo Horizonte — MG | BHMAP/IDE-BHGEO WFS `https://bhmap.pbh.gov.br/v2/api/idebhgeo/wfs` | Camadas cadastrais/territoriais oficiais publicadas. | Não extrapolar para os demais municípios de MG. |
| Rio de Janeiro — RJ | ArcGIS REST — imóveis territoriais e GeoPAL | Identificadores territoriais/parcela e geometria quando retornados. | Camadas não são presumidas como fonte de SQL/IPTU individual, titularidade ou matrícula. Não extrapolar para o estado. |
| Distrito Federal — DF | IDE-DF ArcGIS REST — camada de imóvel/certidão | A camada oficial identificada publica campos cadastrais como inscrição/IPTU, CIU, endereço, quadra/lote e áreas, conforme o retorno. | DF é território distinto de município/UF estadual; cada campo ainda depende do retorno real da camada. |
| Goiânia — GO | ArcGIS REST municipal — cadastro imobiliário | Campos documentados incluem `nrinscr`, logradouro, número, quadra, lote, área de terreno e área edificada, quando retornados. | `nrinscr` deve ser chamado de inscrição cadastral até haver comprovação de equivalência com SQL/IPTU. Não extrapolar para GO inteiro. |
| Blumenau — SC | Serviço municipal de lotes / ArcGIS REST | Identificadores como `IQ`, número do lote, bairro, área cartográfica e geometria, conforme camada. | `IQ` é identificador cadastral; não renomear como SQL/IPTU. Não extrapolar para SC inteiro. |
| Recife — PE | Portal municipal de dados abertos / API CKAN — dataset de IPTU | Recursos de cadastro fiscal publicados no portal, quando o recurso é consultável e retorna registros. | A existência do dataset não garante datastore/API consultável nem geometria. Não inferir proprietário, débitos ou SQL não retornado. |
| Porto Alegre — RS | ArcGIS REST municipal — lotes fiscais | Campos publicados incluem `id_lotes`, `setor`, `qtd` (quarteirão), bairro e geometria, conforme a camada. | A camada identificada não inclui SQL/IPTU individual nem área nos atributos documentados; lote próximo não confirma endereço exato. |

### Endpoints oficiais referenciados

- Praia Grande: https://geoserver.praiagrande.sp.gov.br/ows
- Santos: https://egov.santos.sp.gov.br/geoserver/wfs
- Bertioga: https://geoportal.bertioga.sp.gov.br/geoserver/ows
- Belo Horizonte: https://bhmap.pbh.gov.br/v2/api/idebhgeo/wfs
- Rio de Janeiro — imóveis territoriais: https://pgeo3.rio.rj.gov.br/arcgis/rest/services/CadParcel/IMOVEIS_TERRITORIAIS/FeatureServer/0
- Rio de Janeiro — GeoPAL: https://pgeo3.rio.rj.gov.br/arcgis/rest/services/CadParcel/GeoPAL/FeatureServer/0
- Distrito Federal: https://www.geoservicos.ide.df.gov.br/arcgis/rest/services/Aplicacoes/CERTIDAO_IMOVEL/FeatureServer/0
- Goiânia: https://portalmapa.goiania.go.gov.br/servicogyn/rest/services/MapaServer/Feature_Base/MapServer/3
- Blumenau: https://geo.blumenau.sc.gov.br/server/rest/services/Cadastro_Imobiliario/Lotes_Blumenau/FeatureServer/0
- Recife — conjunto IPTU: https://dados.recife.pe.gov.br/dataset/imposto-predial-e-territorial-urbano-iptu
- Recife — API CKAN: https://dados.recife.pe.gov.br/api/3/action/package_show?id=imposto-predial-e-territorial-urbano-iptu
- Porto Alegre: https://gis-smamus.portoalegre.rs.gov.br/server/rest/services/01_PUBLICACOES/dmweb_lotes_fiscais/MapServer/0
- GeoSampa: https://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs

## 4. Fontes nacionais e especializadas — propósito e limites

| Fonte | Uso correto | Não presumir |
|---|---|---|
| IBGE/CNEFE | Endereços e referências territoriais/censitárias quando publicados. | Titularidade, SQL/IPTU ou geometria fiscal de lote. |
| IBGE Localidades/SIDRA | Indicadores estatísticos por unidade geográfica, variável e período identificados. | Renda individual ou característica exata de um imóvel sem suporte na granularidade da tabela. |
| INDE | Descoberta de metadados e serviços geoespaciais de órgãos públicos. | Que uma camada descoberta tenha parcelas pesquisáveis ou atributos fiscais. |
| Receita Federal/CNPJ | Situação cadastral, razão social, CNAE e campos oficialmente fornecidos. | Que o CNPJ identifique o proprietário do imóvel ou que a API descubra todas as empresas de um raio. |
| SINTER/CIB | Identificação cadastral quando a fonte oficial disponibilizar o dado ao usuário autorizado. | Acesso anônimo, cobertura universal ou equivalência automática entre CIB e SQL/matrícula. |
| SNCR/INCRA e CNIR | Cadastro rural e identificadores fornecidos em serviços autorizados. | Acesso irrestrito, titularidade atual ou equivalência com registro imobiliário. |
| SICAR/CAR | Cadastro ambiental rural e atributos ambientais publicados. | Matrícula, domínio/propriedade ou regularidade registral. |
| SIGEF | Parcelas georreferenciadas e campos existentes no conjunto acessado. | Que toda parcela tenha matrícula/titular publicados ou que o dado substitua certidão registral. |
| ICMBio | Unidades de conservação e camadas ambientais oficiais. | Propriedade de um imóvel. |
| IPHAN | Bens, processos e camadas de patrimônio histórico/arqueológico publicados. | Propriedade ou restrição jurídica conclusiva sem consulta à fonte competente. |
| OpenStreetMap | Ruas, pontos e contexto geográfico com atribuição adequada. | Limites oficiais de lote ou cadastro tributário. |
| Portais municipais de IPTU | Situação tributária/campos publicados pelo município, dentro das permissões de acesso. | Ausência de débitos quando a consulta falha, exige login ou não retorna dados. |
| RI Digital/ONR e registros competentes | Consulta registral conforme modalidade, serventia e autorização aplicáveis. | Matrícula a partir de endereço, lote, SQL, CIB ou inscrição fiscal sem retorno registral. |

## 5. Estados de integração que a interface e os relatórios devem distinguir

- **Implementado no código:** existe adaptador; não significa que o endpoint esteja disponível.
- **Configurado:** URL/camada está definida; não significa que a consulta por endereço funcione.
- **Conexão verificada:** endpoint respondeu no teste registrado.
- **Consulta útil verificada:** endereço de teste produziu o tipo de dado esperado.
- **Cobertura medida:** municípios, camada, campos e data de teste foram registrados com evidência.
- **Condicional/autenticado:** depende de credenciais ou autorização oficial.
- **Descoberta apenas:** metadados/candidato encontrados, sem integração cadastral validada.
- **Indisponível/timeout/erro:** falha técnica; não converter em “imóvel não existe”.
- **Campo ausente na fonte:** dado não publicado pela camada consultada; não preencher por inferência.

## 6. Evidência mínima por conector

Para considerar uma integração validada, registrar: município/UF, endereço de teste, endpoint oficial, camada/serviço, data/hora, estado HTTP, tempo de resposta, quantidade de feições, campos retornados, CRS/geometria, resultado esperado versus obtido e limitações. Manter testes determinísticos para normalização/erros e smoke test real separado. A evidência de um município não valida outros municípios.

## 7. Próxima manutenção do inventário

Ao adicionar um conector, atualizar esta matriz no mesmo PR e incluir:
1. município/UF e órgão responsável;
2. URL oficial e camada/serviço exatos;
3. campos reais, com nomes e semântica preservados;
4. campos não publicados ou condicionais;
5. testes unitários e evidência ao vivo;
6. classificação de estado conforme a seção 5.

**Regra de entrega:** branch/PR → testes e checks verdes → revisão do diff → merge em `main`. Publicar instaladores no R2 somente quando solicitado explicitamente e depois da validação aplicável.
