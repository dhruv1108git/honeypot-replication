import unittest

from cotmon.client import MonitorClient, MonitorRequest, MonitorUnavailable, TransientBackendError

REQ = MonitorRequest(model="m", system="s", user="u", max_output_tokens=16)


class FlakyBackend:
    def __init__(self, failures):
        self.failures = failures
        self.calls = 0

    def complete(self, req):
        self.calls += 1
        if self.calls <= self.failures:
            raise TransientBackendError("HTTP 503")
        return "<score>1</score>"


class MonitorClientTest(unittest.TestCase):
    def test_retries_then_succeeds(self):
        backend = FlakyBackend(failures=2)
        delays = []
        client = MonitorClient(backend, max_retries=4, backoff_s=1.0, sleep=delays.append)
        self.assertEqual(client.complete(REQ), "<score>1</score>")
        self.assertEqual(backend.calls, 3)
        self.assertEqual(len(delays), 2)
        self.assertLess(delays[0], delays[1])

    def test_gives_up(self):
        backend = FlakyBackend(failures=10)
        client = MonitorClient(backend, max_retries=2, backoff_s=0.0, sleep=lambda _: None)
        with self.assertRaises(MonitorUnavailable):
            client.complete(REQ)
        self.assertEqual(backend.calls, 3)


if __name__ == "__main__":
    unittest.main()
