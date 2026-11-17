# PoC 03 — P1/P2: Ollama portátil e verificação de segurança (2026-11-16)

Escopo autorizado: instalar o Ollama portátil (zip) e verificá-lo em loopback, **sem modelos**. Nada de IA, memória, ferramentas ou endpoints foi implementado. Sem commit.

## P1 — Instalação portátil
| Item | Resultado |
|---|---|
| Versão | **Ollama 0.40.16** (release oficial `ollama/ollama`, publicada em 2026-11-09), licença MIT |
| Artefato | `ollama-windows-amd64.zip`, 1.618.244.995 bytes |
| SHA-256 | `50fcf5ad54277f2fa5d173ebfc93bcb017adbc0c9ef2314daabc96ca9e6aa64e`: confere com o digest da API do GitHub **e** com o `sha256sum.txt` da release |
| Conteúdo do zip | 80 entradas, 0 caminhos suspeitos (`..`/absolutos), só `ollama.exe`, `llama-server.exe`, `llama-quantize.exe` e 68 DLLs |
| Assinatura Authenticode | **Válida (CN=Ollama Inc.)** no `ollama.exe`, nos 2 utilitários e nas 68 DLLs |
| Destino | `runtime\ollama\` (75 arquivos, 2,11 GB), fora do Git |
| Não feito | instalador, administrador, serviço, início automático, PATH, variáveis globais |

## P2 — Servidor em loopback e testes (sem modelos)
Execução por `runtime\tools\ollama-serve.ps1` (fora do Git): variáveis só no processo filho (`OLLAMA_HOST=127.0.0.1:11434`, `OLLAMA_MODELS=runtime\ollama-models`, `OLLAMA_NO_CLOUD=1`, `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_KEEP_ALIVE=10m`) e `USERPROFILE`/`HOME` apontando para `runtime\ollama-home`.

| Verificação | Resultado |
|---|---|
| Bind real | `netstat`: `127.0.0.1:11434 LISTENING`, único soquete do processo; log: `Listening on 127.0.0.1:11434 (version 0.40.16)` |
| Nuvem | log: `Ollama cloud disabled: true` |
| Sem modelos | `GET /` 200 "Ollama is running"; `/api/version` 200; `/api/tags` e `/api/ps` 200 com lista vazia; `POST /api/chat` com modelo inexistente: 404 `{"error":"model '…' not found"}` |
| Cabeçalho `Host` | `evil.example:11434` e `127.0.0.1.evil.example`: **403**; `localhost:11434`: 200. **O Ollama valida o `Host`** (fecha o ponto que estava em aberto) |
| `Origin` / CORS | Origens `https://evil.example`, `http://evil.example:11434` e `null`: **403**, sem `Access-Control-*`. Preflight com origem externa: 403 |
| POST "simples" cross-origin (`text/plain`) e `application/json` com `Origin` externo | **403** nos dois; sem `Origin` (cliente não-navegador como o Core): processa normalmente |
| Rede local | Conexão **recusada** nos 9 IPv4 da máquina (incl. Wi-Fi `192.168.100.13`, redes virtuais WSL/Hyper-V/VirtualBox) e em `[::1]`; só `127.0.0.1`/`localhost` responde |
| Tráfego de saída | Nenhuma conexão externa em ~25 s de observação; o processo só tem o soquete de escuta; sem UDP |
| Firewall | 0 regras criadas (consulta de leitura); firewall não alterado |
| Escritas fora de `runtime\` | Nenhuma: `~\.ollama`, `%LOCALAPPDATA%\Ollama` e `%APPDATA%\ollama` não existem; sem variáveis globais `OLLAMA*`; sem entrada de inicialização |
| GPU integrada | Descartada por padrão (`dropping integrated GPU; to enable, set OLLAMA_IGPU_ENABLE=1`): inferência em **CPU** (31,7 GiB totais, 17,9 GiB livres no momento) |
| Contexto padrão | `default_num_ctx=4096` (confirmado no log) |
| Repouso | ≈28 MB de RAM, 14 threads |
| Chave | O Ollama gerou um par `id_ed25519` em `runtime\ollama-home\.ollama\` (privada nunca exibida, fora dos logs; só a pública aparece no log) |

## Riscos observados
1. **Origens permitidas por padrão são amplas** (log): `http(s)://localhost[:*]`, `127.0.0.1[:*]`, `0.0.0.0[:*]`, `app://*`, `file://*`, `tauri://*`, `vscode-webview://*`, `vscode-file://*`. Qualquer página servida em `localhost` (qualquer porta, inclusive um servidor de desenvolvimento ou o próprio Core), um arquivo HTML aberto por `file://` ou um app com webview pode chamar a API do Ollama pelo navegador do usuário. `OLLAMA_ORIGINS` só **acrescenta** à lista (a documentação diz "additional origins"); não há como reduzi-la por variável. Sem autenticação, qualquer processo local do mesmo usuário também usa o modelo. *Mitigação nesta PoC*: o Core é o único cliente; o Ollama não é repassado pela API; nunca abrir páginas não confiáveis no mesmo equipamento enquanto o servidor estiver ligado. Risco aceito e documentado.
2. **"model recommendations cache"**: o log mostra uma tarefa agendada (próxima execução em ≈3h46m, `consecutive_failures=0`). Não observei conexão de saída em 25 s, mas **não verifiquei** se ela contata servidores externos quando executa, nem se `OLLAMA_NO_CLOUD=1` a impede. Requer observação mais longa (≥4 h) antes de dizer que o servidor é 100% offline. Não alterei o firewall, como combinado.
3. **O download de modelos (P3) exige internet**: o Ollama contata o registro de modelos. Depois do P3 pode-se reavaliar um bloqueio de saída (por exemplo `HTTPS_PROXY` inválido no processo filho, que também impediria novos downloads).
4. **A chave `id_ed25519`** é material sensível (identifica a instalação para recursos de nuvem, desativados). Fica em `runtime\ollama-home\`, fora do Git; nunca incluir em backups públicos.
5. Metade dos itens "não verificados" da especificação foi resolvida (validação de `Host`, GPU integrada, ausência de início automático); continua em aberto o ponto 2.

## Estado ao final
Servidor encerrado (0 processos, nada escutando na porta 11434). Nenhum modelo baixado. `runtime\ollama`, `ollama-home`, `ollama-models` (vazio, só a estrutura que o Ollama criou) e `tools` existem fora do Git. O zip baixado (1,6 GB) ficou numa pasta temporária fora do projeto.

## Recomendação para o P3
Avançar para o P3 (download de `qwen3:4b-instruct-2507-q4_K_M` e `qwen3:8b-q4_K_M`), com estas condições: manter o servidor ligado só durante os testes; reexecutar a observação de tráfego durante e depois do download; registrar *digest* e licença embutida; e decidir, depois, se o risco 2 justifica reforço de rede.
