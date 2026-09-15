from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Wiegand26Card:
    salto_rom: str
    card_id: int
    facility_code: int
    card_number: int

    @property
    def display_id(self) -> str:
        return f"{self.facility_code}-{self.card_number}"


def convert_salto_rom_to_wiegand26(rom_code: str) -> Wiegand26Card:
    normalized = rom_code.strip().replace(" ", "").upper()
    if len(normalized) != 14:
        raise ValueError("SALTO HotelCardID 14 hex karakter olmalıdır.")
    try:
        raw = bytes.fromhex(normalized)
    except ValueError as error:
        raise ValueError("SALTO HotelCardID geçerli hexadecimal değil.") from error
    if raw[4:] != b"\x00\x00\x00":
        raise ValueError("Yalnızca 4-byte MIFARE CSN kartları destekleniyor.")

    csn32 = int.from_bytes(raw[:4], byteorder="little")
    card_id = csn32 & 0xFFFFFF
    return Wiegand26Card(
        salto_rom=normalized,
        card_id=card_id,
        facility_code=(card_id >> 16) & 0xFF,
        card_number=card_id & 0xFFFF,
    )
