# P8.1 — Tela 01: Standby (FIT AI / Obsidian Amber)

## 1. Referência
`Imagem do ChatGPT 22 de nov. de 2026, 13_16_56.png` (1672 × 941), fora do repositório (imagem de referência de design, do autor do projeto). Todas as coordenadas do código estão no espaço de pixels dessa imagem; o palco escala o conjunto para a janela.

## 2. Objetivo
Primeira tela real do Fit AI: fundo preto, emblema centralizado, wordmark `FIT AI`, dois pares de arcos finos, linhas laterais, luz âmbar no horizonte e reflexos no piso. Sem cabeçalho, menu, chat, carro, cartões ou sensores. Funciona sem backend (nenhuma requisição de rede).

## 3. Tokens (`src/styles/tokens.css`)
Fundo `#000000`/`#050303`; âmbar `#ff8500`, `#ffac42`, `#b85a0a`, núcleo `#feedb4`; metal `#fafafa … #322e2c`; texto `#f5f5f5`/`#979797`. Valores refinados por amostras da referência (91 % dos pixels < 5 % de luminância).

## 4. Tipografia
Não há fonte carregada: o wordmark é desenhado em SVG (largura ampla, itálico de 23,3°, altura de capitular 50 px no espaço da referência). FIT em prata, AI em laranja.

## 5. Componentes (`src/components/standby/`, `src/screens/StandbyScreen/`)
`StandbyScreen` (palco 16:9, `<main>`, fases), `HondaEmblem`, `FitAiWordmark`, `AmbientArcs`, `LightHorizon`, `AmbientReflection`, `Layer`, `geometry.ts` (fonte única de números).

## 6. Movimento (`src/motion/`)
`timings.ts` (linha do tempo), `variants.ts` (variants tipadas), `useStandbyPhase.ts`, `useReducedMotion.ts`. Easing `[0.22, 1, 0.36, 1]`; só `opacity`, `transform` e comprimento de traço SVG; sem blur contínuo, sem bounce, sem typewriter, sem partículas.

## 7. Linha do tempo
| ms | Evento |
|---|---|
| 0–400 | fundo/halo |
| 400–1300 | emblema (fade + 8 px + escala .96→1) |
| 900–1600 | wordmark; brilho único 1350–2300 |
| 1200–2400 | arcos se desenham |
| 1500–2600 | horizonte, linhas laterais, reflexo |
| ≥ 2600 | `idle` |

Fases: `entering` (→1600), `settling` (→2600), `idle`.

## 8. Loops ambientes (só em `idle`, CSS, só opacidade)
Halo 9 s (.84–1), arcos internos 11 s, arcos externos 14 s, horizonte 8 s.

## 9. Reduced motion
`prefers-reduced-motion: reduce` → estado final imediato (`initial={false}`, fase `idle`), sem timers, sem loops (verificado: 0 animações em execução).

## 10. Resoluções
1920×1080, 1600×900, 1366×768, 1280×720, 1024×600: sem rolagem nem overflow (testado, inclusive redimensionando em execução). Proporções diferentes de 16:9 ganham faixas pretas.

## 11. Testes
- Vitest/RTL (`StandbyScreen.test.tsx`, 8 testes): sem fetch, acessibilidade, ausência de controles/texto/chat/telemetria, fases com fake timers e limpeza, reduced motion, roteamento.
- Playwright (`e2e/standby.mjs`): 31 verificações (fase idle, overflow, erros de console, requisições, reduced motion, resize).
- Total da UI: 92 testes unitários; e2e do HUD anterior: 14/14 (agora em `/#/hud`).

## 12. Screenshots
Geradas em `ui/e2e/out/standby/` (ignorado pelo Git): `final-*`, `entrance-*`, `reduced-*`, `resized-*`.

## 13. Como rodar (Windows)
```
cd FiT-AI\ui
npm run dev            # http://127.0.0.1:5173  (Standby; o HUD antigo fica em /#/hud)
npm test
npm run build && node e2e/standby.mjs
node e2e/standby-perf.mjs
```

## 14. Dependências
Nenhuma adicionada nesta etapa. Bundle de produção: JS 375,6 kB (120,9 kB gzip), CSS 17,9 kB (4,9 kB gzip) — inclui o HUD anterior, que ainda está no mesmo bundle. `npm audit`: 0 vulnerabilidades.

## 15. Limitações
- **Marca:** HONDA e o emblema H são marcas da Honda Motor Co., Ltd. Ver "Marca e licenciamento" abaixo.
- Fidelidade é comparação visual manual com a referência, sem métrica de similaridade. O acabamento cromado é feito com gradientes SVG (sem renderização 3D real), então o brilho metálico é mais simples que o da imagem de referência; os reflexos no piso também são mais simples.
- Desempenho medido só em Edge headless com rasterização por software: ~16 % de thread principal durante a entrada (2,6 s) e ~0,2 % em idle. Não há afirmação de 60 fps.
- Um agente de QA visual independente revisou a versão anterior do emblema; os ajustes de reflexo, horizonte, arcos, halo e linhas laterais foram aplicados depois disso e não foram revisados de novo.

## 15b. Marca e licenciamento
- **Asset:** geometria vetorial do emblema clássico (moldura arredondada + H) de Wikimedia Commons, `File:Honda.svg` (https://commons.wikimedia.org/wiki/File:Honda.svg; original https://upload.wikimedia.org/wikipedia/commons/3/38/Honda.svg), baixado em 2026-11-22. Conferido visualmente: é o emblema automotivo clássico (vermelho, com o texto HONDA embaixo), não o novo H de 2024+.
- **Uso parcial:** só os dois caminhos do emblema (`path1965` = H, `path1967` = moldura) foram copiados para `ui/src/components/standby/hondaEmblemPaths.ts`; o texto HONDA do arquivo não é usado. A cor vermelha original não é usada: os caminhos são pintados com gradientes cromados e luz âmbar na borda (`HondaEmblem.tsx`).
- **Licença no Commons:** domínio público por falta de originalidade (PD-textlogo / TOO-Japão); arquivo feito em CorelDRAW; campo de autor "desconhecido" (a Wikipédia alemã cita Christian Bier). A própria página avisa que a obra "pode ser protegida como marca em algumas jurisdições".
- **Restrição:** a ausência de direito autoral não dá direito de usar a marca. HONDA e o emblema H são marcas da Honda Motor Co., Ltd. O uso aqui é um projeto pessoal e local, sem distribuição. Antes de qualquer publicação ou distribuição, é preciso avaliar a autorização da Honda, ou trocar o emblema por uma identidade própria. O projeto não tem vínculo nem aprovação da Honda.
- **Isolamento:** o emblema está em um único componente e um único arquivo de dados, então a troca é uma edição só.

## 16. Preparação para a Tela 02 (apenas documentada, não implementada)
Interface prevista entre telas: `STANDBY → VOICE ACTIVATION → LOGO COLLAPSE → VEHICLE REVEAL → ACTIVE VEHICLE HUD`. O `StandbyScreen` já expõe `data-phase` e usa `Layer`s independentes, de modo que o emblema pode ser recolhido sem refazer o fundo. Nada disso foi implementado; P8.2 não foi iniciada.
