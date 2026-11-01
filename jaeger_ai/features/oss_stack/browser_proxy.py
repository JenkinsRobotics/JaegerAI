"""Loopback forward proxy for the shared browser, with DNS-pinned public destinations."""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit


class DestinationBlocked(ValueError):
    pass


def is_blocked_address(address: str) -> bool:
    """Fail closed for every address that is not globally routable."""
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return not ip.is_global


def resolve_public(host: str, port: int, resolver=socket.getaddrinfo) -> tuple:
    if host.lower().rstrip('.') == 'localhost' or host.lower().rstrip('.').endswith('.localhost'):
        raise DestinationBlocked(host)
    try:
        addresses = resolver(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as exc:
        raise DestinationBlocked(host) from exc
    if not addresses or any(is_blocked_address(entry[4][0]) for entry in addresses):
        raise DestinationBlocked(host)
    return addresses[0]


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (OSError, ConnectionError):
        pass
    finally:
        writer.close()


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    upstream = None
    try:
        header = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 10)
        if len(header) > 65536:
            raise ValueError('header too large')
        line, rest = header.split(b'\r\n', 1)
        method, target, version = line.decode('ascii').split(' ', 2)
        if method == 'CONNECT':
            parsed = urlsplit('//' + target)
            host, port = parsed.hostname, parsed.port
            if not host or not port:
                raise ValueError('invalid CONNECT target')
        else:
            parsed = urlsplit(target)
            if parsed.scheme != 'http' or not parsed.hostname:
                raise ValueError('invalid proxy target')
            host, port = parsed.hostname, parsed.port or 80
        family, _, _, _, sockaddr = await asyncio.to_thread(resolve_public, host, port)
        upstream_reader, upstream = await asyncio.open_connection(sockaddr[0], sockaddr[1], family=family)
        if method == 'CONNECT':
            writer.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
        else:
            path = (parsed.path or '/') + (('?' + parsed.query) if parsed.query else '')
            upstream.write(f'{method} {path} {version}\r\n'.encode('ascii') + rest)
        await writer.drain()
        await asyncio.gather(_pipe(reader, upstream), _pipe(upstream_reader, writer))
    except (DestinationBlocked, ValueError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
        writer.write(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
        await writer.drain()
    except (OSError, asyncio.TimeoutError):
        writer.write(b'HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
        await writer.drain()
    finally:
        if upstream:
            upstream.close()
        writer.close()


async def start_proxy() -> asyncio.AbstractServer:
    return await asyncio.start_server(_handle, '127.0.0.1', 0, limit=65537)
