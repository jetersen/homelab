var settings = require("./settings.json");
var registrar = NewRegistrar("none", "NONE");
var view = typeof DNS_VIEW === "undefined" ? "all" : DNS_VIEW;
var provider = typeof DNS_PROVIDER === "undefined" ? "all" : DNS_PROVIDER;
if (view !== "all" && view !== "public" && view !== "internal") { throw new Error("Unknown DNS_VIEW"); }
if (provider !== "all" && provider !== "cloudflare" && provider !== "technitium" && provider !== "unifi") { throw new Error("Unknown DNS_PROVIDER"); }
if ((view === "internal" && provider === "cloudflare") || (view === "public" && provider !== "all" && provider !== "cloudflare")) {
  throw new Error("DNS_PROVIDER does not belong to DNS_VIEW");
}

function relative(name, zone) {
  if (name === zone) { return "@"; }
  return name.slice(0, -(zone.length + 1));
}
function internalZone(zone, provider, skipClientNames) {
  var records = [A("*", settings.envoyIPv4), AAAA("*", settings.envoyIPv6)];
  settings.infrastructure.forEach(function (record) {
    var isLan = record.name.slice(-(".lan." + settings.domain).length) === ".lan." + settings.domain;
    if (isLan !== (zone === "lan." + settings.domain)) { return; }
    if (skipClientNames && record.unifiManagedElsewhere) { return; }
    records.push(A(relative(record.name, zone), record.ipv4));
  });
  // NO_PURGE is a migration guard until the existing unmanaged records are imported.
  D(zone + "!" + provider, registrar, DnsProvider(provider, 0), DefaultTTL(settings.ttl), NO_PURGE, records);
}
if (view === "all" || view === "internal") {
  if (provider === "all" || provider === "technitium") {
    var technitium = NewDnsProvider("technitium", "AXFRDDNS");
    internalZone(settings.domain, technitium, false);
    internalZone("lan." + settings.domain, technitium, false);
  }
  if (provider === "all" || provider === "unifi") {
    var unifi = NewDnsProvider("unifi", "UNIFI");
    internalZone(settings.domain, unifi, true);
    internalZone("lan." + settings.domain, unifi, true);
  }
}
if ((view === "all" || view === "public") && (provider === "all" || provider === "cloudflare")) {
  var cloudflare = NewDnsProvider("cloudflare", "CLOUDFLAREAPI");
  var records = settings.publicRecords.map(function (record) {
    return CNAME(relative(record.name, settings.domain), record.target + ".", record.proxied ? CF_PROXY_ON : CF_PROXY_OFF);
  });
  D(settings.domain + "!public", registrar, DnsProvider(cloudflare, 0), DefaultTTL(settings.ttl), NO_PURGE, records);
}
