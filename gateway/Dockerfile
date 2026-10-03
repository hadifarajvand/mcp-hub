FROM caddy:2.10-alpine

# The upstream binary has cap_net_bind_service set, which cannot be exec'd with
# cap_drop: ALL + no-new-privileges. We listen on 8080, so drop the capability.
RUN apk add --no-cache libcap && setcap -r /usr/bin/caddy && apk del libcap

COPY Caddyfile /etc/caddy/Caddyfile
COPY --chmod=755 entrypoint.sh /entrypoint.sh

USER 65534:65534
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1

ENTRYPOINT ["/entrypoint.sh"]
