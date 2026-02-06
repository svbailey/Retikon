from __future__ import annotations

import argparse
import sys

from gcp_adapter.duckdb_uri_signer import sign_gcs_uri
from retikon_core.errors import RecoverableError


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify that the service account can sign GCS URLs."
    )
    parser.add_argument("--uri", required=True, help="gs://bucket/path to sign")
    args = parser.parse_args()

    try:
        signed = sign_gcs_uri(args.uri)
    except RecoverableError as exc:
        print(f"Signing failed: {exc}")
        return 1
    except Exception as exc:  # pragma: no cover - unexpected
        print(f"Signing failed: {exc}")
        return 1

    if signed == args.uri:
        print("Signing skipped or returned original URI.")
        return 2

    print("Signed URL generated successfully:")
    print(signed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
