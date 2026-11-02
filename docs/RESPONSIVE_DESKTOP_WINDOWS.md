# Correção de janelas e telas menores (etapa 3.3)

## Sintoma reproduzido pelo usuário

Em Windows, com resolução reduzida, taskbar visível e/ou dimensionamento
do sistema acima de 100%, janelas de Configurações e Inteligência de Mercado
abriam com tamanhos fixos (até 1280 × 820 ou mínimo 980 × 680). A barra
inferior e os controles eram cortados pelo limite da tela. Os cabeçalhos
de tabelas eram comprimidos e apareciam incompletos.

## Comportamento esperado

- Ao abrir uma janela, sua geometria se adapta à **área útil do monitor**,
  excluindo taskbar/dock e respeitando coordenadas de múltiplos monitores.
  As dimensões são em pixels **lógicos**, já corrigidos pelo fator DPI do Qt.
- O tamanho mínimo nunca supera a área útil do monitor; o conteúdo ganha
  rolagem quando necessário, sem empurrar ações para fora da tela.
- **Configurações:** catálogo rola independentemente; a fileira **Validar**,
  **Salvar** e **Fechar** permanece acessível.
- **Inteligência de Mercado:** a aba de busca possui rolagem vertical.
  Os campos de pesquisa ficam em duas linhas; as oito ações reorganizam-se
  em **duas colunas** em janelas menores, ou quatro nas largas.
  O mapa e a tabela podem ser vistos rolando a página.
- **Tabela de empresas:** mantém cabeçalhos e colunas legíveis com scroll
  horizontal, evitando condensar Faturamento, CNPJ e Endereço até truncá-los.
  A aba Resultados e exportação mantém a navegação correta após receber
  o contêiner de rolagem.
- **Base oficial CNPJ:** separa filtros da fileira de exportação/geocodificação
  e permite rolagem horizontal na tabela, sem alterar dados ou funções.
- **Dossiês:** as janelas independentes têm tamanhos iniciais limitados ao
  monitor; mapa, tabelas e filtros permanecem acessíveis.
- **Integrações:** a lista de fontes ganha rolagem própria, preservando
  botão Fechar e diagnósticos visíveis.
- **Janela principal:** o conteúdo pode rolar sem ocultar a barra lateral,
  e seu tamanho inicial cabe no monitor.

## Validação

- Testes determinísticos de geometria lógica (1366 × 728,
  800 × 560, área do segundo monitor com 150% de escala, coordenadas
  negativas em múltiplos monitores).
- Linux Qt offscreen: abrir janelas reais de Configurações, Inteligência de
  Mercado (sem WebEngine e sem rede) e CNPJ local; checar posição dos
  botões, reflow das ações, tabelas e scroll.
- Python compileall, pytest e Ruff antes da integração.
- A homologação visual final dos instaladores em Windows/Linux continua
  separada. Nenhum build de instaladores ou publicação R2 nesta alteração.

## Fora de escopo

Nenhum endpoint cadastral, regra de SQL/IPTU, registro CNPJ, mapa de lote,
licença, marketing ou inteligência de cálculo foi alterado: trata-se apenas
de dimensionamento e navegação.
