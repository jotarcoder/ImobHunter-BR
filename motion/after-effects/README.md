# ImobHunter-BR — After Effects Motion Direction

## Objetivo

Transformar a identidade atual do produto em um **product film cinematográfico premium**, sem transformar a landing page em uma versão funcional do sistema.

A landing continua institucional. O After Effects demonstra capacidade, arquitetura e posicionamento através de uma linguagem audiovisual contemporânea.

## Sistema visual

- Fundo: `#06111B`
- Verde assinatura: `#35FF77`
- Texto principal: `#EDF5FA`
- Texto secundário: `#91A5B6`
- Painéis: `#0A1827` / `#0E1C2B`
- Grade: `#1D3449`
- Acentos: `#68B8FF`, `#FF7894`
- Tipografia: Inter; Bold para títulos e Regular para suporte.
- Grade editorial: 160 px vertical / 120 px horizontal em 1920x1080.
- Linguagem: precisão, profundidade, escala, silêncio e microdetalhes.

## Pipeline do After Effects

### 1. Construção
Executar:

`motion/after-effects/ImobHunter_Cinematic_V2_16s.jsx`

Isso cria a composição `IMOBHUNTER_CINEMATIC_V2_16S`.

### 2. Acabamento cinematográfico
Com a composição aberta/selecionada, executar:

`motion/after-effects/ImobHunter_Cinematic_V2_Finish.jsx`

Esse segundo script aplica:
- motion blur com shutter de 180°;
- depth of field da câmera;
- foco variável ao longo da narrativa;
- controle de atmosfera;
- markers de acabamento.

O Finish Pass é propositalmente separado do construtor para permitir recalibrar o acabamento sem reconstruir a peça inteira.

### 3. Revisão manual
No After Effects:
- conferir a fonte Inter instalada;
- revisar curvas de velocidade;
- conferir DOF em 100% e 50%;
- ajustar blur se a máquina tiver comportamento diferente;
- conferir legibilidade dos textos;
- revisar o frame final antes do render.

## Cinematografia V2 — 16 segundos

**0–1,2 s — Atmosfera**
- câmera começa distante;
- partículas discretas em diferentes planos Z;
- grade nasce em baixa intensidade;
- glow verde e azul controlados.

**1,2–1,75 s — Hero**
- eyebrow;
- “Dados reais.”;
- “Decisões inteligentes.”;
- subtítulo;
- stagger e profundidade sem bounce.

**1,75–4,05 s — Produto**
- interface como objeto material 3D;
- barra, busca, badge e cards em sequência;
- cursor de pesquisa;
- câmera em push-in/arco.

**4,05–6,2 s — Inteligência**
- fontes tornam-se rede de evidências;
- nós e conexões aparecem progressivamente.

**6,2–10 s — Dossiê**
- evidências convergem;
- identificação, endereço, área, coordenadas, proveniência e confiança aparecem em camadas.

**10–14,9 s — Assinatura**
- simplificação agressiva;
- “Caçando oportunidades.”;
- ImobHunter-BR;
- CTA.

**14,9–16 s — Outro**
- respiração de câmera;
- recuo de profundidade;
- fade cinematográfico.

## Referências de linguagem

Usar como referência de **princípios**, não como cópia:

1. **Apple product films** — câmera, luz, escala e materialidade.
2. **Linear** — dark UI, tipografia, grid e microinterações.
3. **Mapbox** — câmera sobre informação geográfica e escala espacial.
4. **Stripe** — composição editorial, clareza e ritmo.
5. **Motion editorial contemporâneo** — partículas discretas e transições motivadas pelo conteúdo.

A referência orienta fotografia, ritmo, composição, profundidade e comportamento; não copia layout, identidade ou animação específica.

## Render

Master: ProRes 422 HQ, 1920×1080, 30 fps.

Web: H.264, 1920×1080, 15–25 Mbps, AAC 48 kHz.

Versão vertical posterior: 1080×1920, reposicionando a composição e preservando a gramática.

## Estado

A evolução está organizada em branches para evitar alteração prematura da `main`:

- `main` — base estável.
- `motion/cinematic-v2` — construtor cinematográfico V2.
- `motion/cinematic-v2-finish` — construtor + acabamento cinematográfico.

Nenhuma dessas etapas deve ser tratada como definitiva na `main` antes da validação no After Effects e revisão do render.
