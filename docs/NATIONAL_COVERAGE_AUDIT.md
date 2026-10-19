# Auditoria de cobertura nacional — baseline

**Este documento é uma auditoria inicial do código, não uma certificação de cobertura ao vivo.** Nenhuma alteração aqui autoriza merge automático para `main` nem publicação no R2.

## Critério de evidência

Avaliar cada fonte em quatro níveis separados:

1. **Código presente:** existe adaptador ou cliente.
2. **Conexão verificada:** endpoint responde em execução real, com timeout e erros registrados.
3. **Consulta útil verificada:** endereço representativo retorna os campos esperados.
4. **Cobertura medida:** municípios, camadas, campos e data do último teste registrados.

Teste unitário com resposta simulada comprova comportamento diante daquela resposta, não disponibilidade real. Geocodificar um endereço não significa encontrar seu lote. Descobrir um WFS no catálogo não prova que ele retorna parcelas pesquisáveis.

## Baseline identificado no repositório

| Área | Implementação identificada | Ainda precisa ser demonstrado |
|---|---|---|
| Endereços nacionais | Adaptadores IBGE/CNEFE e geocodificador nacional | Precisão por município, número predial, cache, erros e fallback |
| Cadastro municipal | WFS de Praia Grande/SP e Belo Horizonte/MG; ArcGIS REST do Rio/RJ; GeoSampa | Consultas reais por endereço, camadas e campos; municípios efetivamente cobertos |
| Descoberta geoespacial | Descoberta municipal e módulo de catálogo INDE | Transformar descoberta em conectores documentados e testados |
| Mapa e lotes vizinhos | Geometrias nos adaptadores quando fornecidas pela fonte | Fluxo desktop completo, centralização, ruas, seleção e vizinhos |
| Dossiê | Modelo de registro/proveniência e campos opcionais | Origem e estado de cada campo, deduplicação e ausência explícita |
| CNPJ | Índice local e cliente opcional autenticado Conecta gov.br | Cobertura do índice; deixar claro que a API enriquece CNPJ conhecido e não descobre sozinha empresas por raio |
| Demografia | Cliente IBGE Localidades/SIDRA (tabela 6579) | Testes ao vivo e referência de variável, período, unidade e município |
| Fontes condicionais | Adaptadores SINTER/CIB, SNCR, CNIR e outras | Endpoint oficial, termos, autenticação e permissões antes de prometer consulta automática |
| Interface | Módulos de busca, mercado e exportação | Busca repetida, timeout, login persistente e redimensionamento em cada SO |

## Ordem de trabalho

### A — observabilidade e inventário
- Manter status de fonte: implementada, condicional, descoberta apenas, estrutura incompleta ou planejada.
- Registrar fonte, endpoint, município, camada, consulta, campos retornados, duração, estado HTTP e timestamp.
- Não registrar tokens, segredos, CPF ou dados pessoais desnecessários.
- Diferenciar teste simulado, conectividade e consulta cadastral útil.

### B — conectores municipais reproduzíveis
- Usar INDE e portais oficiais para descobrir serviços, validando cada endpoint diretamente.
- Priorizar WFS, OGC API Features e ArcGIS REST documentados.
- Consultar endereço conhecido e validar geometria, CRS, área e identificadores.
- Para cada integração: fixtures, testes unitários e smoke test com falha diagnóstica.
- Nunca inventar SQL/IPTU, CIB, área, proprietário ou matrícula.

### C — mapa e dossiê
- Testar endereço → geocodificação → consulta cadastral → geometria → visualização.
- Validar CRS e geometria antes de desenhar.
- Não transformar dados OSM em limites fiscais.
- Para cada campo: encontrado, indisponível na fonte, não consultado ou falha de consulta, com proveniência.

### D — mercado e configuração
- Distinguir índice local de estabelecimentos, API CNPJ autenticada e indicadores públicos municipais.
- Separar receita declarada de estimativa e documentar qualquer método estimativo.
- Usar SIDRA com código municipal, variável e período explícitos.
- Exibir requisitos de credenciais, teste de conexão, timeout e erro sem revelar segredos.

### E — estabilidade multiplataforma
- Cobrir busca repetida, timeout/cancelamento, cache, login, redimensionamento e exportação.
- Validar Windows, Linux, macOS Intel e Apple Silicon.
- Builds verdes não substituem teste manual de fluxo.
- Só declarar conclusão quando os quatro pacotes forem do mesmo commit validado.

## Próxima entrega técnica

Automatizar um relatório de cobertura real por município/fonte, distinguindo explicitamente `not_tested`, `connection_ok`, `address_found`, `parcel_found` e `field_available`. O relatório será a base para ampliar cobertura nacional sem declarar suporte ainda não comprovado.
