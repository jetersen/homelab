// ES5 keeps this usable directly in DNSControl's JavaScript runtime.
function publicRouteRecords(snapshot, settings) {
  if (!snapshot || !Array.isArray(snapshot.items)) {
    throw new Error("Expected a Kubernetes List of Gateways and routes");
  }
  var prefix = "public.external-dns.kubernetes.io/";
  var gateways = {};
  var records = {};
  function key(namespace, name) { return namespace + "/" + name; }
  function annotations(object) { return object.metadata.annotations || {}; }
  function ready(conditions, type, generation) {
    return (conditions || []).some(function (c) {
      return typeof generation === "number" && c.type === type && c.status === "True" && c.observedGeneration === generation;
    });
  }
  function dnsName(value, allowWildcard) {
    if (typeof value !== "string") { throw new Error("DNS name must be a string"); }
    var name = value.trim().toLowerCase().replace(/\.$/, "");
    var labels = name.split(".");
    if (name.length > 253 || !labels.every(function (label, index) {
      return (allowWildcard && index === 0 && label === "*") ||
        (label.length <= 63 && /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/.test(label));
    })) {
      throw new Error("Invalid DNS hostname: " + value);
    }
    return name;
  }
  function hostname(value) {
    var name = dnsName(value, true);
    if (name === "lan." + settings.domain || name.slice(-(".lan." + settings.domain).length) === ".lan." + settings.domain) {
      throw new Error("LAN hostnames cannot be published publicly: " + name);
    }
    if (name === settings.domain || name.slice(-("." + settings.domain).length) !== "." + settings.domain) {
      throw new Error("Public route hostname is outside the managed domain: " + name);
    }
    return name;
  }
  snapshot.items.forEach(function (object) {
    if (object.kind === "Gateway") {
      gateways[key(object.metadata.namespace, object.metadata.name)] = object;
    }
  });
  var expected = gateways[key(settings.gateway.namespace, settings.gateway.name)];
  if (!expected || !ready((expected.status || {}).conditions, "Programmed", expected.metadata.generation)) {
    throw new Error("Configured Gateway is missing or not programmed");
  }
  snapshot.items.forEach(function (route) {
    if (route.kind !== "HTTPRoute" && route.kind !== "TCPRoute") { return; }
    var ann = annotations(route);
    if (ann[prefix + "enabled"] !== "true") { return; }
    var parents = (route.spec || {}).parentRefs || [];
    var matched = [];
    parents.forEach(function (parent) {
      if ((parent.kind || "Gateway") !== "Gateway" || (typeof parent.group === "undefined" ? "gateway.networking.k8s.io" : parent.group) !== "gateway.networking.k8s.io") { return; }
      var namespace = parent.namespace || route.metadata.namespace;
      if (key(namespace, parent.name) !== key(settings.gateway.namespace, settings.gateway.name)) { return; }
      var statuses = ((route.status || {}).parents || []).filter(function (status) {
        var ref = status.parentRef;
        return status.controllerName === "gateway.envoyproxy.io/gatewayclass-controller" &&
          (ref.kind || "Gateway") === "Gateway" &&
          (typeof ref.group === "undefined" ? "gateway.networking.k8s.io" : ref.group) === "gateway.networking.k8s.io" &&
          (ref.namespace || route.metadata.namespace) === namespace && ref.name === parent.name &&
          ref.sectionName === parent.sectionName && ref.port === parent.port;
      });
      if (!statuses.some(function (status) {
        return ready(status.conditions, "Accepted", route.metadata.generation) && ready(status.conditions, "ResolvedRefs", route.metadata.generation);
      })) { throw new Error("Public route is not ready: " + key(route.metadata.namespace, route.metadata.name)); }
      matched.push(gateways[key(namespace, parent.name)]);
    });
    if (!matched.length) { throw new Error("Public route does not attach to the configured Gateway"); }
    var names = route.kind === "HTTPRoute" ? ((route.spec || {}).hostnames || []) : [];
    if (ann[prefix + "hostname"]) { names = names.concat(ann[prefix + "hostname"].split(",")); }
    if (!names.length) { throw new Error("Public route has no DNS hostname"); }
    var target = ann[prefix + "target"] || annotations(matched[0])[prefix + "target"] || settings.publicTarget;
    target = dnsName(target, false);
    // An explicit public target is required; Gateway LAN addresses never become public records.
    if (target.indexOf(".") === -1 || /^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$/.test(target)) {
      throw new Error("Expected one public DNS target, not an IP address");
    }
    var ttl = ann[prefix + "ttl"] ? Number(ann[prefix + "ttl"]) : settings.ttl;
    if (!isFinite(ttl) || Math.floor(ttl) !== ttl || ttl < 60 || ttl > 86400) { throw new Error("Invalid DNS TTL"); }
    names.forEach(function (name) {
      name = hostname(name.trim());
      if (name === target) { throw new Error("Public CNAME cannot point to itself"); }
      var record = { name: name, target: target, ttl: ttl, proxied: route.kind === "HTTPRoute" };
      if (records[name] && JSON.stringify(records[name]) !== JSON.stringify(record)) {
        throw new Error("Conflicting public DNS records for " + name);
      }
      records[name] = record;
    });
  });
  return Object.keys(records).sort().map(function (name) { return records[name]; });
}
