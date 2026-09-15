import pyodbc
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from salto.settings import SaltoConnectionSettings, SaltoSettingsStore


class SaltoSettingsDialog(QDialog):
    connection_verified = Signal(object, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("SALTO bağlantı ayarları")
        self.setMinimumWidth(540)

        self._store = SaltoSettingsStore()
        current = self._store.load()
        saved_password = self._store.load_password()

        self.server_input = QLineEdit(current.server)
        self.server_input.setPlaceholderText("Örn. 192.168.1.20 veya SERVER\\INSTANCE")

        self.database_input = QLineEdit(current.database)

        self.driver_combo = QComboBox()
        drivers = [driver for driver in pyodbc.drivers() if "SQL Server" in driver]
        self.driver_combo.addItems(drivers)
        if current.driver in drivers:
            self.driver_combo.setCurrentText(current.driver)
        elif drivers:
            preferred = next(
                (
                    driver
                    for driver in (
                        "ODBC Driver 18 for SQL Server",
                        "ODBC Driver 17 for SQL Server",
                        "ODBC Driver 13 for SQL Server",
                        "SQL Server Native Client 11.0",
                        "SQL Server",
                    )
                    if driver in drivers
                ),
                drivers[0],
            )
            self.driver_combo.setCurrentText(preferred)

        self.windows_auth = QCheckBox("Windows hesabımla bağlan")
        self.windows_auth.setChecked(current.use_windows_auth)

        self.username_input = QLineEdit(current.username)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setText(saved_password)
        self.password_input.setPlaceholderText("SQL parolası")

        self.trust_certificate = QCheckBox("Sunucu sertifikasına güven")
        self.trust_certificate.setChecked(current.trust_server_certificate)

        self.result_label = QLabel("Ayarlar kaydedildiğinde bağlantı doğrulanır.")
        self.result_label.setWordWrap(True)

        form = QFormLayout()
        form.addRow("SQL Server:", self.server_input)
        form.addRow("Veritabanı:", self.database_input)
        form.addRow("ODBC sürücüsü:", self.driver_combo)
        form.addRow("Kimlik doğrulama:", self.windows_auth)
        form.addRow("Kullanıcı adı:", self.username_input)
        form.addRow("Parola:", self.password_input)
        form.addRow("Şifreleme:", self.trust_certificate)

        group = QGroupBox("SALTO SQL Server")
        group.setLayout(form)

        self.connect_button = QPushButton("Kaydet ve bağlan")
        self.connect_button.setObjectName("primaryButton")
        self.connect_button.clicked.connect(self._save_and_connect)
        cancel_button = QPushButton("İptal")
        cancel_button.clicked.connect(self.reject)

        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(cancel_button)
        actions.addWidget(self.connect_button)

        layout = QVBoxLayout()
        layout.addWidget(group)
        layout.addWidget(self.result_label)
        layout.addLayout(actions)
        self.setLayout(layout)

        self.windows_auth.toggled.connect(self._update_auth_fields)
        self._update_auth_fields()

    def _update_auth_fields(self) -> None:
        sql_auth = not self.windows_auth.isChecked()
        self.username_input.setEnabled(sql_auth)
        self.password_input.setEnabled(sql_auth)

    def _values(self) -> SaltoConnectionSettings:
        return SaltoConnectionSettings(
            server=self.server_input.text().strip(),
            database=self.database_input.text().strip(),
            driver=self.driver_combo.currentText().strip(),
            use_windows_auth=self.windows_auth.isChecked(),
            username=self.username_input.text().strip(),
            trust_server_certificate=self.trust_certificate.isChecked(),
        )

    def _validate(self) -> bool:
        values = self._values()
        if not values.server or not values.database or not values.driver:
            QMessageBox.warning(
                self,
                "Eksik bilgi",
                "Sunucu, veritabanı ve ODBC sürücüsü alanları zorunludur.",
            )
            return False
        if not values.use_windows_auth and not values.username:
            QMessageBox.warning(
                self, "Eksik bilgi", "SQL kullanıcı adını girin."
            )
            return False
        return True

    def _save_and_connect(self) -> None:
        if not self._validate():
            return

        values = self._values()
        self.connect_button.setEnabled(False)
        self.result_label.setText("Ayarlar doğrulanıyor…")

        try:
            connection_string = values.build_connection_string(
                self.password_input.text()
            )
            with pyodbc.connect(connection_string, timeout=8) as connection:
                row = connection.cursor().execute(
                    "SELECT DB_NAME(), @@SERVERNAME"
                ).fetchone()

            self.result_label.setText(
                f"Bağlantı başarılı — Sunucu: {row[1]}, Veritabanı: {row[0]}"
            )
            self.result_label.setStyleSheet("color: #18794e; font-weight: 600;")
            self._store.save(values, self.password_input.text())
            self.connection_verified.emit(values, connection_string)
            self.accept()
        except pyodbc.Error as error:
            self.result_label.setText("Bağlantı kurulamadı.")
            self.result_label.setStyleSheet("color: #b42318; font-weight: 600;")
            QMessageBox.critical(self, "SALTO bağlantı hatası", str(error))
        finally:
            self.connect_button.setEnabled(True)
