# Environment Setup

md-babel-py can be run via Nix flake or Docker.

## Nix Flake

### Run directly

```bash
nix run . -- run file.md --stdout
```

### Build and install

```bash
nix build
./result/bin/md-babel-py run file.md --stdout
```

### Development shell

```bash
nix develop
# Now you have md-babel-py + pytest, mypy, ruff + all evaluators
```

### Packages

| Package | Description |
|---------|-------------|
| `default` | Full package with all evaluators in PATH |
| `minimal` | Just Python package, no bundled evaluators |
| `docker` | Docker image tarball |

### Included evaluators

- python3, node (with REPL session support)
- graphviz (dot)
- asymptote
- pikchr
- openscad + xvfb-run + imagemagick

## Docker

### Via Nix (recommended)

```bash
nix build .#docker
docker load < result
docker run -v $(pwd):/work md-babel-py:latest run /work/file.md --stdout
```

### Via Dockerfile

```bash
docker build -t md-babel-py .
docker run -v $(pwd):/work md-babel-py run /work/file.md --stdout
```

### Examples

Process a file and print to stdout:
```bash
docker run -v $(pwd):/work md-babel-py run /work/README.md --stdout
```

Process a file in-place:
```bash
docker run -v $(pwd):/work md-babel-py run /work/README.md
```

Process with custom config:
```bash
docker run -v $(pwd):/work md-babel-py run /work/file.md --config /work/config.json
```

Only run Python blocks:
```bash
docker run -v $(pwd):/work md-babel-py run /work/file.md --lang python
```
