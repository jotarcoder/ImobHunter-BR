# Inventário de fontes cadastrais públicas candidatas — integrações pendentes

**Escopo:** candidatos municipais já identificados na pesquisa inicial. Este documento não declara cobertura estadual nem integração funcional no aplicativo. O Brasil não tem uma API parcelária única que sirva a todos os municípios; cada endpoint deve ser validado por cidade, camada, endereço, campos e geometria.

## Integrações municipais já presentes no código / main

- São Paulo capital — GeoSampa.
- Praia Grande/SP — WFS municipal.
- Belo Horizonte/MG — WFS municipal.
- Rio de Janeiro/RJ — ArcGIS REST municipal e fallback GeoPAL (identificador de parcela, não SQL/IPTU quando a camada não o fornece).
- Distrito Federal — camada IDE-DF.
- Santos/SP e Bertioga/SP — WFS municipal, incorporados no PR #138.

A presença de um conector não garante que cada endereço retorne SQL/IPTU. O aplicativo deve expor apenas os atributos realmente recebidos da fonte.

## Candidatos pendentes identificados

| UF | Município | Fonte pública | Formato / campos documentados | Situação e próximo passo |
|---|---|---|---|---|
| GO | Goiânia | [ArcGIS REST — Cadastro Imobiliário, camada 3](https://portalmapa.goiania.go.gov.br/servicogyn/rest/services/MapaServer/Feature_Base/FeatureServer/3) | FeatureServer com consulta JSON/GeoJSON; campos documentados incluem `nrinscr`, `nmlogradou`, `nrimovel`, `nrquadra`, `nrlote`, `areaterr` e `areaedif`. | **Adaptador implementado no PR #139 e teste unitário adicionado.** Ainda precisa CI verde e teste ao vivo por endereço. `nrinscr` é exposto como inscrição municipal, não SQL/IPTU, até confirmar a definição fiscal. |
| SC | Blumenau | [WFS oficial — metadados das camadas](https://geo.blumenau.sc.gov.br/wfs/wfs.html) | WFS/OGC; `GEO.WFS_QUADRAS`, `GEO.WFS_LOTES`, `GEO.WFS_EDIFICACOES` e `GEO.WFS_CONDOMINIOS`; campos publicados incluem `Quadra` e `IQ`. Endpoint: `https://geo.blumenau.sc.gov.br/server/services/publicacao/Publicacao_WFS/MapServer/WFSServer`. | **WFS público confirmado por metadados.** Testar GetCapabilities/GetFeature, CRS, geometria e significado de `IQ`; não assumir que é SQL/IPTU sem validar o dicionário. |
| PE | Recife | [Portal de Dados Abertos — IPTU](https://dados.recife.pe.gov.br/dataset/imposto-predial-e-territorial-urbano-iptu) | Conjunto de dados do cadastro fiscal imobiliário por contribuinte e ano; disponibiliza recursos CSV e dicionário JSON. | **Dados públicos confirmados; API de consulta individual por endereço não confirmada.** Inspecionar o dicionário e recursos, verificar campos e licença, e só então planejar importação/cache local ou endpoint de consulta. Não chamar o download de CSV de API online por endereço. |
| RS | Porto Alegre | [Portal municipal de dados geoespaciais](https://gis-smamus.portoalegre.rs.gov.br/smamus/+dados/) | Portal público cita dados geoespaciais/cadastrais, mas o endpoint de consulta individual e os campos fiscais ainda precisam ser identificados e validados. | **Candidato para investigação, não integração confirmada.** Identificar serviço/URL oficial estável, camada parcelária, termos de uso, CRS e campos; não declarar SQL/IPTU disponível antes do teste. |

## Ordem técnica sugerida

1. **Goiânia/GO:** código do adaptador já adicionado no PR #139; executar CI e validar a consulta real antes de concluir.
2. **Blumenau/SC:** próxima integração de API, WFS de lotes e quadras, após validar os campos e CRS.
3. **Recife/PE:** auditar o dicionário e recursos de IPTU; determinar se é possível pesquisa por endereço sem uma API individual.
4. **Porto Alegre/RS:** concluir descoberta do endpoint/camada antes de codificar.

## Critérios obrigatórios para cada integração

- Requisitar somente endpoints oficiais públicos, sem contornar login, CAPTCHA ou controles de acesso.
- Adicionar testes determinísticos com respostas simuladas e testar erros/timeout.
- Executar smoke test real com endereço conhecido e registrar endpoint, camada, campos, quantidade, timestamp e diagnóstico.
- Validar sistema de coordenadas e geometria antes de exibir lotes no mapa.
- Distinguir inscrição cadastral, SQL, inscrição IPTU, identificador de lote e CIB; não renomear um campo sem evidência.
- Não inferir proprietário, débitos ou titularidade.
- Não declarar cobertura de um estado com base em um único município.
- Manter o fluxo de entrega: PR → checks e testes verdes → revisão do diff → merge em `main`; publicação no R2 somente se houver mudança de instaladores e após validação.

## Fontes de referência

- Goiânia: metadados oficiais do [FeatureServer de Cadastro Imobiliário](https://portalmapa.goiania.go.gov.br/servicogyn/rest/services/MapaServer/Feature_Base/FeatureServer/3).
- Blumenau: [metadados oficiais WFS](https://geo.blumenau.sc.gov.br/wfs/wfs.html).
- Recife: [dataset municipal de IPTU](https://dados.recife.pe.gov.br/dataset/imposto-predial-e-territorial-urbano-iptu).
- Porto Alegre: [portal municipal de dados geoespaciais](https://gis-smamus.portoalegre.rs.gov.br/smamus/+dados/).
