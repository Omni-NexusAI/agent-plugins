"""Explicit native contacts only. No network, host imports, secrets or dispatch."""
import ipaddress
import re
from urllib.parse import urlsplit

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_. -]{0,63}\Z")
SECRET = re.compile(r"A2A_PEER_[A-Z0-9_]{1,80}\Z")
LAN = tuple(ipaddress.ip_network(n) for n in
            ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
TAILSCALE = ipaddress.ip_network("100.64.0.0/10")


def _url(value, kind):
    if not isinstance(value, str):
        raise ValueError("Native peer URL must be a string")
    parsed = urlsplit(value)
    try:
        address = ipaddress.IPv4Address(parsed.hostname or "")
        port = parsed.port
    except ValueError:
        raise ValueError("Native peer URL needs an explicit IPv4 address and port") from None
    allowed = any(address in net for net in LAN) if kind == "lan" else address in TAILSCALE
    if (parsed.scheme not in ("http", "https") or not allowed or not port
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path.rstrip("/") != "/a2a"
            or parsed.hostname != str(address)):
        raise ValueError("Invalid native " + kind + " peer URL")
    return parsed.scheme + "://" + str(address) + ":" + str(port) + "/a2a", port


def render(config):
    """Fail closed on malformed/ambiguous metadata; return no preferred peer."""
    peers = config.get("peers", []) if isinstance(config, dict) else None
    if not isinstance(peers, list) or len(peers) > 20:
        raise ValueError("Native peers must be a list of at most 20 entries")
    lines, names = [], set()
    for peer in peers:
        if not isinstance(peer, dict):
            raise ValueError("Native peer entry must be an object")
        name, secret = peer.get("name"), peer.get("secret_name")
        if not isinstance(name, str) or not NAME.fullmatch(name) or name != name.strip():
            raise ValueError("Invalid native peer name")
        if name.casefold() in names:
            raise ValueError("Duplicate native peer name")
        names.add(name.casefold())
        if (peer.get("framework") != "agent-zero" or peer.get("card_name") != "Agent Zero"
                or peer.get("card_provider") != "Agent Zero"):
            raise ValueError("Directory accepts verified native Agent Zero contacts only")
        version, verified = peer.get("protocol_version"), peer.get("verified_at")
        if not isinstance(version, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,2}", version):
            raise ValueError("Invalid native protocol version metadata")
        if not isinstance(verified, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", verified):
            raise ValueError("Native card verification date is required")
        if not isinstance(secret, str) or not SECRET.fullmatch(secret):
            raise ValueError("A dedicated native secret reference is required")
        lan, lan_port = _url(peer.get("lan_url"), "lan")
        tailscale, tail_port = _url(peer.get("tailscale_url"), "tailscale")
        if lan_port != tail_port:
            raise ValueError("Native alternate must use the verified same peer port")
        suffix = "/t-§§secret(" + secret + ")"
        lines += ["- " + name + ": native Agent Zero; card Agent Zero / Agent Zero; protocol "
                  + version + "; operator verified " + verified + ".",
                  "  LAN primary agent_url: " + lan + suffix,
                  "  Tailscale alternative agent_url: " + tailscale + suffix]
    if not lines:
        return ""
    return ("Explicit native Agent Zero contacts (no default peer)\n" + "\n".join(lines)
            + "\nFor a user-selected listed native peer, use the existing a2a_chat at its native URL. "
            "Secret references resolve through native Agent Zero; do not read their values. "
            "Prefer LAN on the local network. The Tailscale address is the same peer across networks, "
            "usable if LAN is unreachable before any message is accepted. Never resend an accepted "
            "or uncertain message; poll its existing task. Hermes is a separate framework and "
            "must not substitute for a named native Agent Zero peer. This directory supplies "
            "contacts only; it performs no authentication, transport, routing or format conversion.")
