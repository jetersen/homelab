"""Relay only the configured target's WoL packet from Cilium to the IoT LAN."""

import logging
import os
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


def magic_packet(mac):
    if not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", mac):
        raise ValueError("Invalid target MAC")
    return b"\xff" * 6 + bytes.fromhex(mac.replace(":", "")) * 16


def forward_packet(data, expected, source, broadcast):
    if data != expected:
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind((source, 0))
        sock.sendto(expected, (broadcast, 9))
    return True


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/healthz" else 404)
        self.end_headers()

    def log_message(self, *_args):
        pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    expected = magic_packet(os.environ["TARGET_MAC"])
    primary_ip = os.environ["POD_IP"]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        receiver.bind((primary_ip, 8089))
        health = HTTPServer((primary_ip, 8080), HealthHandler)
        threading.Thread(target=health.serve_forever, daemon=True).start()
        while True:
            data, _sender = receiver.recvfrom(2048)
            try:
                if forward_packet(
                    data, expected, os.environ["IOT_SOURCE_IP"], os.environ["IOT_BROADCAST"]
                ):
                    logging.info("Sent TV wake packet on IoT")
            except OSError:
                logging.exception("Could not send wake packet")
