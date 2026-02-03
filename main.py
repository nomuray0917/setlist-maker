import sys
import json
import datetime
import re
import os
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QHBoxLayout, QLabel, QLineEdit, QTextEdit,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QHeaderView, QMessageBox, QFileDialog, QAbstractItemView,
                               QInputDialog, QComboBox, QDialog, QListWidget,
                               QCheckBox, QDialogButtonBox)
from PySide6.QtGui import QAction, QKeySequence, QShortcut, QCloseEvent
from PySide6.QtCore import Qt, QSettings
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

# --- データ管理クラス ---
class SetlistItem:
  def __init__(self, title, description="", duration="", is_mc=False):
    self.title = title
    self.description = description
    self.duration = duration
    self.is_mc = is_mc

  def to_dict(self):
    return {
        "title": self.title,
        "description": self.description,
        "duration": self.duration,
        "is_mc": self.is_mc
    }

  @classmethod
  def from_dict(cls, data):
    return cls(
        title=data.get("title", ""),
        description=data.get("description", ""),
        duration=data.get("duration", ""),
        is_mc=data.get("is_mc", False)
    )

# --- バンド設定ダイアログ ---
class BandManagerDialog(QDialog):
  def __init__(self, parent=None, band_list=[]):
    super().__init__(parent)
    self.setWindowTitle("バンド管理設定")
    self.resize(300, 400)

    self.band_list = list(band_list)
    self.setup_ui()

  def setup_ui(self):
    layout = QVBoxLayout(self)

    layout.addWidget(QLabel("登録バンド一覧:"))
    self.list_widget = QListWidget()
    self.list_widget.addItems(self.band_list)
    layout.addWidget(self.list_widget)

    btn_layout = QHBoxLayout()
    add_btn = QPushButton("追加")
    add_btn.clicked.connect(self.add_band)
    del_btn = QPushButton("削除")
    del_btn.clicked.connect(self.del_band)
    btn_layout.addWidget(add_btn)
    btn_layout.addWidget(del_btn)
    layout.addLayout(btn_layout)

    button_box = QDialogButtonBox(
        QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    button_box.accepted.connect(self.accept)
    button_box.rejected.connect(self.reject)
    layout.addWidget(button_box)

  def add_band(self):
    name, ok = QInputDialog.getText(self, "バンド追加", "バンド名を入力:")
    if ok and name:
      if name not in self.band_list:
        self.band_list.append(name)
        self.list_widget.addItem(name)

  def del_band(self):
    row = self.list_widget.currentRow()
    if row >= 0:
      name = self.list_widget.item(row).text()
      if QMessageBox.question(self, "確認", f"「{name}」を削除しますか？", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
        self.band_list.pop(row)
        self.list_widget.takeItem(row)

# --- メインウィンドウ ---
class SetlistApp(QMainWindow):
  def __init__(self):
    super().__init__()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    self.setlist_dir = os.path.join(base_dir, "setlists")
    self.output_dir = os.path.join(base_dir, "export")
    os.makedirs(self.setlist_dir, exist_ok=True)
    os.makedirs(self.output_dir, exist_ok=True)

    self.current_file_path = None
    self.is_dirty = False

    self.settings = QSettings("MyBandApp", "SetlistMaker")
    self.band_list = self.settings.value("band_list", ["carrel bites"])
    if not isinstance(self.band_list, list): self.band_list = [
        "carrel bites"]

    self.current_artist = self.settings.value(
        "current_artist", self.band_list[0])
    if self.current_artist not in self.band_list and self.band_list:
      self.current_artist = self.band_list[0]

    self.use_duration = self.settings.value(
        "use_duration", False, type=bool)

    self.resize(1000, 800)
    try: pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
    except: pass

    self.setup_ui()
    self.setup_menu()
    self.setup_shortcuts()

    # 初期表示状態の反映
    self.toggle_duration_mode(self.use_duration)
    self.update_window_title()

  def update_window_title(self):
    filename = "新規ファイル"
    if self.current_file_path:
      filename = os.path.basename(self.current_file_path)
    prefix = "*" if self.is_dirty else ""
    self.setWindowTitle(
        f"{prefix}{filename} - {self.current_artist} [Setlist Maker]")

  def mark_as_dirty(self):
    if not self.is_dirty:
      self.is_dirty = True
      self.update_window_title()
    if self.use_duration: self.update_total_time()

  def mark_as_clean(self):
    self.is_dirty = False
    self.update_window_title()

  def setup_ui(self):
    main_widget = QWidget()
    self.setCentralWidget(main_widget)
    main_layout = QHBoxLayout(main_widget)

    # 左側パネル
    left_panel = QVBoxLayout()

    # バンド選択
    band_layout = QHBoxLayout()
    band_layout.addWidget(QLabel("🎸 Artist:"))
    self.artist_combo = QComboBox()
    self.artist_combo.addItems(self.band_list)
    self.artist_combo.setCurrentText(self.current_artist)
    self.artist_combo.currentTextChanged.connect(self.change_current_artist)
    band_layout.addWidget(self.artist_combo)
    self.settings_btn = QPushButton("バンド管理...")
    self.settings_btn.clicked.connect(self.open_band_manager)
    band_layout.addWidget(self.settings_btn)
    left_panel.addLayout(band_layout)
    left_panel.addSpacing(10)

    # 日付・イベント
    info_group = QVBoxLayout()
    info_group.setSpacing(5)
    date_layout = QHBoxLayout()
    date_layout.addWidget(QLabel("📅 日付:"))
    self.year_input = QLineEdit()
    self.year_input.setFixedWidth(60)
    self.year_input.setText(str(datetime.date.today().year))
    self.year_input.textChanged.connect(self.mark_as_dirty)
    date_layout.addWidget(self.year_input)
    date_layout.addWidget(QLabel("年"))
    self.month_combo = QComboBox()
    self.month_combo.addItems([str(i) for i in range(1, 13)])
    self.month_combo.setCurrentText(str(datetime.date.today().month))
    self.month_combo.currentTextChanged.connect(self.mark_as_dirty)
    date_layout.addWidget(self.month_combo)
    date_layout.addWidget(QLabel("月"))
    self.day_combo = QComboBox()
    self.day_combo.addItems([str(i) for i in range(1, 32)])
    self.day_combo.setCurrentText(str(datetime.date.today().day))
    self.day_combo.currentTextChanged.connect(self.mark_as_dirty)
    date_layout.addWidget(self.day_combo)
    date_layout.addWidget(QLabel("日"))
    date_layout.addStretch()
    info_group.addLayout(date_layout)
    info_group.addWidget(QLabel("🎪 イベント名 / 会場:"))
    self.event_input = QLineEdit()
    self.event_input.setPlaceholderText("例: 学園祭ライブ")
    self.event_input.textChanged.connect(self.mark_as_dirty)
    info_group.addWidget(self.event_input)
    left_panel.addLayout(info_group)
    left_panel.addSpacing(20)

    # 曲入力
    left_panel.addWidget(QLabel("🎵 曲名:"))
    self.title_input = QLineEdit()
    self.title_input.setPlaceholderText("曲名を入力 (Ctrl+Enterで追加)")
    left_panel.addWidget(self.title_input)

    # 演奏時間設定エリア
    time_setting_layout = QHBoxLayout()

    # チェックボックス
    self.chk_duration = QCheckBox("演奏時間を有効にする")
    self.chk_duration.setChecked(self.use_duration)
    self.chk_duration.toggled.connect(self.on_duration_toggled)
    time_setting_layout.addWidget(self.chk_duration)

    # プルダウン（初期状態は非表示の場合もある）
    self.time_widgets_layout = QHBoxLayout()
    self.min_combo = QComboBox()
    self.min_combo.addItems([str(i) for i in range(31)])  # 0-30分
    self.min_combo.setEditable(True)
    self.min_combo.setCurrentText("4")
    self.min_combo.setFixedWidth(60)

    self.sec_combo = QComboBox()
    self.sec_combo.addItems([f"{i:02}" for i in range(60)])
    self.sec_combo.setCurrentText("00")
    self.sec_combo.setFixedWidth(50)

    self.lbl_min = QLabel("分")
    self.lbl_sec = QLabel("秒")

    self.time_widgets_layout.addWidget(self.min_combo)
    self.time_widgets_layout.addWidget(self.lbl_min)
    self.time_widgets_layout.addWidget(self.sec_combo)
    self.time_widgets_layout.addWidget(self.lbl_sec)
    self.time_widgets_layout.addStretch()

    self.time_container = QWidget()
    self.time_container.setLayout(self.time_widgets_layout)
    time_setting_layout.addWidget(self.time_container)
    time_setting_layout.addStretch()

    left_panel.addLayout(time_setting_layout)

    left_panel.addWidget(QLabel("📝 説明・備考:"))
    self.desc_input = QTextEdit()
    self.desc_input.setPlaceholderText("照明、機材、立ち位置などのメモ")
    self.desc_input.setMaximumHeight(80)
    left_panel.addWidget(self.desc_input)

    btn_layout = QHBoxLayout()
    self.add_song_btn = QPushButton("曲を追加 (Ctrl+Enter)")
    self.add_song_btn.clicked.connect(self.add_song)
    self.add_mc_btn = QPushButton("🎤 MCを追加")
    self.add_mc_btn.clicked.connect(self.add_mc)
    btn_layout.addWidget(self.add_song_btn)
    btn_layout.addWidget(self.add_mc_btn)
    left_panel.addLayout(btn_layout)
    left_panel.addStretch()

    # ファイル操作
    file_btn_layout = QHBoxLayout()
    self.new_btn = QPushButton("新規")
    self.new_btn.clicked.connect(self.new_file)
    self.load_btn = QPushButton("開く")
    self.load_btn.clicked.connect(self.load_file)
    self.save_as_btn = QPushButton("名前保存")
    self.save_as_btn.clicked.connect(self.save_as_file)
    self.save_btn = QPushButton("上書き")
    self.save_btn.clicked.connect(self.save_file)
    file_btn_layout.addWidget(self.new_btn)
    file_btn_layout.addWidget(self.load_btn)
    file_btn_layout.addWidget(self.save_as_btn)
    file_btn_layout.addWidget(self.save_btn)
    left_panel.addLayout(file_btn_layout)

    export_layout = QHBoxLayout()
    self.export_btn = QPushButton("📄 PDF書き出し")
    self.export_btn.setStyleSheet(
        "background-color: #4CAF50; color: white; font-weight: bold; padding: 10px;")
    self.export_btn.clicked.connect(self.export_pdf)
    self.copy_btn = QPushButton("📋 LINE用にコピー")
    self.copy_btn.setStyleSheet(
        "background-color: #06C755; color: white; font-weight: bold; padding: 10px;")
    self.copy_btn.clicked.connect(self.copy_to_clipboard)
    export_layout.addWidget(self.export_btn)
    export_layout.addWidget(self.copy_btn)
    left_panel.addLayout(export_layout)

    # 右側パネル
    right_panel = QVBoxLayout()
    self.table = QTableWidget()
    self.table.setColumnCount(4)
    self.table.setHorizontalHeaderLabels(["Type", "曲名 / 内容", "時間", "備考"])
    self.table.setColumnWidth(0, 70)
    self.table.setColumnWidth(2, 60)
    self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
    self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
    self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
    self.table.setSelectionMode(QAbstractItemView.SingleSelection)
    self.table.itemChanged.connect(self.on_item_changed)
    right_panel.addWidget(self.table)

    self.total_time_label = QLabel("Total Time: 00:00")
    self.total_time_label.setAlignment(Qt.AlignRight)
    self.total_time_label.setStyleSheet(
        "font-weight: bold; font-size: 14px; margin: 5px;")
    right_panel.addWidget(self.total_time_label)

    control_layout = QHBoxLayout()
    self.del_btn = QPushButton("削除")
    self.del_btn.clicked.connect(self.delete_item)
    self.up_btn = QPushButton("▲ 上へ")
    self.up_btn.clicked.connect(lambda: self.move_item(-1))
    self.down_btn = QPushButton("▼ 下へ")
    self.down_btn.clicked.connect(lambda: self.move_item(1))
    control_layout.addWidget(self.del_btn)
    control_layout.addWidget(self.up_btn)
    control_layout.addWidget(self.down_btn)
    right_panel.addLayout(control_layout)

    main_layout.addLayout(left_panel, 1)
    main_layout.addLayout(right_panel, 2)
    self.mark_as_clean()

  def setup_menu(self):
    menu_bar = self.menuBar()
    file_menu = menu_bar.addMenu("ファイル(&F)")
    new_action = QAction("新規作成", self)
    new_action.setShortcut("Ctrl+N")
    new_action.triggered.connect(self.new_file)
    file_menu.addAction(new_action)
    load_action = QAction("開く...", self)
    load_action.setShortcut("Ctrl+O")
    load_action.triggered.connect(self.load_file)
    file_menu.addAction(load_action)
    save_as_action = QAction("名前を付けて保存...", self)
    save_as_action.setShortcut("Ctrl+Shift+S")
    save_as_action.triggered.connect(self.save_as_file)
    file_menu.addAction(save_as_action)
    save_action = QAction("上書き保存", self)
    save_action.setShortcut("Ctrl+S")
    save_action.triggered.connect(self.save_file)
    file_menu.addAction(save_action)
    file_menu.addSeparator()
    settings_action = QAction("バンド設定...", self)
    settings_action.triggered.connect(self.open_band_manager)
    file_menu.addAction(settings_action)

  def setup_shortcuts(self):
    self.shortcut_add = QShortcut(QKeySequence("Ctrl+Return"), self)
    self.shortcut_add.activated.connect(self.add_song)
    self.shortcut_add_enter = QShortcut(QKeySequence("Ctrl+Enter"), self)
    self.shortcut_add_enter.activated.connect(self.add_song)

  def open_band_manager(self):
    dialog = BandManagerDialog(self, self.band_list)
    if dialog.exec() == QDialog.Accepted:
      self.band_list = dialog.band_list
      self.settings.setValue("band_list", self.band_list)
      self.artist_combo.blockSignals(True)
      self.artist_combo.clear()
      self.artist_combo.addItems(self.band_list)
      if self.current_artist in self.band_list:
        self.artist_combo.setCurrentText(self.current_artist)
      elif self.band_list:
        self.current_artist = self.band_list[0]
        self.artist_combo.setCurrentText(self.current_artist)
      self.artist_combo.blockSignals(False)
      self.update_window_title()

  def on_duration_toggled(self, checked):
    self.use_duration = checked
    self.settings.setValue("use_duration", self.use_duration)
    self.toggle_duration_mode(checked)

  def toggle_duration_mode(self, enabled):
    self.time_container.setVisible(enabled)
    self.table.setColumnHidden(2, not enabled)
    self.total_time_label.setVisible(enabled)
    if enabled:
      self.update_total_time()

  def change_current_artist(self, text):
    if text:
      self.current_artist = text
      self.settings.setValue("current_artist", self.current_artist)
      self.update_window_title()

  def on_item_changed(self, item):
    row = item.row()
    col = item.column()
    data_item = self.table.item(row, 0).data(Qt.UserRole)
    if not data_item: return
    text = item.text()
    if col == 1:
      if not data_item.is_mc: data_item.title = text
    elif col == 2: data_item.duration = text
    elif col == 3: data_item.description = text
    self.mark_as_dirty()

  def parse_time(self, time_str):
    try:
      parts = re.split(r'[:：]', time_str)
      if len(parts) == 2:
        m, s = int(parts[0]), int(parts[1])
        return m * 60 + s
      elif len(parts) == 1 and parts[0].isdigit():
        return int(parts[0]) * 60
    except: pass
    return 0

  def update_total_time(self):
    total_seconds = 0
    for row in range(self.table.rowCount()):
      item = self.table.item(row, 0).data(Qt.UserRole)
      total_seconds += self.parse_time(item.duration)
    m = total_seconds // 60
    s = total_seconds % 60
    self.total_time_label.setText(f"Total Time: {m:02}:{s:02}")

  # --- 修正: 日本語ボタンのカスタムメッセージボックス ---
  def check_unsaved_changes(self):
    if not self.is_dirty: return True

    # カスタムダイアログを作成
    msg_box = QMessageBox(self)
    msg_box.setWindowTitle("未保存")
    msg_box.setText("変更内容が保存されていません。\n保存しますか？")
    msg_box.setIcon(QMessageBox.Question)

    # 日本語ボタンを追加
    btn_yes = msg_box.addButton("はい", QMessageBox.YesRole)
    btn_no = msg_box.addButton("いいえ", QMessageBox.NoRole)
    btn_cancel = msg_box.addButton("キャンセル", QMessageBox.RejectRole)

    msg_box.setDefaultButton(btn_yes)
    msg_box.exec()

    clicked = msg_box.clickedButton()
    if clicked == btn_yes:
      return self.save_file()
    elif clicked == btn_no:
      return True  # 保存せず破棄
    else:
      return False  # キャンセル

  def new_file(self):
    if not self.check_unsaved_changes(): return
    self.table.setRowCount(0)
    today = datetime.date.today()
    self.year_input.setText(str(today.year))
    self.month_combo.setCurrentText(str(today.month))
    self.day_combo.setCurrentText(str(today.day))
    self.event_input.clear()
    self.clear_inputs()
    self.current_file_path = None
    self.mark_as_clean()
    if self.use_duration: self.update_total_time()

  def add_song(self):
    title = self.title_input.text().strip()
    if not title: return

    duration = ""
    if self.use_duration:
      duration = f"{self.min_combo.currentText()}:{self.sec_combo.currentText()}"

    item = SetlistItem(
        title, self.desc_input.toPlainText(), duration, is_mc=False)
    self.add_row_to_table(item)
    self.clear_inputs()
    self.mark_as_dirty()

  def add_mc(self):
    desc = self.desc_input.toPlainText()
    item = SetlistItem("MC", desc, "", is_mc=True)
    self.add_row_to_table(item)
    self.clear_inputs()
    self.mark_as_dirty()

  def update_row_numbers(self):
    self.table.blockSignals(True)
    song_counter = 0
    for row in range(self.table.rowCount()):
      item = self.table.item(row, 0).data(Qt.UserRole)
      if item.is_mc:
        self.table.setVerticalHeaderItem(row, QTableWidgetItem("MC"))
      else:
        song_counter += 1
        self.table.setVerticalHeaderItem(
            row, QTableWidgetItem(str(song_counter)))
    self.table.blockSignals(False)

  def add_row_to_table(self, item: SetlistItem):
    self.table.blockSignals(True)
    row = self.table.rowCount()
    self.table.insertRow(row)
    type_str = "🎤 MC" if item.is_mc else "🎵 Song"
    type_item = QTableWidgetItem(type_str)
    type_item.setFlags(type_item.flags() ^ Qt.ItemIsEditable)
    self.table.setItem(row, 0, type_item)
    self.table.setItem(row, 1, QTableWidgetItem(item.title))
    self.table.setItem(row, 2, QTableWidgetItem(item.duration))
    self.table.setItem(row, 3, QTableWidgetItem(item.description))
    self.table.item(row, 0).setData(Qt.UserRole, item)
    self.table.blockSignals(False)
    self.update_row_numbers()

  def clear_inputs(self):
    self.title_input.clear()
    self.desc_input.clear()
    self.min_combo.setCurrentText("4")
    self.sec_combo.setCurrentText("00")
    self.title_input.setFocus()

  def delete_item(self):
    current_row = self.table.currentRow()
    if current_row >= 0:
      self.table.removeRow(current_row)
      self.update_row_numbers()
      self.mark_as_dirty()

  def move_item(self, direction):
    row = self.table.currentRow()
    if row < 0: return
    target_row = row + direction
    if 0 <= target_row < self.table.rowCount():
      self.table.blockSignals(True)
      item_obj = self.table.item(row, 0).data(Qt.UserRole)
      self.table.removeRow(row)
      self.table.insertRow(target_row)
      type_str = "🎤 MC" if item_obj.is_mc else "🎵 Song"
      type_item = QTableWidgetItem(type_str)
      type_item.setFlags(type_item.flags() ^ Qt.ItemIsEditable)
      self.table.setItem(target_row, 0, type_item)
      self.table.setItem(target_row, 1, QTableWidgetItem(item_obj.title))
      self.table.setItem(
          target_row, 2, QTableWidgetItem(item_obj.duration))
      self.table.setItem(
          target_row, 3, QTableWidgetItem(item_obj.description))
      self.table.item(target_row, 0).setData(Qt.UserRole, item_obj)
      self.table.selectRow(target_row)
      self.table.blockSignals(False)
      self.update_row_numbers()
      self.mark_as_dirty()

  def get_date_string(self):
    y = self.year_input.text()
    m = self.month_combo.currentText().zfill(2)
    d = self.day_combo.currentText().zfill(2)
    return f"{y}/{m}/{d}"

  def get_default_filename(self, extension):
    date_text = self.get_date_string()
    event_text = self.event_input.text().strip()
    date_part = date_text.replace("/", "-")
    event_part = re.sub(r'[\\/:*?"<>|]', '_', event_text)
    if date_part and event_part: return f"{date_part}_{event_part}{extension}"
    elif date_part: return f"{date_part}_live{extension}"
    else: return f"setlist{extension}"

  def copy_to_clipboard(self):
    if self.table.rowCount() == 0: return
    text = f"【{self.current_artist}】\n"
    text += f"Date: {self.get_date_string()} / {self.event_input.text()}\n"
    text += "-" * 20 + "\n"
    song_counter = 0
    total_seconds = 0
    for row in range(self.table.rowCount()):
      item = self.table.item(row, 0).data(Qt.UserRole)
      if item.is_mc:
        text += "◆ MC"
        if item.description: text += f" ({item.description})"
        text += "\n"
      else:
        song_counter += 1
        text += f"{song_counter}. {item.title}"
        if self.use_duration and item.duration:
          text += f" ({item.duration})"
          total_seconds += self.parse_time(item.duration)
        if item.description:
          text += f" ... {item.description}"
        text += "\n"
    text += "-" * 20 + "\n"
    if self.use_duration:
      m = total_seconds // 60
      s = total_seconds % 60
      text += f"Total Time: {m:02}:{s:02}\n"
    QApplication.clipboard().setText(text)
    QMessageBox.information(self, "コピー完了", "クリップボードにコピーしました！")

  def save_file(self):
    if self.current_file_path: return self._write_to_file(self.current_file_path)
    else: return self.save_as_file()

  def save_as_file(self):
    if self.table.rowCount() == 0:
      QMessageBox.warning(self, "警告", "保存するデータがありません")
      return False
    default_name = self.get_default_filename(".set")
    default_path = os.path.join(self.setlist_dir, default_name)
    file_path, _ = QFileDialog.getSaveFileName(
        self, "名前を付けて保存", default_path, "Setlist Files (*.set);;All Files (*)")
    if not file_path: return False
    return self._write_to_file(file_path)

  def _write_to_file(self, file_path):
    data_to_save = {
        "artist": self.current_artist,
        "year": self.year_input.text(),
        "month": self.month_combo.currentText(),
        "day": self.day_combo.currentText(),
        "event": self.event_input.text(),
        "items": []
    }
    for row in range(self.table.rowCount()):
      item_obj = self.table.item(row, 0).data(Qt.UserRole)
      data_to_save["items"].append(item_obj.to_dict())
    try:
      with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data_to_save, f, indent=4, ensure_ascii=False)
      self.current_file_path = file_path
      self.mark_as_clean()
      QMessageBox.information(self, "保存", "保存しました！")
      return True
    except Exception as e:
      QMessageBox.critical(self, "エラー", f"保存失敗:\n{e}")
      return False

  def load_file(self):
    if not self.check_unsaved_changes(): return
    file_path, _ = QFileDialog.getOpenFileName(
        self, "セットリストを開く", self.setlist_dir, "Setlist Files (*.set);;JSON Files (*.json);;All Files (*)")
    if not file_path: return
    try:
      with open(file_path, 'r', encoding='utf-8') as f:
        data_loaded = json.load(f)
      self.table.setRowCount(0)
      if isinstance(data_loaded, list):
        items = data_loaded
      else:
        loaded_artist = data_loaded.get("artist", "")
        if loaded_artist:
          if loaded_artist not in self.band_list:
            self.band_list.append(loaded_artist)
            self.artist_combo.addItem(loaded_artist)
          self.current_artist = loaded_artist
          self.artist_combo.setCurrentText(loaded_artist)
        if "date" in data_loaded:
          try:
            dt = datetime.datetime.strptime(
                data_loaded["date"], "%Y/%m/%d")
            self.year_input.setText(str(dt.year))
            self.month_combo.setCurrentText(str(dt.month))
            self.day_combo.setCurrentText(str(dt.day))
          except: pass
        else:
          self.year_input.setText(data_loaded.get("year", ""))
          self.month_combo.setCurrentText(
              data_loaded.get("month", "1"))
          self.day_combo.setCurrentText(data_loaded.get("day", "1"))
        self.event_input.setText(data_loaded.get("event", ""))
        items = data_loaded.get("items", [])
      for item_data in items:
        item_obj = SetlistItem.from_dict(item_data)
        self.add_row_to_table(item_obj)
      self.current_file_path = file_path
      self.mark_as_clean()
      if self.use_duration: self.update_total_time()
      QMessageBox.information(self, "完了", "読み込みました！")
    except Exception as e:
      QMessageBox.critical(self, "エラー", f"読み込み失敗:\n{e}")

  def closeEvent(self, event: QCloseEvent):
    if self.check_unsaved_changes(): event.accept()
    else: event.ignore()

  def export_pdf(self):
    if self.table.rowCount() == 0:
      QMessageBox.warning(self, "警告", "リストが空です！")
      return
    default_name = self.get_default_filename(".pdf")
    default_path = os.path.join(self.output_dir, default_name)
    file_path, _ = QFileDialog.getSaveFileName(
        self, "PDF保存", default_path, "PDF Files (*.pdf)")
    if not file_path: return
    try:
      c = canvas.Canvas(file_path, pagesize=A4)
      width, height = A4
      c.setFont("HeiseiKakuGo-W5", 28)
      c.drawString(20 * mm, height - 30 * mm,
                   f"SETLIST: {self.current_artist}")
      c.setFont("HeiseiKakuGo-W5", 14)
      date_str = self.get_date_string()
      event_str = self.event_input.text()
      header_info = f"Date: {date_str}   Venue: {event_str}"
      c.drawString(20 * mm, height - 42 * mm, header_info)
      y_position = height - 60 * mm
      song_counter = 0
      total_seconds = 0
      for row in range(self.table.rowCount()):
        item = self.table.item(row, 0).data(Qt.UserRole)
        if y_position < 40 * mm:
          c.showPage()
          y_position = height - 30 * mm
        if item.is_mc:
          c.setFillColorRGB(0.3, 0.3, 0.3)
          c.setFont("HeiseiKakuGo-W5", 14)
          c.drawString(30 * mm, y_position, f"◆ MC")
          if item.description:
            c.setFont("HeiseiKakuGo-W5", 11)
            c.drawString(55 * mm, y_position,
                         f"({item.description})")
          y_position -= 15 * mm
        else:
          song_counter += 1
          c.setFillColorRGB(0, 0, 0)
          c.setFont("HeiseiKakuGo-W5", 22)
          c.drawString(25 * mm, y_position,
                       f"{song_counter}. {item.title}")
          if self.use_duration and item.duration:
            c.setFont("HeiseiKakuGo-W5", 14)
            c.drawRightString(
                width - 20 * mm, y_position, item.duration)
            total_seconds += self.parse_time(item.duration)
          if item.description:
            y_position -= 8 * mm
            c.setFont("HeiseiKakuGo-W5", 12)
            c.setFillColorRGB(0.2, 0.2, 0.6)
            c.drawString(35 * mm, y_position,
                         f"※ {item.description}")
          y_position -= 5 * mm
          c.setStrokeColorRGB(0.8, 0.8, 0.8)
          c.line(20 * mm, y_position, width - 20 * mm, y_position)
          y_position -= 15 * mm
      if self.use_duration:
        m = total_seconds // 60
        s = total_seconds % 60
        c.setFont("HeiseiKakuGo-W5", 12)
        c.setFillColorRGB(0, 0, 0)
        c.drawString(20 * mm, 15 * mm, f"Total Time: {m:02}:{s:02}")
      c.save()
      QMessageBox.information(self, "成功", "PDFを出力しました！")
    except Exception as e:
      QMessageBox.critical(self, "エラー", f"PDF作成エラー:\n{e}")

if __name__ == "__main__":
  app = QApplication(sys.argv)
  window = SetlistApp()
  window.show()
  sys.exit(app.exec())
