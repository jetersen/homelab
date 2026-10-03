"""Run in the user's terminal to store backup or Pulumi S3 credentials in Proton Pass."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def capture(command, payload=None, label="CLI operation"):
    result = subprocess.run(command, input=payload, capture_output=True, text=True)
    if result.returncode:
        # CLI output may contain secrets; never print it on failure.
        raise RuntimeError(f"{label} failed (exit {result.returncode}); output withheld")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", action="store_true", help="Create missing Proton Pass items")
    parser.add_argument("--pulumi-state", action="store_true", help="Store only the dedicated Pulumi state S3 login")
    args = parser.parse_args()
    titles = ["OVHcloud Homelab Pulumi S3"] if args.pulumi_state else ["OVHcloud Homelab S3", "Homelab Kopia"]
    items = json.loads(capture([
        "pass-cli", "item", "list", "--vault-name", "Personal", "--filter-state", "active", "--output", "json",
    ], label="Read vault metadata"))["items"]
    missing = []
    for title in titles:
        matches = [item for item in items if item["title"] == title]
        if len(matches) > 1 or (matches and matches[0]["item_type"] != "login"):
            raise RuntimeError(f"Expected at most one login named {title}; no items created")
        if not matches:
            missing.append(title)
    if not missing:
        print("Requested Proton Pass items already exist; nothing changed.")
        return
    if not args.store:
        print("Ready to create: " + ", ".join("Personal/" + title for title in missing))
        print("No credentials read or saved. Run with --store in your own terminal to proceed.")
        return
    if titles[0] in missing:
        if not os.environ.get("PULUMI_CONFIG_PASSPHRASE"):
            raise RuntimeError("Run through Varlock with BACKUP_IAC_CONFIGURED=true")
        directory = str(Path(__file__).resolve().parent)
        # Decrypted outputs stay in memory, never in files, argv, or terminal output.
        outputs = json.loads(capture([
            "pulumi", "-C", directory, "stack", "output", "--stack", "homelab",
            "--json", "--show-secrets", "--non-interactive",
        ], label="Read encrypted Pulumi outputs"))
        bucket_key = "stateBucketName" if args.pulumi_state else "bucketName"
        bucket_name = "jetersen-homelab-pulumi" if args.pulumi_state else "jetersen-homelab-kopia"
        access_key = "stateAccessKeyId" if args.pulumi_state else "accessKeyId"
        secret_key = "stateSecretAccessKey" if args.pulumi_state else "secretAccessKey"
        if outputs.get("projectId") != "8f573109804548c5acd72a72af919479" or outputs.get(bucket_key) != bucket_name:
            raise RuntimeError("Unexpected project or bucket; no items created")
        if not all(isinstance(outputs.get(key), str) and outputs[key] for key in [access_key, secret_key]):
            raise RuntimeError("S3 credentials are missing; no items created")
        capture([
            "pass-cli", "item", "create", "login", "--vault-name", "Personal",
            "--from-template", "-",
        ], json.dumps({
            "title": titles[0], "username": outputs[access_key],
            "password": outputs[secret_key], "urls": ["https://s3.de.io.cloud.ovh.net"],
        }), label="Create S3 login")
        print("Stored Personal/" + titles[0] + ".")
    else:
        print("Kept existing Personal/" + titles[0] + ".")
    if args.pulumi_state:
        return
    if titles[1] in missing:
        password = json.loads(capture([
            "pass-cli", "password", "generate", "random", "--length", "64",
            "--numbers", "true", "--uppercase", "true", "--symbols", "true", "--output", "json",
        ], label="Generate Kopia password"))["password"]
        if not isinstance(password, str) or len(password) != 64:
            raise RuntimeError("Unexpected generated password format; Kopia item not created")
        capture([
            "pass-cli", "item", "create", "login", "--vault-name", "Personal",
            "--from-template", "-",
        ], json.dumps({"title": titles[1], "password": password, "urls": []}), label="Create Kopia login")
        print("Created Personal/Homelab Kopia with a separate generated repository password.")
    else:
        print("Kept existing Personal/Homelab Kopia.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Do not print subprocess output or a traceback with credential-bearing values.
        if isinstance(error, RuntimeError):
            print(str(error), file=sys.stderr)
        else:
            print(f"Setup failed ({type(error).__name__}); details withheld", file=sys.stderr)
        sys.exit(1)
