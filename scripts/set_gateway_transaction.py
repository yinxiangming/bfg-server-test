#!/usr/bin/env python3
"""Bind a provider transaction ID to one pending payment in a disposable DB."""

import argparse
import os
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-dir", required=True)
    parser.add_argument("--payment-id", type=int, required=True)
    parser.add_argument("--workspace-id", type=int, required=True)
    parser.add_argument("--gateway-id", type=int, required=True)
    parser.add_argument("--transaction-id", required=True)
    args = parser.parse_args()

    if os.environ.get("BFG2_E2E_DISPOSABLE") != "1":
        raise SystemExit("BFG2_E2E_DISPOSABLE=1 is required")

    database_path = Path(os.environ["BFG2_E2E_DATABASE_PATH"]).resolve()
    marker_path = Path(os.environ["BFG2_E2E_DISPOSABLE_MARKER"]).resolve()
    if not database_path.is_file() or marker_path.parent != database_path.parent:
        raise SystemExit("Disposable SQLite database and marker are required")
    if marker_path.read_text(encoding="utf-8").strip() != "bfg2-e2e-disposable-v1":
        raise SystemExit("Invalid disposable marker")

    server_dir = Path(args.server_dir).resolve()
    os.chdir(server_dir)
    sys.path.insert(0, str(server_dir))
    os.environ.setdefault(
        "DJANGO_SETTINGS_MODULE",
        os.environ.get("BFG2_E2E_SERVER_SETTINGS", "config.prod"),
    )

    import django

    django.setup()

    from django.conf import settings
    from bfg.finance.models import Payment

    configured_database = Path(settings.DATABASES["default"]["NAME"]).resolve()
    if configured_database != database_path:
        raise SystemExit("Django is not using BFG2_E2E_DATABASE_PATH")

    payment = Payment.all_objects.get(
        pk=args.payment_id,
        workspace_id=args.workspace_id,
        gateway_id=args.gateway_id,
        status="pending",
    )
    if payment.gateway_transaction_id:
        raise SystemExit("Payment already has a gateway transaction ID")
    payment.gateway_transaction_id = args.transaction_id
    payment.save(update_fields=["gateway_transaction_id"])


if __name__ == "__main__":
    main()
