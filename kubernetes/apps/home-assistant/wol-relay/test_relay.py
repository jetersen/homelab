import unittest
from unittest.mock import patch

from relay import forward_packet, magic_packet


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


if __name__ == "__main__":
    unittest.main()
