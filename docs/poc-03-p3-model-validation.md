# PoC 03 — P3: download e validação dos modelos locais (2026-11-16)

**Resultado: P3 aprovado nos critérios de aceite, com ressalvas registradas na seção 12.** Nada de P4 foi implementado: nenhum `LLMProvider`, memória, ferramenta real, endpoint, grounding ou alteração no Core. Sem commit.

## 1. Ambiente
Windows 11, Intel Core i5-1235U (10 núcleos), 31,7 GB de RAM, GPU integrada Iris Xe, sem GPU dedicada. Disco livre: 214,0 GB antes, 201,6 GB depois (7,19 GB ocupados pelos modelos). Inferência **somente em CPU** (o Ollama descarta a iGPU por padrão: `dropping integrated GPU; to enable, set OLLAMA_IGPU_ENABLE=1`; não habilitada).

## 2. Ollama
Versão **0.40.16**, portátil em `runtime\ollama\`. Reauditado antes de começar: `ollama.exe` e utilitários com assinatura válida (CN=Ollama Inc.); 71 binários (exe/dll) com assinatura válida; **75/75 arquivos idênticos ao zip original** verificado no P1 (SHA-256 do zip `50fcf5ad…a64e`). Sem instalação global, sem processo, sem listener, sem variável global e sem modelos no estado inicial.
Ambiente do servidor (log `server config`): `OLLAMA_HOST=127.0.0.1:11434`, `OLLAMA_MODELS=runtime\ollama-models`, `OLLAMA_NO_CLOUD=true`, `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_KEEP_ALIVE=10m`, `OLLAMA_IGPU_ENABLE` vazio. Todas aplicadas só ao processo filho (`runtime\tools\ollama-serve.ps1`), com o "home" do Ollama em `runtime\ollama-home\`.

## 3–5. Modelos, identificadores, tamanhos e digests

| | Modelo A | Modelo B |
|---|---|---|
| Tag (exata, sem alias) | `qwen3:4b-instruct-2507-q4_K_M` | `qwen3:8b-q4_K_M` |
| ID do modelo (digest do manifesto v2) | `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0` | `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41` |
| Camada de pesos | `sha256:85e4a5b7b8ef0e48af0e8658f5aaab9c2324c76c1641493f4d1e25fce54b18b9` (2.497.280.480 B) | `sha256:a3de86cd1c13…` (5.225.374.496 B) |
| Template / params / config | `eade0a07cac7…` / `0914c7781e00…` / `b72accf9724e…` | `ae370d884f10…` / `cff3f395ef37…` / `05a61d37b084…` |
| Licença (camada) | `d18a5cc71b84…` (11.338 B, igual nos dois) | idem |
| Tamanho total (`/api/tags`) | 2.497.293.803 B (≈2,5 GB) | 5.225.388.164 B (≈5,2 GB) |
| Download | 21:51:21 → 21:53:22, **121 s** (≈20,6 MB/s médios) | 21:54:01 → 21:57:44, **223 s** (≈23,4 MB/s médios) |
| Retentativas / erros no cliente | 0 | 0 |

A tag `qwen3:4b-instruct` pedida inicialmente foi substituída pela tag explícita acima (decisão da especificação); a equivalência alias↔tag **não foi verificada** (não baixei o alias).

## 6. Verificação de integridade (independente do "success" do Ollama)
Para cada modelo: o SHA-256 recalculado do **manifesto v2** (`manifests-v2\ollama.com\library\qwen3\<tag>`) é igual ao digest que o `/api/tags` informa; e **cada blob** (config + 4 camadas) teve o SHA-256 recalculado e o tamanho conferido contra o manifesto: 5/5 corretos nos dois modelos, 0 blobs parciais. Os digests das camadas coincidem com os exibidos nas páginas públicas das tags no Ollama (verificação cruzada). Um erro **meu** durante a verificação (comparei contra o manifesto legado em vez do v2 e emiti "FALHA" indevidamente) foi detectado e corrigido na hora; a comparação correta passou.
**Limitação**: a cadeia de hashes prova que os arquivos locais são exatamente o que o registro anunciou. **Não há** verificação de assinatura criptográfica do publicador dos pesos; a confiança no conteúdo depende do registro do Ollama (TLS) e do próprio fornecedor.

## 7. Licenças
- **Licença embutida** (camada `d18a5cc71b84`, igual nos dois): texto padrão da **Apache License 2.0** (11.338 B). Não traz linha de titular de copyright; a página do Ollama também não.
- **Projeto original**: fichas oficiais do Qwen no Hugging Face (`Qwen/Qwen3-8B` e `Qwen/Qwen3-4B-Instruct-2507`), consultadas em 2026-11-16: **apache-2.0**.
- **Ollama** (software): MIT.
- Concordância entre o declarado e o distribuído: sim quanto ao tipo de licença. **Não verificado**: quem produziu a quantização Q4_K_M distribuída (publicada na biblioteca do Ollama) e se há avisos de atribuição adicionais. Apache-2.0 permite uso e redistribuição, exigindo manter o texto da licença e os avisos; **não redistribuímos pesos nem binários** (ficam em `runtime\`, fora do Git).

## 8. Metadados (via `/api/show`; "anunciado" ≠ "comprovado")

| | A | B |
|---|---|---|
| Arquitetura / quantização / formato | qwen3 / Q4_K_M (`file_type` 15) / gguf | idem |
| Parâmetros | 4,02 B | 8,19 B |
| Camadas / cabeças (kv) / embedding | 36 / 32 (8) / 2560 | 36 / 32 (8) / 4096 |
| Contexto anunciado | 262.144 | 40.960 |
| Capacidades anunciadas | tools, thinking, completion | completion, tools, thinking |
| Defaults do modelfile | temp 0,7, top_k 20, top_p 0,8 | temp 0,6, top_k 20, top_p 0,95 |
| `stop` | `<\|im_start\|>`, `<\|im_end\|>` | idem |
Observação: o Ollama anuncia `thinking` também para o 4B Instruct-2507, embora a ficha do modelo diga que ele só opera em modo sem raciocínio; no teste, `think:false` foi aceito e não houve campo de raciocínio. O contexto usado nos testes foi `num_ctx=4096` (padrão do Ollama), não o anunciado.

## 9. Testes mínimos (1 execução por teste; `num_ctx` 4096, temperatura 0,2, `seed` 1, `think:false`; resultados brutos em `runtime\logs\p3-smoke-*.json`)

| Teste | A (4B) | B (8B) |
|---|---|---|
| 1 Carregamento | OK, 4,8 s (parede); em memória: 3,19 GB (`/api/ps`), 0 em VRAM | OK, 8,0 s; 5,95 GB, 0 em VRAM |
| 2 Português | Responde em português fluente, **mas sem seguir a premissa**: afirmou que "não tem função em um assistente automotivo" | Responde em português, descrevendo a função de forma coerente com a pergunta |
| 3 JSON (schema via `format`) | JSON válido e conforme o esquema | JSON válido e conforme o esquema |
| 4 Ferramenta (fictícia, **não executada**) | `tool_calls` reconhecido: `ler_rotacao_motor` com `{}` | idem |
| 5 Thinking | `think:false`: sem raciocínio, 3 tokens | `think:false`: sem raciocínio (3 tokens, 3,9 s). **Padrão (`think` nulo)**: produziu raciocínio (794 caracteres, conteúdo **não armazenado**) e 319 tokens em 81,6 s para a mesma conta simples |
Conclusão do teste 5: no 8B, `think:false` **foi respeitado** nesta variante e é essencial para latência; em outras variantes pode se comportar diferente. Não é nota de qualidade: o teste 2 do 4B indica que o prompt precisará de instrução de sistema clara, a ser avaliada no P5.

## 10. Desempenho preliminar (observado, **não é benchmark**: 1 execução, poucas dezenas de tokens, sem controle de energia/térmico)
- Geração: A ≈ 6,7–6,8 tok/s; B ≈ 3,5–3,9 tok/s (após carregado).
- Avaliação de prompt (prompts curtos): A ≈ 19–21 tok/s; B ≈ 10–12 tok/s.
- RAM somada dos processos Ollama + runner com o modelo carregado: A ≈ 3,1 GB; B ≈ 5,7 GB.
- O campo `load_duration` veio 0,0 na carga com mensagens vazias; usei o tempo de parede.
- Uma pergunta curta de telemetria de ponta a ponta (duas chamadas) ainda não foi medida; é do P5.

## 11. Rede e segurança
- **Bind**: `127.0.0.1:11434` (servidor) e dois listeners do *runner* `llama-server.exe` (filho do `ollama.exe` do runtime, `--host 127.0.0.1`, portas aleatórias, `--offline --no-webui`). **0 listeners fora do loopback**; 0 serviços do Windows, 0 regras de firewall, 0 variáveis globais, 0 entradas de inicialização, nada em `~\.ollama`, `%LOCALAPPDATA%\Ollama` ou `%APPDATA%\ollama`.
- **Tráfego de saída** (amostragem de sockets a cada ≈0,7 s, 5.807 amostras de 21:51:02 a 22:07:48; **não** é captura de pacotes):
  - Download A e B: conexões HTTPS (443) para `104.18.16.170`/`104.18.17.170` (IPs que resolvem hoje `registry.ollama.ai`) e `172.64.190.1` (resolve o armazenamento de blobs em Cloudflare R2). Associação feita pelo DNS atual, não por SNI.
  - Conexões *keep-alive* ao registro persistiram até 21:59:06, depois do fim dos downloads; **nenhuma** conexão externa durante os testes de inferência (21:59:16–22:02:28).
  - **Repouso: 300 s exatos (22:02:47–22:07:47), 0 conexões externas.** UDP: nenhum.
- **Privacidade/credenciais**: 0 ocorrências de padrões de segredo nos 36 arquivos de `runtime\logs`; os logs não contêm trechos dos prompts testados; 0 WARN/ERROR no log do servidor. O par `id_ed25519` fica em `runtime\ollama-home\.ollama\`, fora do Git (nada com esse nome em `FiT-AI`). O Core não referencia o Ollama (0 ocorrências em `src/`) e não o expõe.
- **Aviso**: a janela de repouso de 5 min **não** cobre a tarefa "model recommendations" agendada (≈3 h 46 min após a partida do servidor). Portanto **não se pode concluir que o Ollama é totalmente offline**.
- Nada de firewall, proxy forçado ou bloqueio de rede foi criado.

## 12. Limitações, riscos e erros
1. Sem assinatura criptográfica do publicador dos pesos (só cadeia de hashes do registro).
2. Atribuição de IPs por DNS atual; amostragem pode perder conexões muito curtas.
3. Repouso de apenas 5 min; tarefa agendada do Ollama não observada.
4. As origens CORS padrão do Ollama continuam amplas (ver `poc-03-p1-p2-ollama.md`); o *runner* também escuta em portas loopback aleatórias sem autenticação: processos locais do mesmo usuário podem usá-lo.
5. Testes mínimos de execução única; capacidade de chamada de ferramentas provada só para 1 ferramenta sem parâmetros e 1 pergunta. Não generalizar.
6. Qualidade em português ainda não avaliada; a resposta do 4B no teste 2 foi fluente porém sem seguir a premissa.
7. Erro meu corrigido durante a verificação (seção 6). Nenhum erro do Ollama, do download ou dos modelos.

## 13. Próximas etapas
Estado ao final: servidor e *runner* encerrados (0 processos, 11434 fechada), monitor encerrado, modelos preservados em `runtime\ollama-models\`. Pronto para o **P4** (somente com autorização expressa): `LLMProvider` (Ollama + Fake), harness de benchmark (P5) e testes. Sugestões: usar `think:false` por padrão; definir instrução de sistema e avaliar português com o corpus de 60 perguntas; considerar uma observação longa (≥4 h, com autorização) antes de afirmar operação offline.
