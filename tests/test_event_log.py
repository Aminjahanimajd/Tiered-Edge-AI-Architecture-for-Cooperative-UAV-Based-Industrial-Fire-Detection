import json
import os
import tempfile
import unittest

from drone_enhanced_core.event_log import AsyncJsonlLogger


class EventLogTests(unittest.TestCase):
    def test_records_are_written_once_and_closed_cleanly(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "events.jsonl")
            with AsyncJsonlLogger(path, max_queue_size=32, flush_every=2) as logger:
                for index in range(10):
                    self.assertTrue(logger.log({"event_id": "e{}".format(index)}))
            self.assertEqual(logger.written_records, 10)
            self.assertEqual(logger.dropped_records, 0)
            with open(path, "r", encoding="utf-8") as input_file:
                records = [json.loads(line) for line in input_file]
            self.assertEqual(len(records), 10)
            self.assertEqual(records[0]["event_id"], "e0")
            self.assertEqual(records[-1]["event_id"], "e9")

    def test_sustained_logging_preserves_records_when_queue_is_sized(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "burst.jsonl")
            logger = AsyncJsonlLogger(path, max_queue_size=2048, flush_every=100)
            accepted = [logger.log({"sequence": index}) for index in range(1000)]
            logger.close()
            self.assertTrue(all(accepted))
            self.assertEqual(logger.written_records, 1000)
            self.assertEqual(logger.dropped_records, 0)
            with open(path, "r", encoding="utf-8") as source:
                records = [json.loads(line) for line in source]
            self.assertEqual([item["sequence"] for item in records], list(range(1000)))


if __name__ == "__main__":
    unittest.main()
