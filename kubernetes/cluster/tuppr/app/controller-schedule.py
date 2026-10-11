"""Wake Tuppr for maintenance and stop it only after current plans complete."""

import argparse
import json
import ssl
import urllib.error
import urllib.request
from pathlib import Path


def plans_complete(plans):
    return len(plans) == 2 and all(
        plan.get("status", {}).get("phase") == "Completed"
        and plan.get("status", {}).get("observedGeneration") == plan["metadata"]["generation"]
        for plan in plans
    )


def run(action, request):
    if action == "sleep":
        plans = [
            request(f"/apis/tuppr.home-operations.com/v1alpha1/{kind}/homelab")
            for kind in ("talosupgrades", "kubernetesupgrades")
        ]
        if not plans_complete(plans):
            print("Upgrade plans are incomplete; leaving Tuppr enabled.")
            return

    path = "/apis/apps/v1/namespaces/system-upgrade/deployments/tuppr/scale"
    scale = request(path)
    scale["spec"]["replicas"] = 1 if action == "wake" else 0
    request(path, scale)
    print(f"Tuppr replicas set to {scale['spec']['replicas']}.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("wake", "sleep"))
    action = parser.parse_args().action
    account = Path("/var/run/secrets/kubernetes.io/serviceaccount")
    context = ssl.create_default_context(cafile=account / "ca.crt")
    token = (account / "token").read_text().strip()

    def request(path, body=None):
        req = urllib.request.Request(
            "https://kubernetes.default.svc" + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
            },
            method="PUT" if body is not None else "GET",
        )
        with urllib.request.urlopen(req, context=context, timeout=30) as response:
            return json.load(response)

    try:
        run(action, request)
    except urllib.error.HTTPError as error:
        raise SystemExit(f"Kubernetes request failed: HTTP {error.code}") from None
    except urllib.error.URLError:
        raise SystemExit("Cannot reach Kubernetes; check Tuppr before retrying.") from None


if __name__ == "__main__":
    main()
