#!/usr/bin/env node

// DNSControl consumes this program's stdout directly through --creds !program.
function required(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing ${name}`);
  }
  return value;
}

const provider = required("DNS_PROVIDER");
const credentials = {};
if (provider === "cloudflare") {
  credentials.cloudflare = { TYPE: "CLOUDFLAREAPI", apitoken: required("CF_API_TOKEN") };
} else if (provider === "technitium") {
  const key = `hmac-sha256:external-dns-technitium:${required("TECHNITIUM_TSIG_SECRET")}`;
  credentials.technitium = {
    TYPE: "AXFRDDNS",
    master: "192.168.1.21:53",
    "transfer-key": key,
    "update-key": key,
  };
} else if (provider === "unifi") {
  credentials.unifi = {
    TYPE: "UNIFI",
    host: "https://unifi.lan.jetersen.dev",
    api_key: required("UNIFI_API_KEY"),
    site: "default",
    api_version: "new",
    skip_tls_verify: "false",
  };
} else {
  throw new Error("Unknown DNS_PROVIDER");
}
process.stdout.write(JSON.stringify(credentials));
