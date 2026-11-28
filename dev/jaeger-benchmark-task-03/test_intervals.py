import unittest

from intervals import total_covered


class CoverageTests(unittest.TestCase):
    def test_overlapping(self):
        self.assertEqual(total_covered([(1, 6), (3, 9)]), 8)

    def test_unsorted_nested_and_disjoint(self):
        self.assertEqual(total_covered([(20, 23), (4, 5), (2, 10), (0, 2)]), 13)

    def test_empty_and_touching(self):
        self.assertEqual(total_covered([]), 0)
        self.assertEqual(total_covered([(-2, 0), (0, 2), (3, 3)]), 4)

    def test_reversed_interval(self):
        with self.assertRaises(ValueError):
            total_covered([(2, 1)])
