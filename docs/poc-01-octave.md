# PoC 01 — OCTAVE no Windows (2026-11-16)

Resultado resumido: **OCTAVE v0.9.6 roda no Windows, o simulador funciona sem hardware, a API (TCP JSON-lines e WebSocket) responde em 127.0.0.1:9876 e o SDK Python oficial leu RPM/velocidade/temperatura simulados.**

## Ambiente
- Windows 11 Pro 10.0.26200, Python 3.14.3, Git 2.52. Sem CMake/compilador/Qt (não foi preciso: usada release oficial).
- Caminhos reais: `Desktop\FIT\externals\*`, `Desktop\FIT\FiT-AI`, runtime em `Desktop\FIT\runtime\octave` (fora de `externals`).

## Instalação
- Release oficial `RobDeGeorge/OCTAVE` v0.9.6 (2026-11-12), `OCTAVE-0.9.6-windows-x86_64.exe` (Inno Setup, 46 MB).
- SHA-256 `67b21033…9225c48` confere com o digest publicado pelo GitHub. **Não há assinatura Authenticode nem attestation** (404).
- Instalado por usuário, sem admin: `/CURRENTUSER /VERYSILENT /NOICONS /DIR=...\runtime\octave` (o padrão exigiria admin + regra de firewall do `adb`). Remoção: `runtime\octave\unins000.exe`.

## Como iniciar (verificado no código `src/main.cpp` e em execução)
```
OCTAVE.exe --headless --sim --service 9876
```
`--sim` = carro simulado (config temporária descartada ao sair), `--headless` = sem QML/janela + serviço, `--service [PORT]`, `--service-bind` (não usar), `--config DIR`, `--pair-code`. `--dev/--profile` só em builds de dev.
O modo com interface gráfica (`--sim` sem `--headless`) foi testado na PoC 02 (ver `poc-02-fit-ai-core.md`).

## Sobre o "problema de segurança" do checkout
Os hooks de `externals/octave/.git/hooks` (`post-checkout`, `post-commit`, `post-merge`, `pre-push`) são o stub padrão do **Git LFS** (`git lfs ...`), lidos sem executar. Falharam porque o `git-lfs` não estava no PATH durante o checkout; não há indício de código malicioso. O `.gitattributes` só envia `*.STL`/`*.SLDPRT` ao LFS. Os hooks não foram alterados.

## API (protocolVersion 3)
- Host `127.0.0.1`, porta `9876`, escuta apenas loopback (confirmado com `Get-NetTCPConnection`).
- TCP JSON-lines e WebSocket na mesma porta. Sem autenticação em loopback (`auth: trusted`, `loopbackOpen: true`); fora da máquina exige pareamento de 6 dígitos.
- Ops: `hello, describe, get, set, call, rows, subscribe/unsubscribe, stream/unstream, pair/unpair, mediaTicket`.
- Envelope: `{"id":N,"op":...}` → `{"id":N,"ok":true,"result":...}`. 27 objetos servidos.
- Testado de fato: handshake WebSocket (101), `hello`, `get paramStore RPM`, `call parameterCatalog.info`, `subscribe paramStore` (evento `params`), `call sim.*`.

## Dados reais obtidos
- Catálogo: RPM 0–8000 `RPM`; SPEED 0–160 **MPH** (unidade nativa; converter para km/h no Core); COOLANT_TEMP 0–120 °C.
- Marcha lenta: `{'RPM': 800, 'SPEED': 0, 'COOLANT_TEMP': 90}`.
- `sim.setThrottle(60)`: RPM 800 → 3168 → 4100 em ~2 s; SPEED 0 → 49,1 mph após ~5,8 s. COOLANT_TEMP ficou em 90 °C durante os 6 s observados (não foi observada variação).
- Veículo simulado: VIN `1J4FA49S03P123456` (Jeep 2003), 111 PIDs suportados, ELM327 simulado protocolo A6 (CAN).

## Testes do SDK oficial
`python -B -m unittest discover -s sdk/python/tests` com `OCTAVE_BIN` apontando para o binário instalado: 35 testes executados, 1 skipped, resultado final **FAILED (errors=3)**. Os 3 erros estão só em `tearDownClass` (`octave exited with 1`); nenhum teste funcional falhou. Reproduzido na PoC 02.5.
Causa confirmada: `HeadlessApp.stop()` do SDK usa `Popen.terminate()` (comentário "SIGTERM") e o teste exige código de saída 0; no Windows `terminate()` é `TerminateProcess` e o código é 1. É uma suposição POSIX do harness de testes do SDK, não uma falha do OCTAVE.

## Atenção: SDK do checkout ≠ SDK da release
O SDK usado (`externals/octave/sdk/python`) é o do HEAD do checkout, 48 commits após a v0.9.6, e difere do SDK da release (ex.: só o HEAD tem `OctaveConnectError` e `Client.closed`). O protocolo é o mesmo (v3). Ver `consolidation-review.md`.

## Atenção: o `paramStore` não tem timestamp e o polling é sob demanda
Um PID só é consultado ao OCTAVE se alguém o pede (tela aberta, varredura da caixa-preta ou `obdManager.setParameterDemand`). Sem pedido, `paramStore` mantém o último valor indefinidamente com o link "conectado". Os valores lidos acima funcionaram porque a varredura da caixa-preta vem ligada por padrão. Provado na PoC 02.5.

## Integração com o Fit AI Core
Viável sem modificar o OCTAVE: o Core é um cliente separado do protocolo (JSON/WebSocket). Licenças: backend GPL-3.0-or-later; SDKs/templates/protocolo MIT; a documentação da API afirma que um cliente só via protocolo pode usar qualquer licença (leitura do projeto, não aconselhamento jurídico). Não copiar código GPL para o Core.

## Pendências / riscos
- Release não assinada; checagem de atualização contacta o GitHub na inicialização (log `octave.network`).
- Honda Fit 2005: protocolo OBD-II real (provável K-line/ISO 9141 — **não verificado**) e PIDs expostos precisam ser testados com hardware, fora do escopo desta fase.
- `android/.gradle/` apareceu como não rastreado em `externals/octave` às 19:38, antes da instalação; origem não identificada (não criado por esta PoC).

## Reproduzir
```
python -B -I poc\octave-client\probe.py     # com o OCTAVE rodando em 9876
```
