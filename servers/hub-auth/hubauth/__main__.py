import sys

if len(sys.argv) > 1 and sys.argv[1] in ("gen-owner", "list-grants", "revoke-client", "revoke-all", "-h", "--help"):
    from .cli import main
    raise SystemExit(main())

import os  # noqa: E402

os.umask(0o077)  # the SQLite DB (token hashes, grants) must not be group/world readable

import uvicorn  # noqa: E402

from .app import build_app  # noqa: E402

if __name__ == "__main__":
    uvicorn.run(build_app(), host="0.0.0.0", port=9000, log_level="warning", proxy_headers=False, server_header=False)
