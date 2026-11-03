# Próximas fontes municipais de SP: Ribeirão Preto e São José dos Campos

Data: 03/11/2026. Objetivo: descobrir **serviços públicos e documentados** que possam retornar quadra, lote e inscrição imobiliária por endereço. **Não confundir camadas cartográficas com SQL/IPTU individual.**

## Ribeirão Preto (DDD 16)
O Geoportal público da prefeitura é um ArcGIS Enterprise e, segundo a própria prefeitura, oferece informações sobre **endereço oficial, quadra, lote e cadastro urbano**. A documentação pública também descreve a Ficha Técnica do Imóvel. Há caminhos públicos para catálogo ArcGIS REST e pesquisa do portal; os campos de cada camada e a sua autorização de acesso ainda precisam ser descobertos.

- Portal oficial: https://webgis.ribeiraopreto.sp.gov.br/portal/apps/sites/#/geoportal
- ArcGIS REST catálogo: https://webgis.ribeiraopreto.sp.gov.br/server/rest/services
- Pesquisa pública ArcGIS Portal: https://webgis.ribeiraopreto.sp.gov.br/portal/sharing/rest/search
- Atenção: **Pesquisa de Imóveis (restrito Imobiliárias)** da Fazenda não deve ser usada sem credenciais oficiais ou autorização. Não contornar senha ou CAPTCHA.

## São José dos Campos (DDD 12)
O Geosanja oficial permite busca por **endereço ou inscrição imobiliária** na interface pública, e documenta geosserviços WMS/WFS/WCS e filtros de atributos. O contrato exato da camada pública para ligação de rua/número a inscrição/quadra/lote precisa ser descoberto.

- Portal oficial: https://geosanja.sjc.sp.gov.br/
- Informações prefeitura: https://www.sjc.sp.gov.br/servicos/urbanismo-e-sustentabilidade/planejamento-urbano/inteligencia-territorial-e-geoprocessamento/
- Manual público: https://treinamento.sjc.sp.gov.br/course/view.php?id=113&section=14

## Evidência e critérios de integração

O script `scripts/probe_sp_next_municipal.py` examina **somente metadados públicos** de serviços ArcGIS, WFS e página/JS pública do Geosanja. Limita o número de consultas, títulos e scripts. Não solicita atributos de proprietários, cadastros tributários individuais ou lotes em massa. A execução fica no workflow `.github/workflows/sp-next-source-probe.yml`, sem qualquer etapa de build, publicação, licença ou R2.

- [ ] Localizar endpoint publicado e listar campos oficiais e geometria da camada correta.
- [ ] Validar consulta de um endereço real **com número** e vincular inscrição, quadra/lote e polígono, se expostos.
- [ ] Escrever adaptadores isolados e testes sem SQL/IPTU inventado.
- [ ] PR de código somente após regressão Pytest/Ruff/compileall e consulta ao vivo.
- [x] Nenhum instalador, nenhuma publicação R2 e nenhum deploy de produção.

**Status inicial:** investigação de fonte em andamento; não declarar esses municípios plenamente integrados apenas porque o geoportal existe.

## Diagnóstico real da descoberta — GitHub Actions 03/11/2026

Workflow: https://github.com/jotarcoder/ImobHunter-BR/actions/runs/41704968107

| Município | Serviço testado | Resultado real no runner | Interpretação |
| --- | --- | --- | --- |
| Ribeirão Preto | ArcGIS REST municipal `/server/rest/services` | `ConnectError` | O runner não conseguiu conectar; **não significa ausência de imóveis ou que o site inteiro esteja offline para todos** |
| Ribeirão Preto | ArcGIS Portal público `/portal/sharing/rest/search` | `ConnectError` | Não foi possível descobrir catálogo e campos da camada pública |
| São José dos Campos | Página oficial Geosanja | HTTP 200, sem referências a scripts no HTML recebido | Confirma somente resposta da página; não descobre endpoint cadastral |
| São José dos Campos | Caminhos convencionais GeoServer `/geoserver/ows`, `/geoserver/wfs` e `/ows` | `HTTPStatusError` nos três | **Esses caminhos testados** não publicaram catálogo WFS válido; o sistema pode usar outro host/caminho |

**Conclusão técnica:** ainda não é possível devolver com confiabilidade **SQL/IPTU, inscrição, quadra ou lote por endereço** desses dois municípios através dos endpoints testados. **Não integrar automaticamente a consulta fiscal do portal** nem usar dados protegidos sem autorização.

### Validação e sequência

- O próximo passo para Ribeirão Preto é identificar o serviço REST/camada pública usado pelo módulo **Cadastro Urbano** e verificar os campos oficiais, inclusive a busca por código IPTU, sem usar a pesquisa de imóveis restrita a imobiliárias.
- Para São José dos Campos, localizar na interface **Informações → Serviços OWS** o endpoint real oficialmente publicado; então usar `GetCapabilities`/`DescribeFeatureType` para confirmar atributos e vínculo com endereço.
- Uma camada apenas geográfica deve ser rotulada **cartográfica**; o aplicativo não deve considerá-la SQL ou inscrição tributária.
- Todo adaptador novo exigirá testes determinísticos, consulta pública real e PR verde antes de merge.
- Nenhuma execução deste PR gera instaladores ou publica no Cloudflare R2.
