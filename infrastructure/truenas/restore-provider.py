#!/usr/bin/env python3
"""Restore the GitHub release copy of our SDK without registry credentials."""

import hashlib
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

root = Path(__file__).resolve().parent
project = ET.parse(root / "Homelab.TrueNas.csproj")
version = next(
    p.attrib["Version"]
    for p in project.iter("PackageReference")
    if p.attrib["Include"] == "Jetersen.Pulumi.TrueNas"
)
name = f"Jetersen.Pulumi.TrueNas.{version}.nupkg"
base = f"https://github.com/jetersen/pulumi-truenas/releases/download/v{version}"
checksums = urllib.request.urlopen(f"{base}/checksums.txt").read().decode()
expected = next(
    line.split()[0]
    for line in checksums.splitlines()
    if line.split()[-1].removeprefix("./") == name
)
data = urllib.request.urlopen(f"{base}/{name}").read()
if hashlib.sha256(data).hexdigest() != expected:
    raise SystemExit("Provider SDK checksum mismatch")
(root / ".packages").mkdir(exist_ok=True)
(root / ".packages" / name).write_bytes(data)
print(f"Verified {name}")
