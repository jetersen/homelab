# Envoy routing

Apps use the shared `https` listener. Towonel uses the `towonel-public` Service
and listener for explicitly published routes. Gateway auto-routing stays disabled.

The `https` listener forwards encoded slashes (`%2F`) unchanged because Forgejo's
API uses them in branch refs. Revisit that setting before adding path-based
route matches or access policies to the listener.

To publish an app, update the public listener's hostname and namespace settings,
attach its HTTPRoute to `towonel-public`, and set `towonel.io/tunnel: enabled`
plus `towonel.io/tunnel-ref`. Add its public DNS alias through DNSControl.
