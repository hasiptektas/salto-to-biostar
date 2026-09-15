from collections.abc import Sequence

import pyodbc

from salto.models import SaltoHotelCard


ACTIVE_HOTEL_CARDS_SQL = """
DECLARE @Now datetime = GETDATE();

SELECT
    u.id_user AS RoomUserId,
    CASE
        WHEN LEFT(u.name, 1) = '@'
            THEN SUBSTRING(u.name, 2, LEN(u.name))
        ELSE u.name
    END AS RoomNumber,
    u.CopyCount + 1 AS NumberOfKeys,
    hc.CopyCount AS KeyCopyNumber,
    hc.HotelCardID AS CardCSN,
    hc.IssuedDate,
    u.dtActivation AS ActivationDate,
    u.dtExpiration AS ExpirationDate,
    CASE
        WHEN hc.CopyCount = 0 THEN 'PRIMARY'
        ELSE 'COPY'
    END AS CardRole
FROM dbo.tb_Users AS u
INNER JOIN dbo.tb_HotelCards AS hc
    ON hc.id_user = u.id_user
    AND hc.IssuedDate >= u.dtActivation
    AND hc.IssuedDate <= u.dtExpiration
    AND hc.CopyCount >= 0
    AND hc.CopyCount <= u.CopyCount
WHERE
    u.type = 3
    AND u.status = 1
    AND u.dtActivation <= @Now
    AND u.dtExpiration > @Now
    AND hc.HotelCardID IS NOT NULL
    AND LTRIM(RTRIM(hc.HotelCardID)) <> ''
ORDER BY
    RoomNumber,
    hc.CopyCount;
"""


class SaltoRepository:
    def __init__(self, connection_string: str) -> None:
        self._connection_string = connection_string

    def fetch_active_hotel_cards(self) -> list[SaltoHotelCard]:
        """Aktif konaklamalara ait ana ve kopya kartları salt-okunur sorgular."""
        with pyodbc.connect(self._connection_string, timeout=10) as connection:
            cursor = connection.cursor()
            rows = cursor.execute(ACTIVE_HOTEL_CARDS_SQL).fetchall()

        return [self._to_hotel_card(row) for row in rows]

    @staticmethod
    def _to_hotel_card(row: Sequence[object]) -> SaltoHotelCard:
        return SaltoHotelCard(
            room_user_id=int(row[0]),
            room_number=str(row[1]).strip(),
            number_of_keys=int(row[2]),
            key_copy_number=int(row[3]),
            card_csn=str(row[4]).strip(),
            issued_date=row[5],
            activation_date=row[6],
            expiration_date=row[7],
            card_role=str(row[8]),
        )
