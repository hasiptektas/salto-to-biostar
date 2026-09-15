from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from salto.repository import SaltoRepository
from salto.settings import SaltoSettingsStore
from salto.wiegand import convert_salto_rom_to_wiegand26
from biostar.client import BioStarClient
from biostar.settings import BioStarSettingsStore
from ui.biostar_settings_dialog import BioStarSettingsDialog
from ui.salto_settings_dialog import SaltoSettingsDialog


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SALTO - BioStar Senkronizasyon")
        self.resize(1280, 720)
        self.setMinimumSize(980, 580)
        self._salto_connection_string: str | None = None
        self._biostar_client: BioStarClient | None = None

        title = QLabel("SALTO → BioStar")
        title.setObjectName("title")
        description = QLabel("Kart kayıtlarını görüntüleyin ve karşılaştırın")
        description.setObjectName("subtitle")

        heading = QVBoxLayout()
        heading.setSpacing(2)
        heading.addWidget(title)
        heading.addWidget(description)

        settings_button = QPushButton("SALTO ayarları")
        settings_button.clicked.connect(self._open_settings)

        top_bar = QHBoxLayout()
        top_bar.addLayout(heading)
        top_bar.addStretch()
        top_bar.addWidget(settings_button)

        self.salto_status_label = QLabel("Bağlı değil")
        self.salto_status_label.setObjectName("statusBadge")
        self.load_salto_button = QPushButton("Yenile")
        self.load_salto_button.setEnabled(False)
        self.load_salto_button.clicked.connect(self._load_salto_cards)
        self.salto_table = self._create_table(
            ["Oda", "Kart", "Kopya", "Kart CSN", "BioStar ID", "H10301", "Veriliş", "Başlangıç", "Bitiş", "Tür"]
        )
        salto_panel = self._create_panel(
            "SALTO bağlantısı",
            self.salto_status_label,
            self.load_salto_button,
            self.salto_table,
        )

        self.biostar_status_label = QLabel("Bağlı değil")
        self.biostar_status_label.setObjectName("statusBadge")
        biostar_settings_button = QPushButton("Ayarlar")
        biostar_settings_button.clicked.connect(self._open_biostar_settings)
        self.biostar_refresh_button = QPushButton("Yenile")
        self.biostar_refresh_button.setEnabled(False)
        self.biostar_refresh_button.clicked.connect(lambda: self._load_biostar_users())
        self.delete_biostar_user_button = QPushButton("Seçili kullanıcıyı sil")
        self.delete_biostar_user_button.setEnabled(False)
        self.delete_biostar_user_button.clicked.connect(self._delete_selected_biostar_user)
        self.biostar_table = self._create_table(
            ["Kullanıcı", "Ad", "Kart sayısı", "Başlangıç", "Bitiş", "Durum"]
        )
        self.biostar_table.cellDoubleClicked.connect(self._show_biostar_user_detail)
        self.biostar_table.itemSelectionChanged.connect(self._update_delete_button)
        biostar_panel = self._create_panel(
            "BioStar bağlantısı", self.biostar_status_label,
            [self.delete_biostar_user_button, self.biostar_refresh_button, biostar_settings_button],
            self.biostar_table,
        )

        lists = QHBoxLayout()
        lists.setSpacing(14)
        lists.addWidget(salto_panel, 1)
        lists.addWidget(biostar_panel, 1)

        self.manual_transfer_button = QPushButton("Seçili kartı manuel ata")
        self.manual_transfer_button.setObjectName("primaryButton")
        self.manual_transfer_button.setEnabled(False)
        self.manual_transfer_button.clicked.connect(self._manual_card_transfer)
        self.room_transfer_button = QPushButton("Seçili odayı manuel aktar")
        self.room_transfer_button.setObjectName("primaryButton")
        self.room_transfer_button.setEnabled(False)
        self.room_transfer_button.clicked.connect(self._manual_room_transfer)
        self.all_rooms_transfer_button = QPushButton("Tüm odaları aktar")
        self.all_rooms_transfer_button.setObjectName("primaryButton")
        self.all_rooms_transfer_button.setEnabled(False)
        self.all_rooms_transfer_button.clicked.connect(self._transfer_all_rooms)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(self.manual_transfer_button)
        actions.addWidget(self.room_transfer_button)
        actions.addWidget(self.all_rooms_transfer_button)

        content = QVBoxLayout()
        content.setContentsMargins(22, 18, 22, 14)
        content.setSpacing(14)
        content.addLayout(top_bar)
        content.addLayout(lists, 1)
        content.addLayout(actions)

        container = QWidget()
        container.setLayout(content)
        self.setCentralWidget(container)

        status_bar = QStatusBar()
        status_bar.showMessage("Hazır")
        self.setStatusBar(status_bar)
        self._apply_styles()

        QTimer.singleShot(0, self._connect_from_saved_settings)
        QTimer.singleShot(50, self._connect_biostar_from_saved_settings)

    @staticmethod
    def _create_panel(
        title: str,
        status: QLabel,
        action: QPushButton | list[QPushButton] | None,
        table: QTableWidget,
    ) -> QFrame:
        title_label = QLabel(title)
        title_label.setObjectName("panelTitle")
        header = QHBoxLayout()
        header.addWidget(title_label)
        header.addWidget(status)
        header.addStretch()
        if isinstance(action, list):
            for button in action:
                header.addWidget(button)
        elif action:
            header.addWidget(action)

        layout = QVBoxLayout()
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)
        layout.addLayout(header)
        layout.addWidget(table)

        panel = QFrame()
        panel.setObjectName("dataPanel")
        panel.setLayout(layout)
        return panel

    @staticmethod
    def _create_table(headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setShowGrid(False)
        table.setWordWrap(False)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(30)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def _open_settings(self) -> None:
        dialog = SaltoSettingsDialog(self)
        dialog.connection_verified.connect(self._salto_connection_verified)
        dialog.exec()

    def _open_biostar_settings(self) -> None:
        dialog = BioStarSettingsDialog(self)
        dialog.connection_verified.connect(self._biostar_connection_verified)
        dialog.exec()

    def _connect_biostar_from_saved_settings(self) -> None:
        store = BioStarSettingsStore()
        settings = store.load()
        password = store.load_password()
        if not settings.base_url or not settings.username or not password:
            return
        self._biostar_client = BioStarClient(settings, password)
        self._load_biostar_users(show_error=False)

    def _biostar_connection_verified(self, client: object) -> None:
        self._biostar_client = client
        self._load_biostar_users()

    def _load_biostar_users(self, show_error: bool = True) -> None:
        if not self._biostar_client:
            return
        self._set_biostar_status("Yükleniyor…", None)
        self.biostar_refresh_button.setEnabled(False)
        try:
            users = self._biostar_client.list_users()
            self.biostar_table.setSortingEnabled(False)
            self.biostar_table.setRowCount(len(users))
            for row_index, user in enumerate(users):
                values = (
                    user.user_id,
                    user.name,
                    str(user.card_count),
                    user.start_datetime,
                    user.expiry_datetime,
                    "Pasif" if user.disabled else "Aktif",
                )
                for column_index, value in enumerate(values):
                    self.biostar_table.setItem(row_index, column_index, QTableWidgetItem(value))
            self.biostar_table.setSortingEnabled(True)
            self._set_biostar_status(f"{len(users)} kullanıcı", True)
            self.manual_transfer_button.setEnabled(bool(self._salto_connection_string))
            self.room_transfer_button.setEnabled(bool(self._salto_connection_string))
            self.all_rooms_transfer_button.setEnabled(bool(self._salto_connection_string))
            self.biostar_refresh_button.setEnabled(True)
            self._update_delete_button()
            self.statusBar().showMessage("BioStar kullanıcı listesi güncellendi.", 5000)
        except Exception as error:
            self._set_biostar_status("Bağlantı hatası", False)
            if show_error:
                QMessageBox.critical(self, "BioStar liste hatası", str(error))
        finally:
            self.biostar_refresh_button.setEnabled(self._biostar_client is not None)

    def _update_delete_button(self) -> None:
        row = self.biostar_table.currentRow()
        user_id = self.biostar_table.item(row, 0).text() if row >= 0 and self.biostar_table.item(row, 0) else ""
        self.delete_biostar_user_button.setEnabled(
            self._biostar_client is not None and bool(user_id) and user_id != "1"
        )

    def _delete_selected_biostar_user(self) -> None:
        row = self.biostar_table.currentRow()
        if row < 0 or not self._biostar_client:
            QMessageBox.warning(self, "Seçim gerekli", "Sağdan silinecek BioStar kullanıcısını seçin.")
            return
        user_id = self.biostar_table.item(row, 0).text()
        name = self.biostar_table.item(row, 1).text()
        card_count = self.biostar_table.item(row, 2).text()
        if user_id == "1":
            QMessageBox.warning(self, "İşlem engellendi", "BioStar yönetici kullanıcısı silinemez.")
            return
        answer = QMessageBox.warning(
            self,
            "BioStar kullanıcısını sil",
            f"Kullanıcı ID: {user_id}\nAd: {name}\nKart sayısı: {card_count}\n\n"
            "Bu işlem kullanıcıyı BioStar'dan kalıcı olarak siler. SALTO verileri değişmez.\n"
            "Devam edilsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.delete_biostar_user_button.setEnabled(False)
        try:
            self._biostar_client.delete_user(user_id)
            QMessageBox.information(self, "Silme başarılı", f"{user_id} — {name} BioStar'dan silindi.")
            self._load_biostar_users()
        except Exception as error:
            QMessageBox.critical(self, "Kullanıcı silme hatası", str(error))
        finally:
            self._update_delete_button()

    def _set_biostar_status(self, text: str, success: bool | None) -> None:
        self.biostar_status_label.setText(text)
        state = "success" if success is True else "error" if success is False else "loading"
        self.biostar_status_label.setProperty("state", state)
        self.biostar_status_label.style().unpolish(self.biostar_status_label)
        self.biostar_status_label.style().polish(self.biostar_status_label)

    def _show_biostar_user_detail(self, row: int, _column: int) -> None:
        if not self._biostar_client:
            return
        user_item = self.biostar_table.item(row, 0)
        if not user_item:
            return
        user_id = user_item.text()
        try:
            user = self._biostar_client.get_user_detail(user_id)
            cards_value = user.get("cards", [])
            cards = cards_value.get("rows", []) if isinstance(cards_value, dict) else cards_value
            if not isinstance(cards, list):
                cards = []
            lines = []
            for index, card in enumerate(cards, start=1):
                card_type = card.get("card_type", {}) or {}
                wiegand_format = (
                    card.get("wiegand_format_id")
                    or card.get("wiegand_format")
                    or {}
                )
                if not isinstance(wiegand_format, dict):
                    wiegand_format = {"id": wiegand_format}
                format_id = str(wiegand_format.get("id", ""))
                format_detail = {}
                if format_id and format_id != "-":
                    try:
                        format_detail = self._biostar_client.get_wiegand_format(format_id)
                    except Exception:
                        format_detail = {}
                lines.append(
                    f"{index}. kart\n"
                    f"  Dahili ID: {card.get('id', '-')}\n"
                    f"  Kart ID: {card.get('card_id', '-')}\n"
                    f"  Görünen ID: {card.get('display_card_id', '-')}\n"
                    f"  Kart türü adı: {card_type.get('name', '-')}\n"
                    f"  card_type.id: {card_type.get('id', '-')}\n"
                    f"  card_type.type: {card_type.get('type', '-')}\n"
                    f"  wiegand_format_id: {wiegand_format.get('id', '-')}\n"
                    f"  Format adı: {format_detail.get('name', '-')}\n"
                    f"  Bit uzunluğu: {format_detail.get('length', '-')}\n"
                    f"  Facility code: {format_detail.get('use_facility_code', '-')}"
                )
            detail = "\n".join(lines) if lines else "Bu kullanıcıda kart detayı bulunamadı."
            QMessageBox.information(
                self,
                f"BioStar kullanıcısı {user_id}",
                f"Ad: {user.get('name', '')}\n"
                f"Başlangıç: {user.get('start_datetime', '')}\n"
                f"Bitiş: {user.get('expiry_datetime', '')}\n\n"
                f"Kartlar:\n{detail}",
            )
        except Exception as error:
            QMessageBox.critical(self, "BioStar detay hatası", str(error))

    def _connect_from_saved_settings(self) -> None:
        store = SaltoSettingsStore()
        settings = store.load()
        if not settings.server or not settings.database or not settings.driver:
            return
        password = store.load_password()
        if not settings.use_windows_auth and (not settings.username or not password):
            return
        self._salto_connection_string = settings.build_connection_string(password)
        self.load_salto_button.setEnabled(True)
        self._load_salto_cards(show_error=False)

    def _salto_connection_verified(self, _settings: object, connection: str) -> None:
        self._salto_connection_string = connection
        self.load_salto_button.setEnabled(True)
        self._set_salto_status("Bağlandı", True)
        self._load_salto_cards()

    def _load_salto_cards(self, show_error: bool = True) -> None:
        if not self._salto_connection_string:
            return
        self.load_salto_button.setEnabled(False)
        self._set_salto_status("Yükleniyor…", None)
        self.statusBar().showMessage("SALTO kartları getiriliyor…")
        try:
            cards = SaltoRepository(self._salto_connection_string).fetch_active_hotel_cards()
            self.salto_table.setSortingEnabled(False)
            self.salto_table.setRowCount(len(cards))
            for row_index, card in enumerate(cards):
                try:
                    converted = convert_salto_rom_to_wiegand26(card.card_csn)
                    biostar_id = str(converted.card_id)
                    h10301 = converted.display_id
                except ValueError:
                    biostar_id = "Desteklenmiyor"
                    h10301 = "-"
                values = (
                    card.room_number,
                    str(card.number_of_keys),
                    str(card.key_copy_number),
                    card.card_csn,
                    biostar_id,
                    h10301,
                    self._format_datetime(card.issued_date),
                    self._format_datetime(card.activation_date),
                    self._format_datetime(card.expiration_date),
                    "Ana" if card.card_role == "PRIMARY" else "Kopya",
                )
                for column_index, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if column_index == 0:
                        item.setData(Qt.ItemDataRole.UserRole, card.room_user_id)
                    self.salto_table.setItem(row_index, column_index, item)
            self.salto_table.setSortingEnabled(True)
            room_count = len({card.room_user_id for card in cards})
            self._set_salto_status(f"{room_count} oda · {len(cards)} kart", True)
            self.manual_transfer_button.setEnabled(self._biostar_client is not None)
            self.room_transfer_button.setEnabled(self._biostar_client is not None)
            self.all_rooms_transfer_button.setEnabled(self._biostar_client is not None)
            self.statusBar().showMessage("SALTO listesi güncellendi.", 5000)
        except Exception as error:
            self._set_salto_status("Bağlantı hatası", False)
            self.statusBar().showMessage("SALTO listesi alınamadı.", 5000)
            if show_error:
                QMessageBox.critical(self, "SALTO sorgu hatası", str(error))
        finally:
            self.load_salto_button.setEnabled(True)

    def _set_salto_status(self, text: str, success: bool | None) -> None:
        self.salto_status_label.setText(text)
        state = "success" if success is True else "error" if success is False else "loading"
        self.salto_status_label.setProperty("state", state)
        self.salto_status_label.style().unpolish(self.salto_status_label)
        self.salto_status_label.style().polish(self.salto_status_label)

    def _manual_card_transfer(self) -> None:
        salto_row = self.salto_table.currentRow()
        biostar_row = self.biostar_table.currentRow()
        if salto_row < 0 or biostar_row < 0:
            QMessageBox.warning(
                self,
                "Seçim gerekli",
                "Soldan bir SALTO kartı, sağdan hedef BioStar kullanıcısını seçin.",
            )
            return
        if not self._biostar_client:
            return

        room = self.salto_table.item(salto_row, 0).text()
        salto_rom = self.salto_table.item(salto_row, 3).text()
        target_user = self.biostar_table.item(biostar_row, 0).text()
        target_name = self.biostar_table.item(biostar_row, 1).text()
        activation_text = self.salto_table.item(salto_row, 7).text()
        expiration_text = self.salto_table.item(salto_row, 8).text()
        salto_activation = datetime.strptime(activation_text, "%d.%m.%Y %H:%M")
        activation = max(salto_activation, datetime.now().replace(second=0, microsecond=0))
        expiration = datetime.strptime(expiration_text, "%d.%m.%Y %H:%M")
        biostar_settings = BioStarSettingsStore().load()
        if not biostar_settings.access_group_id:
            QMessageBox.warning(
                self,
                "Erişim grubu gerekli",
                "Önce BioStar Ayarlar bölümünden erişim grubunu seçip kaydedin.",
            )
            return
        try:
            converted = convert_salto_rom_to_wiegand26(salto_rom)
        except ValueError as error:
            QMessageBox.critical(self, "Kart dönüştürme hatası", str(error))
            return

        answer = QMessageBox.question(
            self,
            "Manuel test aktarımını onayla",
            f"SALTO odası: {room}\n"
            f"SALTO ROM: {salto_rom}\n"
            f"BioStar Kart ID: {converted.card_id}\n"
            f"H10301: {converted.display_id}\n"
            f"Format: 26 bit (ID 0)\n\n"
            f"Hedef kullanıcı: {target_user} — {target_name}\n"
            f"Başlangıç: {self._format_datetime(activation)}\n"
            f"Bitiş: {expiration_text}\n"
            f"Erişim grubu: {biostar_settings.access_group_name} "
            f"(ID {biostar_settings.access_group_id})\n\n"
            "Bu işlem kartı atar, kullanıcı tarihlerini ve erişim grubunu günceller. Devam edilsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.manual_transfer_button.setEnabled(False)
        try:
            target_detail = self._biostar_client.get_user_detail(target_user)
            target_cards_value = target_detail.get("cards", [])
            target_cards = (
                target_cards_value.get("rows", [])
                if isinstance(target_cards_value, dict)
                else target_cards_value
            )
            if not isinstance(target_cards, list):
                target_cards = []
            existing = self._biostar_client.find_card(converted.card_id)
            if existing:
                internal_id = str(existing.get("id", ""))
                target_ids = {str(card.get("id")) for card in target_cards}
                assigned = existing.get("is_assigned")
                if internal_id not in target_ids and (
                    assigned is True or str(assigned).lower() == "true"
                ):
                    raise RuntimeError("Kart BioStar'da başka bir kullanıcıya atanmış; güvenlik için işlem durduruldu.")
            else:
                existing = self._biostar_client.create_wiegand26_card(converted.card_id)
                internal_id = str(existing["id"])

            self._biostar_client.assign_card_and_stay(
                target_user,
                internal_id,
                activation,
                expiration,
                biostar_settings.access_group_id,
            )
            QMessageBox.information(
                self,
                "Aktarım başarılı",
                f"{converted.display_id} kartı {target_user} — {target_name} kullanıcısına atandı.",
            )
            self._load_biostar_users()
        except Exception as error:
            QMessageBox.critical(self, "Manuel aktarım hatası", str(error))
        finally:
            self.manual_transfer_button.setEnabled(True)

    def _manual_room_transfer(self) -> None:
        salto_row = self.salto_table.currentRow()
        if salto_row < 0:
            QMessageBox.warning(self, "Seçim gerekli", "Soldan aktarılacak odanın bir kartını seçin.")
            return
        if not self._biostar_client:
            return
        settings = BioStarSettingsStore().load()
        if not settings.access_group_id:
            QMessageBox.warning(
                self, "Erişim grubu gerekli",
                "Önce BioStar Ayarlar bölümünden erişim grubunu seçip kaydedin.",
            )
            return

        room = self.salto_table.item(salto_row, 0).text()
        room_user_id = str(self.salto_table.item(salto_row, 0).data(Qt.ItemDataRole.UserRole))
        room_reference = room
        room_rows = [
            row for row in range(self.salto_table.rowCount())
            if str(self.salto_table.item(row, 0).data(Qt.ItemDataRole.UserRole)) == room_user_id
        ]
        salto_activation = min(
            datetime.strptime(self.salto_table.item(row, 7).text(), "%d.%m.%Y %H:%M")
            for row in room_rows
        )
        expiration = max(
            datetime.strptime(self.salto_table.item(row, 8).text(), "%d.%m.%Y %H:%M")
            for row in room_rows
        )
        activation = max(salto_activation, datetime.now().replace(second=0, microsecond=0))
        if expiration <= activation:
            QMessageBox.warning(self, "Geçersiz konaklama", "Bu odanın çıkış zamanı geçmiş.")
            return

        converted_cards = []
        try:
            for row in room_rows:
                rom = self.salto_table.item(row, 3).text()
                converted_cards.append((rom, convert_salto_rom_to_wiegand26(rom)))
        except ValueError as error:
            QMessageBox.critical(self, "Kart dönüştürme hatası", str(error))
            return

        card_lines = "\n".join(
            f"• {rom} → {card.display_id}" for rom, card in converted_cards
        )
        answer = QMessageBox.question(
            self,
            "Oda aktarımını onayla",
            f"SALTO oda: {room} (id_user: {room_user_id})\n"
            f"BioStar Ad: {room}\n"
            "BioStar ID: BioStar tarafından otomatik verilecek\n"
            f"Başlangıç: {self._format_datetime(activation)}\n"
            f"Bitiş: {self._format_datetime(expiration)}\n"
            f"Erişim grubu: {settings.access_group_name} (ID {settings.access_group_id})\n\n"
            f"Aktarılacak kartlar:\n{card_lines}\n\n"
            "Kullanıcı yoksa oluşturulacak, varsa güncellenecektir. Devam edilsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.room_transfer_button.setEnabled(False)
        try:
            result, biostar_user_id, card_count = self._execute_room_transfer(
                room_reference, converted_cards, activation, expiration, settings.access_group_id
            )
            verb = "oluşturuldu" if result == "created" else "güncellendi"
            QMessageBox.information(
                self, "Oda aktarımı başarılı",
                f"{room_reference} kullanıcısı {verb}.\n"
                f"BioStar ID: {biostar_user_id}\n{card_count} kart işlendi.",
            )
            self._load_biostar_users()
        except Exception as error:
            QMessageBox.critical(self, "Oda aktarım hatası", str(error))
        finally:
            self.room_transfer_button.setEnabled(True)

    def _execute_room_transfer(
        self,
        room_name: str,
        converted_cards: list[tuple[str, object]],
        activation: datetime,
        expiration: datetime,
        access_group_id: str,
    ) -> tuple[str, str, int]:
        if not self._biostar_client:
            raise RuntimeError("BioStar bağlantısı yok.")
        matched_user = self._biostar_client.find_user_by_name(room_name)
        target = self._biostar_client.get_user_detail(matched_user.user_id) if matched_user else None
        target_cards_value = target.get("cards", []) if target else []
        target_cards = (
            target_cards_value.get("rows", [])
            if isinstance(target_cards_value, dict) else target_cards_value
        )
        target_ids = {str(card.get("id")) for card in target_cards if card.get("id")}
        internal_ids = []
        for _rom, converted in converted_cards:
            existing = self._biostar_client.find_card(converted.card_id)
            if existing:
                internal_id = str(existing.get("id", ""))
                assigned = existing.get("is_assigned")
                if internal_id not in target_ids and (
                    assigned is True or str(assigned).lower() == "true"
                ):
                    raise RuntimeError(f"{converted.display_id} kartı başka kullanıcıya atanmış.")
            else:
                existing = self._biostar_client.create_wiegand26_card(converted.card_id)
                internal_id = str(existing["id"])
            internal_ids.append(internal_id)
        result, user_id = self._biostar_client.create_or_update_room_user(
            room_name, internal_ids, activation, expiration, access_group_id
        )
        return result, user_id, len(internal_ids)

    def _transfer_all_rooms(self) -> None:
        if not self._biostar_client or self.salto_table.rowCount() == 0:
            QMessageBox.warning(self, "Veri yok", "Önce SALTO ve BioStar listelerini yükleyin.")
            return
        settings = BioStarSettingsStore().load()
        if not settings.access_group_id:
            QMessageBox.warning(
                self, "Erişim grubu gerekli",
                "Önce BioStar Ayarlar bölümünden erişim grubunu seçip kaydedin.",
            )
            return
        room_user_ids = list(dict.fromkeys(
            str(self.salto_table.item(row, 0).data(Qt.ItemDataRole.UserRole))
            for row in range(self.salto_table.rowCount())
        ))
        answer = QMessageBox.warning(
            self,
            "Tüm aktif odaları aktar",
            f"{len(room_user_ids)} aktif oda ve {self.salto_table.rowCount()} kart BioStar'a aktarılacak.\n"
            f"Erişim grubu: {settings.access_group_name} (ID {settings.access_group_id})\n\n"
            "Kullanıcılar oluşturulabilir veya güncellenebilir. Devam edilsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.all_rooms_transfer_button.setEnabled(False)
        self.room_transfer_button.setEnabled(False)
        successes = []
        errors = []
        try:
            for index, room_user_id in enumerate(room_user_ids, start=1):
                room_rows = [
                    row for row in range(self.salto_table.rowCount())
                    if str(self.salto_table.item(row, 0).data(Qt.ItemDataRole.UserRole)) == room_user_id
                ]
                room = self.salto_table.item(room_rows[0], 0).text()
                self.statusBar().showMessage(f"Aktarılıyor: {room} ({index}/{len(room_user_ids)})")
                try:
                    salto_activation = min(
                        datetime.strptime(self.salto_table.item(row, 7).text(), "%d.%m.%Y %H:%M")
                        for row in room_rows
                    )
                    expiration = max(
                        datetime.strptime(self.salto_table.item(row, 8).text(), "%d.%m.%Y %H:%M")
                        for row in room_rows
                    )
                    activation = max(salto_activation, datetime.now().replace(second=0, microsecond=0))
                    if expiration <= activation:
                        raise RuntimeError("Çıkış zamanı geçmiş.")
                    converted_cards = []
                    for row in room_rows:
                        rom = self.salto_table.item(row, 3).text()
                        converted_cards.append((rom, convert_salto_rom_to_wiegand26(rom)))
                    result, user_id, card_count = self._execute_room_transfer(
                        room, converted_cards, activation, expiration, settings.access_group_id
                    )
                    successes.append(f"{room}: ID {user_id}, {card_count} kart")
                except Exception as error:
                    errors.append(f"{room}: {error}")
        finally:
            self.all_rooms_transfer_button.setEnabled(True)
            self.room_transfer_button.setEnabled(True)

        self._load_biostar_users()
        error_text = "\n".join(errors[:15])
        if len(errors) > 15:
            error_text += f"\n… ve {len(errors) - 15} hata daha"
        QMessageBox.information(
            self,
            "Toplu aktarım tamamlandı",
            f"Başarılı oda: {len(successes)}\nHatalı oda: {len(errors)}"
            + (f"\n\nHatalar:\n{error_text}" if errors else ""),
        )

    @staticmethod
    def _format_datetime(value: object) -> str:
        return value.strftime("%d.%m.%Y %H:%M") if hasattr(value, "strftime") else str(value)

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #f4f6f8; color: #17202a; font-family: "Segoe UI"; font-size: 13px; }
            QLabel#title { font-size: 23px; font-weight: 650; }
            QLabel#subtitle { color: #66727d; font-size: 12px; }
            QFrame#dataPanel { background: white; border: 1px solid #dde3e8; border-radius: 8px; }
            QLabel#panelTitle { font-size: 14px; font-weight: 600; }
            QLabel#statusBadge { color: #66727d; background: #eef1f4; border-radius: 9px; padding: 2px 7px; font-size: 11px; }
            QLabel#statusBadge[state="success"] { color: #11663f; background: #dff5e9; }
            QLabel#statusBadge[state="error"] { color: #9f2920; background: #fde7e5; }
            QLabel#statusBadge[state="loading"] { color: #725400; background: #fff3cd; }
            QTableWidget { background: white; alternate-background-color: #f7f9fa; border: 1px solid #e4e8ec; border-radius: 5px; selection-background-color: #dcecff; selection-color: #17202a; }
            QHeaderView::section { background: #eef2f5; color: #46515a; border: none; border-bottom: 1px solid #d8dee3; padding: 7px; font-size: 11px; font-weight: 600; }
            QPushButton { background: white; border: 1px solid #c9d1d8; border-radius: 6px; padding: 7px 13px; }
            QPushButton:hover { background: #eef3f7; }
            QPushButton#primaryButton { background: #1769aa; border-color: #1769aa; color: white; }
            QPushButton:disabled { background: #e1e5e8; border-color: #e1e5e8; color: #89939b; }
            """
        )
