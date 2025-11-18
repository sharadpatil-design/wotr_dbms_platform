CI: Alerting & Test Receiver notes
=================================

This file documents how the repository's CI validates alert delivery locally and the small local test receiver used for safe end-to-end checks.

1) Secret file(s)
------------------
- `observability/secrets/webhook_url` — a plain UTF-8 file containing the webhook URL that Alertmanager reads via `url_file` in `alertmanager_config.yml`.

CI creates this file automatically during the smoke job to point at the local `test-receiver` so no external webhooks are used.

2) Test receiver
----------------
The test receiver lives in `ci/test_receiver` and exposes:
- `POST /webhook` — records the last received webhook body and returns 204
- `GET /last` — returns the last recorded webhook body (204 if none)

3) Generator behavior
---------------------
Use `scripts/generate_alertmanager_config.py` to regenerate `observability/alertmanager_config.yml` from the template.
The script supports:
- `--restart` — runs `docker-compose restart alertmanager` (keeps container identity)
- `--recreate` — runs `docker-compose up -d --force-recreate alertmanager` (recommended on Docker for Windows / CI so bind mounts are applied)

4) CI flow (high-level)
------------------------
- CI builds images.
- CI writes `observability/secrets/webhook_url` pointing to `http://test-receiver:5000/webhook`.
- CI starts dependent services and `test-receiver`.
- CI runs `python3 scripts/generate_alertmanager_config.py --recreate` so Alertmanager is recreated with the secret mount.
- CI runs `ci/smoke_test.py` (ingest is fatal now).
- CI optionally runs `ci/assert_alert_delivery.py` which posts a synthetic alert to Alertmanager and polls `ci/test_receiver` (`/last`) to confirm delivery.

5) Making the assert step optional or configurable
-------------------------------------------------
Set the workflow environment variable `ALERT_ASSERT` to `false` to skip the delivery assertion step. Timeouts can be tuned via `ALERT_ROUTE_TIMEOUT` and `ALERT_DELIVERY_TIMEOUT` (seconds).

6) Opening a PR
---------------
If you'd like me to open a PR for these changes, I can prepare a branch and provide the git commands to push it to your remote. CI changes are already in the working tree; pushing requires your credentials on the remote.
