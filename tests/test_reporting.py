import unittest

import io
from types import SimpleNamespace

from cotmon.reporting import format_elapsed, write_summary_csv


class ReportingTest(unittest.TestCase):
    def test_short_elapsed(self):
        self.assertEqual(format_elapsed(0), "0:00")
        self.assertEqual(format_elapsed(9.8), "0:09")

    def test_simple_csv(self):
        summary = SimpleNamespace(per_deployment={
            "research-agent": SimpleNamespace(scored=2, alerts=1, errors=0)})
        stream = io.StringIO()
        write_summary_csv(summary, stream)
        self.assertEqual(stream.getvalue(), "deployment,scored,alerts,errors\nresearch-agent,2,1,0\n")
