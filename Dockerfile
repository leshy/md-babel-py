# Standalone Dockerfile (alternative to nix build .#docker)
#
# Preferred method - use Nix flake:
#   nix build .#docker
#   docker load < result
#   docker run -v $(pwd):/work md-babel-py:latest run /work/README.md --stdout
#
# Or use this Dockerfile directly:
#   docker build -t md-babel-py .
#   docker run -v $(pwd):/work md-babel-py run /work/README.md --stdout

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    nodejs \
    npm \
    graphviz \
    asymptote \
    openscad \
    xvfb \
    imagemagick \
    && rm -rf /var/lib/apt/lists/*

# pikchr - build from source
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc-dev \
    && cd /tmp \
    && apt-get install -y --no-install-recommends curl \
    && curl -LO https://pikchr.org/home/tarball/trunk/pikchr.tar.gz \
    && tar xzf pikchr.tar.gz \
    && cd pikchr-* \
    && make \
    && cp pikchr /usr/local/bin/ \
    && cd / && rm -rf /tmp/pikchr* \
    && apt-get purge -y gcc libc-dev curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .

# Copy default config
RUN mkdir -p /root/.config/md-babel && cp config.json /root/.config/md-babel/

WORKDIR /work
ENTRYPOINT ["md-babel-py"]
CMD ["--help"]
