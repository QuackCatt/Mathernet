import unittest

from mathernet.http_client import create_ssl_context


class HttpClientTests(unittest.TestCase):
    def test_ssl_context_loads_an_available_system_ca_bundle(self):
        context = create_ssl_context()
        self.assertTrue(context.get_ca_certs())
        self.assertNotEqual(context.verify_mode, 0)


if __name__ == "__main__":
    unittest.main()
