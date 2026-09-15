import sys
import unittest
from datetime import datetime
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from salto.repository import SaltoRepository  # noqa: E402
from salto.settings import SaltoConnectionSettings  # noqa: E402
from salto.wiegand import convert_salto_rom_to_wiegand26  # noqa: E402


class SaltoRepositoryTests(unittest.TestCase):
    def test_converts_salto_rom_to_h10301(self) -> None:
        card = convert_salto_rom_to_wiegand26("E5C1F0C5000000")
        self.assertEqual(card.card_id, 15778277)
        self.assertEqual(card.facility_code, 240)
        self.assertEqual(card.card_number, 49637)
        self.assertEqual(card.display_id, "240-49637")

    def test_builds_sql_auth_connection_string(self) -> None:
        settings = SaltoConnectionSettings(
            server="SQL01\\SALTO",
            database="SALTO_SPACE",
            username="readonly_user",
            use_windows_auth=False,
        )

        connection_string = settings.build_connection_string("secret")

        self.assertIn("SERVER={SQL01\\SALTO}", connection_string)
        self.assertIn("DATABASE={SALTO_SPACE}", connection_string)
        self.assertIn("UID={readonly_user}", connection_string)
        self.assertIn("PWD={secret}", connection_string)

    def test_converts_query_row_to_hotel_card(self) -> None:
        issued = datetime(2026, 9, 14, 10, 37, 35)
        activation = datetime(2026, 9, 13)
        expiration = datetime(2026, 9, 15, 12, 30)

        card = SaltoRepository._to_hotel_card(
            (
                11,
                "1104",
                3,
                0,
                "95AD3ECD000000 ",
                issued,
                activation,
                expiration,
                "PRIMARY",
            )
        )

        self.assertEqual(card.room_user_id, 11)
        self.assertEqual(card.room_number, "1104")
        self.assertEqual(card.number_of_keys, 3)
        self.assertEqual(card.key_copy_number, 0)
        self.assertEqual(card.card_csn, "95AD3ECD000000")
        self.assertEqual(card.expiration_date, expiration)
        self.assertEqual(card.card_role, "PRIMARY")


if __name__ == "__main__":
    unittest.main()
