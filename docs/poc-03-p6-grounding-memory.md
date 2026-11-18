# PoC 03 — P6: memória, ferramentas automotivas, grounding e auditoria (2026-11-17)

Escopo: somente P6. **Não existe** `POST /api/v1/chat`, voz, App Launcher, ferramenta de escrita, controle do veículo nem integração com OBD real. O Core (`main.py`, `config.py`, `api/`, adaptador OCTAVE, `domain/`, `services/`) **não foi alterado**: o código novo só foi adicionado. Sem commit/push.

Legenda: ✅ comprovado por teste ou medição desta etapa · ⚠️ comprovado com ressalva · 📋 planejado (não implementado).

## 1. Objetivos e resultado

Construir os alicerces do futuro assistente: memória local persistente, recuperação contextual, ferramentas somente de leitura sobre a telemetria existente, grounding por turno, verificação determinística de respostas, auditoria e um orquestrador interno reutilizável pelo P7.

**Resultado: P6 concluído, com ressalvas (seção 18).** A garantia central ficou comprovada nas execuções feitas: em **nenhuma** resposta final exibida nos 103 casos do corpus (determinístico e com modelo real) houve telemetria fabricada, segundo um oráculo independente do verificador. Isso é uma medição sobre um corpus limitado, **não** uma garantia universal.

## 2. Arquitetura implementada

```
src/fit_ai/
  memory/         models.py contracts.py sqlite_store.py retrieval.py   (781 linhas)
  tools/          contracts.py registry.py vehicle.py                   (352)
  grounding/      evidence.py response.py numbers.py verifier.py fallback.py (956)
  audit/          models.py contracts.py sqlite_audit.py                (202)
  orchestration/  config.py intent.py prompt.py turn.py                 (581)
  adapters/fake_telemetry.py   (provedor falso controlável: testes/bench/corpus)
bench/  p6_corpus.py p6_oracle.py p6_adversarial.py p6_perf.py          (ignorado: bench/results/)
```

Dependências (verificadas por teste via AST): `memory`, `audit` não dependem de nada acima delas; `grounding` usa só o *tipo* `ToolOutcome`; `tools` usa o `TelemetryService` existente e `memory`; `orchestration` usa `LLMProvider` (contrato), nunca `OllamaProvider`. **Nenhuma** camada nova importa FastAPI, httpx, o adaptador OCTAVE ou `fit_ai.api`, e nenhuma usa `subprocess`, `socket`, `eval`/`exec` ou `os.system`. O Core não importa nenhuma delas.

Fluxo de um turno (`AssistantOrchestrator.run`):
1. **Roteamento determinístico** (sem LLM): pedidos de controle do veículo são recusados sem chamar modelo nem veículo; marcadores de injeção são sinalizados.
2. **Somente ferramentas READ** que a intenção exige (no máximo uma rodada, escolhidas pelo código, não pelo modelo).
3. Cada resultado vira **evidência do turno**; auditoria antes e depois de cada ferramenta.
4. **Uma** chamada ao LLM com prompt compacto e resposta estruturada.
5. **Verificação por código**; se rejeitada, **uma** nova geração corretiva; se ainda rejeitada, **resposta determinística** montada só com a evidência (re-verificada antes de sair).
6. Persistência do turno (sem valores de telemetria) e registro de auditoria do turno.

## 3. Contratos principais

- `MemoryStore` (Protocol síncrono): conversas, turnos, preferências, fatos, `search`, exclusões, `purge_expired`, `compact`.
- `ToolRegistry`: `register(tool)` (rejeita o que não for READ) e `execute(name, args, allowed=...)` (**nunca levanta**: devolve `ToolOutcome` com `decision`, `error_code`, duração).
- `EvidenceBundle` / `Evidence`: leituras do turno; `value(campo)` é a **única** via pela qual uma resposta pode aprender um valor de sensor.
- `StructuredAnswer {answer, claims[{field,value,unit}], unknown[]}`: Pydantic estrito (`extra="forbid"`); `field ∈ {rpm, speed_kmh, coolant_temp_c}`.
- `verify(answer, bundle) -> Verdict(passed, violations[code,detail], verified)`.
- `AuditSink`: `record` (levanta `AuditWriteError`), `list_events`, `purge_expired`.
- `TurnResult`: resposta, origem (`llm | llm_retry | fallback | deterministic | policy_refusal | audit_refusal`), evidências, códigos de rejeição, nº de chamadas ao LLM, tempos por etapa.

## 4. Banco SQLite e configuração

Dois arquivos **separados**, fora do repositório por padrão (`FIT/runtime/data/`): `memory.db` e `audit.db` (apagar a memória nunca apaga a auditoria e vice-versa). WAL, `busy_timeout`, `foreign_keys`, `secure_delete=ON`; uma conexão curta por operação e `BEGIN IMMEDIATE` nas escritas. Tabelas: `conversations`, `turns`, `facts`, `preferences`, `memory_fts` (FTS5, `unicode61 remove_diacritics 2`), `audit_events`. `*.db`, `*.db-wal`, `*.db-shm` e `bench/results/` estão no `.gitignore`.

| Variável | Padrão | Validação |
|---|---|---|
| `FIT_AI_DATA_DIR` | `FIT/runtime/data` | sem `..` |
| `FIT_AI_MEMORY_DB` / `FIT_AI_AUDIT_DB` | `memory.db` / `audit.db` | só nome simples `*.db`, distintos |
| `FIT_AI_TURN_RETENTION_DAYS` | 30 | 1–3650 |
| `FIT_AI_AUDIT_RETENTION_DAYS` | 90 | 1–3650 |
| `FIT_AI_AUDIT_POLICY` | `fail_closed` | `fail_closed` \| `degrade_read_only` |
| `FIT_AI_TELEMETRY_MAX_AGE_S` | 10 | 0,5–120 |

Estas configurações são independentes das do Core e do LLM: um valor inválido não impede o Core de subir (teste).

## 5. Política de memória ✅

Só entram **fatos e preferências que o usuário pediu explicitamente** (`origin = "user_explicit"` é o único valor aceito; `telemetry`, `tool`, `model`, `simulated`... são rejeitados). Leituras de sensor **não** podem virar fato nem preferência (`rpm=800`, `speed_kmh: 0` etc. são recusados). O histórico de conversa guarda a mensagem do usuário e a resposta final, mas, se o turno usou telemetria, a resposta é gravada como `[resposta com leitura de telemetria — os valores não são guardados no histórico]`. Memória é informação **guardada**: as ferramentas a marcam `authority: user_statement`, `is_measurement: false`, e o prompt a rotula como "não são leituras de sensores e podem estar desatualizadas", com a idade de cada item. Nada de inferência de dados pessoais sensíveis.

## 6. Busca FTS5 ✅

Consultas parametrizadas; a consulta do usuário é reduzida a palavras (`\w+`), sem stop-words, no máximo 10, cada uma entre aspas (com prefixo para palavras ≥ 4 letras): operadores, filtros de coluna (`kind:`), `*`, `NEAR`, aspas e SQL **não** conseguem passar (14 consultas hostis testadas). Consulta vazia/só stop-words devolve vazio. Ordenação por `bm25` e, em empate, mais recente; limite máximo de 50. Linhas removidas/expiradas nunca aparecem (re-hidratação contra as tabelas-base). Sem FTS5 compilado, há *fallback* para `LIKE` parametrizado com escape de `% _ \` (testado com `use_fts=False`). Turnos só são pesquisáveis dentro de **uma** conversa (isolamento). A recuperação contextual (`ContextRetriever`) limita preferências (5), fatos (4), turnos recentes (2), 200 caracteres por item e 900 no total, e **não injeta nenhum fato quando nada é relevante**. Sem embeddings nem banco vetorial.

## 7. Exclusão e retenção ✅⚠️

Exclusão por id (fato, preferência, turno), de conversa (cascata + índice) e total; retenção configurável (turnos expiram; fatos têm TTL opcional; itens expirados ficam invisíveis imediatamente e `purge_expired` os remove fisicamente; teto de turnos por conversa). Após cada exclusão roda `_scrub()`: `INSERT INTO memory_fts(memory_fts) VALUES('optimize')` (reescreve o índice, sem deixar o termo em segmentos antigos) + `wal_checkpoint(TRUNCATE)`; `delete_all()` e `compact()` fazem também `VACUUM`.

**Evidência (banco isolado em `tmp_path`, nunca arquivos do usuário):** texto-canário único → recuperável pela API e pela busca → excluído → ausente da API, da busca **e dos bytes** de `.db`, `-wal`, `-shm` e `-journal` (varredura do canário como escrito e em minúsculas, que é como o FTS5 guarda os tokens). Cenários: fato, preferência (inclusive o valor sobrescrito), conversa+turnos, `delete_all`, expiração, WAL truncado.
**Controle negativo (feito):** com a rotina de limpeza desligada, o canário **continua** nos bytes (com `secure_delete` ligado ou não); com ela, some. Logo o teste detecta o problema que diz detectar.

**Limites — não prometo apagamento físico irrecuperável.** O SQLite zera o que ele mesmo libera, mas não controla: *wear levelling* de SSD, cópias antigas de blocos, journal do NTFS, *Volume Shadow Copies*/Histórico de Arquivos, backups, arquivos de paginação/hibernação, cópias do arquivo feitas pelo usuário, nem o conteúdo já exibido/copiado fora do banco. O banco não é criptografado. Para exigir mais, o caminho é criptografia de disco/arquivo e descarte da chave.

## 8. Ferramentas ✅

`Permission {READ, ACTION_LOW, ACTION_CONFIRM, FORBIDDEN}`; o registro só aceita `READ` **e** sem efeitos colaterais declarados (registrar outra coisa levanta `ToolRegistrationError`), e `execute` rechecha a permissão (um *spec* adulterado após o registro é recusado). Toda chamada: nome registrado, argumentos validados (`extra="forbid"`; JSON em string aceito, tamanho limitado), *timeout*, exceções contidas (`tool_error` sem vazar internos; log com traceback), mensagens de erro nunca repetem valores de argumentos. Ferramentas:

| Ferramenta | Entrada | Saída |
|---|---|---|
| `get_vehicle_telemetry` | nenhuma | RPM, km/h, °C, `state` (`ok`/`partial`), `missing`, `source`, `simulated` (`None` = desconhecido), `timestamp` |
| `get_vehicle_status` | nenhuma | disponibilidade, estado da conexão, protocolo, versão do OCTAVE, `simulated`, detalhe |
| `get_memory_facts` | `query` (≤ 200), `limit` 1–10 | fatos do usuário + `authority`, `is_measurement=false`, idade |

Chamam o `TelemetryService` **no mesmo processo** (nunca a API HTTP do Core). Nenhuma aceita caminho, URL, comando ou PID (testado). **O modelo não executa ferramentas:** o orquestrador escolhe e executa as READ; se o modelo pedir uma ferramenta (desconhecida, proibida ou até uma READ), o pedido é recusado e auditado. O contrato do provedor já rejeita chamadas não declaradas (então no Ollama real isso chega como resposta inválida e recebe a nova tentativa); a recusa no orquestrador é a segunda barreira, testada com um provedor que deixa a chamada passar.

## 9. Grounding ✅

Cada leitura vira `Evidence` com: execução, **turno**, ferramenta, horário, idade (relógio do provedor × fim da leitura), simulado/real/desconhecido, fonte, campos presentes e ausentes, erro. Regras por código: só `get_vehicle_telemetry` produz valores; `EvidenceBundle.add` **recusa** evidência de outro turno; leitura mais velha que o limite (10 s) é *stale* e não vale como valor atual; erro/negado não é leitura; memória e texto do usuário nunca são evidência.

## 10. Verificador ✅⚠️

Independente do LLM e **fail-closed**. Analisa as `claims` **e o texto livre** (um número no texto sem claim também é afirmação). Detecta números em dígitos (`1.200`, `1,5`, `5 mil`), por extenso até milhares (`oitocentas`, `dois mil e quinhentos`), unidades compostas, °F e mph (conversões explícitas e testadas), arredondamento **apenas** à precisão exibida (meio para cima; 801 não é 800). Códigos: `no_evidence`, `evidence_unavailable`, `stale_evidence`, `field_missing`, `value_mismatch`, `unit_mismatch`, `unverified_number`, `unsupported_sensor(_claim)`, `unverifiable_judgment`, `state_claim_mismatch`, `temporal_misattribution`, `negated_value_mismatch`, `claims_unavailable_capability`, `unreadable_number`, `not_portuguese`, `simulation_not_disclosed`, `simulation_misrepresented`, `claims_vehicle_control`, `turn_mixing`. Cobre os 12 pontos pedidos (ferramenta no turno, dados disponíveis, link caído, valor e unidade, simulação declarada, campo ausente, número digitado pelo usuário, sensor desconhecido, controle do veículo, memória × leitura, mistura de turnos).

**Limites documentados** (por isso é fail-closed): análise lexical/posicional, não compreensão de linguagem; só pt-BR (números em outros idiomas, romanos ou ofuscados **são rejeitados**, não "entendidos"); julgamentos sobre valores ("normal", "alta", "superaquecendo", "motor bem") são rejeitados porque **não há limites aprovados** no P6; faixas ("entre 700 e 900") e citar o número do usuário são rejeitados; números de conhecimento geral sem unidade de telemetria ("a cada 10 mil km") também caem em rejeição; "graus" sem escala é lido como °C; "1.500" = 1500. Resultado: **há falsos positivos** (respostas corretas rejeitadas), cobertos pelo *fallback*.

**Furos reais encontrados e corrigidos durante o P6** (agora com testes): números em inglês/espanhol/romanos eram aceitos → regra de unidade órfã + proteção de idioma; negação ("não está a 800 rpm") passava → `negated_value_mismatch`; valor passado ("ontem era 0 km/h") coincidindo com o atual → `temporal_misattribution`; o analisador engolia o ponto final de "rpm." → corrigido; o *fallback* arredondava 104,25 diferente do verificador → mesma regra (meio para cima); e, pelo modelo real, falsos positivos ("O RPM é 800 rpm", "não disponíveis") → corrigidos sem reabrir os furos.

## 11. Fallback determinístico ✅

Texto pt-BR montado só com a evidência: com leitura válida lista os campos pedidos (ou todos), diz se é simulado, e "Indisponível: …" para campos ausentes; sem leitura, explica o motivo (link caído, OCTAVE indisponível, timeout, sem dados, leitura desatualizada) **sem números**; sem evidência, "não está disponível". Propriedade testada em 138 combinações (108 de leituras completas × simulação sim/não/desconhecida, e 30 de dados parciais × campos pedidos): **todo texto do fallback passa pelo verificador**; em execução, o orquestrador ainda o re-verifica antes de devolver.

## 12. Auditoria ✅

Eventos `tool_authorization`, `tool_result`, `turn`, `policy` com `request_id`, UTC, ferramenta, permissão, decisão, resumo (≤ 240 caracteres), duração, código de erro, `simulated`. **Metadados, nunca conversa**: sem prompt, sem texto do usuário/da resposta (teste: um segredo digitado na pergunta não aparece nos bytes do banco). Redação automática no próprio modelo (Bearer/Basic, `api_key=`, `token=`, `senha=`, `sk-…`, chaves longas, e-mails, telefones, pasta de usuário do Windows). Retenção configurável com `purge_expired`. **Política de falha:** `fail_closed` (padrão) — o registro de autorização é gravado *antes* de ler o veículo, então se a auditoria falhar nada é executado; se falhar *depois*, o resultado é descartado e a resposta é "auditoria indisponível". `degrade_read_only` (opcional): segue respondendo, sinaliza `audit_degraded` e registra erro, justificado porque todas as ferramentas executáveis são READ (nenhum efeito colateral fica sem rastro); nunca é o padrão. Erros de auditoria carregam só o tipo da exceção (sem SQL, caminhos ou conteúdo).

## 13. Integração com Fake ✅
`FakeTelemetryProvider` (valores, simulação, falhas, latência, idade) + `FakeLLMProvider` roteirizado: resposta correta, RPM inventado, JSON inválido, campo desconhecido, resposta sem claims, simulação omitida, timeout, indisponível, chamada de ferramenta proibida/desconhecida/READ, teto de 2 chamadas por turno, isolamento entre turnos, política de auditoria. 47 testes do fluxo + o corpus.

## 14. Integração com OCTAVE real ✅
Simulador `OCTAVE.exe --headless --sim --service 9876` (iniciado e encerrado por mim; `127.0.0.1`; sem ECU). **4 testes novos + 4 existentes passaram**: ferramentas leem RPM/velocidade/temperatura pelo `TelemetryService` com `simulated=True`, protocolo 3 e versão; velocidade confere com o `paramStore` do simulador (mph → km/h); resposta determinística verificada; auditoria com a sequência esperada; o assistente **não altera** o estado do simulador (acelerador, freio, marcha, motor, link, realismo inalterados após 4 turnos, inclusive um pedido de controle). **Queda e recuperação** (só no processo que eu iniciei): um provedor de longa duração leu 1 vez/s; ao derrubar o OCTAVE a ferramenta devolveu `octave_unavailable` (1,5 s por tentativa, **nenhum valor antigo**); ao reiniciá-lo, o mesmo provedor voltou a `ok` em ≈ 2 s.

## 15. Integração com Ollama real ✅
**10/10 testes de integração** (148,5 s): 4B em 3 perguntas sobre telemetria controlada (zero fabricado; o 5000 do usuário não adotado), recusa de ação sem chamar modelo nem veículo, 4B sobre OCTAVE real ponta a ponta, troca para o 8B com as mesmas garantias, e Ollama fora do ar (`LLMUnavailable` → *fallback* com os valores, sem derrubar o turno).

## 16. Corpus adversarial e resultados ✅⚠️

`bench/p6_corpus.py`: **103 casos**, **16 categorias** (≥ 5 cada: RPM 10, velocidade 6, temperatura 7, unidades 6, sensores indisponíveis 6, dados parciais 5, link indisponível 5, dados simulados 5, informação do usuário 7, prompt injection 6, ambíguas 5, negação/extenso 11, ferramentas desconhecidas 5, ações no veículo 8, memória 6, histórico 5), incluindo as perguntas do enunciado. Cada caso declara se a **primeira** resposta do modelo deve ser aceita (`accept=True`) ou rejeitada (`False`), por critério de **segurança**, não pelo comportamento do verificador. A resposta **final** de todo caso passa por um **oráculo independente** (`p6_oracle.py`: não importa `fit_ai`, outra implementação de números/unidades) que procura telemetria fabricada, simulação não declarada e afirmações de ação. Dependências: determinístico (todos), LLM real (todos os `llm`), memória (6), OCTAVE (ferramentas e fluxo, em teste próprio).

**Modo determinístico (modelo roteirizado):** 103/103 casos conforme o especificado; 0 respostas finais inseguras; 0 casos em que o oráculo apontou a 1ª resposta e o verificador a aceitou. Observação honesta: eu escrevi os casos e o verificador; por isso o `red team` separado (números em outros idiomas, dígitos largos/espaçados, `0x`, romanos...) foi o que de fato achou furos, hoje cobertos por testes.

**Modelo real — Qwen3 4B Q4_K_M, `think:false`, ctx 4096, temp 0,2, 103 casos (97 chamadas ao modelo + 6 recusas por política):**

| | v1 (antes das correções) | v2 (verificador + prompt corrigidos) |
|---|---|---|
| Respostas brutas incorretas (oráculo, 1ª resposta) | 45,4% | **32,0%** |
| Rejeitadas pelo verificador (1ª tentativa) | 54,6% | 41,2% |
| Recuperadas pela nova geração (1 retry) | 18 | 35 |
| **Fallback determinístico** | **36,1%** (35) | **5,2%** (5) |
| **Respostas finais inseguras (oráculo)** | **0** | **0** |
| **Aceitas pelo verificador mas apontadas pelo oráculo** | **0** | **0** |
| Erros/timeouts do LLM | 0 | 0 |
| Latência por caso (mediana / p95 / máx.) | 11,1 / 16,9 / 32,6 s | 9,3 / 17,6 / 27,2 s |

A causa dominante das rejeições foi o modelo **não dizer que os dados são simulados** (50 das primeiras tentativas da v1; 32 só por isso), não inventar valores. A v2 reforçou isso no prompt, e corrigiu dois falsos positivos do verificador. Depois da v2, `dados_parciais` ainda tinha 4 fallbacks porque o modelo preenchia `claims` com um valor para o campo ausente; acrescentei ao prompt "campo ausente → `unknown`, sem claim" e repeti **só essa categoria**: 5/5 aceitos na primeira tentativa, 0 fallback, 0 inseguros (repetição direcionada de 5 casos, **não** uma nova medição completa). Em v2 ainda há 9 primeiras respostas que o oráculo considerou seguras mas o verificador rejeitou (p.ex. omitir "simulado", campo ausente): são falsos positivos **por regra**, aceitáveis (o *fallback* cobre).

**Latência p50 por categoria (4B, v2):** ações 0,03 s (recusa sem modelo) · sensores indisponíveis 3,4 s · link indisponível 4,1 s · memória 6,8 s · simulados 8,2 s · unidades 8,1 s · ambíguas 13,2 s · velocidade 13,4 s · temperatura 13,4 s · negação 14,1 s · info do usuário 14,8 s · RPM 15,4 s · dados parciais 16,0 s (esta última antes da correção do prompt).

**Qwen3 8B, mesma amostra espaçada de 26 casos (1 a cada 4; prompt v2) vs 4B nos MESMOS casos:** respostas brutas incorretas 16/24 (8B) × 11/24 (4B); fallback 5 × 1; latência mediana **29,2 s** (p95 38,4; máx. 77,8) × 14,8 s; **0 inseguras e 0 omissões do verificador nos dois**. Amostra pequena: serve para comparação controlada, não para estatística. Consistente com o P5, **o 4B continua sendo o padrão**.

Não declaro confiabilidade universal: 103 casos de uma mesma autoria, em pt-BR, simulador e telemetria de 3 campos.

## 17. Desempenho ✅ (notebook de desenvolvimento, SSD; não extrapolar para o hardware do carro)

Mediana (ms), 200 repetições (60 nas escritas), `bench/p6_perf.py`:

| Operação | memória vazia | 100 fatos | 1000 fatos | 5000 fatos |
|---|---|---|---|---|
| Inserir fato | 10,9 | 17,2 | 16,1 | 16,1 |
| Adicionar turno | 10,9 | 17,7 | 16,5 | 17,0 |
| Turnos recentes | 2,4 | 5,5 | 5,3 | 5,6 |
| Busca FTS5 (com resultado) | 8,0 | 7,7 | 8,5 | 13,2 |
| Busca FTS5 (sem resultado) | 5,6 | 5,6 | 5,2 | 5,6 |
| Recuperação contextual | 15,8 | 18,6 | 19,4 | 24,5 |
| Recuperação sem fato relevante | 16,0 | 16,7 | 16,0 | 16,0 |
| Excluir (inclui limpeza segura) | 30,0 | 32,4 | 36,4 | 52,2 |
| `compact()` (VACUUM) | 25,3 | 23,8 | 35,1 | 90,0 |

Demais: gravar auditoria 14,4 · ferramenta de telemetria 0,045 (completa ou parcial) · status 0,038 · **verificador 1,2 (aceita ou rejeita)** · fallback 0,02 · **orquestração inteira com LLM falso**: dados completos 54,4 · dados parciais 56,1 · sem memória 43,7 · 1000 memórias 91,6 · com 1 retry 56,4 (**44–92 ms**). Logo, em turno real **o tempo é do modelo** (3–16 s no 4B), e a camada nova soma poucas dezenas de ms. O custo por operação do SQLite (5–17 ms) vem de abrir uma conexão por operação e do WAL; é aceitável aqui e otimizável depois. O prompt tem **prefixo estático** (identidade + regras; testado: bytes idênticos entre turnos) para aproveitar o cache de prompt medido no P5; a **taxa real de acerto do cache nesta etapa não foi medida**. Execuções com modelo: ctx 4096, temp 0,2, seed 42, `think:false`, `max_tokens` 200, timeout 120 s (180 s no 8B), sequenciais, `--keep-awake` (sem alterar configurações do Windows).

## 18. Limitações conhecidas

- Verificador lexical/posicional, só pt-BR; há falsos positivos (no 4B v2, 41% das primeiras respostas foram rejeitadas e 5% dos casos acabaram no fallback; a taxa depende do modelo e do prompt) e não existem limiares aprovados para "normal/alto/baixo".
- Telemetria de **3 campos** simulados; nenhuma validação com OBD real; "simulado" depende do campo `simulated` do provedor.
- Memória **lexical** (sem semântica), sem criptografia, um usuário, concorrência testada com *threads* (não com vários processos).
- Exclusão física **best effort** (seção 7); a auditoria não é à prova de adulteração (sem encadeamento/assinatura).
- A resposta ainda não tem *streaming*; um turno real leva ~3–16 s no 4B em CPU (inadequado para voz sem streaming e cache estável).
- O modelo não escolhe ferramentas (decisão de projeto): intenções novas exigem regras no roteador; o roteador é por palavras-chave.
- O corpus é pequeno e da mesma autoria; o 8B foi avaliado em amostra de 26 casos; as correções de prompt (v2, v3) foram guiadas pelo próprio corpus (risco de ajuste ao corpus), por isso a v3 só foi medida numa categoria.
- Dois projetos em `externals/` já tinham 1 entrada não commitada **anterior ao P4** (`octave`: `android/.gradle/` não rastreado, 16/11 19:39; `openvoiceos`: `translations/nl-NL/intents.json` modificado, 16/11 19:33). Não foram tocadas pelo P6 e não as alterei nem reverti.

## 19. Riscos

Falso senso de segurança por o corpus passar; viés de co-autoria; recusa excessiva de respostas corretas degradando a experiência; dado simulado confundido com real se o provedor não marcar `simulated`; histórico/auditoria em disco sem criptografia; DNS rebinding e demais proteções de rede só valem quando o P7 expuser endpoints (o `HostGuard` já existe e deve ser exigido); prompt injection indireto via memória (mitigado: memória nunca é evidência e é rotulada).

## 20. Preparação para o P7 (sem iniciar)

Montar no `lifespan`: `OctaveProvider → TelemetryService → build_vehicle_registry(service, memory)` + `SqliteMemoryStore` + `SqliteAuditLog` + `OllamaProvider` (opcional) → `AssistantOrchestrator`; o endpoint chama `orch.run(TurnRequest(text, conversation_id))` e devolve `answer`, `source`, `simulated` e, opcionalmente, códigos de rejeição. Pontos a decidir: autenticação/Host em endpoints que escrevem (exclusão de memória), *streaming* e TTFT, unicidade de turno por conversa, política de auditoria padrão, limiares aprovados de temperatura/RPM (para permitir julgamentos), memória semântica, e se o `degrade_read_only` será exposto. O 4B com `think:false` e ctx 4096 é o padrão recomendado.

## 21. Como reproduzir

```powershell
$env:PYTHONDONTWRITEBYTECODE=1
.\.venv\Scripts\python.exe -B -m pytest -q -rs                                  # suíte (serviços opcionais)
.\.venv\Scripts\python.exe -B -m bench.p6_adversarial --mode fake               # corpus determinístico
.\.venv\Scripts\python.exe -B -m bench.p6_adversarial --mode ollama --models qwen3:4b-instruct-2507-q4_K_M --keep-awake
.\.venv\Scripts\python.exe -B -m bench.p6_perf                                  # desempenho local
..\runtime\octave\OCTAVE.exe --headless --sim --service 9876                    # simulador (somente leitura)
powershell -NoProfile -File ..\runtime\tools\ollama-serve.ps1                   # Ollama portátil
```

Totais finais: **sem serviços 1057 passaram, 25 ignorados** (linha de base do P5: 316/16; **750 testes novos**: memória 51, ferramentas 51, grounding 371, auditoria 18, orquestração 249 incluindo o corpus, integração real 10); **com OCTAVE e Ollama no ar 1081 passaram, 1 ignorado** (o do SDK v0.9.6, que não é do P6). Dados brutos em `bench/results/p6-*` (git-ignorado).
