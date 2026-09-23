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

CARD_COUNT_MISMATCH_SQL = """
DECLARE @Now datetime = GETDATE();

SELECT
    u.id_user,
    u.name,
    u.status,
    u.CopyCount + 1 AS ExpectedCards,
    COUNT(hc.HotelCardID) AS FoundCards,
    u.dtActivation,
    u.dtExpiration
FROM dbo.tb_Users AS u
LEFT JOIN dbo.tb_HotelCards AS hc
    ON hc.id_user = u.id_user
    AND hc.IssuedDate >= u.dtActivation
    AND hc.IssuedDate <= u.dtExpiration
    AND hc.CopyCount >= 0
    AND hc.CopyCount <= u.CopyCount
    AND hc.HotelCardID IS NOT NULL
    AND LTRIM(RTRIM(hc.HotelCardID)) <> ''
WHERE
    u.type = 3
    AND u.status = 1
    AND u.dtActivation <= @Now
    AND u.dtExpiration > @Now
GROUP BY
    u.id_user, u.name, u.status, u.CopyCount,
    u.dtActivation, u.dtExpiration
HAVING COUNT(hc.HotelCardID) <> u.CopyCount + 1
ORDER BY u.name;
"""

ROOM_CARD_DETAIL_SQL = """
SELECT
    u.id_user,
    u.name,
    u.CopyCount,
    u.CopyCount + 1 AS ExpectedCards,
    u.dtActivation,
    u.dtExpiration,
    hc.HotelCardID,
    hc.CopyCount AS CardCopyCount,
    hc.IssuedDate,
    CASE
        WHEN hc.HotelCardID IS NULL THEN 'Kart kaydı yok'
        WHEN LTRIM(RTRIM(hc.HotelCardID)) = '' THEN 'CSN boş'
        WHEN hc.IssuedDate < u.dtActivation THEN 'Konaklama başlangıcından eski'
        WHEN hc.IssuedDate > u.dtExpiration THEN 'Konaklama bitişinden sonra'
        WHEN hc.CopyCount < 0 OR hc.CopyCount > u.CopyCount THEN 'Kopya sırası kapsam dışı'
        ELSE 'Güncel sorguya dahil'
    END AS CardState
FROM dbo.tb_Users AS u
LEFT JOIN dbo.tb_HotelCards AS hc ON hc.id_user = u.id_user
WHERE u.name = '@' + ?
ORDER BY hc.IssuedDate DESC, hc.CopyCount;
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

    def fetch_card_count_mismatches(self) -> list[tuple]:
        """Aktif odalarda beklenen ve bulunan kart sayısı uyuşmayanları getirir."""
        with pyodbc.connect(self._connection_string, timeout=10) as connection:
            rows = connection.cursor().execute(CARD_COUNT_MISMATCH_SQL).fetchall()
        return [tuple(row) for row in rows]

    def fetch_room_card_details(self, room_number: str) -> list[tuple]:
        """Bir oda kullanıcısının tüm HotelCards geçmişini getirir."""
        normalized = room_number.strip().lstrip("@").strip()
        if not normalized:
            raise ValueError("Oda numarası boş olamaz.")
        with pyodbc.connect(self._connection_string, timeout=10) as connection:
            rows = connection.cursor().execute(ROOM_CARD_DETAIL_SQL, normalized).fetchall()
        return [tuple(row) for row in rows]

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
