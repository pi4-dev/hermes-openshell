#!/bin/sh
# Fail-closed: kontenery (172.16.0.0/12) nie wyjdą do internetu inaczej niż przez squid (172.30.0.10).
# Uruchom na hoście po starcie Dockera (reguły DOCKER-USER nie przetrwają restartu bez persystencji).
set -eu
iptables -I DOCKER-USER 1 -s 172.16.0.0/12 ! -d 172.16.0.0/12 -j DROP
iptables -I DOCKER-USER 1 -s 172.30.0.10 -j RETURN
iptables -I DOCKER-USER 1 -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
iptables -L DOCKER-USER -n --line-numbers
