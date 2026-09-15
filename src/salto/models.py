from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class SaltoHotelCard:
    """BioStar'a aktarılmaya hazır aktif SALTO otel kartı."""

    room_user_id: int
    room_number: str
    number_of_keys: int
    key_copy_number: int
    card_csn: str
    issued_date: datetime
    activation_date: datetime
    expiration_date: datetime
    card_role: str
