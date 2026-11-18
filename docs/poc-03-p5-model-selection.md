# PoC 03 — P5: benchmark comparativo e seleção do modelo local (2026-11-17)

Escopo: somente P5. Não há memória, ferramentas reais, grounding, API de chat, voz nem App Launcher. Nenhum modelo foi baixado. Sem commit/push. O Core, os adaptadores OCTAVE e os contratos do P4 **não foram alterados** (só foram adicionados arquivos em `bench/` e testes).

## 1. Recomendação

**Padrão do Fit AI: `qwen3:4b-instruct-2507-q4_K_M` (Qwen3 4B Instruct), com `think:false`, contexto 4096.** O Qwen3 8B Q4_K_M fica como alternativa configurável (`FIT_AI_MODEL`) para usos não interativos.

Motivo, com base só no que foi medido:

| | Qwen3 4B | Qwen3 8B |
|---|---|---|
| Qualidade na bateria (180 chamadas pontuadas, 90 por modelo) | **90/90** | **90/90** |
| Geração (mediana) | **~10 tok/s** | ~5,7 tok/s |
| Leitura de prompt, tokens novos (mediana) | **~31–34 tok/s** | ~17 tok/s |
| Prompt de ~1,3 mil tokens a frio (mediana / p95) | **36 s / 39 s** | 65 s / 68 s |
| Resposta de intenção JSON (mediana) | **~5,4 s** | ~11 s |
| RAM dos processos de inferência (ctx 4096) | **~3,2 GB** | ~5,7 GB |
| Timeouts / falhas / interrupções | 0 / 0 / 0 | 0 / 0 / 0 |

Na bateria, o 8B **não** mostrou qualidade superior que justificasse ser ~1,8× mais lento e usar ~2,5 GB a mais. **Ressalva importante:** a bateria saturou (100% nos dois), então ela prova que o 4B é suficiente *para estas tarefas*, mas **não prova que os dois sejam equivalentes** em tarefas mais difíceis. O P6 deve usar um conjunto mais exigente antes de considerar o assunto encerrado.

## 2. Método

- **Hardware:** i5-1235U (10 núcleos / 12 threads, híbrida), 31,7 GB RAM, só CPU, na tomada, plano "Equilibrado". Ollama 0.40.16 portátil (`NUM_PARALLEL=1`, `MAX_LOADED_MODELS=1`, `n_threads=6` padrão do servidor, `n_batch=512`).
- **Parâmetros idênticos nos dois modelos:** `think:false`, temperatura 0,2, contexto 4096, `seed = 42 + rodada` (varia entre rodadas, igual para os dois), `num_predict` por cenário, timeout de 300 s por chamada, mesmo prompt de sistema (versão `system_pt_br`).
- **Intercalação:** 5 rodadas; em cada uma o 4B e o 8B rodam os mesmos 18 cenários **na mesma ordem embaralhada** (semente fixa por rodada), alternando de modelo para que deriva térmica ou carga em segundo plano atinja os dois por igual. Cooldown de 20 s entre rodadas.
- **Aquecimento descartado:** 1 chamada por (rodada, modelo) para carregar o modelo e preparar o prefixo do prompt de sistema (10 aquecimentos, fora das estatísticas).
- **Cache de prompt:** cada chamada recebe um identificador único no início do turno do usuário (`[r3] ...`); só o prefixo do prompt de sistema (~305 tokens) vem do cache, como no uso real. A taxa de leitura do prompt é calculada **somente sobre os tokens novos** (`prompt_tokens − cached_prompt_tokens`); uma primeira versão do harness superestimava esse número e foi corrigida antes da execução.
- **RAM:** soma de *working set* e memória privada dos processos sob `runtime/ollama` (o modelo roda no processo filho `llama-server`), mais o tamanho que o próprio Ollama informa em `/api/ps`. Amostrado após cada chamada.
- **Estabilidade:** a temperatura da CPU exige administrador e **não foi medida**. O critério foi a deriva de vazão (abortar se a mediana da rodada caísse abaixo de 60% da inicial por 2 rodadas). Não houve aborto; a mediana de geração por rodada variou < 8% (4B: 9,8–10,6; 8B: 5,6–5,7 tok/s).
- **p95:** interpolação linear. Com n = 5 por cenário o p95 fica próximo do máximo; leia-o como "pior caso observado", não como estimativa de cauda.
- Dados brutos (git-ignorados, só métricas, sem prompts/respostas): `bench/results/p5-20261117-114909-ctx4096/` (principal), `p5-20261117-143759-ctx8192/` (contexto), `p5-promptcost-*.json` (threads). A tentativa `p5-20261117-124310-ctx8192/` foi **invalidada** (§7) e mantida só para auditoria.

## 3. Qualidade (pontuação objetiva, separada da velocidade)

Pontuação automática por regras (não é julgamento humano). Total por modelo: 90 chamadas.

| Categoria | Cenários | O que se exige | 4B | 8B |
|---|---|---|---|---|
| Intenção em pt-BR (JSON com enum) | 6 frases × 5 | rótulo correto entre 6 intenções | 30/30 | 30/30 |
| Chamada de ferramenta fictícia | 3 pedidos × 5 | primeira chamada = ferramenta certa | 15/15 | 15/15 |
| Não chamar ferramenta sem necessidade | 2 × 5 | sem chamada e resposta não vazia | 10/10 | 10/10 |
| JSON estruturado | 1 × 5 | `P0301`, origem = informado pelo usuário, schema válido | 5/5 | 5/5 |
| Sensores indisponíveis | 3 × 5 | sem valor medido inventado **e** reconhece a falta do dado | 15/15 | 15/15 |
| Português claro | 1 × 5 | vocabulário pt, sem inglês, terminou por `stop` | 5/5 | 5/5 |
| Prompt longo (função) | 2 × 5 | resposta não vazia | 10/10 | 10/10 |

Os cenários de sensor incluem (a) pergunta sem nenhuma ferramenta (pneu, combustível) e (b) ferramenta que devolve `{"status":"indisponivel"}`. A regra de "inventou dado" é conservadora: qualquer número seguido de unidade (psi, °C, rpm, litros, %...) reprova. Todas as ferramentas são fictícias e **nunca foram executadas**.

Limites desta avaliação: uma única volta de conversa, prompts curtos, poucas frases por intenção, regras heurísticas, ceiling de 100%. Ela mede conformidade funcional, não "inteligência" nem fluência fina.

## 4. Desempenho (contexto 4096, mediana / p95 em segundos de latência total, 5 amostras)

| Cenário | 4B total s | 8B total s | tokens novos (4B/8B) |
|---|---|---|---|
| Intenção (média das 6 frases) | 5,0–5,6 (p95 ≤ 6,6); 1,6 se o prefixo estava em cache | 10,1–11,3 (p95 ≤ 12,9); 3,5 em cache | 140–150 |
| Pergunta curta sem ferramenta (UNAV) | 1,1–3,3 | 4,0–4,7 | 19–32 |
| JSON estruturado (STRUCT) | 6,7 / 6,9 | 11,2 / 12,4 | 58 / 66 |
| Português (PTCHAT) | 8,5 / 9,1 | 15,9 / 16,1 | 36 / 44 |
| Ferramenta (bloco de 3 ferramentas ≈ 260 tokens) — prefixo frio | 10,8–12,9 | 18,5–23,4 | 250–280 |
| Ferramenta — prefixo em cache | 2,3 | 4,4–4,8 | 14–22 |
| Resposta com resultado de ferramenta (UNAV_tool_unavailable) | 12,5 / 12,8 | 22,1 / 22,5 | 331 / 303 |
| **Prompt ~1,3 mil tokens, a frio** | **36,2 / 39,1** | **65,3 / 67,9** | 1003 / 1011 |
| Mesmo prompt, repetido (cache) | 1,9 | 3,2 | 1 |

Vazão: geração 4B 9,4–11,3 tok/s, 8B 5,3–6,0 tok/s; leitura de prompt 4B 27–36 tok/s, 8B 16–19 tok/s.

Os p95 altos de `TOOL_rpm`/`TOOL_speed` (4B 10,0/8,9 s; 8B 18,2/15,4 s) **não são instabilidade**: dependem de o bloco de ferramentas já estar no cache (mediana 2,3 s) ou não (≈10 s), efeito de ordem idêntico para os dois modelos.

## 5. Custo dos prompts de ~1,3 mil tokens

- O tempo é quase **todo leitura de prompt em CPU**: 1003 tokens novos a ~30 tok/s (4B) = 33 s; a ~16 tok/s (8B) = 62 s. A geração das 40 saídas custa ≈ 2–8 s. O tamanho do contexto não é o culpado (§6).
- **O cache muda tudo:** o mesmo prompt repetido custa 1,9 s (4B) / 3,2 s (8B), porque só o último token é processado. Na prática: **manter estável o prefixo** (prompt de sistema + definições de ferramentas + histórico antigo) e só acrescentar no final. O prompt de sistema (~305 tokens) e 3 ferramentas (~260) custam ≈ 18 s no 4B se o cache for perdido (por exemplo, ao trocar de modelo ou mudar o prefixo).
- **Threads (sonda, 4B, 3 rodadas intercaladas, só o prompt de 1,3 mil tokens):** padrão (6) 30,2 tok/s; 4 → 27,1; 8 → 33,1; **12 → 37,2 (+23%)**. Mais threads ajudam; é uma sonda do 4B, sem avaliar o impacto no aquecimento nem em outros processos do carro. `num_thread` **não** faz parte do contrato `LLMProvider`/`LLMSettings`; mexer nisso é decisão do P6, não do P5. A sonda usou o endpoint do Ollama diretamente (`bench/p5_prompt_cost.py`), isolada do contrato.

## 6. Contexto 4096 × 8192 (viável no hardware; subconjunto de 7 cenários, 5 rodadas, `--keep-awake`)

| | 4B 4096 | 4B 8192 | 8B 4096 | 8B 8192 |
|---|---|---|---|---|
| Prompt 1,3 mil tokens a frio (s, mediana) | 36,2 | 35,8 | 65,3 | 66,5 |
| Geração (tok/s, mediana) | ~10 | 8,0–12,0 (mesma faixa) | ~5,7 | 4,9–6,0 (mesma faixa) |
| RAM inferência (WS mediana, GB) | 3,2 | **3,7** | 5,7 | **6,3** |
| Qualidade | 90/90 | 35/35 | 90/90 | 35/35 |

Dobrar o contexto **não alterou a latência** com o mesmo prompt; custou ~0,5–0,6 GB de RAM por modelo. Conclusão: **manter 4096 como padrão** e usar 8192 só se um caso real precisar de mais histórico. Não foram testados prompts que de fato preencham 8192 tokens (a leitura a frio levaria ~4–5 min no 4B), então a latência de contextos realmente grandes é **extrapolação, não medida**.

## 7. Falhas, timeouts e interrupções

| Execução | Chamadas válidas | Falhas | Timeouts | Interrupções |
|---|---|---|---|---|
| Principal, ctx 4096 (11:49–12:33) | 180/180 | 0 | 0 | 0 |
| Threads, 12 chamadas | 12/12 | 0 | 0 | 0 |
| ctx 8192, repetição válida (14:37–15:05) | 70/70 | 0 | 0 | 0 |
| ctx 8192, **1ª tentativa — invalidada** | 42 | 1 | 1 (artefato) | 1 (abortada por orçamento de tempo) |

Causa da tentativa invalidada: o sistema parou por ~75 min (12:45–14:00; o log do Ollama não tem nenhuma linha nesse intervalo com uma requisição em andamento; uma chamada registrou 4370 s contra timeout de 300 s) e depois por ~13 min na rodada 4. É **consistente com suspensão do PC**, embora o log de energia do Windows não tenha confirmado. Esses dados **não foram usados**: foram preservados com `INVALID.md`, o harness passou a marcar como inválida e repetir uma vez qualquer chamada que estoure o timeout em > 30 s, e a execução foi refeita do zero com `--keep-awake` (`SetThreadExecutionState`, por processo; nenhuma configuração do Windows foi alterada).

## 8. Limitações

- Bateria de qualidade saturada (100% nos dois): não discrimina os modelos; pontuação heurística, 1 volta, só pt-BR, poucas frases por intenção.
- n = 5 por cenário; p95 ≈ máximo. Sem avaliação humana nem de fluência.
- RAM = *working set* dos processos de inferência (inclui páginas mapeadas do modelo) e `/api/ps`; não é "memória exclusiva".
- Temperatura da CPU não medida (exige admin); estabilidade avaliada só por deriva de vazão.
- Sem streaming → sem TTFT. Latências são de resposta completa.
- Sonda de threads feita só com o 4B; contexto 8192 só em subconjunto e sem preencher o contexto.
- A máquina é de desenvolvimento (uso interativo em paralelo); o hardware final do carro será diferente.
- A latência de leitura de prompt a frio (36 s / 65 s para ~1,3 mil tokens) é **inadequada para voz em tempo real** sem cache estável, streaming e prompts enxutos.

## 9. Para iniciar o P6 (sem avançar)

1. Adotar o 4B como padrão e tratar o 8B como opção; reavaliar com um conjunto **mais difícil** (grounding adversarial, instruções ambíguas, perguntas de múltiplas voltas) para saber se o 8B ganha onde a bateria atual não alcança.
2. Projetar o prompt para **prefixo estável** (sistema + ferramentas primeiro, histórico depois) e orçar tokens.
3. Decidir se `num_thread` entra na configuração (ganho medido +23% no prompt, com 12 threads).
4. Streaming e TTFT ainda não existem; necessários para a experiência de voz.
