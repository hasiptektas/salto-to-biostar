from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BioStarUser:
    user_id: str
    name: str
    card_count: int
    start_datetime: str
    expiry_datetime: str
    disabled: bool
