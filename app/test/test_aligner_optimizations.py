import unittest

from pipeline.aligner import stabilize_initial_segment


class StabilizeInitialSegmentTests(unittest.TestCase):
    def test_moves_first_segment_back_to_start_when_it_is_late(self):
        segments = [{"start": 3.2, "end": 4.2, "text": "hello"}]

        stabilize_initial_segment(segments)

        self.assertLessEqual(segments[0]["start"], 0.8)
        self.assertGreater(segments[0]["end"], segments[0]["start"])


if __name__ == "__main__":
    unittest.main()
