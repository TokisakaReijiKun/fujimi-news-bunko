import socket
import unittest
from server import make_local_server


class ServerBindingTests(unittest.TestCase):
    def test_second_server_cannot_share_port(self):
        server = make_local_server(lambda environ, start_response: [], '127.0.0.1', 0)
        port = server.server_port
        try:
            with self.assertRaises(SystemExit):
                make_local_server(lambda environ, start_response: [], '127.0.0.1', port)
            with socket.create_connection(('127.0.0.1', port), timeout=2):
                pass
        finally:
            server.server_close()
        replacement = make_local_server(lambda environ, start_response: [], '127.0.0.1', port)
        replacement.server_close()
