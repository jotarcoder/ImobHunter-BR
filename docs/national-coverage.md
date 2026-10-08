# Cobertura nacional do ImobHunter-BR

## Regra principal

DDD não é a unidade de integração do imóvel. O DDD é usado para descoberta e roteamento. A unidade real de cobertura é:

1. UF
2. município / código IBGE
3. cadastro imobiliário municipal
4. fonte pública disponível
5. imóvel identificado por endereço, inscrição municipal, CIB ou coordenadas

Isso evita criar 67 integrações artificiais e permite que um município com mais de uma fonte seja tratado corretamente.

## Ordem das fontes

Para cada consulta, o motor deve procurar nesta ordem:

- Sinter/CIB, quando o imóvel e os dados públicos estiverem disponíveis;
- cadastro imobiliário/IPTU oficial do município;
- dados geoespaciais oficiais do município;
- dados oficiais estaduais/federais aplicáveis;
- outros catálogos públicos com origem e licença claramente identificadas.

Cada campo retornado deve carregar:

- fonte;
- URL/identificador da fonte;
- data/hora da consulta;
- município/UF;
- nível de confiança;
- regra que produziu o valor.

## Identificação do imóvel

O motor deve tentar normalizar e cruzar:

- logradouro;
- número;
- complemento;
- bairro;
- CEP;
- município;
- UF;
- coordenadas;
- inscrição imobiliária;
- setor/quadra/lote quando existir;
- CIB quando existir;
- identificador cadastral específico da prefeitura.

## Proprietário e contribuinte

O sistema nunca deve inferir proprietário a partir de endereço, CPF, telefone ou outras bases.

Se a fonte oficial pública expuser legitimamente o proprietário ou contribuinte, o campo pode ser retornado com sua origem e restrições. Se a fonte não expuser, o resultado deve ser "não disponível na fonte consultada".

CPF não deve ser descoberto, adivinhado, correlacionado ou enriquecido por bases não autorizadas. CNPJ pode ser exibido quando estiver explicitamente público e vinculado ao registro da fonte.

## IPTU e débitos

O motor deve distinguir:

- contribuinte do IPTU;
- inscrição imobiliária;
- valor venal;
- área;
- lançamento do exercício;
- situação do lançamento;
- dívida/pendência explicitamente publicada;
- certidão ou consulta oficial.

Ausência de informação não significa ausência de débito.

## Cobertura DDD

A matriz nacional contém os 67 códigos nacionais atualmente usados no Brasil. O relacionamento DDD -> município deve ser atualizado pela fonte oficial da Anatel, e não por uma tabela manual permanente.

## Estados

A arquitetura deve suportar 27 UFs e milhares de municípios sem criar uma classe específica por DDD.

Cada conector municipal deve implementar o mesmo contrato de saída e somente mudar a forma de consulta da fonte local.

## Contrato de resultado

Todo conector deve produzir registros normalizados, por exemplo:

- property_identity
- address
- cadastral
- taxpayer
- owner
- tax
- land_use
- area
- zoning
- heritage
- rural
- geometry
- sources
- confidence
- warnings

Campos não disponíveis ficam nulos e recebem uma explicação de indisponibilidade. Nunca devem ser preenchidos por suposição.

## Fases de implementação

### Fase 1 — base nacional
- municípios e códigos IBGE;
- DDDs e relacionamento município/DDD;
- normalização de endereço;
- geocodificação;
- registro de fontes;
- contrato comum dos conectores.

### Fase 2 — fontes federais
- Sinter/CIB;
- CAFIR/INCRA quando aplicável;
- dados abertos da Receita Federal;
- demais fontes federais imobiliárias e territoriais públicas.

### Fase 3 — fontes estaduais
- cadastros e geosserviços estaduais que tenham relação com imóvel, território, patrimônio, uso do solo ou tributação.

### Fase 4 — fontes municipais
- IPTU;
- cadastro imobiliário;
- mapa cadastral;
- portal de consulta;
- geosserviços;
- dívida/pendências quando publicamente consultáveis;
- legislação e zoneamento;
- patrimônio/tombamento.

### Fase 5 — motor de correlação
- endereço -> município;
- endereço -> cadastro;
- cadastro -> CIB;
- quadra/lote -> imóvel;
- imóvel -> fontes complementares;
- consolidação sem duplicação;
- confiança e proveniência.

### Fase 6 — produto
- pesquisa por endereço;
- pesquisa por quadra/lote quando suportada;
- ficha imobiliária;
- fontes e evidências;
- exportação;
- cache local;
- funcionamento offline para dados previamente coletados.

### Fase 7 — controle comercial
Somente depois da fundação nacional:
- painel admin;
- usuários;
- assinaturas anuais;
- licenças;
- dispositivos;
- ativação;
- revogação;
- auditoria;
- instaladores multiplataforma.

## Regra de qualidade

Não declarar "cobertura completa" só porque um DDD está cadastrado. Um DDD é considerado coberto quando todos os municípios associados possuem pelo menos o fluxo de identificação de endereço funcionando e cada fonte adicional tem seu status explicitamente registrado.

Estados/municípios sem uma fonte pública adequada continuam pesquisáveis por endereço e recebem um relatório transparente indicando quais campos não estão disponíveis publicamente.
