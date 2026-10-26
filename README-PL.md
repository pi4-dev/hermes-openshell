<!-- Polskie tłumaczenie README.md — przy zmianach aktualizuj oba pliki. -->
# hermes-openshell

[English version](README.md)

Agent [Hermes](https://github.com/NousResearch/hermes-agent) (NousResearch), [Claude Code](https://code.claude.com/docs) na subskrypcji Claude albo oba naraz, każdy we własnym sandboxie [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell), z gatewayem jako Docker Compose. Opcjonalnie cały ruch wychodzący sandboxa, także zapytania do modelu, idzie przez Squida w kontenerze (upstream proxy).

## Architektura

```
Hermes (sandbox) ──▶ proxy supervisora OpenShell ──▶ [Squid (whitelista)] ──▶ internet
                     (polityka per binarka)   │          opcjonalnie
                                              └──▶ model-relay ──▶ [Squid] ──▶ API modelu
                                                   (klucz, endpoint, nazwa modelu)

Claude Code (sandbox) ──▶ proxy supervisora OpenShell ──▶ [Squid] ──▶ api.anthropic.com
                          (dokłada token subskrypcji)
```

- Hermes zna tylko relay modelu (`http://host.docker.internal:8082/v1`), alias modelu `assistant` i atrapę klucza. Usługa `model-relay` trzyma `MODEL_BASE_URL`, `MODEL_API_KEY` i `MODEL_NAME`. Dodaje klucz, podmienia alias na prawdziwy model i sama odpowiada na `/v1/models`. Z odpowiedzi usuwa nazwy modeli, pola z providerem, komentarze SSE i strony błędów inne niż JSON, a przekazuje dalej tylko wywołania inferencji. Nie zdradza oprogramowania serwera, a na wszystko inne odpowiada tym samym pustym 404; health i metryki są na osobnym porcie (zobacz Relay modelu: health i metryki).
- Sandbox nie dostaje żadnych ustawień modelu ani providera OpenShell. `hermes` w obrazie to launcher, który usuwa zmienne `OPENSHELL_*` i kieruje zmienne z bundlem CA na neutralne kopie. `hermes/config.yaml` nie ma komentarzy, bo Hermes może go przeczytać.
- Nadal widoczne w sandboxie, bo to sam runtime OpenShell: PID 1 `/.openshell/runtime/openshell-sandbox` w `/proc`, montowania pod `/.openshell` i `/run/openshell-supervisor-ca` oraz CA TLS `OpenShell Sandbox CA` na przechwytywanych połączeniach HTTPS. Dociekliwy agent nadal może ustalić, że działa w OpenShell, ale nie pozna endpointu modelu ani klucza.
- Kontenery sandboxów nie są usługami compose. Tworzy je gateway przez `docker.sock`.
- Bez upstream proxy ruch wychodzący kontrolują tylko polityki OpenShell (`policy/hermes-policy.yaml`, `policy/claude-policy.yaml`, per binarka).

### Agenci: Hermes, Claude Code albo oba

`COMPOSE_PROFILES` w `.env` wybiera agentów. Compose buduje i uruchamia tylko ich usługi, a bootstrap tworzy ich sandboxy:

| `COMPOSE_PROFILES` | Sandboxy | Usługi |
|---|---|---|
| `hermes` | `hermes` | model-relay, obraz Hermesa |
| `claude` | `claude` | obraz Claude Code |
| `hermes,claude` | `hermes` i `claude`, równolegle | wszystkie powyższe |

Agenci współdzielą tylko gateway. Każdy ma własny sandbox, politykę i dostęp do modelu, a pliki przechodzą między nimi tylko przez ciebie (zobacz przykłady w Praca z Claude Code).

- Claude Code działa na subskrypcji Claude (Pro, Max, Team lub Enterprise) z tokenem z `claude setup-token`, a nie na kluczu API. Bootstrap zapisuje token w gatewayu jako providera `claude-subscription` (`providers/claude-subscription.yaml`). W sandboxie `CLAUDE_CODE_OAUTH_TOKEN` zawiera tylko placeholder. Supervisor wstawia prawdziwy token do nagłówka `Authorization` zapytań, które `/usr/local/bin/claude` wysyła do `api.anthropic.com`, i nigdzie indziej. Z tym hostem może się łączyć tylko Claude Code i procesy, które uruchomi, a prawdziwy token nigdy nie trafia do sandboxa.
- `claude/settings.json` wyłącza automatyczne aktualizacje (Claude Code aktualizuje przebudowa obrazu, zobacz Aktualizacja Claude Code), telemetrię, raporty błędów i automatyczny marketplace pluginów, więc Claude Code nie potrzebuje żadnego hosta poza `api.anthropic.com`.
- Sandbox z Claude nie jest zanonimizowany jak ten z Hermesem: placeholder i `OPENSHELL_SANDBOX` pokazują, że działa w OpenShell, a jego endpoint modelu to i tak api.anthropic.com.

### Opcjonalne upstream proxy (Squid)

Proxy włącza linia `COMPOSE_FILE=docker-compose.yml:docker-compose.proxy.yml` w `.env`. W `.env.example` jest włączona. Zakomentuj ją, żeby działać bez Squida.

- `HTTPS_PROXY` w sandboxie nie działa z założenia, bo supervisor przepisuje środowisko proxy agenta. Squid jest więc podpięty jako upstream supervisora przez `[openshell.drivers.docker] https_proxy` w `openshell/gateway.proxy.toml`.
- Dostęp przechodzi przez dwie niezależne bramki. Host musi być **jednocześnie** w polityce agenta, `policy/hermes-policy.yaml` albo `policy/claude-policy.yaml` (OpenShell, per binarka), i w `squid/whitelist.txt` (Squid, per domena).
- Przez Squida idzie też ruch samego gatewaya, relay modelu i budowa obrazów (`pip`, `git`, `npm`, pobranie Node i Claude Code).
- `firewall.sh` może dodatkowo zablokować bezpośrednie wyjście kontenerów, tak żeby Squid był jedyną drogą na zewnątrz.

| Ścieżka | Rola |
|---|---|
| `docker-compose.yml` | bazowy stack: openshell-init (klucze JWT), openshell-gateway, bootstrap; per agent: model-relay i obraz Hermesa (`hermes`), obraz Claude Code (`claude`) |
| `docker-compose.proxy.yml` | opcjonalne upstream proxy: squid i ustawienia proxy dla gatewaya i buildów |
| `openshell/gateway.toml` | driver docker, tryb sieci bridge (bez proxy) |
| `openshell/gateway.proxy.toml` | to samo plus upstream proxy supervisora (używany z proxy) |
| `squid/` | konfiguracja i whitelista domen |
| `model-relay/` | relay zgodny z OpenAI, który trzyma klucz, endpoint i nazwę modelu; jedyny endpoint modelu znany Hermesowi; `/health` i `/metrics` na osobnym porcie |
| `hermes/` | obraz sandboxa z Hermesem i gotowym dashboardem WWW, `config.yaml` (tylko relay i alias modelu) i launcher `hermes` |
| `claude/` | obraz sandboxa z Claude Code: bazowy obraz sandboxa (git, Node, Python, uv, narzędzia do budowania), wydanie Claude Code z `CLAUDE_RELEASE` i ustawienia Claude |
| `providers/claude-subscription.yaml` | profil providera OpenShell: token subskrypcji, tylko dla `claude` → `api.anthropic.com` |
| `bootstrap/` | jednorazowa konfiguracja przez CLI OpenShell: rejestracja gatewaya, provider, sandboxy |
| `policy/hermes-policy.yaml` | polityka OpenShell sandboxa z Hermesem (filesystem, proces, sieć) |
| `policy/claude-policy.yaml` | polityka OpenShell sandboxa z Claude Code |
| `firewall.sh` | reguły DOCKER-USER: kontenery wychodzą tylko przez squida (tylko z proxy) |

## Uruchomienie krok po kroku

Kroki oznaczone **(proxy)** dotyczą tylko trybu z włączonym upstream proxy. W przeciwnym razie je pomiń.

1. **Wymagania.** Linux z Docker Engine **28.0 lub nowszym** i pluginem compose (sprawdź: `docker version --format '{{.Server.Version}}'`). Starsze wersje przerywają tworzenie sandboxa błędem `getent unable to find entry "998:998" in passwd database`, bo szukają użytkownika kontenera na hoście. Jądro musi wspierać Landlock (ABI 3 lub nowsze) i seccomp.

2. **Konfiguracja.** Wykonaj `cp .env.example .env` i uzupełnij:
   - `COMPOSE_FILE`: zostaw, żeby używać upstream proxy, zakomentuj, żeby działać bez niego,
   - `COMPOSE_PROFILES`: `hermes`, `claude` albo `hermes,claude` (zobacz Agenci wyżej),
   - `HOST_BRIDGE_IP` (z `ip -4 addr show docker0`),
   - dla Hermesa: `MODEL_BASE_URL`, `MODEL_API_KEY`, `MODEL_NAME`,
   - dla Claude Code: `CLAUDE_CODE_OAUTH_TOKEN`, token z `claude setup-token` (zobacz Token Claude niżej).

3. **(proxy) IP i whitelista.** Wpisz to samo IP mostka w `https_proxy` w `openshell/gateway.proxy.toml`, bo TOML nie czyta `.env`. Host backendu modelu dopisz do `squid/whitelist.txt` (Hermes). `api.anthropic.com` (Claude Code) już tam jest.

4. **(proxy) Firewall (zalecane).** Uruchom `sudo sh firewall.sh`. Skrypt blokuje bezpośrednie wyjście kontenerów do internetu, z wyjątkiem squida. Działa tylko dzięki `supervisor_network_mode = "bridge"`. Nie uruchamiaj go bez proxy, bo odetnie kontenerom cały ruch wychodzący.

5. **(proxy) Start squida i test.**
   ```
   docker compose up -d squid
   curl -x http://172.17.0.1:3128 -I https://pypi.org
   ```

6. **Budowa obrazów:** `docker compose build` buduje obrazy wybranych agentów. Z proxy robisz to po starcie squida, bo `pip`, `git`, `npm` i pobranie Claude Code w buildzie idą przez niego. Obrazy bazowe i sprawdzenie wydania Claude Code (`ADD` w `claude/Dockerfile`) pobiera sam dockerd, więc ewentualne proxy ustaw w daemonie.

7. **Start gatewaya.**
   ```
   docker compose up -d openshell-gateway
   curl -sf http://127.0.0.1:8081/healthz
   ```
   Port musi być 8080 po obu stronach, bo sandboxy wołają z powrotem `host.openshell.internal:8080`.
   Compose najpierw uruchamia `openshell-init`, który zapisuje klucze JWT sandboxów w `/var/lib/openshell/tls`. Driver docker ich wymaga. Gateway trzyma bazę, klucze i wypakowaną binarkę supervisora w `/var/lib/openshell` na hoście i działa jako root, tak jak setup `deploy/docker` w repo OpenShell.

8. **Bootstrap:** `docker compose up bootstrap`. Uruchamia też relay modelu dla Hermesa i czeka, aż będzie zdrowy (healthy). Skrypt rejestruje gateway i tworzy sandboxy wybranych agentów z ich politykami; dla Claude Code najpierw zapisuje token w gatewayu. Ponowne uruchomienie: `docker compose run --rm bootstrap`; istniejące sandboxy zostają bez zmian, ale token Claude jest aktualizowany, więc po nowym `claude setup-token` popraw `.env` i uruchom go ponownie. Działający sandbox używa nowego tokenu w nowych procesach po kilku sekundach. Żeby zmienić model, klucz albo endpoint, popraw `.env` i uruchom `docker compose up -d model-relay`; sandboxa nie trzeba ruszać. Jeśli okno kontekstu modelu nie wynosi 131072 tokenów, ustaw `context_length` w `hermes/config.yaml` i przebuduj obraz.

9. **Praca z agentami.** Zainstaluj CLI OpenShell na hoście, w tej samej wersji co gateway. Paczka `openshell` na PyPI to tylko SDK Pythona, a upstreamowy `install.sh` stawia też własny lokalny gateway, więc weź statyczną binarkę z wydania:
   ```
   V=0.1.5
   A=openshell-$(uname -m)-unknown-linux-musl.tar.gz
   curl -fsSLO https://github.com/NVIDIA/OpenShell/releases/download/v$V/$A
   curl -fsSLO https://github.com/NVIDIA/OpenShell/releases/download/v$V/openshell-checksums-sha256.txt
   grep " $A\$" openshell-checksums-sha256.txt | sha256sum -c
   sudo tar -xzf $A -C /usr/local/bin openshell
   ```
   Potem:
   ```
   openshell gateway add http://127.0.0.1:8080 --name local
   openshell sandbox exec --tty hermes -- hermes
   openshell sandbox exec --tty claude -- claude
   ```
   `sandbox exec` uruchamia w sandboxie nowy proces. Powłokę dostaniesz przez `openshell sandbox exec --tty hermes -- /bin/bash -l`. `openshell sandbox connect hermes` nie otwiera powłoki. Podłącza się do głównego procesu sandboxa (`HERMES_CMD`) i odtwarza jego ostatnie wyjście. Przy domyślnym `sleep infinity` nic nie pokazuje, więc tylko wygląda na zawieszone. `Ctrl-C` rozłącza i zostawia główny proces uruchomiony. Do ciągłej pracy (Telegram, Slack, API) ustaw `HERMES_CMD=hermes gateway run` i odtwórz sandbox (`openshell sandbox delete hermes`, potem ponownie bootstrap). Wtedy `sandbox connect` pokazuje wyjście tego gatewaya. Wymaga klienta `ssh` na hoście. Dla Claude Code zobacz przykłady w Praca z Claude Code.

### Token Claude

`CLAUDE_CODE_OAUTH_TOKEN` to długoterminowy token z `claude setup-token`, ważny rok. Wymaga subskrypcji Claude (Pro, Max, Team lub Enterprise). Utwórz go na dowolnej maszynie, na której możesz zalogować się tym kontem, ale nie w sandboxie OpenShell: jego polityka nie przepuszcza logowania, a prawdziwy token z założenia nigdy tam nie trafia.

- **Twój komputer z przeglądarką i Claude Code:** uruchom `claude setup-token`. Otworzy się przeglądarka, a po zalogowaniu terminal wypisze token (`sk-ant-oat01-…`).
- **Host Dockera przez SSH, bez przeglądarki:** zainstaluj Claude Code (`curl -fsSL https://claude.ai/install.sh | bash`) i uruchom `claude setup-token`. Wypisze link: otwórz go na dowolnym urządzeniu, zaloguj się i wklej otrzymany kod z powrotem do terminala.
- **Bez instalowania czegokolwiek na hoście:** użyj jednorazowego kontenera z bazowego obrazu sandboxa, który ma już Claude Code. To zwykły kontener z normalną siecią, nie sandbox, a logowanie przebiega jak przez SSH:
  ```
  docker run --rm -it --entrypoint claude ghcr.io/nvidia/openshell-community/sandboxes/base:latest setup-token
  ```
  Z działającym `firewall.sh` (tryb z proxy) kontenery nie mają bezpośredniego dostępu do internetu, więc użyj jednej z dwóch pierwszych opcji.

Potem wpisz token do `.env` jako `CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-…` i uruchom bootstrap (`docker compose run --rm bootstrap`, jeśli był już uruchamiany). Traktuj token jak hasło; `.env` jest w `.gitignore`. `CLAUDE_CODE_OAUTH_TOKEN` wyeksportowany w powłoce ma dla `docker compose` pierwszeństwo przed `.env`, więc usuń go tam (`unset`). Gdy token wygaśnie, Claude zgłosi `401 OAuth access token is invalid`: utwórz nowy tak samo, podmień go w `.env` i ponownie uruchom bootstrap. Działający sandbox przejmie go bez odtwarzania.

### Interfejs WWW (dashboard)

Obraz zawiera webowy dashboard Hermesa razem z czatem. Sandbox nie ma własnej sieci, więc dashboard słucha w nim na `127.0.0.1:9119`, a `openshell forward` tuneluje ten port na hosta:

1. Uruchom dashboard jako główny proces sandboxa: ustaw w `.env` `HERMES_CMD=hermes dashboard --skip-build --no-open` i odtwórz sandbox (`openshell sandbox delete hermes`, potem `docker compose up bootstrap`). Bez `--skip-build` Hermes przy starcie próbuje przebudować dashboard, co w sandboxie nie może się udać.
2. Na hoście: `openshell forward start 9119 hermes -d`, potem otwórz http://127.0.0.1:9119/. `openshell forward stop 9119 hermes` zamyka tunel.
3. Z innej maszyny przez SSH: `ssh -L 9119:127.0.0.1:9119 user@host-dockera`, potem otwórz tam http://127.0.0.1:9119/.

Przy bindzie na loopback dashboard nie ma logowania i daje pełną kontrolę nad Hermesem (konfiguracja, klucze, sesje), więc nie przekierowuj go na `0.0.0.0` ani inny interfejs.

### Relay modelu: health i metryki

Na porcie API (8082) relay odpowiada sandboxom tylko na `/v1/models` i wywołania inferencji. Wszystko inne, także `/health` i `/metrics`, dostaje ten sam pusty 404, a żadna odpowiedź nie zdradza oprogramowania serwera. Health i metryki są na osobnym porcie, `MODEL_RELAY_OPS_ADDR` w `.env` (domyślnie `127.0.0.1:9082`), na który polityki sandboxów nie pozwalają:

- `GET /health` zwraca `{"status": "ok"}`. Compose używa go jako healthchecku kontenera (`docker compose ps model-relay` pokazuje `healthy`), a bootstrap na niego czeka.
- `GET /metrics` zwraca metryki Prometheusa. Ich etykiety nie zawierają nazw modelu ani backendu:

| Metryka | Typ | Etykiety, znaczenie |
|---|---|---|
| `model_relay_requests_total` | counter | `path` (ścieżka API albo `other` dla wszystkiego innego), `code` |
| `model_relay_request_duration_seconds` | histogram | `path`; całe zapytanie, razem ze streamingiem |
| `model_relay_time_to_first_byte_seconds` | histogram | `path`; do nagłówków odpowiedzi backendu |
| `model_relay_tokens_total` | counter | `type` (`input`, `output`), według backendu |
| `model_relay_in_flight_requests` | gauge | zapytania w trakcie przekazywania |
| `process_start_time_seconds` | gauge | czas startu relaya |

Prometheus na tym samym hoście zbiera je tak:
```yaml
scrape_configs:
  - job_name: model-relay
    static_configs:
      - targets: ["127.0.0.1:9082"]
```
Z kontenera Prometheusa w sieci compose `osnet` celem jest `model-relay:9000`. Dla Prometheusa na innej maszynie ustaw `MODEL_RELAY_OPS_ADDR` na adres hosta w LAN i uruchom `docker compose up -d model-relay`.

Przykładowe zapytania do Grafany:
- tokeny na minutę: `sum by (type) (rate(model_relay_tokens_total[5m])) * 60`
- p95 czasu do pierwszego bajtu: `histogram_quantile(0.95, sum by (le) (rate(model_relay_time_to_first_byte_seconds_bucket[5m])))`
- nieudane wywołania inferencji: `sum by (code) (rate(model_relay_requests_total{path!="other",code!~"2.."}[5m]))`
- zapytania spoza API, na przykład agent skanujący relay: `increase(model_relay_requests_total{path="other"}[1h])`

Tokeny są liczone, gdy backend podaje zużycie: w każdej odpowiedzi bez streamingu, a w streamach tylko wtedy, gdy backend je dołącza.

### Praca z Claude Code

`openshell sandbox exec --tty claude -- claude` uruchamia Claude Code interaktywnie w sandboxie. Subskrypcja jest już skonfigurowana, więc nie ma logowania. Przy pierwszym starcie w danym folderze Claude pyta, czy mu ufasz, a `claude --continue` wznawia ostatnią sesję w tym folderze (sesje zostają w sandboxie).

Sandbox nie dzieli z hostem żadnego folderu. Kod wchodzi i wychodzi przez `openshell sandbox upload` i `download`, przez gita albo przez wyjście `sandbox exec`. `upload` wkłada katalog *do* katalogu docelowego, więc wgrywaj do `/sandbox` albo `/tmp`. Dla commitów robionych w sandboxie ustaw raz tożsamość gita:
```
openshell sandbox exec claude -- git config --global user.name "Claude (sandbox)"
openshell sandbox exec claude -- git config --global user.email claude@sandbox.invalid
```

**Projekt tam i z powrotem.** Z repozytorium gita upload stosuje `.gitignore` i pomija `.git`, więc pliki `.env`, `node_modules` i historia zostają na hoście:
```
openshell sandbox upload claude ./myapp /sandbox                # -> /sandbox/myapp
openshell sandbox exec --tty --workdir /sandbox/myapp claude -- claude
openshell sandbox download claude /sandbox/myapp ./myapp-claude
```

**Z historią gita: bundle do środka, patche na zewnątrz.** Claude pracuje na klonie i commituje, a ty przeglądasz jego commity i nakładasz je na hoście:
```
git -C ~/src/myapp bundle create /tmp/myapp.bundle --all
openshell sandbox upload claude /tmp/myapp.bundle /tmp
openshell sandbox exec --workdir /sandbox claude -- git clone /tmp/myapp.bundle myapp
openshell sandbox exec --tty --workdir /sandbox/myapp claude -- claude   # "dodaj walidację wejścia z testami i zrób commit"
openshell sandbox exec --workdir /sandbox/myapp claude -- git format-patch origin/HEAD --stdout > claude.patch
git -C ~/src/myapp am < claude.patch
```
Publiczne repozytorium można też sklonować prosto z GitHuba: `openshell sandbox exec --workdir /sandbox claude -- git clone https://github.com/<owner>/<repo>.git`. Sandbox nie ma poświadczeń GitHuba, więc push zostaje na hoście.

**Bez interakcji, do skryptów.** `claude -p` wykonuje jedno zadanie i wypisuje wynik. Bez uprawnień tylko czyta, więc pozwól na to, czego zadanie potrzebuje:
```
# Pytania o kod
openshell sandbox exec --workdir /sandbox/myapp claude -- claude -p "Wyjaśnij architekturę w 10 punktach"
# Edycja plików i tylko polecenie testów
openshell sandbox exec --workdir /sandbox/myapp claude -- claude -p "Napraw padające testy" \
  --permission-mode acceptEdits --allowedTools "Bash(npm test:*)"
# Bez żadnych pytań o zgodę
openshell sandbox exec --workdir /sandbox/myapp claude -- claude -p "Zaktualizuj zależności i napraw build" \
  --dangerously-skip-permissions
openshell sandbox exec --workdir /sandbox/myapp claude -- git diff > upgrade.patch
```
Z `--dangerously-skip-permissions`, także interaktywnie, Claude wykonuje wszystko bez pytania, ale tylko w sandboxie: polityka OpenShell nadal decyduje, do jakich hostów dociera i jakie pliki widzi, a token nie opuszcza supervisora.

**Claude i Hermes równolegle** (`COMPOSE_PROFILES=hermes,claude`). Na przykład Claude pisze zmianę, a Hermes ją recenzuje:
```
openshell sandbox exec --workdir /sandbox/myapp claude -- git format-patch origin/HEAD --stdout > change.patch
openshell sandbox upload hermes change.patch /tmp
openshell sandbox exec hermes -- hermes -z "Zrecenzuj /tmp/change.patch: błędy, brakujące testy, ryzykowne zmiany"
```

**Aktualizacja Claude Code.** Obraz instaluje wydanie wskazane przez `CLAUDE_RELEASE` w `.env`: `latest` (domyślnie), `stable` (mniej więcej tydzień w tyle, z mniejszą liczbą regresji) albo konkretną wersję, np. `2.1.310`. `docker compose build claude-image` instaluje nowe wydanie, jeśli jest; w przeciwnym razie build pochodzi z cache. Sandbox zostaje przy obrazie, z którego go utworzono, więc odtwórz go, po pobraniu z niego tego, czego potrzebujesz:
```
docker compose build claude-image
openshell sandbox download claude /sandbox/myapp ./myapp-backup
openshell sandbox delete claude
docker compose run --rm bootstrap
openshell sandbox exec claude -- claude --version
```
Nowsze modele przychodzą z nowszymi wydaniami Claude Code (`/model`). Autoupdater jest wyłączony celowo. Tylko `/usr/local/bin/claude` może wysyłać token do api.anthropic.com, a ten plik należy do roota, więc agent nie może go podmienić. Automatyczna aktualizacja zainstalowałaby Claude Code w katalogu domowym sandboxa, do którego agent może pisać.

**Więcej sandboxów z Claude**, na przykład jeden na projekt, wszystkie na tej samej subskrypcji. Uruchom to w katalogu repozytorium, bo `--policy` to lokalny plik:
```
openshell sandbox create --name claude-api --from claude-sandbox:local \
  --policy policy/claude-policy.yaml --provider claude-subscription --detach -- sleep infinity
openshell sandbox exec --tty claude-api -- claude
```

**Czego potrzebuje projekt.**
- Narzędzia: obraz ma gita, Node 22, Pythona 3 z uv, gcc i make. Inne dodaj w `claude/Dockerfile`, potem uruchom `docker compose build claude-image`, `openshell sandbox delete claude` i ponownie bootstrap. Usunięcie sandboxa usuwa jego pliki, więc najpierw pobierz to, czego potrzebujesz.
- Sieć: polityka pozwala gitowi łączyć się z GitHubem, a npm i PyPI instalować paczki. Hosty potrzebne projektowi dopisz do `policy/claude-policy.yaml` (z proxy także do `squid/whitelist.txt`) i zastosuj je w działającym sandboxie przez `openshell policy set claude --policy policy/claude-policy.yaml --wait`. Pobrania stron przez samego Claude idą z `/usr/local/bin/claude`, więc dla takich hostów wskaż tę binarkę.
- Serwer deweloperski, który Claude uruchomi w sandboxie na `127.0.0.1:5173`, jest dostępny z hosta po `openshell forward start 5173 claude -d`, pod http://127.0.0.1:5173/.

### Późniejsza zmiana trybu

- **Wyłączenie proxy:** najpierw usuń squida (`docker compose rm -sf squid`), potem zakomentuj `COMPOSE_FILE` w `.env`.
- **Włączenie proxy:** odkomentuj `COMPOSE_FILE` i przejdź kroki 3–5.

Następnie uruchom `docker compose up -d openshell-gateway` (compose odtworzy gateway z drugą konfiguracją) i odtwórz sandboxy, żeby przejęły nowe ustawienia supervisora.

## Weryfikacja

- `openshell sandbox exec hermes -- hermes -z "ping"` powinien dostać odpowiedź z backendu modelu.
- `docker compose logs model-relay` pokazuje zapytanie (`POST /v1/chat/completions`). `openshell policy get hermes --full` pokazuje regułę `model` dla `host.docker.internal:8082`. `curl -s http://127.0.0.1:9082/health` zwraca `{"status": "ok"}`, a `curl -s http://127.0.0.1:9082/metrics | grep model_relay_requests_total` liczy to zapytanie.
- `openshell sandbox exec claude -- claude -p "reply with OK"` powinien dostać odpowiedź od Claude. `openshell sandbox exec claude -- printenv CLAUDE_CODE_OAUTH_TOKEN` wypisuje tylko placeholder (`openshell:resolve:env:…`), a `openshell logs claude | grep anthropic` pokazuje `ALLOWED /usr/local/bin/claude(0) -> api.anthropic.com:443 [policy:_provider_claude_subscription …]`. `401 OAuth access token is invalid` oznacza zły albo wygasły token: wygeneruj nowy przez `claude setup-token`, wpisz go do `.env` i uruchom ponownie bootstrap.
- Host spoza polityki powinien zostać odrzucony już przez OpenShell.
- **(proxy)** Log squida: `docker compose exec squid tail -f /var/log/squid/access.log`. Po zapytaniu z Hermesa powinien się w nim pojawić `CONNECT <host-modelu>:443` od relaya, a po zapytaniu z Claude Code `CONNECT api.anthropic.com:443`.
- **(proxy)** Host dozwolony w polityce, ale nieobecny w whiteliście, powinien dać `TCP_DENIED` w squidzie.

## Do sprawdzenia względem przypiętej wersji OpenShell

- Instalacja Hermesa na obrazie `openshell-community/sandboxes/base`: `uv sync --frozen` z `uv.lock` checkoutu `HERMES_REF` (zwykły pip nie rozwiązuje zależności hermes-agent). Lock obejmuje tylko Pythona 3.14, czyli wersję z obrazu bazowego. Przypnij `HERMES_REF`.
- Polityka wskazuje binarkę `/sandbox/.uv/python/**`, czyli prawdziwą ścieżkę Pythona z obrazu bazowego (`/usr/local/bin/python3` to symlink do niego). Po zmianie obrazu bazowego sprawdź w sandboxie `readlink -f "$(command -v python3)"` i popraw politykę.
- `claude/install-claude.py` instaluje natywny build Claude Code z downloads.claude.ai do `/usr/local/bin/claude`, ścieżki wskazanej w `providers/claude-subscription.yaml`, i sprawdza jego sha256 względem manifestu wydania, tak jak oficjalny `install.sh`. Jeśli nowa wersja Claude Code potrzebuje innego hosta, `openshell logs claude` pokaże go jako `DENIED`.
- **(proxy)** `proxy_connect_by_hostname = true` jest konieczne, bo inaczej CONNECT idzie na IP i `dstdomain` w squidzie nie działa.
