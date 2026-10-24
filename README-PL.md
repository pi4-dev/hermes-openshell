<!-- Polskie tłumaczenie README.md — przy zmianach aktualizuj oba pliki. -->
# hermes-openshell

[English version](README.md)

Agent [Hermes](https://github.com/NousResearch/hermes-agent) (NousResearch) uruchomiony w sandboxie [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell) z gatewayem jako Docker Compose. Opcjonalnie cały ruch wychodzący sandboxa, także zapytania do modelu, idzie przez Squida w kontenerze (upstream proxy).

## Architektura

```
Hermes (sandbox) ──▶ proxy supervisora OpenShell ──▶ [Squid (whitelista)] ──▶ internet / API modelu
                     (polityka per binarka,             opcjonalnie
                      inference.local + klucz poza sandboxem)
```

- Hermes wysyła zapytania tylko na `https://inference.local/v1`. OpenShell podmienia model i wstrzykuje prawdziwy klucz, którego sandbox nigdy nie widzi.
- Kontener sandboxa z Hermesem nie jest usługą compose. Tworzy go gateway przez `docker.sock`.
- Bez upstream proxy ruch wychodzący kontroluje tylko polityka OpenShell (`policy/hermes-policy.yaml`, per binarka).

### Opcjonalne upstream proxy (Squid)

Proxy włącza linia `COMPOSE_FILE=docker-compose.yml:docker-compose.proxy.yml` w `.env`. W `.env.example` jest włączona. Zakomentuj ją, żeby działać bez Squida.

- `HTTPS_PROXY` w sandboxie nie działa z założenia, bo supervisor przepisuje środowisko proxy agenta. Squid jest więc podpięty jako upstream supervisora przez `[openshell.drivers.docker] https_proxy` w `openshell/gateway.proxy.toml`.
- Dostęp przechodzi przez dwie niezależne bramki. Host musi być **jednocześnie** w `policy/hermes-policy.yaml` (OpenShell, per binarka) i w `squid/whitelist.txt` (Squid, per domena).
- Przez Squida idzie też ruch samego gatewaya i budowa obrazów (`pip`, `git`).
- `firewall.sh` może dodatkowo zablokować bezpośrednie wyjście kontenerów, tak żeby Squid był jedyną drogą na zewnątrz.

| Ścieżka | Rola |
|---|---|
| `docker-compose.yml` | bazowy stack: openshell-gateway, budowa obrazu Hermesa, bootstrap |
| `docker-compose.proxy.yml` | opcjonalne upstream proxy: squid i ustawienia proxy dla gatewaya i buildów |
| `openshell/gateway.toml` | driver docker, tryb sieci bridge (bez proxy) |
| `openshell/gateway.proxy.toml` | to samo plus upstream proxy supervisora (używany z proxy) |
| `squid/` | konfiguracja i whitelista domen |
| `hermes/` | obraz sandboxa z Hermesem i `config.yaml` (model -> inference.local) |
| `bootstrap/` | jednorazowa konfiguracja: rejestracja gatewaya, provider, routing inference, sandbox |
| `policy/hermes-policy.yaml` | polityka OpenShell (filesystem, proces, sieć) |
| `firewall.sh` | reguły DOCKER-USER: kontenery wychodzą tylko przez squida (tylko z proxy) |

## Uruchomienie krok po kroku

Kroki oznaczone **(proxy)** dotyczą tylko trybu z włączonym upstream proxy. W przeciwnym razie je pomiń.

1. **Wymagania.** Linux z Docker Engine i pluginem compose. Jądro musi wspierać Landlock i seccomp.

2. **Konfiguracja.** Wykonaj `cp .env.example .env` i uzupełnij:
   - `COMPOSE_FILE`: zostaw, żeby używać upstream proxy, zakomentuj, żeby działać bez niego,
   - `HOST_BRIDGE_IP` (z `ip -4 addr show docker0`),
   - `DOCKER_GID` (z `getent group docker | cut -d: -f3`),
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
   docker compose up -d openshell-gateway
   curl -sf http://127.0.0.1:8080/healthz
   ```
   Port musi być 8080 po obu stronach, bo sandboxy wołają z powrotem `host.openshell.internal:8080`.

8. **Bootstrap:** `docker compose up bootstrap`. Skrypt rejestruje gateway, tworzy providera, ustawia routing inference i tworzy sandbox. Ponowne uruchomienie: `docker compose run --rm bootstrap`.

9. **Praca z Hermesem** (CLI na hoście w tej samej wersji co gateway: `uv tool install openshell`):
   ```
   openshell gateway add http://127.0.0.1:8080 --name local
   openshell sandbox connect hermes
   hermes
   ```
   Do ciągłej pracy (Telegram, Slack, API) ustaw `HERMES_CMD=hermes gateway run` i odtwórz sandbox.

### Późniejsza zmiana trybu

- **Wyłączenie proxy:** najpierw usuń squida (`docker compose rm -sf squid`), potem zakomentuj `COMPOSE_FILE` w `.env`.
- **Włączenie proxy:** odkomentuj `COMPOSE_FILE` i przejdź kroki 3–5.

Następnie uruchom `docker compose up -d openshell-gateway` (compose odtworzy gateway z drugą konfiguracją) i odtwórz sandbox, żeby przejął nowe ustawienia supervisora.

## Weryfikacja

- W sandboxie: `curl https://inference.local/v1/models` powinien dostać odpowiedź z backendu modelu.
- Host spoza polityki powinien zostać odrzucony już przez OpenShell.
- **(proxy)** Log squida: `docker compose exec squid tail -f /var/log/squid/access.log`. Po zapytaniu do `inference.local` powinien się w nim pojawić `CONNECT <host-modelu>:443`.
- **(proxy)** Host dozwolony w polityce, ale nieobecny w whiteliście, powinien dać `TCP_DENIED` w squidzie.

## Do sprawdzenia względem przypiętej wersji OpenShell

- Sposób wskazania pliku TOML w kontenerze gatewaya. `OPENSHELL_GATEWAY_CONFIG` to założenie; porównaj z `deploy/docker/docker-compose.yml` w repo OpenShell.
- `image_pull_policy` dla lokalnego obrazu `hermes-sandbox:local` (w obu plikach `openshell/gateway*.toml`). Alternatywa to lokalne registry.
- Instalacja Hermesa przez pip z gita na obrazie `openshell-community/sandboxes/base`. Przypnij `HERMES_REF`.
- Błąd `CERTIFICATE_VERIFY_FAILED` przy `inference.local`: ustaw w sandboxie `SSL_CERT_FILE=/etc/openshell-tls/ca-bundle.pem`.
- **(proxy)** `proxy_connect_by_hostname = true` jest konieczne, bo inaczej CONNECT idzie na IP i `dstdomain` w squidzie nie działa.
