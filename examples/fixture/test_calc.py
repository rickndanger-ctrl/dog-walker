import unittest
from calc import discounted_price


class DiscountTests(unittest.TestCase):
    def test_percent(self):
        self.assertEqual(discounted_price(200, 10), 180)

    def test_zero(self):
        self.assertEqual(discounted_price(75, 0), 75)

    def test_full(self):
        self.assertEqual(discounted_price(50, 100), 0)
