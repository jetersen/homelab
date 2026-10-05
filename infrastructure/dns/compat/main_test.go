package main

import (
	"bytes"
	"encoding/hex"
	"testing"

	"codeberg.org/miekg/dns"
	"codeberg.org/miekg/dns/rdata"
)

func TestTechnitiumForwarderWireData(t *testing.T) {
	// Private RDATA is opaque. It can contain bytes that are not a DNS name.
	data := []byte{0x01, 0xff, 0x00, 0x80, 0x06, 0xc0, 0xa8, 0x01, 0x01}
	message := dns.NewMsg("example.test.", dns.TypeAXFR)
	message.Response = true
	message.Answer = []dns.RR{&dns.RFC3597{
		Hdr:     dns.Header{Name: "lan.example.test.", Class: dns.ClassINET, TTL: 300},
		RFC3597: rdata.RFC3597{RRType: 65281, Data: hex.EncodeToString(data)},
	}}
	if err := message.Pack(); err != nil {
		t.Fatal(err)
	}

	decoded := &dns.Msg{Data: bytes.Clone(message.Data)}
	if err := decoded.Unpack(); err != nil {
		t.Fatalf("Technitium FWD must not use the AdGuard decoder: %v", err)
	}
	forwarder, ok := decoded.Answer[0].(*dns.RFC3597)
	if !ok || forwarder.Type() != 65281 || forwarder.RFC3597.Data != hex.EncodeToString(data) {
		t.Fatalf("Forwarder type or data was changed: %#v", decoded.Answer[0])
	}
	if err := decoded.Pack(); err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(message.Data, decoded.Data) {
		t.Fatal("Forwarder wire data was not preserved")
	}

	truncated := &dns.Msg{Data: message.Data[:len(message.Data)-1]}
	if err := truncated.Unpack(); err == nil {
		t.Fatal("Truncated forwarder data must still be rejected")
	}
}
