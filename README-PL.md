<!-- Polskie tłumaczenie README.md — przy zmianach aktualizuj oba pliki. -->
# hermes-openshell

[English version](README.md)

Agent [Hermes](https://github.com/NousResearch/hermes-agent) (NousResearch) uruchomiony w sandboxie [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell) z gatewayem jako Docker Compose. Opcjonalnie cały ruch wychodzący sandboxa, także zapytania do modelu, idzie przez Squida w kontenerze (upstream proxy).

## Architektura

```
Hermes (sandbox) ──▶ proxy supervisora OpenShell ──▶ [Squid (whitelista)] ──▶ internet
                     (polityka per binarka)   │          opcjonalnie
                                              └──▶ model-relay ──▶ [Squid] ──▶ API modelu
                                                   (klucz, endpoint, nazwa modelu)
```

- Hermes zna tylko relay modelu (`http://host.docker.internal:8082/v1`), alias modelu `assistant` i atrapę klucza. Usługa `model-relay` trzyma `MODEL_BASE_URL`, `MODEL_API_KEY` i `MODEL_NAME`. Dodaje klucz, podmienia alias na prawdziwy model i sama odpowiada na `/v1/models`. Z odpowiedzi usuwa nazwy modeli, pola z providerem i komentarze SSE, a przekazuje dalej tylko wywołania inferencji.
- Sandbox nie dostaje żadnych ustawień modelu ani providera OpenShell. `hermes` w obrazie to launcher, który usuwa zmienne `OPENSHELL_*` i kieruje zmienne z bundlem CA na neutralne kopie. `hermes/config.yaml` nie ma komentarzy, bo Hermes może go przeczytać.
- Nadal widoczne w sandboxie, bo to sam runtime OpenShell: PID 1 `/.openshell/runtime/openshell-sandbox` w `/proc`, montowania pod `/.openshell` i `/run/openshell-supervisor-ca` oraz CA TLS `OpenShell Sandbox CA` na przechwytywanych połączeniach HTTPS. Dociekliwy agent nadal może ustalić, że działa w OpenShell, ale nie pozna endpointu modelu ani klucza.
- Kontener sandboxa z Hermesem nie jest usługą compose. Tworzy go gateway przez `docker.sock`.
- Bez upstream proxy ruch wychodzący kontroluje tylko polityka OpenShell (`policy/hermes-policy.yaml`, per binarka).

### Opcjonalne upstream proxy (Squid)

Proxy włącza linia `COMPOSE_FILE=docker-compose.yml:docker-compose.proxy.yml` w `.env`. W `.env.example` jest włączona. Zakomentuj ją, żeby działać bez Squida.

- `HTTPS_PROXY` w sandboxie nie działa z założenia, bo supervisor przepisuje środowisko proxy agenta. Squid jest więc podpięty jako upstream supervisora przez `[openshell.drivers.docker] https_proxy` w `openshell/gateway.proxy.toml`.
- Dostęp przechodzi przez dwie niezależne bramki. Host musi być **jednocześnie** w `policy/hermes-policy.yaml` (OpenShell, per binarka) i w `squid/whitelist.txt` (Squid, per domena).
- Przez Squida idzie też ruch samego gatewaya, relay modelu i budowa obrazów (`pip`, `git`).
- `firewall.sh` może dodatkowo zablokować bezpośrednie wyjście kontenerów, tak żeby Squid był jedyną drogą na zewnątrz.

| Ścieżka | Rola |
|---|---|
| `docker-compose.yml` | bazowy stack: openshell-init (klucze JWT), openshell-gateway, model-relay, budowa obrazu Hermesa, bootstrap |
| `docker-compose.proxy.yml` | opcjonalne upstream proxy: squid i ustawienia proxy dla gatewaya i buildów |
| `openshell/gateway.toml` | driver docker, tryb sieci bridge (bez proxy) |
| `openshell/gateway.proxy.toml` | to samo plus upstream proxy supervisora (używany z proxy) |
| `squid/` | konfiguracja i whitelista domen |
| `model-relay/` | relay zgodny z OpenAI, który trzyma klucz, endpoint i nazwę modelu; jedyny endpoint modelu znany Hermesowi |
| `hermes/` | obraz sandboxa z Hermesem, `config.yaml` (tylko relay i alias modelu) i launcher `hermes` |
| `bootstrap/` | jednorazowa konfiguracja przez CLI OpenShell: rejestracja gatewaya, sandbox |
| `policy/hermes-policy.yaml` | polityka OpenShell (filesystem, proces, sieć) |
| `firewall.sh` | reguły DOCKER-USER: kontenery wychodzą tylko przez squida (tylko z proxy) |

## Uruchomienie krok po kroku

Kroki oznaczone **(proxy)** dotyczą tylko trybu z włączonym upstream proxy. W przeciwnym razie je pomiń.

1. **Wymagania.** Linux z Docker Engine **28.0 lub nowszym** i pluginem compose (sprawdź: `docker version --format '{{.Server.Version}}'`). Starsze wersje przerywają tworzenie sandboxa błędem `getent unable to find entry "998:998" in passwd database`, bo szukają użytkownika kontenera na hoście. Jądro musi wspierać Landlock (ABI 3 lub nowsze) i seccomp.

2. **Konfiguracja.** Wykonaj `cp .env.example .env` i uzupełnij:
   - `COMPOSE_FILE`: zostaw, żeby używać upstream proxy, zakomentuj, żeby działać bez niego,
   - `HOST_BRIDGE_IP` (z `ip -4 addr show docker0`),
   - `MODEL_BASE_URL`, `MODEL_API_KEY`, `MODEL_NAME`.

3. **(proxy) IP i whitelista.** Wpisz to samo IP mostka w `https_proxy` w `openshell/gateway.proxy.toml`, bo TOML nie czyta `.env`. Host backendu modelu dopisz do `squid/whitelist.txt`.

4. **(proxy) Firewall (zalecane).** Uruchom `sudo sh firewall.sh`. Skrypt blokuje bezpośrednie wyjście kontenerów do internetu, z wyjątkiem squida. Działa tylko dzięki `supervisor_network_mode = "bridge"`. Nie uruchamiaj go bez proxy, bo odetnie kontenerom cały ruch wychodzący.

5. **(proxy) Start squida i test.**
   ```
   docker compose up -d squid
   curl -x http://172.17.0.1:3128 -I https://pypi.org
   ```

6. **Budowa obrazów:** `docker compose build`. Z proxy robisz to po starcie squida, bo `pip` i `git` w buildzie idą przez niego. Pobieranie obrazów bazowych robi sam dockerd, więc ewentualne proxy ustaw w daemonie.

7. **Start gatewaya.**
   ```
   docker compose up -d openshell-gateway model-relay
   curl -sf http://127.0.0.1:8081/healthz
   ```
   Port musi być 8080 po obu stronach, bo sandboxy wołają z powrotem `host.openshell.internal:8080`.
   Compose najpierw uruchamia `openshell-init`, który zapisuje klucze JWT sandboxów w `/var/lib/openshell/tls`. Driver docker ich wymaga. Gateway trzyma bazę, klucze i wypakowaną binarkę supervisora w `/var/lib/openshell` na hoście i działa jako root, tak jak setup `deploy/docker` w repo OpenShell.

8. **Bootstrap:** `docker compose up bootstrap`. Skrypt rejestruje gateway i tworzy sandbox z polityką. Ponowne uruchomienie: `docker compose run --rm bootstrap`; istniejący sandbox zostaje bez zmian. Żeby zmienić model, klucz albo endpoint, popraw `.env` i uruchom `docker compose up -d model-relay`; sandboxa nie trzeba ruszać. Jeśli okno kontekstu modelu nie wynosi 131072 tokenów, ustaw `context_length` w `hermes/config.yaml` i przebuduj obraz.

9. **Praca z Hermesem.** Zainstaluj CLI OpenShell na hoście, w tej samej wersji co gateway. Paczka `openshell` na PyPI to tylko SDK Pythona, a upstreamowy `install.sh` stawia też własny lokalny gateway, więc weź statyczną binarkę z wydania:
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
   ```
   `sandbox exec` uruchamia w sandboxie nowy proces. Powłokę dostaniesz przez `openshell sandbox exec --tty hermes -- /bin/bash -l`. `openshell sandbox connect hermes` nie otwiera powłoki. Podłącza się do głównego procesu sandboxa (`HERMES_CMD`) i odtwarza jego ostatnie wyjście. Przy domyślnym `sleep infinity` nic nie pokazuje, więc tylko wygląda na zawieszone. `Ctrl-C` rozłącza i zostawia główny proces uruchomiony. Do ciągłej pracy (Telegram, Slack, API) ustaw `HERMES_CMD=hermes gateway run` i odtwórz sandbox (`openshell sandbox delete hermes`, potem ponownie bootstrap). Wtedy `sandbox connect` pokazuje wyjście tego gatewaya. Wymaga klienta `ssh` na hoście.

### Późniejsza zmiana trybu

- **Wyłączenie proxy:** najpierw usuń squida (`docker compose rm -sf squid`), potem zakomentuj `COMPOSE_FILE` w `.env`.
- **Włączenie proxy:** odkomentuj `COMPOSE_FILE` i przejdź kroki 3–5.

Następnie uruchom `docker compose up -d openshell-gateway` (compose odtworzy gateway z drugą konfiguracją) i odtwórz sandbox, żeby przejął nowe ustawienia supervisora.

## Weryfikacja

- `openshell sandbox exec hermes -- hermes -z "ping"` powinien dostać odpowiedź z backendu modelu.
- `docker compose logs model-relay` pokazuje zapytanie (`POST /v1/chat/completions`). `openshell policy get hermes --full` pokazuje regułę `model` dla `host.docker.internal:8082`.
- Host spoza polityki powinien zostać odrzucony już przez OpenShell.
- **(proxy)** Log squida: `docker compose exec squid tail -f /var/log/squid/access.log`. Po zapytaniu z Hermesa powinien się w nim pojawić `CONNECT <host-modelu>:443` od relaya.
- **(proxy)** Host dozwolony w polityce, ale nieobecny w whiteliście, powinien dać `TCP_DENIED` w squidzie.

## Do sprawdzenia względem przypiętej wersji OpenShell

- Instalacja Hermesa na obrazie `openshell-community/sandboxes/base`: `uv sync --frozen` z `uv.lock` checkoutu `HERMES_REF` (zwykły pip nie rozwiązuje zależności hermes-agent). Lock obejmuje tylko Pythona 3.14, czyli wersję z obrazu bazowego. Przypnij `HERMES_REF`.
- Polityka wskazuje binarkę `/sandbox/.uv/python/**`, czyli prawdziwą ścieżkę Pythona z obrazu bazowego (`/usr/local/bin/python3` to symlink do niego). Po zmianie obrazu bazowego sprawdź w sandboxie `readlink -f "$(command -v python3)"` i popraw politykę.
- **(proxy)** `proxy_connect_by_hostname = true` jest konieczne, bo inaczej CONNECT idzie na IP i `dstdomain` w squidzie nie działa.
