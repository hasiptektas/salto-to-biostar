from dataclasses import dataclass

import keyring
from PySide6.QtCore import QSettings


@dataclass(frozen=True, slots=True)
class BioStarConnectionSettings:
    base_url: str = "https://192.168.60.9"
    username: str = "admin"
    verify_certificate: bool = False
    access_group_id: str = ""
    access_group_name: str = ""

    def normalized_url(self) -> str:
        return self.base_url.strip().rstrip("/")


class BioStarSettingsStore:
    SERVICE = "SaltoBioStarSync"
    ACCOUNT = "biostar-api-password"

    def __init__(self) -> None:
        self._settings = QSettings("Wiegand", "SaltoBioStarSync")

    def load(self) -> BioStarConnectionSettings:
        self._settings.beginGroup("biostar")
        value = BioStarConnectionSettings(
            base_url=str(self._settings.value("base_url", "https://192.168.60.9")),
            username=str(self._settings.value("username", "admin")),
            verify_certificate=str(
                self._settings.value("verify_certificate", "false")
            ).lower() in {"1", "true", "yes"},
            access_group_id=str(self._settings.value("access_group_id", "")),
            access_group_name=str(self._settings.value("access_group_name", "")),
        )
        self._settings.endGroup()
        return value

    def load_password(self) -> str:
        return keyring.get_password(self.SERVICE, self.ACCOUNT) or ""

    def save(self, value: BioStarConnectionSettings, password: str) -> None:
        self._settings.beginGroup("biostar")
        self._settings.setValue("base_url", value.normalized_url())
        self._settings.setValue("username", value.username)
        self._settings.setValue("verify_certificate", value.verify_certificate)
        self._settings.setValue("access_group_id", value.access_group_id)
        self._settings.setValue("access_group_name", value.access_group_name)
        self._settings.endGroup()
        self._settings.sync()
        if password:
            keyring.set_password(self.SERVICE, self.ACCOUNT, password)
