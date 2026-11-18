# PoC 03 — P4: AI Engine, LLMProvider e benchmark harness (2026-11-16/17)

Escopo: somente P4. Não há Conversation Service, `POST /api/v1/chat`, memória, ferramentas reais, grounding programático nem streaming. Sem commit/push. As alterações P1/P2/P3 não commitadas foram preservadas.

## 1. Arquitetura

```
src/fit_ai/ai/
  contracts.py        LLMProvider (Protocol async), GenerateRequest, prepare_request, check_response
  models.py           ChatMessage, ToolDefinition, ToolCall, LLMResponse, Usage, Timings, ProviderHealth
  errors.py           hierarquia LLMError (tipada)
  config.py           LLMSettings (FIT_AI_*), validadores de modelo e URL
  ollama_provider.py  adaptador HTTP (httpx.AsyncClient) — único lugar que conhece o formato do Ollama
  fake_provider.py    FakeLLMProvider + Reply (determinístico, scriptável, registra chamadas)
  identity.py + prompts/system_pt_br.md   instrução de sistema versionada
bench/                scenarios.py + run_benchmark.py (harness; resultados em bench/results/, ignorado pelo Git)
```

O pacote `fit_ai.ai` não importa FastAPI, OCTAVE, SQLite nem a API do Core. O Core (`main.py`, `config.py`, OBD/OCTAVE) **não foi alterado**; as configurações da IA ficam em `LLMSettings`, separadas de `fit_ai.config.Settings`, para que um erro em variável `FIT_AI_LLM_*` nunca impeça o Core de subir.

## 2. Contrato LLMProvider

```python
async def generate(messages, *, tools=(), response_format=None, timeout_s=None, max_tokens=None, think=None) -> LLMResponse
async def health() -> ProviderHealth      # nunca levanta por falha do provedor
```

`LLMResponse`: `content`, `tool_calls`, `model`, `finish_reason`, `usage` (prompt/cached/completion tokens), `timings` (`total_s`, `load_s`, `prompt_eval_s`, `generation_s`), `thinking_chars` (só o tamanho; o raciocínio não é guardado), `metadata`. Campos ausentes viram `None`. `total_s` é o total do provedor, **não** TTFT. `ToolCall` é apenas o *pedido* do modelo: o motor nunca executa ferramentas. `response_format` aceita `"json"` ou um JSON Schema.

## 3. OllamaProvider × FakeLLMProvider

Ambos passam pela mesma `prepare_request` (validação) e `check_response` (resposta vazia/incompleta) e satisfazem o mesmo `Protocol` (testes de contrato). O Ollama fala HTTP real (`/api/chat`, `stream:false`, `think:false` por padrão, `num_ctx`, `temperature`, `seed`, `num_predict` explícitos), reutiliza a conexão, serializa chamadas (uma por vez) e fecha o cliente em `aclose()`/`async with`. O Fake devolve respostas roteirizadas (texto, JSON, ferramenta, vazio, timeout, indisponível, transporte, malformada, incompleta, atraso), respeita timeout/cancelamento e registra cada chamada.

## 4. Configuração

| Variável | Padrão | Validação |
|---|---|---|
| `FIT_AI_MODEL` | `qwen3:4b-instruct-2507-q4_K_M` | `nome:tag` explícito, tag ≠ `latest` |
| `FIT_AI_OLLAMA_URL` | `http://127.0.0.1:11434` | só `http` em loopback, porta explícita, sem credenciais/caminho |
| `FIT_AI_LLM_TIMEOUT_S` | 120 | 1–600 |
| `FIT_AI_LLM_CONTEXT` | 4096 | 512–16384 |
| `FIT_AI_LLM_MAX_TOKENS` | 256 | 1–4096 e < contexto |
| `FIT_AI_LLM_TEMPERATURE` | 0.2 | 0–2 |
| `FIT_AI_LLM_SEED` | 42 | 0–2³¹−1 |
| `FIT_AI_LLM_THINK` | false | booleano |

Trocar de modelo é só mudar `FIT_AI_MODEL` (ou `LLMSettings.with_model`). Ollama desligado **não** é erro de configuração.

## 5. Tratamento de falhas

Erros tipados (`LLMError`): `LLMUnavailable`, `LLMTimeout`, `LLMTransportError`, `LLMInvalidResponse`, `LLMModelNotFound`, `LLMModelUnavailable`, `LLMContextExceeded`, `LLMIncompleteResponse`, `LLMInvalidRequest`, `LLMConfigurationError`. Sem `except Exception` silencioso. O timeout cobre fila + execução; o cancelamento assíncrono é propagado. Com o Ollama fora do ar o Core continua respondendo (testes da API passam com o servidor desligado).

## 6. Operação do Ollama portátil

```powershell
powershell -NoProfile -File ..\runtime\tools\ollama-serve.ps1   # sobe em 127.0.0.1:11434 (recusa se a porta estiver ocupada)
powershell -NoProfile -File ..\runtime\tools\ollama-stop.ps1    # encerra só o ollama.exe de runtime\ollama
```

## 7. Testes

```powershell
$env:PYTHONDONTWRITEBYTECODE=1
.\.venv\Scripts\python.exe -B -m pytest -q -rs                       # suíte principal (não precisa de Ollama)
.\.venv\Scripts\python.exe -B -m pytest tests/integration/test_llm_live.py -q -rs   # real (precisa do Ollama ligado)
```

Os testes reais são ignorados automaticamente, com o motivo, quando o servidor ou o modelo não existe; **ignorado ≠ aprovado**.

Resultado final desta etapa (Ollama desligado): **309 aprovados, 16 ignorados, 0 falhas** (11 ignorados = integração Ollama, 4 = OCTAVE vivo, 1 = SDK v0.9.6 sem `OctaveConnectError`). Integração real com Ollama ligado: **11/11 aprovados** em 84,7 s (pergunta simples, JSON estruturado, tool call reportada e não executada, ida-e-volta com resultado de ferramenta, troca para Qwen3 8B com `think:false`, health com digest verificado, timeout, cancelamento, estouro de contexto, modelo inexistente sem download; a indisponibilidade do servidor é coberta pelos testes unitários e pelo fato de a suíte principal rodar com o Ollama desligado).

## 8. Benchmark harness

```powershell
.\.venv\Scripts\python.exe -B -m bench.run_benchmark --models qwen3:4b-instruct-2507-q4_K_M qwen3:8b-q4_K_M --repeat 1
.\.venv\Scripts\python.exe -B -m bench.run_benchmark --provider fake     # ensaio sem Ollama (JSON/ferramenta falham de propósito)
```

Sete cenários (S1 curta PT, S2 contextual, S3 JSON Schema, S4 tool call fictícia, S5 veículo sem ferramentas, S6 contexto maior, S7 `think:false`), sempre **sequenciais**, `--repeat` limitado a 10. Cada um tem uma checagem funcional. A saída (`results.json` + `summary.md` em `bench/results/<data>/`, ignorado pelo Git) contém só métricas — sem prompts nem respostas, a menos que `--include-content`. TTFT não é medido (sem streaming).

### Validação funcional curta (1 amostra por cenário, CPU i5-1235U, ctx 4096) — **não é benchmark estatístico**

| Cenário | Qwen3 4B: ok · gen tok/s · total s | Qwen3 8B: ok · gen tok/s · total s |
|---|---|---|
| S1 curta PT | sim · 9,3 · 14,5 (inclui carga 3,3 s) | sim · 5,0 · 34,0 (inclui carga 4,8 s) |
| S2 contextual | sim · 8,3 · 17,5 | sim · 5,0 · 19,0 |
| S3 JSON Schema | sim · 8,6 · 4,5 | sim · 5,0 · 18,3 |
| S4 tool call | sim · 9,4 · 8,0 | sim · 5,2 · 13,9 |
| S5 sem ferramentas | sim · 11,5 · 1,6 | sim · 5,2 · 10,1 |
| S6 contexto ~1,3 mil tokens | sim · 7,6 · 51,7 | sim · 4,1 · 97,3 |
| S7 think:false | sim · 9,4 · 4,5 | sim · 6,2 · 28,1 |

Observações: (a) a primeira versão do S6 (~3 mil+ tokens) estourou o timeout de 120 s nos dois modelos; foi reduzida. O tempo é dominado pelo *prompt eval* em CPU — prompts grandes são o principal risco de latência para o uso no carro; (b) as taxas são maiores que as do P3 (4B ≈ 6,7; 8B ≈ 3,5–3,9 tok/s), provavelmente por variação de carga da máquina; só o P5 (amostras suficientes) pode decidir; (c) não foi avaliada a qualidade das respostas, só a conformidade funcional.

## 9. Limitações conhecidas

- Sem streaming nem TTFT (arquitetura permite adicionar depois).
- Uma chamada por vez (`OLLAMA_NUM_PARALLEL=1`); fila interna sem prioridade.
- O prompt de sistema orienta mas **não garante** grounding: a validação programática é do P6.
- Benchmarks com 1 amostra; variância e qualidade não avaliadas (P5).
- Somente CPU; latência de prompts longos é alta.
- O harness `--provider fake` não valida a qualidade do modelo, só o encanamento.

## 10. Próximos passos

- **P5:** benchmark comparativo com amostras suficientes (harness pronto), decidir entre Qwen3 4B e 8B.
- **P6:** grounding programático e ferramentas automotivas sobre o `FakeLLMProvider`.
- **P7:** Conversation Service e `POST /api/v1/chat`.
