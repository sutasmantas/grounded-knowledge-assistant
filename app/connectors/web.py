"""URL connector with server-side request forgery controls.

The controls follow the OWASP SSRF Prevention Cheat Sheet recommendation for
the "arbitrary external host" case:

* only `http` and `https` are accepted;
* embedded credentials are rejected instead of being forwarded upstream;
* every hostname is resolved and *all* A/AAAA records are checked against a
  deny list of loopback, private, link-local, reserved, multicast and cloud
  metadata addresses;
* the HTTP client's own redirect support is disabled, and each hop is
  revalidated as if it were the original user-supplied URL;
* the connected peer address is verified against the pre-validated set, so a
  DNS record that changes between validation and connection cannot be used;
* redirects, response size, and timeouts are bounded, and the response content
  type must be one the parser registry actually supports.

Operators who genuinely need to index an internal wiki can set
`ATLAS_CONNECTOR_URL_ALLOW_PRIVATE_NETWORKS=true`. Cloud metadata addresses
stay blocked in that mode as well, because no knowledge-base use case requires
them.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.connectors.base import (
    ConnectorItemError,
    ConnectorSecurityError,
    DiscoveredItem,
    FetchedItem,
    checksum,
    stable_source_id,
)
from app.parsers import ParserRegistry

ALLOWED_SCHEMES = frozenset({"http", "https"})
DEFAULT_PORTS = {"http": 80, "https": 443}
BLOCKED_HOSTNAMES = frozenset(
    {
        "metadata",
        "metadata.google.internal",
        "metadata.goog",
        "metadata.amazonaws.com",
        "instance-data",
        "instance-data.ec2.internal",
    }
)
METADATA_ADDRESSES = frozenset(
    {
        "169.254.169.254",  # AWS, Azure, GCP, DigitalOcean
        "fd00:ec2::254",  # AWS IMDS over IPv6
        "100.100.100.200",  # Alibaba Cloud
        "192.0.0.192",  # Oracle Cloud
    }
)
USER_AGENT = "atlas-knowledge-connector/2.0 (+https://github.com/sutasmantas)"


@dataclass(frozen=True)
class ResolvedTarget:
    url: str
    host: str
    port: int
    addresses: frozenset[str]


def canonical_url(raw: str) -> str:
    parts = urlsplit(raw.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    port = parts.port
    netloc = host
    if port and port != DEFAULT_PORTS.get(scheme):
        netloc = f"{host}:{port}"
    path = parts.path or "/"
    return urlunsplit((scheme, netloc, path, parts.query, ""))


IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def _blocked_reason(address: IpAddress) -> str | None:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return _blocked_reason(address.ipv4_mapped)
    if str(address) in METADATA_ADDRESSES:
        return "a cloud metadata service address"
    if address.is_loopback:
        return "a loopback address"
    if address.is_link_local:
        return "a link-local address"
    if address.is_multicast:
        return "a multicast address"
    if address.is_unspecified:
        return "an unspecified address"
    if address.is_reserved:
        return "a reserved address"
    if getattr(address, "is_site_local", False):
        return "a site-local address"
    if address.is_private:
        return "a private address"
    return None


def check_address(raw_address: str, *, allow_private_networks: bool) -> None:
    try:
        address = ipaddress.ip_address(raw_address)
    except ValueError as exc:
        raise ConnectorSecurityError(
            f"'{raw_address}' is not a usable IP address."
        ) from exc
    if str(address) in METADATA_ADDRESSES or (
        isinstance(address, ipaddress.IPv6Address)
        and address.ipv4_mapped
        and str(address.ipv4_mapped) in METADATA_ADDRESSES
    ):
        raise ConnectorSecurityError(
            "Cloud metadata service addresses are never reachable from a connector."
        )
    if allow_private_networks:
        return
    reason = _blocked_reason(address)
    if reason:
        raise ConnectorSecurityError(
            f"The URL resolves to {reason} ({address}), which connectors may not reach."
        )


def resolve_target(raw: str, *, allow_private_networks: bool = False) -> ResolvedTarget:
    parts = urlsplit(raw.strip())
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise ConnectorSecurityError(
            "Connector URLs must use the http or https scheme."
        )
    if parts.username or parts.password or "@" in (parts.netloc or ""):
        raise ConnectorSecurityError(
            "Connector URLs must not embed credentials."
        )
    host = (parts.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise ConnectorSecurityError("The connector URL has no hostname.")
    if host in BLOCKED_HOSTNAMES:
        raise ConnectorSecurityError(
            "Cloud metadata hostnames are never reachable from a connector."
        )
    try:
        port = parts.port or DEFAULT_PORTS[scheme]
    except ValueError as exc:
        raise ConnectorSecurityError("The connector URL has an invalid port.") from exc

    addresses: set[str] = set()
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        addresses.add(str(literal))
    else:
        try:
            resolved = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        except OSError as exc:
            raise ConnectorItemError(
                f"The hostname '{host}' could not be resolved."
            ) from exc
        addresses.update(str(entry[4][0]).split("%")[0] for entry in resolved)
    if not addresses:
        raise ConnectorItemError(f"The hostname '{host}' resolved to no addresses.")
    for address in sorted(addresses):
        check_address(address, allow_private_networks=allow_private_networks)
    return ResolvedTarget(
        url=raw.strip(),
        host=host,
        port=port,
        addresses=frozenset(addresses),
    )


class UrlConnector:
    name = "url"

    def __init__(
        self,
        *,
        urls: list[str],
        registry: ParserRegistry,
        max_bytes: int,
        max_items: int,
        timeout_seconds: float = 10.0,
        max_redirects: int = 3,
        allow_private_networks: bool = False,
        instance_id: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        if not urls:
            raise ConnectorItemError("At least one URL is required.")
        if len(urls) > max_items:
            raise ConnectorItemError(
                f"The URL connector accepts at most {max_items} URLs per run."
            )
        self.registry = registry
        self.max_bytes = max_bytes
        self.timeout_seconds = timeout_seconds
        self.max_redirects = max_redirects
        self.allow_private_networks = allow_private_networks
        self.urls = [canonical_url(url) for url in urls]
        for url in urls:
            # Fail the whole run on an unsafe URL rather than partially syncing.
            resolve_target(url, allow_private_networks=allow_private_networks)
        self.instance_id = instance_id or stable_source_id(
            self.name, "config", "|".join(sorted(self.urls))
        )
        self._owns_client = client is None
        self._client = client or httpx.Client(
            follow_redirects=False,
            timeout=httpx.Timeout(timeout_seconds),
            headers={"User-Agent": USER_AGENT},
        )

    def describe(self) -> dict[str, str]:
        return {
            "connector": self.name,
            "instance_id": self.instance_id,
            "url_count": str(len(self.urls)),
            "allow_private_networks": str(self.allow_private_networks).lower(),
        }

    def discover(self) -> Iterator[DiscoveredItem]:
        for url in self.urls:
            parts = urlsplit(url)
            segment = parts.path.rstrip("/").rsplit("/", 1)[-1]
            filename = segment or (parts.hostname or "document")
            yield DiscoveredItem(
                source_id=stable_source_id(self.name, self.instance_id, url),
                source_uri=url,
                filename=filename,
                title=_title_from_url(parts.path, parts.hostname or url),
                media_type=None,
                size_bytes=None,
                fingerprint=None,
                metadata={"url": url},
            )

    def fetch(self, item: DiscoveredItem) -> FetchedItem:
        url = item.metadata.get("url") or item.source_uri
        content, media_type = self._get(url)
        return FetchedItem(
            item=item,
            content=content,
            media_type=media_type,
            checksum=checksum(content),
            metadata={"url": url, "content_type": media_type or ""},
        )

    def _get(self, url: str) -> tuple[bytes, str]:
        current = url
        for _ in range(self.max_redirects + 1):
            target = resolve_target(
                current,
                allow_private_networks=self.allow_private_networks,
            )
            with self._client.stream("GET", current) as response:
                self._verify_peer(response, target)
                if response.is_redirect:
                    location = response.headers.get("location", "").strip()
                    if not location:
                        raise ConnectorItemError(
                            "The server sent a redirect without a location."
                        )
                    current = str(httpx.URL(current).join(location))
                    continue
                if response.status_code != httpx.codes.OK:
                    raise ConnectorItemError(
                        f"{url} returned HTTP {response.status_code}."
                    )
                media_type = self._validate_content_type(url, response)
                return self._read_bounded(url, response), media_type
        raise ConnectorSecurityError(
            f"{url} exceeded the {self.max_redirects}-redirect limit."
        )

    def _verify_peer(self, response: httpx.Response, target: ResolvedTarget) -> None:
        stream = response.extensions.get("network_stream")
        get_extra_info = getattr(stream, "get_extra_info", None)
        if get_extra_info is None:
            return
        peer = get_extra_info("server_addr")
        if not peer:
            return
        address = str(peer[0]).split("%")[0]
        check_address(
            address,
            allow_private_networks=self.allow_private_networks,
        )
        if address not in target.addresses:
            raise ConnectorSecurityError(
                "The connected address was not among the validated addresses "
                "for this hostname."
            )

    def _validate_content_type(self, url: str, response: httpx.Response) -> str:
        declared = response.headers.get("content-type", "")
        media_type = declared.split(";")[0].strip().lower()
        if media_type not in self.registry.supported_media_types:
            raise ConnectorItemError(
                f"{url} returned unsupported content type "
                f"'{media_type or 'unknown'}'."
            )
        return media_type

    def _read_bounded(self, url: str, response: httpx.Response) -> bytes:
        declared_length = response.headers.get("content-length")
        if declared_length and declared_length.isdigit():
            if int(declared_length) > self.max_bytes:
                raise ConnectorItemError(
                    f"{url} declares {declared_length} bytes, above the "
                    f"{self.max_bytes}-byte connector limit."
                )
        buffer = bytearray()
        for chunk in response.iter_bytes():
            buffer.extend(chunk)
            if len(buffer) > self.max_bytes:
                response.close()
                raise ConnectorItemError(
                    f"{url} exceeded the {self.max_bytes}-byte connector limit."
                )
        if not buffer:
            raise ConnectorItemError(f"{url} returned an empty body.")
        return bytes(buffer)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


def _title_from_url(path: str, fallback: str) -> str:
    segment = path.rstrip("/").rsplit("/", 1)[-1]
    if not segment:
        return fallback
    stem = segment.rsplit(".", 1)[0]
    return stem.replace("_", " ").replace("-", " ").strip().title() or fallback
