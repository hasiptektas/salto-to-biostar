from datetime import datetime
import unittest

from biostar.client import BioStarClient
from biostar.models import BioStarUser


class BioStarClientDateTests(unittest.TestCase):
    def test_salto_datetime_is_sent_without_hour_shift(self) -> None:
        result = BioStarClient._to_biostar_utc(datetime(2026, 9, 13, 0, 0))
        self.assertEqual(result, "2026-09-13T00:00:00.00Z")

    def test_next_user_id_is_calculated_from_existing_users(self) -> None:
        client = object.__new__(BioStarClient)
        client.list_users = lambda: [
            BioStarUser(str(value), "", 0, "", "", False)
            for value in range(1, 8)
        ]
        self.assertEqual(client.get_next_user_id(), "8")



if __name__ == "__main__":
    unittest.main()
