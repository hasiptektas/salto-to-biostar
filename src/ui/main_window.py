from datetime import datetime

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
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
from ui.background_task import BackgroundTask
from storage.activity_log import ActivityLog


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SALTO - BioStar Senkronizasyon")
        self.resize(1280, 720)
        self.setMinimumSize(980, 580)
        self._salto_connection_string: str | None = None
        self._biostar_client: BioStarClient | None = None
        self._activity_log = ActivityLog()
        self._thread_pool = QThreadPool.globalInstance()
        self._background_tasks: set[BackgroundTask] = set()
        self._user_groups_loaded = False
        self._operation_in_progress = False
        self._last_salto_load_ok = False
        self._automation_timer = QTimer(self)
        self._automation_timer.timeout.connect(self._run_automatic_sync)

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
        biostar_settings_button = QPushButton("BioStar ayarları")
        biostar_settings_button.clicked.connect(self._open_biostar_settings)

        top_bar = QHBoxLayout()
        top_bar.addLayout(heading)
        top_bar.addStretch()
        top_bar.addWidget(settings_button)
        top_bar.addWidget(biostar_settings_button)

        self.salto_status_label = QLabel("Bağlı değil")
        self.salto_status_label.setObjectName("statusBadge")
        self.load_salto_button = QPushButton("Yenile")
        self.load_salto_button.setEnabled(False)
        self.load_salto_button.clicked.connect(lambda: self._load_salto_cards())
        self.copy_salto_button = QPushButton("Listeyi kopyala")
        self.copy_salto_button.clicked.connect(self._copy_salto_table)
        self.salto_table = self._create_table(
            [
                "Oda", "Beklenen Kart", "Kart Sırası", "Kart CSN", "BioStar Kart ID (26-bit)",
                "H10301", "Veriliş", "Başlangıç", "Bitiş", "Tür", "Kontrol",
            ]
        )
        self.salto_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._salto_copy_shortcut = QShortcut(QKeySequence.StandardKey.Copy, self.salto_table)
        self._salto_copy_shortcut.activated.connect(lambda: self._copy_salto_table(selected_only=True))
        salto_panel = self._create_panel(
            "SALTO bağlantısı",
            self.salto_status_label,
            [self.copy_salto_button, self.load_salto_button],
            self.salto_table,
        )

        self.biostar_status_label = QLabel("Bağlı değil")
        self.biostar_status_label.setObjectName("statusBadge")
        self.biostar_group_filter = QComboBox()
        self.biostar_group_filter.setMinimumWidth(150)
        self.biostar_group_filter.addItem("Tüm kullanıcılar", "")
        self.biostar_group_filter.currentIndexChanged.connect(self._filter_biostar_users_by_group)
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
            [self.biostar_group_filter, self.delete_biostar_user_button, self.biostar_refresh_button],
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
        self.sync_interval_input = QComboBox()
        self.sync_interval_input.addItem("1 dakika", 1)
        self.sync_interval_input.addItem("5 dakika", 5)
        self.sync_interval_input.setCurrentIndex(1)
        self.start_automation_button = QPushButton("Otomasyonu başlat")
        self.start_automation_button.setEnabled(False)
        self.start_automation_button.clicked.connect(self._start_automation)
        self.stop_automation_button = QPushButton("Durdur")
        self.stop_automation_button.setEnabled(False)
        self.stop_automation_button.clicked.connect(self._stop_automation)
        actions.addWidget(QLabel("Kontrol aralığı:"))
        actions.addWidget(self.sync_interval_input)
        actions.addWidget(self.start_automation_button)
        actions.addWidget(self.stop_automation_button)
        actions.addStretch()
        actions.addWidget(self.manual_transfer_button)
        actions.addWidget(self.room_transfer_button)
        actions.addWidget(self.all_rooms_transfer_button)

        sync_layout = QVBoxLayout()
        sync_layout.setContentsMargins(0, 0, 0, 0)
        sync_layout.addLayout(lists, 1)
        sync_layout.addLayout(actions)
        sync_page = QWidget()
        sync_page.setLayout(sync_layout)

        self.user_groups_table = self._create_table(["Grup ID", "Kullanıcı grubu"])
        self.user_groups_table.cellClicked.connect(self._load_selected_group_users)
        self.group_users_table = self._create_table(
            ["Kullanıcı ID", "Ad", "Kart", "Başlangıç", "Bitiş", "Durum"]
        )
        self.group_target_input = QComboBox()
        self.move_group_user_button = QPushButton("Seçili kullanıcıyı gruba taşı")
        self.move_group_user_button.clicked.connect(self._move_selected_user_to_group)
        self.refresh_groups_button = QPushButton("Grupları yenile")
        self.refresh_groups_button.clicked.connect(self._load_user_groups)
        group_actions = QHBoxLayout()
        group_actions.addWidget(QLabel("Hedef grup:"))
        group_actions.addWidget(self.group_target_input, 1)
        group_actions.addWidget(self.move_group_user_button)
        group_actions.addWidget(self.refresh_groups_button)
        group_lists = QHBoxLayout()
        group_lists.setSpacing(14)
        group_lists.addWidget(self.user_groups_table, 1)
        group_lists.addWidget(self.group_users_table, 2)
        group_layout = QVBoxLayout()
        group_layout.setContentsMargins(0, 0, 0, 0)
        group_layout.addWidget(QLabel(
            "Soldan grubu seçin; sağda grubun kullanıcılarını görün ve gerekirse hedef gruba taşıyın."
        ))
        group_layout.addLayout(group_lists, 1)
        group_layout.addLayout(group_actions)
        group_page = QWidget()
        group_page.setLayout(group_layout)

        self.verification_table = self._create_table(
            [
                "Oda", "SALTO Kart ID'leri", "BioStar Kullanıcı ID", "BioStar Kart ID'leri",
                "Kart Sayısı", "Bitiş", "Gruplar", "Sonuç",
            ]
        )
        self.verify_button = QPushButton("Şimdi doğrula")
        self.verify_button.setObjectName("primaryButton")
        self.verify_button.clicked.connect(self._verify_salto_biostar)
        self.verification_summary = QLabel("Henüz doğrulama yapılmadı.")
        verify_actions = QHBoxLayout()
        verify_actions.addWidget(self.verification_summary)
        verify_actions.addStretch()
        verify_actions.addWidget(self.verify_button)
        verify_layout = QVBoxLayout()
        verify_layout.setContentsMargins(0, 0, 0, 0)
        verify_layout.addWidget(QLabel(
            "SALTO ve BioStar kayıtlarını değiştirmeden; oda, kart ve grup seviyesinde karşılaştırır."
        ))
        verify_layout.addWidget(self.verification_table, 1)
        verify_layout.addLayout(verify_actions)
        verify_page = QWidget()
        verify_page.setLayout(verify_layout)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_view.setPlainText(self._activity_log.read_tail())
        self.refresh_log_button = QPushButton("Günlüğü yenile")
        self.refresh_log_button.clicked.connect(self._refresh_log_view)
        self.clear_log_view_button = QPushButton("Görünümü temizle")
        self.clear_log_view_button.clicked.connect(self.log_view.clear)
        self.clear_log_file_button = QPushButton("Günlük dosyasını temizle")
        self.clear_log_file_button.clicked.connect(self._clear_log_file)
        log_actions = QHBoxLayout()
        log_actions.addWidget(QLabel("Son 1000 kayıt gösteriliyor."))
        log_actions.addStretch()
        log_actions.addWidget(self.clear_log_view_button)
        log_actions.addWidget(self.clear_log_file_button)
        log_actions.addWidget(self.refresh_log_button)
        log_layout = QVBoxLayout()
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.addWidget(self.log_view, 1)
        log_layout.addLayout(log_actions)
        log_page = QWidget()
        log_page.setLayout(log_layout)

        self.unassigned_cards_table = self._create_table(
            ["Dahili ID", "Kart ID", "Görünen ID", "Kart türü", "Wiegand formatı"]
        )
        self.refresh_unassigned_button = QPushButton("Sahipsiz kartları yenile")
        self.refresh_unassigned_button.clicked.connect(self._load_unassigned_cards)
        self.delete_unassigned_button = QPushButton("Seçili sahipsiz kartı sil")
        self.delete_unassigned_button.clicked.connect(self._delete_selected_unassigned_card)
        orphan_actions = QHBoxLayout()
        orphan_actions.addWidget(QLabel("Silme yalnızca seçili karta ve kullanıcı onayına uygulanır."))
        orphan_actions.addStretch()
        orphan_actions.addWidget(self.refresh_unassigned_button)
        orphan_actions.addWidget(self.delete_unassigned_button)
        orphan_layout = QVBoxLayout()
        orphan_layout.setContentsMargins(0, 0, 0, 0)
        orphan_layout.addWidget(self.unassigned_cards_table, 1)
        orphan_layout.addLayout(orphan_actions)
        orphan_page = QWidget()
        orphan_page.setLayout(orphan_layout)

        self.salto_mismatch_table = self._create_table(
            ["Room ID", "Oda", "Durum", "Beklenen", "Bulunan", "Fark", "Başlangıç", "Bitiş"]
        )
        self.refresh_salto_mismatch_button = QPushButton("Kart farklarını yenile")
        self.refresh_salto_mismatch_button.clicked.connect(self._load_salto_card_mismatches)
        mismatch_actions = QHBoxLayout()
        mismatch_actions.addWidget(QLabel("Aktif odalarda beklenen ve bulunan kart sayısı farkları."))
        mismatch_actions.addStretch()
        mismatch_actions.addWidget(self.refresh_salto_mismatch_button)
        mismatch_layout = QVBoxLayout()
        mismatch_layout.setContentsMargins(0, 0, 0, 0)
        mismatch_layout.addWidget(self.salto_mismatch_table, 1)
        mismatch_layout.addLayout(mismatch_actions)
        mismatch_page = QWidget()
        mismatch_page.setLayout(mismatch_layout)

        self.room_detail_input = QLineEdit()
        self.room_detail_input.setPlaceholderText("Oda numarası, örn. 3107")
        self.room_detail_input.setMaximumWidth(220)
        self.room_detail_input.returnPressed.connect(self._load_salto_room_detail)
        self.load_room_detail_button = QPushButton("Odayı sorgula")
        self.load_room_detail_button.clicked.connect(self._load_salto_room_detail)
        self.room_detail_table = self._create_table(
            [
                "Room ID", "Oda", "User CopyCount", "Beklenen", "Başlangıç", "Bitiş",
                "Kart CSN", "Kart CopyCount", "Veriliş", "Kart durumu",
            ]
        )
        room_detail_actions = QHBoxLayout()
        room_detail_actions.addWidget(QLabel("Oda:"))
        room_detail_actions.addWidget(self.room_detail_input)
        room_detail_actions.addWidget(self.load_room_detail_button)
        room_detail_actions.addStretch()
        room_detail_layout = QVBoxLayout()
        room_detail_layout.setContentsMargins(0, 0, 0, 0)
        room_detail_layout.addLayout(room_detail_actions)
        room_detail_layout.addWidget(self.room_detail_table, 1)
        room_detail_page = QWidget()
        room_detail_page.setLayout(room_detail_layout)

        tabs = QTabWidget()
        tabs.addTab(sync_page, "Senkronizasyon")
        tabs.addTab(verify_page, "Doğrulama")
        tabs.addTab(group_page, "Kullanıcı Grupları")
        tabs.addTab(mismatch_page, "Eksik/Fazla Kartlar")
        tabs.addTab(room_detail_page, "Oda Kart Detayı")
        tabs.addTab(orphan_page, "Sahipsiz Kartlar")
        tabs.addTab(log_page, "İşlem Günlüğü")

        content = QVBoxLayout()
        content.setContentsMargins(22, 18, 22, 14)
        content.setSpacing(14)
        content.addLayout(top_bar)
        content.addWidget(tabs, 1)

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
        action: QWidget | list[QWidget] | None,
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
        self._user_groups_loaded = False
        self._load_biostar_users()

    def _load_biostar_users(self, show_error: bool = True, group_id: str | None = None) -> None:
        if not self._biostar_client:
            return
        self._set_biostar_status("Yükleniyor…", None)
        self.biostar_refresh_button.setEnabled(False)
        client = self._biostar_client
        selected_group_id = (
            str(self.biostar_group_filter.currentData() or "")
            if group_id is None else str(group_id)
        )

        def success(users) -> None:
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
            group_suffix = f" · {self.biostar_group_filter.currentText()}" if selected_group_id else ""
            self._set_biostar_status(f"{len(users)} kullanıcı{group_suffix}", True)
            self.manual_transfer_button.setEnabled(bool(self._salto_connection_string))
            self.room_transfer_button.setEnabled(bool(self._salto_connection_string))
            self.all_rooms_transfer_button.setEnabled(bool(self._salto_connection_string))
            self.biostar_refresh_button.setEnabled(True)
            self._update_delete_button()
            self.statusBar().showMessage("BioStar kullanıcı listesi güncellendi.", 5000)
            self._log_event("INFO", f"BioStar kullanıcı listesi yenilendi: {len(users)} kullanıcı.")
            self.start_automation_button.setEnabled(bool(self._salto_connection_string))
            if not self._user_groups_loaded:
                self._load_user_groups(show_error=False)

        def failure(error: Exception) -> None:
            self._set_biostar_status("Bağlantı hatası", False)
            self._log_event("ERROR", f"BioStar kullanıcı listesi alınamadı: {error}")
            if show_error:
                QMessageBox.critical(self, "BioStar liste hatası", str(error))

        def finished() -> None:
            self.biostar_refresh_button.setEnabled(self._biostar_client is not None)

        self._start_background_task(
            lambda: client.list_users(selected_group_id or None),
            lambda users: (success(users), finished()),
            lambda error: (failure(error), finished()),
        )

    def _load_user_groups(self, show_error: bool = True) -> None:
        if not self._biostar_client:
            return
        client = self._biostar_client
        self.refresh_groups_button.setEnabled(False)

        def success(groups) -> None:
            self.user_groups_table.setRowCount(len(groups))
            previous_target = str(self.group_target_input.currentData() or "")
            self.group_target_input.clear()
            for row, group in enumerate(groups):
                group_id = str(group.get("id", ""))
                group_name = str(group.get("name", group_id))
                self.user_groups_table.setItem(row, 0, QTableWidgetItem(group_id))
                self.user_groups_table.setItem(row, 1, QTableWidgetItem(group_name))
                self.group_target_input.addItem(group_name, group_id)
            target_index = self.group_target_input.findData(previous_target)
            if target_index >= 0:
                self.group_target_input.setCurrentIndex(target_index)
            previous_filter = str(self.biostar_group_filter.currentData() or "")
            preferred_filter = previous_filter or BioStarSettingsStore().load().user_group_id
            self.biostar_group_filter.blockSignals(True)
            self.biostar_group_filter.clear()
            self.biostar_group_filter.addItem("Tüm kullanıcılar", "")
            for group in groups:
                group_id = str(group.get("id", ""))
                if group_id:
                    self.biostar_group_filter.addItem(str(group.get("name", group_id)), group_id)
            filter_index = self.biostar_group_filter.findData(preferred_filter)
            self.biostar_group_filter.setCurrentIndex(filter_index if filter_index >= 0 else 0)
            self.biostar_group_filter.blockSignals(False)
            self._user_groups_loaded = True
            if str(self.biostar_group_filter.currentData() or ""):
                self._load_biostar_users(group_id=str(self.biostar_group_filter.currentData()))

        def failure(error: Exception) -> None:
            if show_error:
                QMessageBox.critical(self, "Kullanıcı grupları hatası", str(error))

        def finished() -> None:
            self.refresh_groups_button.setEnabled(self._biostar_client is not None)

        self._start_background_task(
            client.list_user_groups,
            lambda groups: (success(groups), finished()),
            lambda error: (failure(error), finished()),
        )

    def _filter_biostar_users_by_group(self, _index: int) -> None:
        if self._user_groups_loaded:
            self._load_biostar_users(group_id=str(self.biostar_group_filter.currentData() or ""))

    def _load_selected_group_users(self, row: int, _column: int = 0) -> None:
        if not self._biostar_client:
            return
        group_item = self.user_groups_table.item(row, 0)
        if not group_item:
            return
        try:
            users = self._biostar_client.list_users(group_item.text())
            self.group_users_table.setRowCount(len(users))
            for user_row, user in enumerate(users):
                values = (
                    user.user_id, user.name, str(user.card_count), user.start_datetime,
                    user.expiry_datetime, "Pasif" if user.disabled else "Aktif",
                )
                for column, value in enumerate(values):
                    self.group_users_table.setItem(user_row, column, QTableWidgetItem(value))
        except Exception as error:
            QMessageBox.critical(self, "Grup kullanıcıları hatası", str(error))

    def _move_selected_user_to_group(self) -> None:
        row = self.group_users_table.currentRow()
        target_group_id = str(self.group_target_input.currentData() or "")
        if row < 0 or not target_group_id or not self._biostar_client:
            QMessageBox.warning(self, "Seçim gerekli", "Bir kullanıcı ve hedef grup seçin.")
            return
        user_id = self.group_users_table.item(row, 0).text()
        user_name = self.group_users_table.item(row, 1).text()
        target_name = self.group_target_input.currentText()
        answer = QMessageBox.question(
            self, "Kullanıcı grubunu değiştir",
            f"{user_id} — {user_name}\nHedef grup: {target_name}\n\nDevam edilsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not self._begin_operation("Kullanıcı grubu değiştirme"):
            return
        try:
            self._biostar_client.move_user_to_group(user_id, target_group_id)
            QMessageBox.information(self, "Grup değiştirildi", f"{user_name}, {target_name} grubuna taşındı.")
            self._log_event("INFO", f"BioStar kullanıcısı gruba taşındı: {user_id} — {user_name} → {target_name}.")
            selected_group_row = self.user_groups_table.currentRow()
            if selected_group_row >= 0:
                self._load_selected_group_users(selected_group_row)
            self._load_biostar_users()
        except Exception as error:
            self._log_event("ERROR", f"Kullanıcı grubu değiştirilemedi: {error}")
            QMessageBox.critical(self, "Grup değiştirme hatası", str(error))
        finally:
            self._end_operation()

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
        if not self._begin_operation("BioStar kullanıcı silme"):
            return
        try:
            self._biostar_client.delete_user(user_id)
            self._log_event("DELETE", f"BioStar kullanıcısı manuel silindi: {user_id} — {name}.")
            QMessageBox.information(self, "Silme başarılı", f"{user_id} — {name} BioStar'dan silindi.")
            self._load_biostar_users()
        except Exception as error:
            self._log_event("ERROR", f"BioStar kullanıcısı silinemedi ({user_id}): {error}")
            QMessageBox.critical(self, "Kullanıcı silme hatası", str(error))
        finally:
            self._end_operation()

    def _set_biostar_status(self, text: str, success: bool | None) -> None:
        self.biostar_status_label.setText(text)
        state = "success" if success is True else "error" if success is False else "loading"
        self.biostar_status_label.setProperty("state", state)
        self.biostar_status_label.style().unpolish(self.biostar_status_label)
        self.biostar_status_label.style().polish(self.biostar_status_label)

    def _log_event(self, level: str, message: str) -> None:
        line = self._activity_log.write(level, message)
        if hasattr(self, "log_view"):
            self.log_view.appendPlainText(line)
            scrollbar = self.log_view.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _refresh_log_view(self) -> None:
        self.log_view.setPlainText(self._activity_log.read_tail())
        scrollbar = self.log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _clear_log_file(self) -> None:
        answer = QMessageBox.warning(
            self, "Günlük dosyasını temizle",
            "Kalıcı işlem günlüğündeki bütün kayıtlar silinecek. Devam edilsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._activity_log.clear()
            self.log_view.clear()
            self.statusBar().showMessage("İşlem günlüğü temizlendi.", 5000)

    def _begin_operation(self, name: str, silent: bool = False) -> bool:
        if self._operation_in_progress:
            if not silent:
                QMessageBox.information(
                    self, "İşlem devam ediyor",
                    "Başka bir aktarım, doğrulama veya silme işlemi tamamlanmadan yeni işlem başlatılamaz.",
                )
            return False
        self._operation_in_progress = True
        self.statusBar().showMessage(f"{name} devam ediyor…")
        for button in (
            self.manual_transfer_button, self.room_transfer_button,
            self.all_rooms_transfer_button, self.verify_button,
            self.delete_biostar_user_button, self.move_group_user_button,
            self.delete_unassigned_button,
        ):
            button.setEnabled(False)
        self.biostar_refresh_button.setEnabled(False)
        self.load_salto_button.setEnabled(False)
        self.refresh_groups_button.setEnabled(False)
        return True

    def _end_operation(self) -> None:
        self._operation_in_progress = False
        self.manual_transfer_button.setEnabled(self._biostar_client is not None)
        self.room_transfer_button.setEnabled(self._biostar_client is not None)
        self.all_rooms_transfer_button.setEnabled(self._biostar_client is not None)
        self.verify_button.setEnabled(True)
        self.move_group_user_button.setEnabled(True)
        self.delete_unassigned_button.setEnabled(True)
        self.biostar_refresh_button.setEnabled(self._biostar_client is not None)
        self.load_salto_button.setEnabled(self._salto_connection_string is not None)
        self.refresh_groups_button.setEnabled(self._biostar_client is not None)
        self._update_delete_button()

    def _load_unassigned_cards(self) -> None:
        if not self._biostar_client:
            return
        self.refresh_unassigned_button.setEnabled(False)
        client = self._biostar_client

        def success(cards) -> None:
            self.unassigned_cards_table.setRowCount(len(cards))
            for row, card in enumerate(cards):
                card_type = card.get("card_type", {}) or {}
                wiegand = card.get("wiegand_format_id", {}) or {}
                values = (
                    str(card.get("id", "")), str(card.get("card_id", "")),
                    str(card.get("display_card_id", "")),
                    str(card_type.get("name", card_type.get("id", ""))) if isinstance(card_type, dict) else str(card_type),
                    str(wiegand.get("name", wiegand.get("id", ""))) if isinstance(wiegand, dict) else str(wiegand),
                )
                for column, value in enumerate(values):
                    self.unassigned_cards_table.setItem(row, column, QTableWidgetItem(value))
            self._log_event("INFO", f"Sahipsiz kart listesi yenilendi: {len(cards)} kart.")

        def failure(error) -> None:
            self._log_event("ERROR", f"Sahipsiz kart listesi alınamadı: {error}")
            QMessageBox.critical(self, "Sahipsiz kart hatası", str(error))

        def finished() -> None:
            self.refresh_unassigned_button.setEnabled(True)

        self._start_background_task(
            client.list_unassigned_cards,
            lambda cards: (success(cards), finished()),
            lambda error: (failure(error), finished()),
        )

    def _delete_selected_unassigned_card(self) -> None:
        row = self.unassigned_cards_table.currentRow()
        if row < 0 or not self._biostar_client:
            QMessageBox.warning(self, "Seçim gerekli", "Silinecek sahipsiz kartı seçin.")
            return
        internal_id = self.unassigned_cards_table.item(row, 0).text()
        card_id = self.unassigned_cards_table.item(row, 1).text()
        answer = QMessageBox.warning(
            self, "Sahipsiz kartı sil",
            f"Dahili ID: {internal_id}\nKart ID: {card_id}\n\n"
            "Kart BioStar veritabanından kalıcı olarak silinecek. Devam edilsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes or not self._begin_operation("Sahipsiz kart silme"):
            return
        try:
            self._biostar_client.delete_unassigned_card(internal_id)
            self._log_event("DELETE", f"Sahipsiz kart silindi: dahili={internal_id}, kart={card_id}.")
            QMessageBox.information(self, "Kart silindi", f"{card_id} kartı silindi.")
            self._load_unassigned_cards()
        except Exception as error:
            self._log_event("ERROR", f"Sahipsiz kart silinemedi ({card_id}): {error}")
            QMessageBox.critical(self, "Kart silme hatası", str(error))
        finally:
            self._end_operation()

    def _start_background_task(self, function, on_success, on_error) -> None:
        task = BackgroundTask(function)
        self._background_tasks.add(task)
        task.signals.succeeded.connect(on_success)
        task.signals.failed.connect(on_error)
        task.signals.completed.connect(lambda: self._background_tasks.discard(task))
        self._thread_pool.start(task)

    def _copy_salto_table(self, selected_only: bool = False) -> None:
        if self.salto_table.rowCount() == 0:
            QMessageBox.information(self, "Kopyalanacak veri yok", "SALTO listesi henüz boş.")
            return
        if selected_only:
            rows = sorted(index.row() for index in self.salto_table.selectionModel().selectedRows())
            if not rows:
                return
        else:
            rows = list(range(self.salto_table.rowCount()))
        headers = [
            self.salto_table.horizontalHeaderItem(column).text()
            for column in range(self.salto_table.columnCount())
        ]
        lines = ["\t".join(headers)]
        for row in rows:
            values = [
                self.salto_table.item(row, column).text()
                if self.salto_table.item(row, column) else ""
                for column in range(self.salto_table.columnCount())
            ]
            lines.append("\t".join(values))
        QApplication.clipboard().setText("\n".join(lines))
        self.statusBar().showMessage(f"{len(rows)} SALTO satırı panoya kopyalandı.", 5000)

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

    def _load_salto_cards(self, show_error: bool = True, on_complete=None) -> None:
        if not self._salto_connection_string:
            if on_complete:
                on_complete(False)
            return
        self.load_salto_button.setEnabled(False)
        self._set_salto_status("Yükleniyor…", None)
        self.statusBar().showMessage("SALTO kartları getiriliyor…")
        connection_string = self._salto_connection_string

        def success(cards) -> None:
            actual_counts: dict[int, int] = {}
            expected_counts: dict[int, int] = {}
            converted_owners: dict[int, list[tuple[str, str]]] = {}
            for card in cards:
                actual_counts[card.room_user_id] = actual_counts.get(card.room_user_id, 0) + 1
                expected_counts[card.room_user_id] = card.number_of_keys
                try:
                    converted_id = convert_salto_rom_to_wiegand26(card.card_csn).card_id
                    converted_owners.setdefault(converted_id, []).append(
                        (card.room_number, card.card_csn)
                    )
                except ValueError:
                    pass
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
                actual_count = actual_counts[card.room_user_id]
                expected_count = card.number_of_keys
                if actual_count == expected_count:
                    check_text = f"Tam {actual_count}/{expected_count}"
                    check_color = QColor("#dff5e9")
                elif actual_count < expected_count:
                    check_text = f"Eksik {actual_count}/{expected_count}"
                    check_color = QColor("#fde7e5")
                else:
                    check_text = f"Fazla {actual_count}/{expected_count}"
                    check_color = QColor("#fff3cd")
                if biostar_id.isdigit():
                    collision_entries = converted_owners.get(int(biostar_id), [])
                    collision_rooms = sorted({owner_room for owner_room, _ in collision_entries})
                    collision_csns = {owner_csn for _, owner_csn in collision_entries}
                    if len(collision_csns) > 1:
                        check_text = "26-bit çakışma: " + ", ".join(collision_rooms)
                        check_color = QColor("#fde7e5")
                sequence_text = (
                    f"Ana (1/{expected_count})"
                    if card.key_copy_number == 0
                    else f"Kopya {card.key_copy_number} ({card.key_copy_number + 1}/{expected_count})"
                )
                values = (
                    card.room_number,
                    str(card.number_of_keys),
                    sequence_text,
                    card.card_csn,
                    biostar_id,
                    h10301,
                    self._format_datetime(card.issued_date),
                    self._format_datetime(card.activation_date),
                    self._format_datetime(card.expiration_date),
                    "Ana" if card.card_role == "PRIMARY" else "Kopya",
                    check_text,
                )
                row_has_problem = not check_text.startswith("Tam ")
                for column_index, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if column_index == 0:
                        item.setData(Qt.ItemDataRole.UserRole, card.room_user_id)
                    if row_has_problem or column_index == 10:
                        item.setBackground(check_color)
                    self.salto_table.setItem(row_index, column_index, item)
            self.salto_table.setSortingEnabled(True)
            room_count = len({card.room_user_id for card in cards})
            problem_room_ids = {
                room_user_id for room_user_id, actual in actual_counts.items()
                if actual != expected_counts[room_user_id]
            }
            collision_room_names = {
                room
                for entries in converted_owners.values()
                if len({csn for _, csn in entries}) > 1
                for room, _ in entries
            }
            problem_room_ids.update(
                card.room_user_id for card in cards if card.room_number in collision_room_names
            )
            problem_rooms = len(problem_room_ids)
            status_text = f"{room_count} oda · {len(cards)} kart"
            if problem_rooms:
                status_text += f" · {problem_rooms} sorunlu oda"
            self._set_salto_status(status_text, problem_rooms == 0)
            self._last_salto_load_ok = True
            self.manual_transfer_button.setEnabled(self._biostar_client is not None)
            self.room_transfer_button.setEnabled(self._biostar_client is not None)
            self.all_rooms_transfer_button.setEnabled(self._biostar_client is not None)
            self.start_automation_button.setEnabled(self._biostar_client is not None)
            self.statusBar().showMessage("SALTO listesi güncellendi.", 5000)
            self._log_event("INFO", f"SALTO listesi yenilendi: {room_count} oda, {len(cards)} kart.")
            if on_complete:
                on_complete(True)

        def failure(error: Exception) -> None:
            self._last_salto_load_ok = False
            self._log_event("ERROR", f"SALTO listesi alınamadı: {error}")
            self._set_salto_status("Bağlantı hatası", False)
            self.statusBar().showMessage("SALTO listesi alınamadı.", 5000)
            if show_error:
                QMessageBox.critical(self, "SALTO sorgu hatası", str(error))
            if on_complete:
                on_complete(False)

        def finished() -> None:
            self.load_salto_button.setEnabled(True)

        self._start_background_task(
            lambda: SaltoRepository(connection_string).fetch_active_hotel_cards(),
            lambda cards: (success(cards), finished()),
            lambda error: (failure(error), finished()),
        )

    def _set_salto_status(self, text: str, success: bool | None) -> None:
        self.salto_status_label.setText(text)
        state = "success" if success is True else "error" if success is False else "loading"
        self.salto_status_label.setProperty("state", state)
        self.salto_status_label.style().unpolish(self.salto_status_label)
        self.salto_status_label.style().polish(self.salto_status_label)

    def _load_salto_card_mismatches(self) -> None:
        if not self._salto_connection_string:
            QMessageBox.warning(self, "SALTO bağlantısı", "Önce SALTO bağlantısını kurun.")
            return
        self.refresh_salto_mismatch_button.setEnabled(False)
        repository = SaltoRepository(self._salto_connection_string)

        def success(rows) -> None:
            self.salto_mismatch_table.setRowCount(len(rows))
            for row_index, row in enumerate(rows):
                expected, found = int(row[3]), int(row[4])
                values = (
                    row[0], row[1], row[2], expected, found, found - expected,
                    self._format_datetime(row[5]), self._format_datetime(row[6]),
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if column in {3, 4, 5}:
                        item.setBackground(QColor("#fde7e5"))
                    self.salto_mismatch_table.setItem(row_index, column, item)
            self._log_event("INFO", f"SALTO kart farkları sorgulandı: {len(rows)} oda.")
            self.statusBar().showMessage(f"{len(rows)} kart sayısı farkı bulundu.", 5000)

        def failure(error) -> None:
            self._log_event("ERROR", f"SALTO kart farkları alınamadı: {error}")
            QMessageBox.critical(self, "SALTO kart farkı hatası", str(error))

        def finished() -> None:
            self.refresh_salto_mismatch_button.setEnabled(True)

        self._start_background_task(
            repository.fetch_card_count_mismatches,
            lambda rows: (success(rows), finished()),
            lambda error: (failure(error), finished()),
        )

    def _load_salto_room_detail(self) -> None:
        room = self.room_detail_input.text().strip().lstrip("@").strip()
        if not self._salto_connection_string:
            QMessageBox.warning(self, "SALTO bağlantısı", "Önce SALTO bağlantısını kurun.")
            return
        if not room:
            QMessageBox.warning(self, "Oda gerekli", "Sorgulanacak oda numarasını yazın.")
            return
        self.load_room_detail_button.setEnabled(False)
        repository = SaltoRepository(self._salto_connection_string)

        def success(rows) -> None:
            self.room_detail_table.setRowCount(len(rows))
            for row_index, row in enumerate(rows):
                values = (
                    row[0], row[1], row[2], row[3], self._format_datetime(row[4]),
                    self._format_datetime(row[5]), row[6] or "-", row[7] if row[7] is not None else "-",
                    self._format_datetime(row[8]) if row[8] is not None else "-", row[9],
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if column == 9:
                        item.setBackground(QColor("#dff5e9" if value == "Güncel sorguya dahil" else "#fde7e5"))
                    self.room_detail_table.setItem(row_index, column, item)
            self._log_event("INFO", f"SALTO oda kart detayı sorgulandı: {room}, {len(rows)} kayıt.")
            if not rows:
                QMessageBox.information(self, "Oda bulunamadı", f"@{room} için kullanıcı kaydı bulunamadı.")

        def failure(error) -> None:
            self._log_event("ERROR", f"SALTO oda kart detayı alınamadı ({room}): {error}")
            QMessageBox.critical(self, "Oda kart detayı hatası", str(error))

        def finished() -> None:
            self.load_room_detail_button.setEnabled(True)

        self._start_background_task(
            lambda: repository.fetch_room_card_details(room),
            lambda rows: (success(rows), finished()),
            lambda error: (failure(error), finished()),
        )

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
        if not self._begin_operation("Manuel kart aktarımı"):
            return
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
            self._log_event(
                "SYNC", f"Kart manuel atandı: oda={room}, kullanıcı={target_user}, kart={converted.display_id}."
            )
            QMessageBox.information(
                self,
                "Aktarım başarılı",
                f"{converted.display_id} kartı {target_user} — {target_name} kullanıcısına atandı.",
            )
            self._load_biostar_users()
        except Exception as error:
            self._log_event("ERROR", f"Manuel kart aktarımı başarısız: {error}")
            QMessageBox.critical(self, "Manuel aktarım hatası", str(error))
        finally:
            self._end_operation()

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
        if not settings.user_group_id:
            QMessageBox.warning(
                self, "Kullanıcı grubu gerekli",
                "Önce BioStar Ayarlar bölümünden kullanıcı grubunu seçip kaydedin.",
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
            f"Kullanıcı grubu: {settings.user_group_name} (ID {settings.user_group_id})\n"
            f"Erişim grubu: {settings.access_group_name} (ID {settings.access_group_id})\n\n"
            f"Aktarılacak kartlar:\n{card_lines}\n\n"
            "Kullanıcı yoksa oluşturulacak, varsa güncellenecektir. Devam edilsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not self._begin_operation("Manuel oda aktarımı"):
            return
        try:
            result, biostar_user_id, card_count = self._execute_room_transfer(
                room_reference, converted_cards, activation, expiration,
                settings.access_group_id, settings.user_group_id,
            )
            verb = "oluşturuldu" if result == "created" else "güncellendi"
            self._log_event(
                "SYNC", f"Oda manuel aktarıldı: {room_reference}, BioStar ID={biostar_user_id}, kart={card_count}."
            )
            QMessageBox.information(
                self, "Oda aktarımı başarılı",
                f"{room_reference} kullanıcısı {verb}.\n"
                f"BioStar ID: {biostar_user_id}\n{card_count} kart işlendi.",
            )
            self._load_biostar_users()
        except Exception as error:
            self._log_event("ERROR", f"Manuel oda aktarımı başarısız: {room_reference}: {error}")
            QMessageBox.critical(self, "Oda aktarım hatası", str(error))
        finally:
            self._end_operation()

    def _execute_room_transfer(
        self,
        room_name: str,
        converted_cards: list[tuple[str, object]],
        activation: datetime,
        expiration: datetime,
        access_group_id: str,
        user_group_id: str,
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
                    owner = (
                        existing.get("user_id") or existing.get("user")
                        or existing.get("assigned_user_id") or "API sahibi belirtmedi"
                    )
                    if isinstance(owner, dict):
                        owner = owner.get("id") or owner.get("name") or str(owner)
                    raise RuntimeError(
                        f"{converted.display_id} kartı başka kullanıcıya atanmış "
                        f"(kart dahili ID={internal_id}, sahip={owner})."
                    )
            else:
                existing = self._biostar_client.create_wiegand26_card(converted.card_id)
                internal_id = str(existing["id"])
            internal_ids.append(internal_id)
        result, user_id = self._biostar_client.create_or_update_room_user(
            room_name, internal_ids, activation, expiration, access_group_id, user_group_id
        )
        return result, user_id, len(internal_ids)

    def _start_automation(self) -> None:
        settings = BioStarSettingsStore().load()
        if not self._biostar_client or not self._salto_connection_string:
            QMessageBox.warning(self, "Bağlantı gerekli", "SALTO ve BioStar bağlantıları kurulmalıdır.")
            return
        if not settings.user_group_id or not settings.access_group_id:
            QMessageBox.warning(
                self, "Grup seçimi gerekli",
                "BioStar Ayarlar bölümünden kullanıcı ve erişim grubunu seçin.",
            )
            return
        answer = QMessageBox.warning(
            self, "Otomasyonu başlat",
            f"Kullanıcı grubu: {settings.user_group_name}\n"
            f"Erişim grubu: {settings.access_group_name}\n"
            f"Aralık: {self.sync_interval_input.currentText()}\n\n"
            "Seçili kullanıcı grubunda olup SALTO'da aktif odası bulunmayan kullanıcılar silinecektir. "
            "Bu grup yalnızca SALTO odaları için kullanılmalıdır. Devam edilsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        interval_minutes = int(self.sync_interval_input.currentData())
        self._automation_timer.start(interval_minutes * 60_000)
        self._log_event(
            "START", f"Otomasyon başlatıldı: {interval_minutes} dk, "
            f"kullanıcı grubu={settings.user_group_name}, erişim grubu={settings.access_group_name}."
        )
        self.start_automation_button.setEnabled(False)
        self.stop_automation_button.setEnabled(True)
        self.sync_interval_input.setEnabled(False)
        self.statusBar().showMessage("Otomasyon çalışıyor; ilk kontrol başlatıldı.")
        QTimer.singleShot(0, self._run_automatic_sync)

    def _stop_automation(self) -> None:
        self._automation_timer.stop()
        self._log_event("STOP", "Otomasyon kullanıcı tarafından durduruldu.")
        self.start_automation_button.setEnabled(
            self._biostar_client is not None and self._salto_connection_string is not None
        )
        self.stop_automation_button.setEnabled(False)
        self.sync_interval_input.setEnabled(True)
        self.statusBar().showMessage("Otomasyon durduruldu.", 5000)

    def _run_automatic_sync(self) -> None:
        if self._operation_in_progress:
            self._log_event("WARN", "Otomatik kontrol atlandı: başka bir işlem devam ediyor.")
            return
        self.statusBar().showMessage("Otomatik kontrol: SALTO verileri yenileniyor…")

        def after_refresh(success: bool) -> None:
            if not success:
                self._log_event("ERROR", "Otomatik kontrol iptal edildi: SALTO okunamadı, silme yapılmadı.")
                self.statusBar().showMessage(
                    "Otomatik kontrol durdu: SALTO okunamadı; silme yapılmadı.", 10000
                )
                return
            self._transfer_all_rooms(automatic=True)

        self._load_salto_cards(show_error=False, on_complete=after_refresh)

    def _verify_salto_biostar(self) -> None:
        if not self._biostar_client or self.salto_table.rowCount() == 0:
            QMessageBox.warning(self, "Veri yok", "Önce SALTO ve BioStar listelerini yükleyin.")
            return
        settings = BioStarSettingsStore().load()
        if not settings.user_group_id or not settings.access_group_id:
            QMessageBox.warning(self, "Grup seçimi gerekli", "BioStar ayarlarından iki grubu da seçin.")
            return
        if not self._begin_operation("SALTO - BioStar doğrulaması"):
            return
        records = []
        for row in range(self.salto_table.rowCount()):
            records.append({
                "room": self.salto_table.item(row, 0).text(),
                "expected_count": int(self.salto_table.item(row, 1).text()),
                "csn": self.salto_table.item(row, 3).text().strip().upper(),
                "expiry": datetime.strptime(self.salto_table.item(row, 8).text(), "%d.%m.%Y %H:%M"),
            })
        client = self._biostar_client
        self.verification_summary.setText("Doğrulanıyor…")

        def work():
            def normalized_name(value: object) -> str:
                text = str(value or "").strip().lstrip("@&").strip().casefold()
                return str(int(text)) if text.isdigit() else text

            room_records = {}
            csn_owners = {}
            for record in records:
                room_records.setdefault(record["room"], []).append(record)
                csn_owners.setdefault(record["csn"], []).append(record["room"])
            all_users = client.list_users()
            managed_users = client.list_users(settings.user_group_id)
            # Bazı BioStar sürümleri /api/users genel listesini eksik veya
            # filtrelenmiş döndürebiliyor. Seçili grubun listesini de birleştir.
            users_by_id = {user.user_id: user for user in all_users}
            # Genel listedeki ad/tarih bilgisi daha dolu olabilir. Grup listesini
            # sadece genel listede bulunmayan ID'leri tamamlamak için kullan.
            for user in managed_users:
                current = users_by_id.get(user.user_id)
                if current is None or (not current.name.strip() and user.name.strip()):
                    users_by_id[user.user_id] = user
            users_by_name = {}
            for user in users_by_id.values():
                users_by_name.setdefault(normalized_name(user.name), []).append(user)
            results = []
            matched = set()
            unmatched_rooms = []
            for room, room_cards in room_records.items():
                csns = [item["csn"] for item in room_cards]
                expected_ids = [str(convert_salto_rom_to_wiegand26(csn).card_id) for csn in csns]
                expected_count = room_cards[0]["expected_count"]
                issues = []
                if len(csns) != len(set(csns)): issues.append("SALTO CSN tekrarı")
                if any(len(set(csn_owners[csn])) > 1 for csn in set(csns)): issues.append("CSN başka odada da var")
                if len(expected_ids) != len(set(expected_ids)): issues.append("26-bit ID çakışması")
                if len(set(csns)) != expected_count: issues.append(f"SALTO sayısı {len(set(csns))}/{expected_count}")
                matches = users_by_name.get(normalized_name(room), [])
                user_id, actual_ids, group_text, expiry_text = "-", [], "-", "-"
                if len(matches) != 1:
                    issues.append("Kullanıcı yok" if not matches else "Aynı adlı birden fazla kullanıcı")
                    if not matches:
                        unmatched_rooms.append(room)
                else:
                    user = matches[0]
                    user_id = user.user_id
                    matched.add(user_id)
                    detail = client.get_user_detail(user_id)
                    cards = detail.get("cards", [])
                    cards = cards.get("rows", []) if isinstance(cards, dict) else cards
                    actual_ids = sorted(str(card.get("card_id", "")) for card in cards if card.get("card_id") is not None)
                    expected_set, actual_set = set(expected_ids), set(actual_ids)
                    if expected_set - actual_set: issues.append("Kart eksik: " + ",".join(sorted(expected_set - actual_set)))
                    if actual_set - expected_set: issues.append("Kart fazla: " + ",".join(sorted(actual_set - expected_set)))
                    if len(actual_ids) != len(actual_set): issues.append("BioStar kart tekrarı")
                    group = detail.get("user_group_id", {}) or {}
                    user_group_ok = isinstance(group, dict) and str(group.get("id", "")) == settings.user_group_id
                    access = detail.get("access_groups", [])
                    access = access.get("rows", []) if isinstance(access, dict) and "rows" in access else access
                    if isinstance(access, dict): access = [access]
                    access_ok = settings.access_group_id in {str(item.get("id", "")) for item in access if isinstance(item, dict)}
                    group_text = f"K:{'✓' if user_group_ok else '✗'} E:{'✓' if access_ok else '✗'}"
                    if not user_group_ok: issues.append("Yanlış kullanıcı grubu")
                    if not access_ok: issues.append("Yanlış erişim grubu")
                    raw_expiry = str(detail.get("expiry_datetime", ""))
                    try:
                        bio_expiry = datetime.fromisoformat(raw_expiry.replace("Z", "+00:00")).replace(tzinfo=None)
                        expiry_ok = abs((bio_expiry - max(item["expiry"] for item in room_cards)).total_seconds()) < 60
                        expiry_text = f"{'✓' if expiry_ok else '✗'} {bio_expiry:%d.%m %H:%M}"
                        if not expiry_ok: issues.append("Bitiş tarihi farklı")
                    except ValueError:
                        expiry_text = raw_expiry or "-"
                        issues.append("Bitiş tarihi okunamadı")
                values = [room, ", ".join(sorted(set(expected_ids))), user_id,
                          ", ".join(sorted(set(actual_ids))) or "-",
                          f"{len(set(csns))}/{expected_count} → {len(set(actual_ids))}",
                          expiry_text, group_text, "TAM" if not issues else " · ".join(issues)]
                results.append((values, not issues))
            for user in managed_users:
                detail = client.get_user_detail(user.user_id)
                group = detail.get("user_group_id", {}) or {}
                if isinstance(group, dict) and str(group.get("id", "")) == settings.user_group_id and user.user_id not in matched:
                    results.append(([user.name, "-", user.user_id, "-", "-", user.expiry_datetime,
                                     "K:✓", "BioStar'da fazla kullanıcı"], False))
            return results, len(room_records), len(all_users), len(managed_users), unmatched_rooms

        def success(payload):
            results, room_count, all_user_count, managed_user_count, unmatched_rooms = payload
            self.verification_table.setRowCount(len(results))
            problems = 0
            for row, (values, ok) in enumerate(results):
                problems += int(not ok)
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if column == 7: item.setBackground(QColor("#dff5e9" if ok else "#fde7e5"))
                    self.verification_table.setItem(row, column, item)
            self.verification_summary.setText(
                f"{room_count} SALTO odası · {len(results) - room_count} fazla BioStar kullanıcısı · {problems} problem"
            )
            self._log_event("VERIFY", f"Doğrulama tamamlandı: {room_count} oda, {problems} problem.")
            self._log_event(
                "VERIFY",
                f"Eşleştirme kaynağı: genel={all_user_count}, seçili grup={managed_user_count} kullanıcı.",
            )
            if unmatched_rooms:
                self._log_event(
                    "WARN", "BioStar adıyla eşleşmeyen SALTO odaları: " + ", ".join(unmatched_rooms)
                )

        def failure(error):
            self.verification_summary.setText("Doğrulama başarısız.")
            self._log_event("ERROR", f"Doğrulama başarısız: {error}")
            QMessageBox.critical(self, "Doğrulama hatası", str(error))

        self._start_background_task(
            work,
            lambda result: (success(result), self._end_operation()),
            lambda error: (failure(error), self._end_operation()),
        )

    def _transfer_all_rooms(self, automatic: bool = False) -> None:
        if not self._biostar_client or self.salto_table.rowCount() == 0:
            if not automatic:
                QMessageBox.warning(self, "Veri yok", "Önce SALTO ve BioStar listelerini yükleyin.")
            return
        settings = BioStarSettingsStore().load()
        if not settings.access_group_id:
            QMessageBox.warning(
                self, "Erişim grubu gerekli",
                "Önce BioStar Ayarlar bölümünden erişim grubunu seçip kaydedin.",
            )
            return
        if not settings.user_group_id:
            QMessageBox.warning(
                self, "Kullanıcı grubu gerekli",
                "Önce BioStar Ayarlar bölümünden kullanıcı grubunu seçip kaydedin.",
            )
            return
        room_user_ids = list(dict.fromkeys(
            str(self.salto_table.item(row, 0).data(Qt.ItemDataRole.UserRole))
            for row in range(self.salto_table.rowCount())
        ))
        if not automatic:
            preview_rooms = []
            for room_user_id in room_user_ids[:25]:
                rows = [
                    row for row in range(self.salto_table.rowCount())
                    if str(self.salto_table.item(row, 0).data(Qt.ItemDataRole.UserRole)) == room_user_id
                ]
                if rows:
                    preview_rooms.append(
                        f"• {self.salto_table.item(rows[0], 0).text()}: {len(rows)} kart, "
                        f"bitiş {self.salto_table.item(rows[0], 8).text()}"
                    )
            preview = "\n".join(preview_rooms)
            if len(room_user_ids) > 25:
                preview += f"\n… ve {len(room_user_ids) - 25} oda daha"
            answer = QMessageBox.warning(
                self,
                "Tüm aktif odaları aktar",
                f"{len(room_user_ids)} aktif oda ve {self.salto_table.rowCount()} kart BioStar'a aktarılacak.\n"
                f"Kullanıcı grubu: {settings.user_group_name} (ID {settings.user_group_id})\n"
                f"Erişim grubu: {settings.access_group_name} (ID {settings.access_group_id})\n\n"
                f"İşlem önizlemesi:\n{preview}\n\n"
                "Seçili kullanıcı grubunda bulunup SALTO aktif oda listesinde olmayan sayısal oda "
                "kullanıcıları silinecek; kartları serbest bırakılacaktır. Aktif odalar oluşturulabilir "
                "veya güncellenebilir. Devam edilsin mi?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        if not self._begin_operation("Toplu senkronizasyon", silent=automatic):
            if automatic:
                self._log_event("WARN", "Otomatik kontrol atlandı: başka bir işlem devam ediyor.")
            return

        jobs = []
        try:
            for room_user_id in room_user_ids:
                rows = [
                    row for row in range(self.salto_table.rowCount())
                    if str(self.salto_table.item(row, 0).data(Qt.ItemDataRole.UserRole)) == room_user_id
                ]
                room = self.salto_table.item(rows[0], 0).text()
                salto_activation = min(
                    datetime.strptime(self.salto_table.item(row, 7).text(), "%d.%m.%Y %H:%M")
                    for row in rows
                )
                expiration = max(
                    datetime.strptime(self.salto_table.item(row, 8).text(), "%d.%m.%Y %H:%M")
                    for row in rows
                )
                activation = max(salto_activation, datetime.now().replace(second=0, microsecond=0))
                converted_cards = []
                for row in rows:
                    rom = self.salto_table.item(row, 3).text()
                    converted_cards.append((rom, convert_salto_rom_to_wiegand26(rom)))
                jobs.append((room, converted_cards, activation, expiration))
        except Exception as error:
            self._end_operation()
            QMessageBox.critical(self, "Aktarım hazırlama hatası", str(error))
            return

        client = self._biostar_client
        initial_missing_counts = BioStarSettingsStore().load_missing_counts()

        def work():
            successes = []
            errors = []
            deleted = []
            warnings = []
            missing_counts = dict(initial_missing_counts)
            active_rooms = {job[0].strip() for job in jobs}

            # Eski oda kullanıcılarını önce temizlemek, onların üzerinde
            # kalan kartları yeni odaya aktarımdan önce serbest bırakır.
            try:
                managed_users = client.list_users(settings.user_group_id)
                if managed_users and not active_rooms:
                    raise RuntimeError("SALTO aktif oda listesi boş; silme atlandı.")
                seen = set()
                for user in managed_users:
                    seen.add(user.user_id)
                    detail = client.get_user_detail(user.user_id)
                    group = detail.get("user_group_id", {}) or {}
                    exact_group = str(group.get("id", "")) if isinstance(group, dict) else ""
                    name = user.name.strip()
                    if exact_group != settings.user_group_id:
                        continue
                    if name in active_rooms:
                        missing_counts.pop(user.user_id, None)
                        continue
                    # Manuel misafir/ad kayıtlarını koru; yalnızca oda numarası
                    # biçimindeki ve seçili gruptaki kayıtlar otomatik yönetilir.
                    if not name.isdigit() or user.user_id == "1":
                        continue
                    missing_counts[user.user_id] = missing_counts.get(user.user_id, 0) + 1
                    should_delete = not automatic or missing_counts[user.user_id] >= 2
                    if should_delete:
                        client.delete_user(user.user_id)
                        deleted.append((user.user_id, name))
                        missing_counts.pop(user.user_id, None)
                    else:
                        warnings.append((user.user_id, name, missing_counts[user.user_id]))
                missing_counts = {key: value for key, value in missing_counts.items() if key in seen}
            except Exception as error:
                errors.append(("Temizlik", str(error)))

            failed_jobs = []
            for job in jobs:
                room, converted_cards, activation, expiration = job
                try:
                    if expiration <= activation:
                        raise RuntimeError("Çıkış zamanı geçmiş.")
                    result, user_id, card_count = self._execute_room_transfer(
                        room, converted_cards, activation, expiration,
                        settings.access_group_id, settings.user_group_id,
                    )
                    successes.append((room, user_id, card_count, result))
                except Exception as error:
                    failed_jobs.append((job, str(error)))

            # Aktif odalar arasında kart el değiştiriyorsa ilk turda eski sahibi
            # henüz güncellenmemiş olabilir. Başarısız odaları bir kez daha dene.
            for job, first_error in failed_jobs:
                room, converted_cards, activation, expiration = job
                try:
                    result, user_id, card_count = self._execute_room_transfer(
                        room, converted_cards, activation, expiration,
                        settings.access_group_id, settings.user_group_id,
                    )
                    successes.append((room, user_id, card_count, result))
                except Exception as retry_error:
                    errors.append((room, f"{retry_error} (ilk deneme: {first_error})"))
            return successes, errors, deleted, warnings, missing_counts

        def success(result) -> None:
            successes, errors, deleted, warnings, missing_counts = result
            BioStarSettingsStore().save_missing_counts(missing_counts)
            for room, user_id, card_count, _action in successes:
                self._log_event("SYNC", f"Oda aktarıldı/güncellendi: {room}, BioStar ID={user_id}, kart={card_count}.")
            for room, error in errors:
                self._log_event("ERROR", f"{room}: {error}")
            for user_id, name, count in warnings:
                self._log_event("WARN", f"SALTO'da bulunamadı: {user_id} — {name}; kontrol={count}/2.")
            for user_id, name in deleted:
                reason = "iki otomatik kontrolde bulunamadı" if automatic else "manuel toplu işlemde onaylandı"
                self._log_event("DELETE", f"Eski oda kullanıcısı silindi: {user_id} — {name}; {reason}.")
            summary = f"Başarılı: {len(successes)} · Silinen: {len(deleted)} · Hata: {len(errors)}"
            self._log_event("INFO", f"Senkronizasyon tamamlandı: {summary}.")
            if automatic:
                self.statusBar().showMessage(f"Otomatik kontrol tamamlandı. {summary}", 10000)
                if errors:
                    QMessageBox.warning(self, "Otomatik senkronizasyon hatası", summary)
            else:
                QMessageBox.information(self, "Toplu aktarım tamamlandı", summary)
            self._load_biostar_users(show_error=not automatic)

        def failure(error) -> None:
            self._log_event("ERROR", f"Toplu senkronizasyon görevi çöktü: {error}")
            QMessageBox.critical(self, "Toplu senkronizasyon hatası", str(error))

        def finished() -> None:
            self._end_operation()

        self._start_background_task(
            work,
            lambda result: (success(result), finished()),
            lambda error: (failure(error), finished()),
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
