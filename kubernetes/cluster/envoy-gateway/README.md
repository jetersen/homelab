# Envoy routing

Apps use the shared `https` listener. Towonel uses the `towonel-public` Service
and listener for explicitly published routes. Gateway auto-routing stays disabled.

To publish an app, update the public listener's hostname and namespace settings,
attach its HTTPRoute to `towonel-public`, and set `towonel.io/tunnel: enabled`
plus `towonel.io/tunnel-ref`. Add its public DNS alias through DNSControl.
