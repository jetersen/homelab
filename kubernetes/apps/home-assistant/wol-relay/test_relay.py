import threading
import unittest
from http.server import HTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

from relay import HealthHandler, forward_packet, magic_packet


class RelayTests(unittest.TestCase):
    def test_packet_is_standard_magic_packet(self):
        packet = magic_packet("02:11:22:33:44:55")
        self.assertEqual(len(packet), 102)
        self.assertEqual(packet[:6], b"\xff" * 6)
        self.assertEqual(packet[6:], bytes.fromhex("021122334455") * 16)

    def test_other_targets_and_extra_data_are_not_forwarded(self):
        expected = magic_packet("02:11:22:33:44:55")
        with patch("relay.socket.socket") as socket:
            for data in (
                b"",
                expected[:-1],
                expected + b"extra",
                magic_packet("02:00:00:00:00:01"),
            ):
                self.assertFalse(forward_packet(data, expected, "192.0.2.2", "192.0.2.255"))
            socket.assert_not_called()

    def test_wake_is_bound_to_iot_source_and_broadcast(self):
        expected = magic_packet("02:11:22:33:44:55")
        with patch("relay.socket.socket") as socket:
            self.assertTrue(forward_packet(expected, expected, "192.0.2.2", "192.0.2.255"))
            sock = socket.return_value.__enter__.return_value
            sock.bind.assert_called_once_with(("192.0.2.2", 0))
            sock.sendto.assert_called_once_with(expected, ("192.0.2.255", 9))


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.server = HTTPServer(("127.0.0.1", 0), HealthHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()

    def test_readiness_requires_iot_source_address(self):
        with patch.dict("os.environ", {"IOT_SOURCE_IP": "127.0.0.1"}):
            with urlopen(self.url + "/healthz", timeout=2) as response:
                self.assertEqual(response.status, 200)
        with patch.dict("os.environ", {"IOT_SOURCE_IP": "192.0.2.2"}):
            with self.assertRaises(HTTPError) as error:
                urlopen(self.url + "/healthz", timeout=2)
            self.assertEqual(error.exception.code, 503)
            error.exception.close()

    def test_missing_iot_source_does_not_fail_liveness(self):
        with patch.dict("os.environ", {"IOT_SOURCE_IP": "192.0.2.2"}):
            with urlopen(self.url + "/livez", timeout=2) as response:
                self.assertEqual(response.status, 200)


if __name__ == "__main__":
    unittest.main()
