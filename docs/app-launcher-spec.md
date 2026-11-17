# Fit AI App Launcher — especificação (PoC 02.5, sem implementação)

Nada aqui foi implementado nem testado. Onde a viabilidade depende de comportamento de terceiros (apps, DRM, navegadores) está marcado **A TESTAR**; não afirmo que funcione.

## 1. Objetivo

Abrir, focar, fechar e voltar à multimídia a partir de um **catálogo fixo de apps autorizados** (YouTube, WhatsApp Web, Chrome, Google Maps, Waze, Spotify, Netflix, Teams, outros), por toque ou voz, com bloqueio de recursos visuais durante a condução.

## 2. Princípios

1. **Catálogo, não comando livre**: só abre entradas do catálogo (arquivo versionado). Nenhum caminho, URL ou argumento vindo da fala/IA é executado; a IA escolhe um `app_id`.
2. **Não burla nada**: sem contornar DRM, login, proteções de app ou termos de plataforma. Sessões ficam com o próprio app/navegador; o Fit AI não lê nem guarda credenciais.
3. **Fail-closed na condução** (§6).
4. Windows primeiro, Linux depois, atrás da mesma interface.
5. Sem rede é um estado normal, não um erro fatal.

## 3. Avaliação técnica (o que se sabe e o que testar)

| Tema | Abordagem proposta | Situação |
|---|---|---|
| App nativo instalado | Executar o binário do catálogo (Windows: caminho/`App Paths`/`start`; Linux: `.desktop`/comando) | Padrão, mas **A TESTAR** por app (Spotify, Teams, WhatsApp desktop) |
| Aplicação web | Navegador Chromium em modo app (`--app=URL`) com **perfil dedicado por app** (`--user-data-dir`), mantendo sessão autenticada isolada | **A TESTAR** (Chrome/Edge no Windows) |
| Tela cheia / foco / retorno | Janela do app em tela cheia; "voltar à multimídia" traz a janela do OCTAVE à frente (ou fecha o app). O Windows restringe quem pode tomar o foco; pode exigir fechar/minimizar o app em vez de forçar foco | **A TESTAR**; em Linux depende de X11/Wayland |
| Sessões autenticadas | Perfil de navegador persistente por app; login feito pelo usuário parado | Depende de cada serviço |
| App indisponível | `NOT_INSTALLED` (com sugestão de instalar/alternativa web), nunca erro genérico | Definir no contrato |
| Internet | Entrada tem `requires_internet`; sem rede responde `NO_NETWORK` antes de abrir | Detecção de rede **A TESTAR** |
| DRM / streaming (Netflix, YouTube Premium, Spotify) | Usar o player oficial do serviço em navegador/app compatível; **qualidade e suporte dependem do navegador e do sistema**. Não prometer resolução nem compatibilidade | **A TESTAR**; Linux com DRM é mais restritivo (não verificado) |
| Web em movimento | Bloqueado (§6). Navegação (Maps/Waze) é caso à parte (§7) | Política |
| Voz | Comando "abrir X" → ferramenta `launch_app(app_id)` → mesma validação de §6 | PoC 03 |
| Windows / Linux | Interface única `AppLauncherProvider`, uma implementação por SO | Windows primeiro |

Observação: o OCTAVE já traz um gerenciador Spotify experimental e player local. Manter **uma só** fonte de Spotify (decidir após testar o do OCTAVE; ver matriz de reutilização).

## 4. Catálogo (exemplo de entrada, dados, não código)

```json
{
  "id": "youtube",
  "name": "YouTube",
  "kind": "web",
  "url": "https://www.youtube.com/",
  "launcher": "chromium_app",
  "requires_internet": true,
  "drm_streaming": true,
  "distraction": "visual_video",
  "allowed_when": "parked",
  "profile": "youtube"
}
```
Campos obrigatórios: `id`, `name`, `kind` (`native`|`web`), alvo (`path` ou `url`), `requires_internet`, `distraction`, `allowed_when`. URLs restritas por lista de origens permitidas; nenhum parâmetro vindo do usuário entra no comando.

`distraction`: `audio_only` | `visual_passive` | `visual_interactive` | `visual_video` | `navigation`.
`allowed_when`: `always` | `parked` | `never_in_v1`.

## 5. Contrato `AppLauncherProvider` (esboço Python)

```python
class LaunchStatus(StrEnum):
    LAUNCHED = "launched"
    ALREADY_RUNNING = "already_running"
    BLOCKED_DRIVING = "blocked_driving"        # inclui estado de condução desconhecido
    NOT_INSTALLED = "not_installed"
    NO_NETWORK = "no_network"
    AUTH_REQUIRED = "auth_required"            # só se o provedor conseguir detectar; senão o app mostra o login
    PLATFORM_UNSUPPORTED = "platform_unsupported"
    FAILED = "failed"

@dataclass(frozen=True)
class AppInfo: id; name; kind; installed: bool; running: bool; requires_internet: bool; distraction: str

@dataclass(frozen=True)
class LaunchResult: status: LaunchStatus; app_id: str; detail: str | None = None

class AppLauncherProvider(Protocol):
    async def list_apps(self) -> list[AppInfo]: ...
    async def get_state(self, app_id: str) -> AppInfo: ...          # KeyError se não está no catálogo
    async def launch(self, app_id: str, ctx: DrivingContext) -> LaunchResult: ...
    async def focus(self, app_id: str, ctx: DrivingContext) -> LaunchResult: ...
    async def close(self, app_id: str) -> LaunchResult: ...
    async def return_to_home(self) -> LaunchResult: ...             # sempre permitido
```
- `app_id` fora do catálogo ⇒ erro de validação, nunca execução.
- `close` e `return_to_home` **sempre** permitidos (sair é seguro).
- O gate de condução fica **no serviço que chama o provedor**, não só no provedor, para que um provedor trocado não o remova (`LaunchPolicy.check(app, ctx)` → permite/nega com motivo).

## 6. Bloqueio durante a condução

Não depender só de velocidade (pode faltar, estar velha ou errada).

```python
class DrivingState(StrEnum): PARKED = "parked"; DRIVING = "driving"; UNKNOWN = "unknown"

@dataclass(frozen=True)
class DrivingContext:
    state: DrivingState
    reasons: tuple[str, ...]     # ex.: ("speed_fresh_zero", "engine_off")
```
Regras propostas:
1. `UNKNOWN` **é tratado como `DRIVING`** (fail-closed). Só `PARKED` libera apps visuais.
2. `PARKED` exige sinais independentes e frescos: velocidade conhecida e igual a 0 **e** pelo menos uma confirmação adicional (motor desligado, freio de estacionamento, marcha em P/neutro quando houver). Quais sinais o Fit expõe via OBD é **desconhecido** hoje; sem confirmação extra, só vale o que for provado.
3. Dado ausente, link do OBD caído, OCTAVE indisponível (`503 vehicle_link_down`/`octave_unavailable`) ou leitura sem demanda ativa ⇒ `UNKNOWN`.
4. Histerese: ao detectar movimento volta a `DRIVING` imediatamente; para voltar a `PARKED` exige estabilidade por alguns segundos.
5. Sem modo "passageiro" nem override por voz na v1 (a IA não pode liberar o bloqueio).
6. Se um app visual já estiver aberto e o estado virar `DRIVING`, o launcher fecha ou esconde o app e volta à multimídia, com aviso por voz/áudio.
7. Áudio puro (`audio_only`) e voz continuam permitidos.
8. **Navegação (Maps/Waze)** é um caso de segurança próprio: tela de rota pode ser aceitável; busca/digitação não. Decidir a política antes de implementar.

## 7. Itens abertos / A TESTAR

- Waze e Google Maps: apenas via web (sem app de desktop conhecido para Windows; **não verificado**); qualidade para uso veicular desconhecida.
- WhatsApp/Teams: sessões e notificações; chamadas de vídeo são `visual_video` (bloqueadas na condução).
- Netflix/streaming: **A TESTAR** em navegador no Windows; não assumir.
- Foco e retorno ao OCTAVE no Windows.
- Perfil de navegador por app e persistência de sessão.
- Que sinais de estacionamento o Fit realmente fornece por OBD.

## 8. Critérios de aceite (futuros)

1. Para cada app do catálogo: lançar, focar, fechar e voltar à multimídia, num teste manual documentado com evidência.
2. Todos os ramos de `LaunchStatus` cobertos por teste automatizado com provedor falso.
3. Teste que prova que `UNKNOWN` bloqueia todo app visual e que `return_to_home` nunca é bloqueado.
4. Nenhuma execução com entrada fora do catálogo (teste de injeção de `app_id`/URL).
5. Auditoria: cada tentativa de abertura registra app, estado de condução, motivo e resultado.
