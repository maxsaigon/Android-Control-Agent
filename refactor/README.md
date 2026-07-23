# Android Control Refactor

A small, device-first replacement for the legacy Android Control dashboard.

## Run locally

```bash
cd refactor
uv sync --extra dev
printf '%s\n' 'replace-with-a-long-password' > runtime/admin-password
python -c 'import secrets; print(secrets.token_urlsafe(48))' > runtime/session-secret
chmod 600 runtime/admin-password runtime/session-secret
uv run uvicorn android_control.main:create_app --factory --reload --port 8090
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
- Dashboard and sensitive APIs require a signed session. `/api/health` and
  token-authenticated device WebSockets remain public.

## Selective device import

Preview a legacy SQLite import (the default never writes):

```bash
python -m android_control.import_legacy ../data/android_control.db
```

Apply after reviewing the report:

```bash
python -m android_control.import_legacy ../data/android_control.db --apply
```

The importer preserves a unique legacy ID, imports ADB identity as offline,
and intentionally excludes plaintext device tokens and task/media history.

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
