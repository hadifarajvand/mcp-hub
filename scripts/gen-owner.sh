#!/bin/sh
# Generate the owner password hash + TOTP secret for hub-auth, in a throwaway container.
# Nothing is stored; copy the printed lines into Dokploy's Environment tab (or your .env).
set -eu
cd "$(dirname "$0")/../servers/hub-auth"
exec docker run --rm -it -v "$PWD":/app:ro -w /app python:3.11-slim sh -c \
  'pip install -q --disable-pip-version-check argon2-cffi==25.1.0 pyotp==2.10.0 mcp==2.3.0 2>&1 | tail -1; python -m hubauth gen-owner'
