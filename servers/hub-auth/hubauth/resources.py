"""The protected MCP routes and the scopes that grant access to them.

Each route is its own OAuth *resource* (RFC 8707): a token is bound to exactly one route and is rejected
on any other. Scope names are prefixed with their route, so a scope identifies its resource unambiguously.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Resource:
    route: str                       # gateway route name, e.g. "web" -> /web/mcp
    title: str
    scopes: dict[str, str]           # scope -> human description shown on the consent screen
    default_scopes: tuple[str, ...]  # granted when a client asks for none
    sensitive: frozenset[str] = field(default_factory=frozenset)  # scopes that can change things / reach secrets

    @property
    def path(self) -> str:
        return f"/{self.route}/mcp"


def build_resources(github_write: bool) -> dict[str, "Resource"]:
    """`github_write` mirrors the github MCP server's mode. Its read-only setting is a hard cap that no per-request
    header can lift, so offering github:write while the server is read-only would show a consent screen that lies."""
    gh_scopes = {"github:read": "Read repositories, issues, pull requests and code"}
    sensitive: frozenset[str] = frozenset()
    if github_write:
        gh_scopes["github:write"] = "CREATE and CHANGE issues, pull requests, branches and files"
        sensitive = frozenset({"github:write"})
    return {r.route: r for r in [
    Resource("web", "Web search & fetch", {"web:read": "Search the web and read pages on your behalf"}, ("web:read",)),
    Resource("latex", "LaTeX projects", {"latex:use": "Create, edit and compile your LaTeX projects"}, ("latex:use",)),
    Resource("transcriber", "Transcription", {"transcriber:use": "Transcribe audio/video with your Google Cloud quota"}, ("transcriber:use",)),
    Resource("github", "GitHub", gh_scopes, ("github:read",), sensitive),
    Resource("google-workspace", "Google Workspace", {
        "workspace:use": "Read AND modify your Gmail, Drive, Docs, Sheets, Calendar and more",
    }, ("workspace:use",), frozenset({"workspace:use"})),
    Resource("dokploy", "Dokploy", {
        "dokploy:use": "Manage your Dokploy server: deploy, restart, configure and DELETE applications and databases",
    }, ("dokploy:use",), frozenset({"dokploy:use"})),
    ]}


GITHUB_WRITE_ENABLED = os.getenv("GITHUB_READ_ONLY", "1").strip().lower() in ("0", "false", "no")
RESOURCES: dict[str, Resource] = build_resources(GITHUB_WRITE_ENABLED)

SCOPE_TO_ROUTE: dict[str, str] = {s: r.route for r in RESOURCES.values() for s in r.scopes}
ALL_SCOPES: list[str] = sorted(SCOPE_TO_ROUTE)


def resource_url(base_url: str, route: str) -> str:
    return base_url.rstrip("/") + RESOURCES[route].path


def route_for_resource(base_url: str, resource: str | None) -> str | None:
    """Map an RFC 8707 resource indicator to a route, requiring an exact (trailing-slash-insensitive) match."""
    if not resource:
        return None
    res = resource.rstrip("/")
    for route in RESOURCES:
        if res == resource_url(base_url, route):
            return route
    return None
