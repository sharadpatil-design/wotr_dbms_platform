#!/usr/bin/env python3
"""
Generate Alertmanager config from template and optional secrets.

Usage:
    python scripts/generate_alertmanager_config.py [--restart] [--recreate]

If --restart is provided, the script will attempt to run `docker-compose restart alertmanager`.
Secrets (optional):
- observability/secrets/webhook_url          (used by webhook-test)
- observability/secrets/slack_webhook_url    (if present, a slack webhook receiver will be added)
- observability/secrets/smtp_host
- observability/secrets/smtp_port
- observability/secrets/smtp_user
- observability/secrets/smtp_password
- observability/secrets/smtp_from
- observability/secrets/smtp_to

The script writes to: observability/alertmanager_config.yml
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OBS = os.path.join(ROOT, 'observability')
TEMPLATE = os.path.join(OBS, 'alertmanager_config.template.yml')
OUTFILE = os.path.join(OBS, 'alertmanager_config.yml')
SECRETS_DIR = os.path.join(OBS, 'secrets')


def read_secret(name):
    p = os.path.join(SECRETS_DIR, name)
    if os.path.exists(p):
        with open(p, 'r', encoding='utf-8') as f:
            return f.read().strip()
    return None


def main():
    with open(TEMPLATE, 'r', encoding='utf-8') as f:
        content = f.read()

    slack_url = read_secret('slack_webhook_url')
    smtp_host = read_secret('smtp_host')
    smtp_port = read_secret('smtp_port')
    smtp_user = read_secret('smtp_user')
    smtp_password = read_secret('smtp_password')
    smtp_from = read_secret('smtp_from')
    smtp_to = read_secret('smtp_to')

    extras = []
    route_lines = []

    if slack_url:
        slack_block = f"""
  - name: 'slack-notify'
    webhook_configs:
      - url: '{slack_url}'
        send_resolved: true
"""
        extras.append(slack_block)
        route_lines.append("    - matchers:\n        - 'severity=\"critical\"'\n      receiver: 'slack-notify'\n")

    if smtp_host and smtp_user and smtp_password and smtp_to and smtp_from:
        smtp_block = f"""
  - name: 'email-admin'
    email_configs:
      - to: '{smtp_to}'
        from: '{smtp_from}'
        smarthost: '{smtp_host}:{smtp_port or "587"}'
        auth_username: '{smtp_user}'
        auth_password: '{smtp_password}'
"""
        extras.append(smtp_block)
        route_lines.append("    - matchers:\n        - 'severity=\"critical\"'\n      receiver: 'email-admin'\n")

    # Build final content
    header, footer = content, ''
    final = header

    if extras:
        final += '\n# Injected receivers (generated from secrets)\n'
        for ex in extras:
            final += ex

    if route_lines:
        # append additional routes under route.routes
        final += "\n# Injected routes for generated receivers\nroute:\n  receiver: 'devnull'\n  group_wait: 10s\n  group_interval: 5m\n  repeat_interval: 1h\n  routes:\n"
        for r in route_lines:
            final += r
        final += "\n"

    with open(OUTFILE, 'w', encoding='utf-8') as f:
        f.write(final)

    print(f"Wrote generated config to {OUTFILE}")

    if '--restart' in sys.argv:
        print('Attempting to restart Alertmanager via docker-compose...')
        try:
            subprocess.check_call(['docker-compose', 'restart', 'alertmanager'], cwd=ROOT)
            print('docker-compose restart alertmanager: OK')
        except Exception as e:
            print('Failed to restart Alertmanager automatically:', e)

    if '--recreate' in sys.argv:
        # Recreate (up -d --force-recreate) ensures bind-mounts are applied on platforms
        # where restarting a container doesn't update mounts (common on Docker for Windows).
        print('Attempting to recreate Alertmanager via docker-compose (force-recreate)...')
        try:
            subprocess.check_call(['docker-compose', 'up', '-d', '--force-recreate', 'alertmanager'], cwd=ROOT)
            print('docker-compose up -d --force-recreate alertmanager: OK')
        except Exception as e:
            print('Failed to recreate Alertmanager automatically:', e)


if __name__ == '__main__':
    main()
