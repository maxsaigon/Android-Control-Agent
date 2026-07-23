# Android Control Refactor

A small, device-first replacement for the legacy Android Control dashboard.

## Run locally

```bash
cd refactor
uv sync --extra dev
uv run uvicorn android_control.main:app --reload --port 8090
```

Open `http://localhost:8090`.

The application uses `./runtime` by default and does not read the legacy
project `.env`.

## Tests

```bash
uv run pytest
```

## Production compatibility

- Public base URL defaults to `https://m.buonme.com`.
- Android Helper WebSocket remains `/ws/device/{token}`.
- New device tokens are returned once and stored as SHA-256 hashes.
- There is no default administrator password.

## Parallel deployment on max.lan

The deploy script keeps the current public service untouched and starts the
refactor on port `8091` by default (`8090` is already used by PocketBase on
the current host):

```bash
./refactor/deploy-max-lan.sh
```

It requires the current branch HEAD to exist on `origin`, reuses the existing
server `.env`, backs up an existing refactor database, and performs health,
resource and dashboard smoke checks.

See `../docs/refactor.md` for architecture, resources and cutover tasks.
