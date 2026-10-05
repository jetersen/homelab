package main

import (
	"os"

	"codeberg.org/miekg/dns"
	"github.com/DNSControl/dnscontrol/v5/commands"
	_ "github.com/DNSControl/dnscontrol/v5/pkg/privatetypes"
	_ "github.com/DNSControl/dnscontrol/v5/pkg/privatetypes/rdata"
	"github.com/DNSControl/dnscontrol/v5/pkg/version"
	_ "github.com/DNSControl/dnscontrol/v5/providers/axfrddns"
	_ "github.com/DNSControl/dnscontrol/v5/providers/cloudflare"
	_ "github.com/DNSControl/dnscontrol/v5/providers/unifi"
)

func init() {
	// Technitium FWD and DNSControl's AdGuard AAAA passthrough share this
	// private code point. Decode it as RFC 3597 data so AXFRDDNS can ignore it.
	// We do not use the AdGuard provider in this build.
	delete(dns.TypeToRR, 65281)
}

func main() {
	os.Exit(commands.Run("DNSControl version " + version.Version()))
}
