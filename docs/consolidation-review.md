# Consolidação e auditoria técnica — PoC 02.5 (2026-11-16)

Escopo: revisar, corrigir problemas comprovados, testar e planejar. Sem IA, sem App Launcher, sem hardware.

## 1. Estado do repositório
- `FiT-AI/` é um repositório Git independente (clone de `github.com/FL4vi0x/FiT-AI`), branch `main`, 1 commit (`f4f94a9 Initial commit`, README de 2 linhas). Nada foi commitado depois.
- Não rastreado: `.gitignore`, `docs/`, `poc/`, `pyproject.toml`, `src/`, `tests/`. Modificado: `README.md`. Ignorados: `.venv/`, caches. Sem alterações preexistentes desconhecidas.
- `externals/`: nenhum arquivo alterado por este trabalho. Estado idêntico ao de antes: `octave/android/.gradle/` (não rastreado, origem desconhecida, anterior à instalação) e `openvoiceos/translations/nl-NL/intents.json` (modificado, 32 linhas trocadas por 32, aparenta ser fim de linha). Nenhum `__pycache__` em `externals/`.

## 2. Problemas encontrados e tratamento

| # | Sev. | Problema | Evidência | Ação |
|---|---|---|---|---|
| 1 | **Alta** | Dado velho servido como fresco: o OCTAVE só consulta PIDs pedidos (tela, varredura da caixa-preta ou `setParameterDemand`) e o `paramStore` não tem timestamp. | OCTAVE headless, varredura e caixa-preta desligadas: simulador a 126 mph, `paramStore SPEED=0`, RPM travado em 4650, `connected=true`. Com demanda: 139,8. | **Corrigido**: o adaptador registra a demanda dos 3 PIDs ao conectar e a libera ao encerrar. Verificado ao vivo no mesmo cenário (Core 48,9 → 99,9 → 151,0 → 202,0 km/h contra 50,8 → 101,9 → 153,0 → 203,9 do simulador; defasagem ≈ 2 km/h do ciclo de polling). |
| 2 | **Alta** | Adaptador quebrava com o **SDK exato da v0.9.6**: ele não tem `OctaveConnectError` nem `Client.closed`. O Core carregava o SDK do HEAD do checkout (48 commits adiante). | 7 testes falharam ao apontar `OCTAVE_SDK_PATH` para `git archive v0.9.6`. | **Corrigido** com detecção de recursos; suíte passa nos dois SDKs. |
| 3 | Média | Com o SDK da release, "OCTAVE parado" virava **504 timeout**: no Windows conectar numa porta fechada de loopback pode esgotar o timeout, e o SDK antigo deixa `TimeoutError` puro escapar. | Chamada real: 504 `octave_timeout`. | **Corrigido**: falha ao conectar é sempre `octave_unavailable` (503). Latência de ~2,0 s no Windows (limitação conhecida, ver §6). |
| 4 | Média | Corrida em `_drop()`: thread atrasada podia fechar uma conexão nova e saudável. | Leitura do código | **Corrigido** (`_drop(only=conn)`), com teste. |
| 5 | Média | README: a frase original do autor foi reescrita. | `git show HEAD:README.md` | **Corrigido** (frase literal restaurada). |
| 6 | Baixa | `__main__.py` subia o servidor ao ser importado. | Leitura | **Corrigido** (`if __name__ == "__main__"`). |
| 7 | Baixa | `pydantic` e `anyio` usados mas não declarados. | Imports vs `pyproject` | **Corrigido**. |
| 8 | Baixa | Erro de config / SDK ausente na partida saía como traceback. | Leitura | **Corrigido** (mensagem e `exit 2`), com testes. |
| 9 | Baixa | Teste com asserção frouxa (`91.2 or 91.3`). | Leitura | **Corrigido** (valor exato). |
| 10 | Info | O harness de teste do SDK falha 3x em `tearDownClass` no Windows. | Reproduzido; `stop()` usa `Popen.terminate()` (código 1 no Windows) e exige 0. | Causa confirmada; é do SDK, não do OCTAVE. Nada a corrigir aqui. |

**Mudança de premissa a validar com o dono do projeto**: a PoC 02 prometia "somente leitura". Agora o adaptador faz uma chamada com efeito colateral dentro do OCTAVE, `obdManager.setParameterDemand` (classificada pelo próprio OCTAVE com escopo `read`; só faz o OCTAVE consultar PIDs). Está limitada por lista de permissões aos 3 PIDs, é liberada no encerramento e é testada. **Nada é escrito no veículo.** Se a demanda ficar registrada após um crash do Core, o OCTAVE continua consultando esses 3 PIDs (inofensivo; é limpa no próximo ciclo normal de encerramento).

Não alterado, só registrado:
- **DNS rebinding / Host header**: a API não valida `Host`. Hoje só expõe telemetria de leitura em loopback, mas se um navegador for lançado no mesmo equipamento (App Launcher) uma página poderia tentar lê-la. Tornar `TrustedHostMiddleware` obrigatório **antes** de qualquer endpoint de escrita ou ferramenta de IA.
- Aviso `httpx` → `httpx2` do Starlette: não adotei `httpx2` por não ter verificado a procedência do pacote.
- Frescor: o Core não consegue provar o frescor de cada amostra (o `paramStore` não tem timestamp). Mitiga-se com a demanda registrada, o `connected` e uma espera de 1 s após conectar; é uma heurística, não uma garantia. Em OBD real (adaptador Bluetooth lento) a espera pode ser insuficiente.
- O Core depende de casamento por texto (`"no reply within"`) do SDK para classificar timeouts de requisição; está coberto por teste, mas quebra silenciosamente se o SDK mudar a mensagem.

## 3. Revisão por componente (resumo)
- **Domínio**: sem dependência de FastAPI/OCTAVE; tipagem completa; `None` para dado ausente; timestamp com timezone; contrato `TelemetryProvider` (Protocol). Sem pendências.
- **Adaptador**: leitura restrita por lista de permissões (leituras + `catalog_info` + `setParameterDemand`); conexão persistente com reconexão; timeouts em dois níveis (SDK + prazo total); unidades verificadas pelo catálogo; erros traduzidos; `closed`/`OctaveConnectError` opcionais. Thread safety: `threading.Lock` para a conexão, `asyncio.Lock` serializa leituras. Sem vazamento observado (conexão fechada em falha, em troca e em `aclose`).
- **Serviço / API**: injeção por `create_app(provider=...)`; erros estruturados `{"error":{code,message}}`; 503/504/502; OpenAPI documentado; só GET (405 nos demais); bind e config recusam não-loopback.
- **Config / partida**: variáveis de ambiente validadas; saída limpa em erro.

## 4. Testes (Python 3.14.3, executados nesta sessão)

| Cenário | Resultado |
|---|---|
| Coletados: 53 unitários, 13 de API, 4 de integração = **70** | |
| OCTAVE parado, SDK do checkout | 66 passed, **4 skipped** (integração) |
| OCTAVE parado, SDK v0.9.6 | 65 passed, **5 skipped** |
| OCTAVE real (headless `--sim`), SDK do checkout | **70 passed** |
| OCTAVE real, SDK v0.9.6 | 69 passed, 1 skipped (`OctaveConnectError` não existe nesse SDK) |
| Falhas | 0 |
| Cobertura (OCTAVE real, SDK do checkout; `coverage` instalado só no venv, **não** declarado no projeto) | **94%** (426 instruções, 25 não cobertas: `__main__` e o corpo de `run()`/uvicorn, ramos de erro de `load_sdk`) |

Cobertos por teste: timeout (SDK e prazo total), queda e reconexão, protocolo incompatível, unidade inesperada, dado ausente, link caído, conversão MPH↔km/h, somente leitura (lista de permissões), registro/liberação de demanda, corrida do `_drop`, e (com OCTAVE real) estado do simulador inalterado após leituras. Testes ignorados não foram contados como aprovados.

Não testado ao vivo: perda de conexão no meio de uma leitura com OCTAVE real além do cenário "OCTAVE encerrado"; `octave_protocol_incompatible` (só fake); OBD real.

Verificações manuais ao vivo desta etapa: experimento de dado velho (antes e depois da correção), Core com SDK da release e OCTAVE parado (503 em ~2,0 s).

## 5. Compatibilidade de SDK
| SDK | Origem | Estado |
|---|---|---|
| Release v0.9.6 | `git archive v0.9.6 sdk/python` | Verificado (suíte + OCTAVE real) |
| Checkout HEAD | `externals/octave/sdk/python` | Verificado, mas difere da release (+154 linhas em `__init__.py`); não é mais o padrão |

**Decisão do dono (fechamento da PoC 02.5): o padrão é o SDK da release v0.9.6**, extraído para `runtime/octave-sdk-0.9.6/` (fora do Git, blob `af32ccc…` idêntico ao da tag). O comando de extração está no README.

## 6. Limitações conhecidas
- OBD real do Fit não testado (protocolo K-line provável, PIDs expostos desconhecidos).
- Frescor por heurística (§2).
- 2 s de latência por requisição quando o OCTAVE está parado (Windows + timeout de conexão); pode-se reduzir com um timeout de conexão menor, não feito.
- Observação do simulador: temperatura constante em 90 °C.
- `simulated` depende do objeto `sim` (marcado experimental no OCTAVE).
- Checkout `externals/octave` (HEAD) serve 29 objetos na documentação; a release 0.9.6 serve 27.

## 7. Evidências
`docs/evidence/octave-gui-0*.png` (PoC 02), resultados desta tabela e os experimentos descritos em §2. Registros brutos de execução em `runtime/logs/` (fora do Git).

## 8. Fechamento (decisões do dono do projeto e última pendência)

- **Licenciamento**: repositório público só para consulta e estudo; sem licença open source e sem autorização geral de reuso, modificação ou redistribuição (README §13). Avisos dos componentes de terceiros preservados.
- **Versão de referência**: OCTAVE v0.9.6 com o SDK da mesma release.
- **Demanda de PIDs**: `setParameterDemand` autorizado exclusivamente para RPM, velocidade e temperatura, sem escrita na ECU nem controle do veículo (a lista de permissões do adaptador implementa isso).
- **Hardware**: continua só o simulador.
- **Segurança de rede (pendência fechada)**: validação do `Host` (`api/security.py`, middleware ASGI próprio, porque o `TrustedHostMiddleware` do Starlette corta o host no primeiro `:` e erra em IPv6), ausência de CORS, inventário de rotas por teste. Resultados na seção de validação final do relatório da sessão.
