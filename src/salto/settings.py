from dataclasses import dataclass

import keyring
from PySide6.QtCore import QSettings


def _odbc_value(value: str) -> str:
    """ODBC bağlantı değerini noktalı virgül ve süslü parantezlere karşı korur."""
    return "{" + value.replace("}", "}}") + "}"


@dataclass(frozen=True, slots=True)
class SaltoConnectionSettings:
    server: str = ""
    database: str = "SALTO_SPACE"
    driver: str = "ODBC Driver 18 for SQL Server"
    use_windows_auth: bool = True
    username: str = ""
    trust_server_certificate: bool = True

    def build_connection_string(self, password: str = "") -> str:
        parts = [
            f"DRIVER={_odbc_value(self.driver)}",
            f"SERVER={_odbc_value(self.server.strip())}",
            f"DATABASE={_odbc_value(self.database.strip())}",
            "APP=SALTO-BioStar Sync",
        ]

        if self.use_windows_auth:
            parts.append("Trusted_Connection=Yes")
        else:
            parts.extend(
                (
                    f"UID={_odbc_value(self.username.strip())}",
                    f"PWD={_odbc_value(password)}",
                )
            )

        parts.append(
            "TrustServerCertificate=Yes"
            if self.trust_server_certificate
            else "TrustServerCertificate=No"
        )
        return ";".join(parts) + ";"


class SaltoSettingsStore:
    GROUP = "salto"
    CREDENTIAL_SERVICE = "SaltoBioStarSync"
    CREDENTIAL_ACCOUNT = "salto-sql-password"

    def __init__(self) -> None:
        self._settings = QSettings("Wiegand", "SaltoBioStarSync")

    def load(self) -> SaltoConnectionSettings:
        self._settings.beginGroup(self.GROUP)
        result = SaltoConnectionSettings(
            server=str(self._settings.value("server", "")),
            database=str(self._settings.value("database", "SALTO_SPACE")),
            driver=str(
                self._settings.value("driver", "ODBC Driver 18 for SQL Server")
            ),
            use_windows_auth=self._as_bool(
                self._settings.value("use_windows_auth", True)
            ),
            username=str(self._settings.value("username", "")),
            trust_server_certificate=self._as_bool(
                self._settings.value("trust_server_certificate", True)
            ),
        )
        self._settings.endGroup()
        return result

    def load_password(self) -> str:
        try:
            return keyring.get_password(
                self.CREDENTIAL_SERVICE, self.CREDENTIAL_ACCOUNT
            ) or ""
        except keyring.errors.KeyringError:
            return ""

    def save(self, value: SaltoConnectionSettings, password: str = "") -> None:
        self._settings.beginGroup(self.GROUP)
        self._settings.setValue("server", value.server)
        self._settings.setValue("database", value.database)
        self._settings.setValue("driver", value.driver)
        self._settings.setValue("use_windows_auth", value.use_windows_auth)
        self._settings.setValue("username", value.username)
        self._settings.setValue(
            "trust_server_certificate", value.trust_server_certificate
        )
        self._settings.endGroup()
        self._settings.sync()
        if password:
            keyring.set_password(
                self.CREDENTIAL_SERVICE, self.CREDENTIAL_ACCOUNT, password
            )

    @staticmethod
    def _as_bool(value: object) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).lower() in {"1", "true", "yes"}
