import httpx
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout,
)

from biostar.client import BioStarClient
from biostar.settings import BioStarConnectionSettings, BioStarSettingsStore


class BioStarSettingsDialog(QDialog):
    connection_verified = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("BioStar bağlantı ayarları")
        self.setMinimumWidth(500)
        self._store = BioStarSettingsStore()
        self._verified_client = None
        self._groups_loaded = False
        current = self._store.load()

        self.url_input = QLineEdit(current.base_url)
        self.username_input = QLineEdit(current.username)
        self.password_input = QLineEdit(self._store.load_password())
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.verify_certificate = QCheckBox("HTTPS sertifikasını doğrula")
        self.verify_certificate.setChecked(current.verify_certificate)
        self.access_group_input = QComboBox()
        self.access_group_input.addItem(
            current.access_group_name or "Bağlantıda erişim grupları yüklenecek",
            current.access_group_id,
        )
        self.result_label = QLabel("Parolayı girip bağlantıyı kaydedin.")

        form = QFormLayout()
        form.addRow("BioStar adresi:", self.url_input)
        form.addRow("Kullanıcı adı:", self.username_input)
        form.addRow("Parola:", self.password_input)
        form.addRow("Güvenlik:", self.verify_certificate)
        form.addRow("Erişim grubu:", self.access_group_input)

        cancel = QPushButton("İptal")
        cancel.clicked.connect(self.reject)
        self.connect_button = QPushButton("Kaydet ve bağlan")
        self.connect_button.setObjectName("primaryButton")
        self.connect_button.clicked.connect(self._save_and_connect)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(cancel)
        actions.addWidget(self.connect_button)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(self.result_label)
        layout.addLayout(actions)
        self.setLayout(layout)

    def _save_and_connect(self) -> None:
        settings = BioStarConnectionSettings(
            base_url=self.url_input.text().strip(),
            username=self.username_input.text().strip(),
            verify_certificate=self.verify_certificate.isChecked(),
            access_group_id=str(self.access_group_input.currentData() or ""),
            access_group_name=(
                self.access_group_input.currentText()
                if self.access_group_input.currentData() else ""
            ),
        )
        password = self.password_input.text()
        if not settings.base_url or not settings.username or not password:
            QMessageBox.warning(self, "Eksik bilgi", "Adres, kullanıcı adı ve parola zorunludur.")
            return
        self.connect_button.setEnabled(False)
        self.result_label.setText("BioStar bağlantısı ve erişim grupları doğrulanıyor…")
        try:
            if not self._groups_loaded:
                client = BioStarClient(settings, password)
                client.login()
                groups = client.list_access_groups()
                if not groups:
                    raise RuntimeError("BioStar'da seçilebilecek erişim grubu bulunamadı.")
                previous_id = settings.access_group_id
                self.access_group_input.clear()
                for group in groups:
                    group_id = str(group.get("id", ""))
                    if group_id:
                        self.access_group_input.addItem(str(group.get("name", group_id)), group_id)
                selected_index = self.access_group_input.findData(previous_id)
                if selected_index >= 0:
                    self.access_group_input.setCurrentIndex(selected_index)
                self._verified_client = client
                self._groups_loaded = True
                self.result_label.setText("Erişim grubunu seçip 'Seçimi kaydet' düğmesine basın.")
                self.connect_button.setText("Seçimi kaydet")
                return
            settings = BioStarConnectionSettings(
                base_url=settings.base_url,
                username=settings.username,
                verify_certificate=settings.verify_certificate,
                access_group_id=str(self.access_group_input.currentData() or ""),
                access_group_name=self.access_group_input.currentText(),
            )
            self._store.save(settings, password)
            self.connection_verified.emit(self._verified_client)
            self.accept()
        except (httpx.HTTPError, RuntimeError) as error:
            self.result_label.setText("Bağlantı kurulamadı.")
            QMessageBox.critical(self, "BioStar bağlantı hatası", str(error))
        finally:
            self.connect_button.setEnabled(True)
