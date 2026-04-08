import sys
import threading
import os
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QProgressBar, QLabel, QListWidget, QListWidgetItem,
    QTextEdit, QSplitter, QCheckBox, QTreeWidget, QTreeWidgetItem,
    QScrollArea, QGridLayout, QScrollBar
)
from PySide6.QtCore import Qt, QThread, Signal, QSize
from PySide6.QtGui import QPixmap, QIcon
from scraper.scryfall import get_all_sets, get_cards_by_set
from scraper.downloader import download_image


class DownloadWorker(QThread):
    """Worker thread for downloading cards."""
    progress = Signal(int)
    total_progress = Signal(int)
    status = Signal(str)
    set_completed = Signal(str, int)  # set_code, downloaded_count
    finished = Signal()
    
    def __init__(self, sets_to_download):
        super().__init__()
        self.sets_to_download = sets_to_download
        self.is_running = True
        self.is_paused = False
        self.total_cards = 0
        self.downloaded_cards = 0
    
    def run(self):
        """Download cards from selected sets."""
        try:
            # Calculate total cards
            total_sets = len(self.sets_to_download)
            for idx, (set_code, set_name) in enumerate(self.sets_to_download):
                if not self.is_running:
                    self.status.emit("Cancelled")
                    break
                
                # Wait if paused
                while self.is_paused and self.is_running:
                    self.msleep(100)
                
                self.status.emit(f"Fetching cards from {set_name}...")
                cards = get_cards_by_set(set_code)
                
                if self.is_running:
                    downloaded_in_set = self.download_set(set_code, set_name, cards)
                    self.set_completed.emit(set_code, downloaded_in_set)
                    set_progress = int((idx + 1) / total_sets * 100)
                    self.total_progress.emit(set_progress)
            
            if self.is_running:
                self.status.emit(f"✓ Complete! Downloaded {self.downloaded_cards} cards")
            self.finished.emit()
        except Exception as e:
            self.status.emit(f"✗ Error: {str(e)}")
            self.finished.emit()
    
    def download_set(self, set_code, set_name, cards):
        """Download all cards from a specific set."""
        total_cards_in_set = 0
        for idx, card in enumerate(cards):
            if not self.is_running:
                break
            
            # Wait if paused
            while self.is_paused and self.is_running:
                self.msleep(100)
            
            if "image_uris" not in card:
                continue
            
            img = card["image_uris"].get("normal")
            if not img:
                continue
            
            name = card["name"].replace(" ", "_").replace("//", "-")
            filename = f"data/{set_code}/{name}.jpg"
            
            # Download and track if successful (not a duplicate)
            if download_image(img, filename):
                self.downloaded_cards += 1
                total_cards_in_set += 1
                self.progress.emit((idx + 1) * 100 // len(cards))
                self.status.emit(f"[{set_name}] Downloaded: {name}")
        
        if total_cards_in_set > 0:
            self.status.emit(f"✓ {set_name}: {total_cards_in_set} cards")
        return total_cards_in_set
    
    def pause(self):
        self.is_paused = True
    
    def resume(self):
        self.is_paused = False
    
    def stop(self):
        self.is_running = False


class CardGridWidget(QWidget):
    """Widget to display a grid of card images."""
    
    def __init__(self, set_code):
        super().__init__()
        self.set_code = set_code
        self.cards_path = Path(f"data/{set_code}")
        self.init_ui()
    
    def init_ui(self):
        """Initialize the grid layout with card images."""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        
        # Container for grid
        container = QWidget()
        grid = QGridLayout()
        grid.setSpacing(5)
        
        # Load card images
        if self.cards_path.exists():
            cards = sorted(self.cards_path.glob("*.jpg"))
            for idx, card_file in enumerate(cards):
                row = idx // 4
                col = idx % 4
                
                # Create thumbnail
                label = QLabel()
                pixmap = QPixmap(str(card_file))
                if not pixmap.isNull():
                    # Scale to thumbnail size (150x210 pixels)
                    scaled_pixmap = pixmap.scaledToHeight(150, Qt.SmoothTransformation)
                    label.setPixmap(scaled_pixmap)
                    label.setToolTip(card_file.stem)
                    grid.addWidget(label, row, col)
        
        container.setLayout(grid)
        scroll.setWidget(container)
        layout.addWidget(scroll)
        self.setLayout(layout)


class MTGProxyDownloaderGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.worker = None
        self.all_sets = []
        self.set_stats = {}  # Track stats for each set
        self.init_ui()
        self.load_sets()
    
    def init_ui(self):
        """Initialize the GUI."""
        self.setWindowTitle("MTG Proxy Downloader")
        self.setGeometry(100, 100, 1400, 800)
        
        # Main widget
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        
        # Main layout
        main_layout = QHBoxLayout()
        
        # Left side - Set selection
        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel("Select Sets to Download:"))
        
        self.sets_list = QListWidget()
        left_layout.addWidget(self.sets_list)
        
        # Select all / Deselect all buttons
        button_layout = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self.select_all_sets)
        clear_all_btn = QPushButton("Clear All")
        clear_all_btn.clicked.connect(self.clear_all_sets)
        button_layout.addWidget(select_all_btn)
        button_layout.addWidget(clear_all_btn)
        left_layout.addLayout(button_layout)
        
        left_widget = QWidget()
        left_widget.setLayout(left_layout)
        left_widget.setMaximumWidth(300)
        
        # Right side - Progress, downloads tree, and logs
        right_layout = QVBoxLayout()
        
        # Progress section
        right_layout.addWidget(QLabel("Overall Progress:"))
        self.overall_progress = QProgressBar()
        right_layout.addWidget(self.overall_progress)
        
        right_layout.addWidget(QLabel("Current Set Progress:"))
        self.current_progress = QProgressBar()
        right_layout.addWidget(self.current_progress)
        
        # Downloaded sets tree
        right_layout.addWidget(QLabel("Downloaded Sets:"))
        self.sets_tree = QTreeWidget()
        self.sets_tree.setHeaderLabels(["Set Name", "Progress"])
        self.sets_tree.setColumnCount(2)
        self.sets_tree.itemExpanded.connect(self.on_set_expanded)
        right_layout.addWidget(self.sets_tree)
        
        # Status log
        right_layout.addWidget(QLabel("Status Log:"))
        self.status_log = QTextEdit()
        self.status_log.setReadOnly(True)
        self.status_log.setMaximumHeight(150)
        right_layout.addWidget(self.status_log)
        
        # Control buttons
        button_layout = QHBoxLayout()
        self.start_btn = QPushButton("Start Download")
        self.start_btn.clicked.connect(self.start_download)
        self.start_btn.setMinimumHeight(40)
        
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.clicked.connect(self.pause_download)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setMinimumHeight(40)
        
        self.resume_btn = QPushButton("Resume")
        self.resume_btn.clicked.connect(self.resume_download)
        self.resume_btn.setEnabled(False)
        self.resume_btn.setMinimumHeight(40)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_download)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setMinimumHeight(40)
        
        button_layout.addWidget(self.start_btn)
        button_layout.addWidget(self.pause_btn)
        button_layout.addWidget(self.resume_btn)
        button_layout.addWidget(self.cancel_btn)
        right_layout.addLayout(button_layout)
        
        # Status label
        self.status_label = QLabel("Ready")
        right_layout.addWidget(self.status_label)
        
        right_widget = QWidget()
        right_widget.setLayout(right_layout)
        
        # Splitter
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([300, 1100])
        
        main_layout.addWidget(splitter)
        main_widget.setLayout(main_layout)
        
        # Load already downloaded sets
        self.load_downloaded_sets()
    
    def load_downloaded_sets(self):
        """Load and display already downloaded sets."""
        data_path = Path("data")
        if data_path.exists():
            for set_folder in sorted(data_path.iterdir()):
                if set_folder.is_dir():
                    card_count = len(list(set_folder.glob("*.jpg")))
                    if card_count > 0:
                        self.add_downloaded_set_to_tree(set_folder.name, card_count)
    
    def add_downloaded_set_to_tree(self, set_code, card_count):
        """Add a downloaded set to the tree view."""
        # Find the set name from all_sets
        set_name = set_code
        for code, name in self.all_sets:
            if code == set_code:
                set_name = name
                break
        
        item = QTreeWidgetItem()
        item.setText(0, f"{set_name} ({set_code})")
        item.setText(1, f"{card_count} cards")
        item.setData(0, Qt.UserRole, set_code)  # Store set code for later
        
        self.sets_tree.addTopLevelItem(item)
        self.set_stats[set_code] = card_count
    
    def on_set_expanded(self, item):
        """Handle set expansion - show card grid."""
        if item.childCount() == 0:
            set_code = item.data(0, Qt.UserRole)
            if set_code:
                # Add grid widget as child
                grid_widget = CardGridWidget(set_code)
                child_item = QTreeWidgetItem()
                child_item.setText(0, "Cards")
                item.addChild(child_item)
                self.sets_tree.setItemWidget(child_item, 0, grid_widget)
    
    def load_sets(self):
        """Load all sets from Scryfall."""
        self.status_label.setText("Loading sets...")
        try:
            self.all_sets = get_all_sets()
            for set_code, set_name in self.all_sets:
                item = QListWidgetItem(f"{set_name} ({set_code})")
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked)
                self.sets_list.addItem(item)
            self.status_label.setText(f"Ready - {len(self.all_sets)} sets available")
        except Exception as e:
            self.status_label.setText(f"Error loading sets: {str(e)}")
            self.log_status(f"Error: {str(e)}")
    
    def select_all_sets(self):
        """Check all sets."""
        for i in range(self.sets_list.count()):
            self.sets_list.item(i).setCheckState(Qt.Checked)
    
    def clear_all_sets(self):
        """Uncheck all sets."""
        for i in range(self.sets_list.count()):
            self.sets_list.item(i).setCheckState(Qt.Unchecked)
    
    def get_selected_sets(self):
        """Get list of selected sets."""
        selected = []
        for i in range(self.sets_list.count()):
            item = self.sets_list.item(i)
            if item.checkState() == Qt.Checked:
                # Extract set code from "Name (CODE)"
                text = item.text()
                set_code = text.split("(")[-1].rstrip(")")
                selected.append((set_code, text.split("(")[0].strip()))
        return selected
    
    def start_download(self):
        """Start downloading selected sets."""
        selected_sets = self.get_selected_sets()
        if not selected_sets:
            self.status_label.setText("Please select at least one set")
            return
        
        self.log_status(f"Starting download of {len(selected_sets)} sets...\n")
        
        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self.sets_list.setEnabled(False)
        
        self.worker = DownloadWorker(selected_sets)
        self.worker.progress.connect(self.update_progress)
        self.worker.total_progress.connect(self.update_total_progress)
        self.worker.status.connect(self.log_status)
        self.worker.set_completed.connect(self.on_set_completed)
        self.worker.finished.connect(self.download_finished)
        self.worker.start()
    
    def on_set_completed(self, set_code, downloaded_count):
        """Called when a set is completed."""
        # Find set name
        set_name = set_code
        for code, name in self.all_sets:
            if code == set_code:
                set_name = name
                break
        
        # Update tree - check if set already exists
        root = self.sets_tree.invisibleRootItem()
        found = False
        for i in range(root.childCount()):
            item = root.child(i)
            if item.data(0, Qt.UserRole) == set_code:
                item.setText(1, f"{downloaded_count} cards")
                found = True
                break
        
        if not found:
            self.add_downloaded_set_to_tree(set_code, downloaded_count)
        
        self.set_stats[set_code] = downloaded_count
    
    def pause_download(self):
        """Pause the download."""
        if self.worker:
            self.worker.pause()
            self.status_label.setText("Paused")
            self.pause_btn.setEnabled(False)
            self.resume_btn.setEnabled(True)
            self.log_status("[PAUSED]")
    
    def resume_download(self):
        """Resume the download."""
        if self.worker:
            self.worker.resume()
            self.status_label.setText("Downloading...")
            self.pause_btn.setEnabled(True)
            self.resume_btn.setEnabled(False)
            self.log_status("[RESUMED]")
    
    def cancel_download(self):
        """Cancel the download."""
        if self.worker:
            self.worker.stop()
            self.worker.wait()
            self.status_label.setText("Cancelled")
            self.log_status("[CANCELLED]")
            self.download_finished()
    
    def update_progress(self, value):
        """Update current set progress bar."""
        self.current_progress.setValue(value)
    
    def update_total_progress(self, value):
        """Update overall progress bar."""
        self.overall_progress.setValue(value)
    
    def log_status(self, message):
        """Add message to status log."""
        self.status_log.append(message)
        # Auto-scroll to bottom
        self.status_log.verticalScrollBar().setValue(
            self.status_log.verticalScrollBar().maximum()
        )
    
    def download_finished(self):
        """Called when download is finished."""
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.resume_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.sets_list.setEnabled(True)
        self.status_label.setText("Done!")


def main():
    app = QApplication(sys.argv)
    window = MTGProxyDownloaderGUI()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

