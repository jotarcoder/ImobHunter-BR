# Recuperação de fontes municipais — Bertioga, Recife e Caxias do Sul

**Diagnóstico em 03/11/2026**, fontes públicas e testes a partir de GitHub Actions. **Sem instaladores e sem R2.**

## 1. Resultados da investigação

| Cidade | Endpoints oficiais analisados | Campos divulgados pela documentação | Resultado de consulta real nesta rodada | Decisão |
| --- | --- | --- | --- | --- |
| **Bertioga/SP** | Geoportal `https://geoportal.bertioga.sp.gov.br/`; WFS `/geoserver/ows`; SIG cadastral municipal | SIG informa camadas Lote e Quadra, porém sem contrato público confirmado para inscrição fiscal por endereço | `ConnectError: SSL CERTIFICATE_VERIFY_FAILED` (cadeia não confiável) | **Não desabilitar verificação TLS**, não usar formulário tributário com autenticação/CAPTCHA como API; aguardar correção de servidor ou alternativa pública formal |
| **Recife/PE** | ESIG `Planejamento/BASES_BAIRRO_FACEQUADRA_LOGRADOURO_LOTE/MapServer/3` e `FeatureServer/3` | `QUADRA`, `LOTE`, `ENDNUMERO`, `NMENDCOMP`, `AREALOTE`, `SEQIMOVEL`, `DSQFL` e geometria; sequência não é SQL paulista | **Ambos os endpoints tiveram `ConnectTimeout`**; consulta por endereço não homologada | Código da consulta exata implementado, com teste de mocks e diagnóstico explícito quando serviços indisponíveis |
| **Caxias do Sul/RS** | `MapViewerPublico/FeatureServer/3`, `MapServer/3` (lotes); versões `/4` (quadras) | `inscricaoloteponto`, `nm_logradouro`, `nr_imovel`, `vlr_area_real`, polígono; quadra em outra camada | **Ambos FeatureServer e MapServer de lotes tiveram `ConnectTimeout`** | Fallback oficial implementado e reportado; inscrição do **lote** não é automaticamente cadastro de IPTU individual |

## 2. Correções de código efetuadas no PR

- Recife: consulta municipal ESIG por `NMENDCOMP` e `ENDNUMERO`, confere rua e número nos registros, aceita apenas polígonos retornados pela prefeitura e sequencial `SEQIMOVEL` associado ao endereço. Sem uso do CKAN como rota principal.
- Caxias: consulta alternativa a `MapServer/3` quando `FeatureServer/3` falhar; o vínculo de quadra pela geometria é limitado às camadas oficiais `/4`, sem escolher candidatos ambíguos.
- Os serviços de ambos são marcados como **indisponíveis** quando todas as alternativas falham; isso impede confundir falha externa com ausência de imóvel.
- Bertioga: nenhuma alteração insegura, sem `verify=False`, sem baixar certificados desconhecidos ou contornar CAPTCHA. Cadastro municipal/manual continua possível através da funcionalidade já existente de fontes personalizadas.

## 3. Fontes e evidências

- **Recife ESIG Lotes (oficial):** https://esigportal2.recife.pe.gov.br/arcgis/rest/services/Planejamento/BASES_BAIRRO_FACEQUADRA_LOGRADOURO_LOTE/MapServer/3
- **Recife serviço alternativo:** https://esigportal2.recife.pe.gov.br/arcgis/rest/services/Planejamento/BASES_BAIRRO_FACEQUADRA_LOGRADOURO_LOTE/FeatureServer/3
- **Recife dados abertos:** https://dados.recife.pe.gov.br/pt_BR/dataset/area-urbana
- **Caxias lotes (oficial):** https://gis.caxias.rs.gov.br/server/rest/services/MapViewerPublico/FeatureServer/3
- **Caxias alternativa:** https://gis.caxias.rs.gov.br/server/rest/services/MapViewerPublico/MapServer/3
- **Bertioga Geoportal:** https://geoportal.bertioga.sp.gov.br/
- **Bertioga relação pública das camadas SIG:** https://www.bertioga.sp.gov.br/wp/wp-content/uploads/2024/08/Relacao-de-Temas-SIG-Bertioga.pdf
- **Bertioga serviços tributários:** https://www.bertioga.sp.gov.br/servicos-online

**Atenção:** páginas de metadados HTTP carregarem em um navegador ou indexador **não demonstra** que `/query` responde no ambiente de produção/distribuição. Os códigos estão sob PR rascunho e **não são considerados cobertura funcional homologada**.

## 4. Para aprovação funcional futura

1. Obter ao menos um **endereço oficial comprovado** em Recife com número, quadra, lote, `SEQIMOVEL` e polígono relacionados; conferir homônimos e múltiplos lotes.
2. Obter em Caxias inscrição do lote, endereço e quadra por fonte realmente acessível, sem converter inscrição em SQL/IPTU.
3. Solicitar à prefeitura de Bertioga a cadeia de certificado válida ou endpoint público documentado que exponha inscrição/quadra/lote, sem autenticação indevida.
4. Só após consultas reais e testes verdes incorporar PR de integração; **não publicar no R2 nem criar versão de instaladores**.
