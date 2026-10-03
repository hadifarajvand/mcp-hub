# Official GitHub MCP server, pinned. Its HTTP mode uses the bearer token on
# each request to call GitHub; the hub gateway injects GITHUB_PERSONAL_ACCESS_TOKEN.
FROM ghcr.io/github/github-mcp-server:v1.14.0

USER 65534:65534
EXPOSE 8082

ENTRYPOINT ["/server/github-mcp-server"]
CMD ["http", "--port", "8082"]
