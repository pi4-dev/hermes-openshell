#!/bin/sh
# Proxy mode only (docker-compose.proxy.yml): without squid these rules cut off all container egress.
# Fail-closed: containers (172.16.0.0/12) cannot reach the internet other than through squid (172.30.0.10).
# Run on the host after Docker starts (DOCKER-USER rules do not survive a restart without persistence).
set -eu
iptables -I DOCKER-USER 1 -s 172.16.0.0/12 ! -d 172.16.0.0/12 -j DROP
iptables -I DOCKER-USER 1 -s 172.30.0.10 -j RETURN
iptables -I DOCKER-USER 1 -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
iptables -L DOCKER-USER -n --line-numbers
