# LaTeX compile worker: TeX Live + tools, NO persistent data, NO network (see docker-compose.yml).
# TEXLIVE_SCHEME=medium (default, ~2 GB) or full (~5 GB).
FROM python:3.11-slim

ARG TEXLIVE_SCHEME=medium
ARG EXTRA_APT="texlive-lang-arabic texlive-lang-european fonts-dejavu-core fonts-freefont-ttf"
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    if [ "$TEXLIVE_SCHEME" = "full" ]; then TEX="texlive-full"; else \
      TEX="texlive-latex-recommended texlive-latex-extra texlive-fonts-recommended texlive-science \
           texlive-pictures texlive-bibtex-extra texlive-xetex texlive-luatex texlive-publishers \
           texlive-plain-generic texlive-extra-utils"; fi && \
    apt-get install -y --no-install-recommends \
      $TEX $EXTRA_APT latexmk biber chktex \
      libyaml-tiny-perl libfile-homedir-perl libunicode-linebreak-perl liblog-log4perl-perl \
      pandoc poppler-utils qpdf ghostscript \
      && rm -rf /var/lib/apt/lists/*

# Debian's defaults are NOT safe (shell_escape=p, openin_any=a). Lock them in the system config too;
# the worker additionally sets them in each job's environment.
RUN printf '%s\n' 'shell_escape = f' 'openin_any = p' 'openout_any = p' \
      > /etc/texmf/texmf.d/99-sandbox.cnf && update-texmf && \
    test "$(kpsewhich -var-value shell_escape)" = f && test "$(kpsewhich -var-value openin_any)" = p && \
    test "$(kpsewhich -var-value openout_any)" = p

# fontconfig: XeTeX/LuaTeX locate system fonts through it (separate layer keeps the TeX layer cached).
RUN apt-get update && apt-get install -y --no-install-recommends fontconfig dvisvgm && rm -rf /var/lib/apt/lists/*

# build_ca: optional CA for builds behind a TLS-intercepting proxy
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    pip install --no-cache-dir uvicorn==0.54.0 starlette==1.7.0

# Pre-build font caches as root into the (read-only at runtime) system tree so LuaTeX/XeTeX start fast.
RUN fc-cache -f && (luaotfload-tool --update --force 2>&1 | tail -2 || true) && \
    (mktexlsr 2>&1 | tail -1 || true)

RUN useradd --uid 10001 --create-home --home-dir /home/worker worker
WORKDIR /app
COPY latex/worker/worker.py /app/worker.py
COPY --chmod=755 latex/worker/safe-biber /usr/local/bin/safe-biber

ENV PYTHONUNBUFFERED=1
USER 10001:10001
EXPOSE 9100
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9100/health', timeout=4)"

CMD ["python", "worker.py"]
