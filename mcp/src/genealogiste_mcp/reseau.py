"""Politique des sorties réseau (#42) : seules des adresses publiques en http(s) sont jointes.
Loopback, privé, link-local, multicast, réservé ou non spécifié sont refusés, à chaque redirection ;
exceptions explicites via GENEALOGISTE_HOTES_AUTORISES (hôte ou hôte:port, séparés par des virgules)."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from urllib.parse import urlparse

DEFAULT_PORTS = {"http": 80, "https": 443}


def getaddrinfo(host: str, port: int) -> list[str]:
    return [i[4][0] for i in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]


def _ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        ip = ipaddress.ip_address(value.split("%", 1)[0].strip("[]"))
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return ip.ipv4_mapped
    return ip


def interdite(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not ip.is_global or ip.is_multicast


class DestinationRefusee(Exception):
    pass


class NetworkPolicy:
    def __init__(self, allowed: Iterable[str] = (), resolver: Callable[[str, int], list[str]] | None = None):
        self.allowed = {a.strip().lower() for a in allowed if a.strip()}
        self.resolver = resolver

    def check(self, url: str) -> None:
        u = urlparse(url)
        if u.scheme not in DEFAULT_PORTS:
            raise DestinationRefusee(f"Schéma refusé ({u.scheme or 'aucun'}) : seuls http et https sont autorisés")
        host = (u.hostname or "").lower()
        if not host:
            raise DestinationRefusee(f"URL sans hôte : {url}")
        port = u.port or DEFAULT_PORTS[u.scheme]
        if host in self.allowed or f"{host}:{port}" in self.allowed:
            return
        ip = _ip(host)
        if ip is not None:
            ips = [ip]
        else:
            try:
                ips = [i for i in map(_ip, (self.resolver or getaddrinfo)(host, port)) if i is not None]
            except OSError:
                return  # nom non résolu : la requête échouera d'elle-même, sans rien atteindre
        bad = sorted({str(i) for i in ips if interdite(i)})
        if bad:
            raise DestinationRefusee(
                f"Destination réseau interne refusée : {host} ({', '.join(bad)}). Pour un service local voulu, "
                "l'ajouter à GENEALOGISTE_HOTES_AUTORISES.")
