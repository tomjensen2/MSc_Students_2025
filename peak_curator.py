#!/usr/bin/env python
"""
Low-Mg²⁺ Peak Curator — PyQtGraph + PyQt5 (v1.4.1)
=================================================
Interactive desktop GUI for quality‑controlled peak detection in Low‑Mg²⁺ field recordings.

🔄 **What's new in v1.4.1**
* Previous reply was truncated—this version is **complete and runnable**.
* Adjustable **Low F / High F** (Hz) for the spectrogram and band‑power trace.
* **Band‑power vs time** plot locked to the main trace.
* **Peaks timeline** row appears after export.
* **Continuous time** for ABF: uses `sweepStartSec` so sweep 2 starts at 30 s, etc.

```bash
pip install numpy pandas scipy pyqtgraph pyqt5 pyabf
python peak_curator.py   # click ➕ Load to open .abf or .csv
```
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Tuple, Optional

import numpy as np
import pandas as pd
import scipy.signal as signal

# ── Qt & plotting ────────────────────────────────────────────────────────────
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QDoubleSpinBox,
    QSpinBox,
    QCheckBox,
    QFileDialog,
    QMessageBox,
    QMenuBar,
    QDialog,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QShortcut,
    QMenu,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QClipboard, QKeySequence
from PyQt5.QtCore import QTimer, pyqtSignal
import pyqtgraph as pg

# ── Optional ABF support ─────────────────────────────────────────────────────
try:
    import pyabf  # type: ignore
except ImportError:  # pragma: no cover
    pyabf = None  # .abf support disabled if library missing

pg.setConfigOptions(antialias=True)


class PeaksTableDialog(QDialog):
    """Pop-out table showing detected peaks with absolute timing."""
    
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Detected Peaks Table")
        self.resize(800, 600)
        self.setWindowFlags(Qt.Window)  # Make it a regular window, not modal
        
        # Keep reference to parent
        self.parent_app = parent
        
        layout = QVBoxLayout(self)
        
        # Info label
        self.info_label = QLabel("No peaks data loaded")
        layout.addWidget(self.info_label)
        
        # Status label (for feedback)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(self.status_label)
        
        # Create table
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSortingEnabled(True)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.table)
        
        # Add buttons
        btn_layout = QHBoxLayout()
        
        self.btn_refresh = QPushButton("🔄 Refresh Data")
        self.btn_refresh.clicked.connect(self.refresh_data)
        
        self.chk_auto_refresh = QCheckBox("Auto-refresh")
        self.chk_auto_refresh.setChecked(True)
        self.chk_auto_refresh.setToolTip("Automatically update table when main window changes")
        
        btn_copy = QPushButton("📋 Copy to Clipboard (Ctrl+C)")
        btn_copy.clicked.connect(self._copy_to_clipboard)
        btn_copy.setToolTip("Copy table data to clipboard in tab-separated format.\nKeyboard shortcut: Ctrl+C")
        
        btn_export = QPushButton("💾 Export Table")
        btn_export.clicked.connect(self._export_table)
        
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.close)
        
        btn_layout.addWidget(self.btn_refresh)
        btn_layout.addWidget(self.chk_auto_refresh)
        btn_layout.addWidget(btn_copy)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_export)
        btn_layout.addWidget(btn_close)
        layout.addLayout(btn_layout)
        
        self.peaks_data = {}
        
        # Add keyboard shortcut for copying (Ctrl+C)
        copy_shortcut = QShortcut(QKeySequence.Copy, self)
        copy_shortcut.activated.connect(self._copy_to_clipboard)
        
        # Load initial data
        self.refresh_data()
    
    def refresh_data(self):
        """Refresh table with current peaks data from parent."""
        self.peaks_data = self.parent_app._get_current_peaks_data()
        self._populate_table(self.peaks_data)
        self._update_info_label()
        
        # Update status
        import datetime
        current_time = datetime.datetime.now().strftime("%H:%M:%S")
        if self.peaks_data:
            self.status_label.setText(f"Data refreshed at {current_time}")
        else:
            self.status_label.setText("")
    
    def _update_info_label(self):
        """Update the info label with current state."""
        if not self.peaks_data:
            self.info_label.setText("No peaks detected")
            return
        
        n_peaks = len(list(self.peaks_data.values())[0])
        timing_method = self.peaks_data.get('Timing_Method', ['unknown'])[0]
        
        # Get amplitude info
        amp_column = [k for k in self.peaks_data.keys() if k.startswith('Amplitude_')]
        units_info = f" ({amp_column[0].split('_')[1]})" if amp_column else ""
        
        if self.parent_app.mode == "abf":
            sweep = self.parent_app.sb_sweep.value()
            channel = self.parent_app.sb_chan.value()
            info_text = f"{n_peaks} peaks{units_info} | Ch {channel}, Sw {sweep} | Timing: {timing_method}"
        else:
            info_text = f"{n_peaks} peaks{units_info} | Timing: {timing_method}"
        
        self.info_label.setText(info_text)
    
    def _populate_table(self, peaks_data):
        """Fill table with peak data."""
        if not peaks_data:
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            return
            
        # Set up columns
        columns = list(peaks_data.keys())
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        
        # Set up rows
        n_peaks = len(list(peaks_data.values())[0])
        self.table.setRowCount(n_peaks)
        
        # Fill data
        for col_idx, (col_name, values) in enumerate(peaks_data.items()):
            for row_idx, value in enumerate(values):
                if isinstance(value, (float, np.floating)):
                    item = QTableWidgetItem(f"{value:.4f}")
                elif isinstance(value, (int, np.integer)):
                    item = QTableWidgetItem(str(int(value)))
                else:
                    item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)  # Read-only
                self.table.setItem(row_idx, col_idx, item)
        
        # Auto-resize columns
        self.table.resizeColumnsToContents()
        header = self.table.horizontalHeader()
        for i in range(len(columns)):
            header.setSectionResizeMode(i, QHeaderView.Interactive)
    
    def _copy_to_clipboard(self):
        """Copy table contents to clipboard in tab-separated format."""
        if not self.peaks_data or self.table.rowCount() == 0:
            QMessageBox.warning(self, "No Data", "No data to copy!")
            return
        
        try:
            # Get clipboard
            clipboard = QApplication.clipboard()
            
            # Check if specific rows are selected
            selected_rows = set()
            for item in self.table.selectedItems():
                selected_rows.add(item.row())
            
            # If no selection, copy all rows
            if not selected_rows:
                selected_rows = set(range(self.table.rowCount()))
            
            selected_rows = sorted(selected_rows)
            
            # Build tab-separated text
            lines = []
            
            # Header row (always included)
            headers = []
            for col in range(self.table.columnCount()):
                header_item = self.table.horizontalHeaderItem(col)
                if header_item:
                    headers.append(header_item.text())
                else:
                    headers.append(f"Column_{col}")
            lines.append('\t'.join(headers))
            
            # Data rows (only selected)
            for row in selected_rows:
                row_data = []
                for col in range(self.table.columnCount()):
                    item = self.table.item(row, col)
                    if item:
                        row_data.append(item.text())
                    else:
                        row_data.append('')
                lines.append('\t'.join(row_data))
            
            # Join all lines
            clipboard_text = '\n'.join(lines)
            
            # Copy to clipboard
            clipboard.setText(clipboard_text)
            
            # Show status feedback
            import datetime
            current_time = datetime.datetime.now().strftime("%H:%M:%S")
            if len(selected_rows) == self.table.rowCount():
                self.status_label.setText(f"Copied all data to clipboard at {current_time}")
                rows_desc = "all rows"
            else:
                self.status_label.setText(f"Copied {len(selected_rows)} selected rows to clipboard at {current_time}")
                rows_desc = f"{len(selected_rows)} selected rows"
            
            # Show confirmation
            QMessageBox.information(
                self, "Copied!", 
                f"Copied {rows_desc} × {self.table.columnCount()} columns to clipboard.\n\n"
                "You can now paste this data into Excel, statistical software, or any text editor.\n\n"
                "Tip: Select specific rows before copying to copy only those rows."
            )
            
        except Exception as e:
            QMessageBox.critical(self, "Copy Error", f"Failed to copy data to clipboard:\n{str(e)}")
    
    def _show_context_menu(self, position):
        """Show context menu when right-clicking on table."""
        if self.table.itemAt(position) is None:
            return  # No item under cursor
        
        menu = QMenu(self)
        
        # Check if rows are selected
        selected_rows = set()
        for item in self.table.selectedItems():
            selected_rows.add(item.row())
        
        if selected_rows:
            copy_text = f"📋 Copy {len(selected_rows)} Selected Rows"
        else:
            copy_text = "📋 Copy All Table Data"
        
        copy_action = menu.addAction(copy_text)
        copy_action.triggered.connect(self._copy_to_clipboard)
        copy_action.setShortcut(QKeySequence.Copy)
        
        menu.addSeparator()
        
        export_action = menu.addAction("💾 Export Table to CSV")
        export_action.triggered.connect(self._export_table)
        
        refresh_action = menu.addAction("🔄 Refresh Data")
        refresh_action.triggered.connect(self.refresh_data)
        
        menu.exec_(self.table.mapToGlobal(position))
    
    def _export_table(self):
        """Export table data to CSV."""
        if not self.peaks_data:
            QMessageBox.warning(self, "No Data", "No peaks data to export!")
            return
            
        fname, _ = QFileDialog.getSaveFileName(
            self, "Export Table", "peaks_table.csv", "CSV files (*.csv)"
        )
        if fname:
            try:
                df = pd.DataFrame(self.peaks_data)
                
                # Add metadata
                metadata = [
                    f"# Peaks Table Export",
                    f"# Generated: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    f"# Source: {self.parent_app.current_file_path.name if self.parent_app.current_file_path else 'Unknown'}",
                    ""
                ]
                
                with open(fname, 'w') as f:
                    f.write('\n'.join(metadata))
                    df.to_csv(f, index=False)
                    
                QMessageBox.information(self, "Export Complete", f"Table exported to:\n{fname}")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export table:\n{str(e)}")
    
    def closeEvent(self, event):
        """Handle window close event."""
        # Notify parent that table is closing
        if hasattr(self.parent_app, '_table_dialog'):
            self.parent_app._table_dialog = None
        event.accept()


class PeakApp(QMainWindow):
    """CSV + ABF peak curator with low‑frequency analysis tools."""

    # ────────────────────────────────────────────────────────────────
    # Construction / UI
    # ────────────────────────────────────────────────────────────────

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Low‑Mg²⁺ Peak Curator — PyQt5/PyQtGraph")
        self.resize(1280, 840)

        # Data containers
        self.mode: str = "csv"  # or "abf"
        self.traces: List[Tuple[np.ndarray, np.ndarray]] = []
        self.abf = None  # pyabf.ABF instance if mode == abf
        self.fs: Optional[float] = None  # sampling rate

        # Runtime state
        self.peaks_removed: set[int] = set()
        self.curated_peaks: Optional[np.ndarray] = None
        self.current_file_path: Optional[Path] = None

        # UI state
        self._table_dialog: Optional[PeaksTableDialog] = None

        # Cached data for performance
        self._cached_spectrogram = None
        self._cached_params = None

        # Build UI elements
        self._build_ui()
        self._welcome()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        vbox = QVBoxLayout(central)

        # ── Menu bar & quick‑load ─────────────────────────────────────
        bar = QMenuBar(self)
        file_menu = bar.addMenu("&File")
        act_open = file_menu.addAction("Open …")
        act_open.triggered.connect(self._ask_open_file)
        act_export = file_menu.addAction("Export CSV...")
        act_export.triggered.connect(self._export_csv)
        
        view_menu = bar.addMenu("&View")
        act_table = view_menu.addAction("Show Peaks Table")
        act_table.triggered.connect(self._show_peaks_table)
        act_timeline = view_menu.addAction("Show Timeline")
        act_timeline.triggered.connect(self._show_timeline)
        
        debug_menu = bar.addMenu("&Debug")
        act_signal_info = debug_menu.addAction("Signal Info...")
        act_signal_info.triggered.connect(self._show_signal_info)
        
        self.setMenuBar(bar)

        # ── Control row ───────────────────────────────────────────────
        ctrl = QHBoxLayout()
        vbox.addLayout(ctrl)

        # Trace selector (CSV)
        self.cb_trace = QComboBox()
        self.cb_trace.currentIndexChanged.connect(self._param_changed)
        ctrl.addWidget(QLabel("Trace:"))
        ctrl.addWidget(self.cb_trace)

        # Channel & sweep (ABF)
        self.sb_chan = QSpinBox(enabled=False)
        self.sb_sweep = QSpinBox(enabled=False)
        self.sb_chan.valueChanged.connect(self._param_changed)
        self.sb_sweep.valueChanged.connect(self._param_changed)
        ctrl.addWidget(QLabel("Chan:"))
        ctrl.addWidget(self.sb_chan)
        ctrl.addWidget(QLabel("Sweep:"))
        ctrl.addWidget(self.sb_sweep)

        # Peak detection params
        self.sb_cut = QDoubleSpinBox(decimals=2, minimum=0.01, maximum=10, value=0.2, singleStep=0.01)
        self.sb_prom = QDoubleSpinBox(decimals=3, minimum=0.001, maximum=10, value=0.05, singleStep=0.005)
        self.sb_dist = QSpinBox(minimum=5, maximum=2000, value=50, singleStep=5)
        for w in (self.sb_cut, self.sb_prom, self.sb_dist):
            w.valueChanged.connect(self._param_changed)
        ctrl.addWidget(QLabel("HP (Hz):"))
        ctrl.addWidget(self.sb_cut)
        ctrl.addWidget(QLabel("Prom:"))
        ctrl.addWidget(self.sb_prom)
        ctrl.addWidget(QLabel("Min dist (ms):"))
        ctrl.addWidget(self.sb_dist)

        # Peak width filtering
        self.sb_min_width = QSpinBox(minimum=1, maximum=1000, value=5, singleStep=1)
        self.sb_max_width = QSpinBox(minimum=1, maximum=1000, value=500, singleStep=10)
        for w in (self.sb_min_width, self.sb_max_width):
            w.valueChanged.connect(self._param_changed)
        ctrl.addWidget(QLabel("Width (ms):"))
        ctrl.addWidget(self.sb_min_width)
        ctrl.addWidget(QLabel("to"))
        ctrl.addWidget(self.sb_max_width)

        # Peak polarity
        self.cb_polarity = QComboBox()
        self.cb_polarity.addItems(["Positive", "Negative", "Both"])
        self.cb_polarity.currentTextChanged.connect(self._param_changed)
        ctrl.addWidget(QLabel("Peaks:"))
        ctrl.addWidget(self.cb_polarity)

        # Add line break for second row of controls
        ctrl.addWidget(QLabel(""))  # Spacer
        
        # Second row of controls - Signal processing
        ctrl2 = QHBoxLayout()
        vbox.addLayout(ctrl2)

        # Smoothing control
        self.chk_smooth = QCheckBox("Smooth")
        self.chk_smooth.stateChanged.connect(self._param_changed)
        self.sb_smooth_window = QSpinBox(minimum=3, maximum=501, value=5, singleStep=2)
        self.sb_smooth_window.valueChanged.connect(self._ensure_odd_window)
        self.sb_smooth_window.setToolTip("Smoothing window size (must be odd)")
        ctrl2.addWidget(self.chk_smooth)
        ctrl2.addWidget(self.sb_smooth_window)

        # 50Hz notch filter
        self.chk_notch = QCheckBox("50Hz Filter")
        self.chk_notch.stateChanged.connect(self._param_changed)
        self.sb_notch_freq = QDoubleSpinBox(decimals=1, minimum=40.0, maximum=70.0, value=50.0, singleStep=0.1)
        self.sb_notch_freq.valueChanged.connect(self._param_changed)
        self.sb_notch_freq.setToolTip("Notch filter frequency")
        ctrl2.addWidget(self.sb_notch_freq)
        ctrl2.addWidget(QLabel("Hz"))

        # Quality factor for notch filter
        ctrl2.addWidget(QLabel("Q:"))
        self.sb_notch_q = QDoubleSpinBox(decimals=1, minimum=5.0, maximum=50.0, value=30.0, singleStep=1.0)
        self.sb_notch_q.valueChanged.connect(self._param_changed)
        self.sb_notch_q.setToolTip("Notch filter quality factor (higher = narrower)")
        ctrl2.addWidget(self.sb_notch_q)

        # Spectrogram / band‑power controls
        self.sb_lowF = QDoubleSpinBox(decimals=2, minimum=0, maximum=100, value=0.0, singleStep=0.1)
        self.sb_hiF = QDoubleSpinBox(decimals=2, minimum=0.1, maximum=500, value=10.0, singleStep=0.1)
        for w in (self.sb_lowF, self.sb_hiF):
            w.valueChanged.connect(self._update_plots)
        self.chk_spec = QCheckBox("Spectrogram")
        self.chk_spec.stateChanged.connect(self._toggle_spectrogram)
        ctrl.addWidget(QLabel("Low F:"))
        ctrl.addWidget(self.sb_lowF)
        ctrl.addWidget(QLabel("High F:"))
        ctrl.addWidget(self.sb_hiF)
        # Add units conversion controls
        self.cb_units = QComboBox()
        self.cb_units.addItems(["Auto", "mV", "µV", "V"])
        self.cb_units.setCurrentText("Auto")
        self.cb_units.currentTextChanged.connect(self._update_plots)
        self.cb_units.setToolTip("Units for amplitude display and export")
        
        ctrl.addWidget(QLabel("Units:"))
        ctrl.addWidget(self.cb_units)

        ctrl.addStretch(1)

        # Action buttons
        self.btn_load = QPushButton("➕ Load")
        self.btn_load.clicked.connect(self._ask_open_file)
        self.btn_reset = QPushButton("Reset")
        self.btn_reset.clicked.connect(self._reset_peaks)
        self.btn_table = QPushButton("📋 Table")
        self.btn_table.clicked.connect(self._show_peaks_table)
        self.btn_timeline = QPushButton("📊 Timeline")
        self.btn_timeline.clicked.connect(self._show_timeline)
        self.btn_export = QPushButton("💾 Export CSV")
        self.btn_export.clicked.connect(self._export_csv)
        
        ctrl.addWidget(self.btn_load)
        ctrl.addWidget(self.btn_reset)
        ctrl.addWidget(self.btn_table)
        ctrl.addWidget(self.btn_timeline)
        ctrl.addWidget(self.btn_export)

        # ── Plots: 0 trace, 1 power, 2 spec, 3 peaks ───────────────────
        self.glw = pg.GraphicsLayoutWidget()
        vbox.addWidget(self.glw)

        # Raw/filtered trace
        self.plot_trace = self.glw.addPlot(row=0, col=0)
        self.plot_trace.setLabel("left", "mV (HP)")
        self.plot_trace.setLabel("bottom", "Time", units="s")
        self.scatter = pg.ScatterPlotItem()
        self.scatter.sigClicked.connect(self._peak_clicked)
        self.plot_trace.addItem(self.scatter)

        # Band‑power trace (mean power in [lowF, hiF])
        self.plot_power = self.glw.addPlot(row=1, col=0)
        self.plot_power.setMaximumHeight(120)
        self.plot_power.setLabel("left", "Band power (a.u.)")
        self.plot_power.setXLink(self.plot_trace)

        # Spectrogram (hidden by default)
        self.plot_spec = self.glw.addPlot(row=2, col=0)
        self.plot_spec.hide()
        self.plot_spec.setXLink(self.plot_trace)
        self.plot_spec.setLabel("left", "Frequency", units="Hz")
        self._spec_img = pg.ImageItem()
        self.plot_spec.addItem(self._spec_img)

        # Peaks timeline (appears after export)
        self.plot_peaks = self.glw.addPlot(row=3, col=0)
        self.plot_peaks.hide()
        self.plot_peaks.setLabel("left", "Peaks")
        self.plot_peaks.setXLink(self.plot_trace)
        self._peak_timeline = pg.ScatterPlotItem(size=6, pen=None, brush=pg.mkBrush(255, 128, 0, 160))
        self.plot_peaks.addItem(self._peak_timeline)

    def _welcome(self):
        """Show welcome message in empty state."""
        self.plot_trace.setTitle("Welcome! Click '➕ Load' to open .csv or .abf files")

    # ------------------------------------------------------------------
    # File handling
    # ------------------------------------------------------------------

    def _ask_open_file(self):
        fname, _ = QFileDialog.getOpenFileName(
            self, "Open", "", "Data files (*.csv *.abf);;CSV files (*.csv);;ABF files (*.abf)"
        )
        if fname:
            self._load_file(Path(fname))

    def _load_file(self, path: Path):
        """Load file with error handling."""
        try:
            # Clear previous state
            self.peaks_removed.clear()
            self.curated_peaks = None
            self.current_file_path = path
            self._cached_spectrogram = None
            self._cached_params = None
            
            if path.suffix.lower() == ".csv":
                self.mode = "csv"
                self._load_csv(path)
            elif path.suffix.lower() == ".abf":
                if pyabf is None:
                    QMessageBox.critical(self, "pyABF missing", "Install pyabf: pip install pyabf")
                    return
                self.mode = "abf"
                self._load_abf(path)
            else:
                QMessageBox.warning(self, "Unsupported", f"Unrecognised file type: {path.suffix}")
                return
                
            # Update plots after successful load
            self._update_plots()
            
        except Exception as e:
            QMessageBox.critical(self, "Error loading file", f"Failed to load {path.name}:\n{str(e)}")
            print(f"Detailed error: {e}")  # For debugging

    def _load_csv(self, path: Path):
        """Load CSV file - expects time, voltage columns."""
        df = pd.read_csv(path)
        
        if df.shape[1] < 2:
            raise ValueError("CSV must have at least 2 columns (time, voltage)")
        
        # Handle different CSV formats
        if df.shape[1] == 2:
            # Single trace
            self.traces = [(df.iloc[:, 0].values, df.iloc[:, 1].values)]
            trace_names = ["Recording 1"]
        elif df.shape[1] >= 4:
            # Multiple traces (assume paired columns)
            self.traces = [
                (df.iloc[:, 0].values, df.iloc[:, 1].values),
                (df.iloc[:, 2].values, df.iloc[:, 3].values)
            ]
            trace_names = ["Recording 1", "Recording 2"]
        else:
            raise ValueError("Unexpected CSV format")
        
        self.cb_trace.clear()
        self.cb_trace.addItems(trace_names)
        self.cb_trace.setEnabled(True)
        self.sb_chan.setEnabled(False)
        self.sb_sweep.setEnabled(False)
        
        # Calculate sampling rate
        t = self.traces[0][0]
        if len(t) > 1:
            self.fs = float(1 / np.mean(np.diff(t)))
        else:
            self.fs = 1000.0  # Default fallback
            
        self.setWindowTitle(f"Peak Curator — {path.name}")

    def _load_abf(self, path: Path):
        """Load ABF file - timing complexity handled during export."""
        try:
            self.abf = pyabf.ABF(str(path))
            self.fs = float(self.abf.dataRate)
            
            # Enable channel & sweep selectors
            self.sb_chan.setEnabled(True)
            self.sb_sweep.setEnabled(True)
            self.sb_chan.setRange(0, self.abf.channelCount - 1)
            self.sb_chan.setValue(0)
            self.sb_sweep.setRange(0, self.abf.sweepCount - 1) 
            self.sb_sweep.setValue(0)
            
            # Disable trace selector and update display
            self.cb_trace.clear()
            self.cb_trace.addItem(f"{path.stem}")
            self.cb_trace.setEnabled(False)
            
            self.setWindowTitle(f"Peak Curator — {path.name}")
            
        except Exception as e:
            raise Exception(f"Failed to load ABF file: {str(e)}")

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------

    def _get_absolute_timing(self, relative_times: np.ndarray, sweep_num: int) -> Tuple[np.ndarray, str]:
        """Calculate absolute timing from relative times within a sweep.
        
        For ABF files, converts relative time to absolute experiment time.
        Example: Peak at 7s in sweep 4 with 30s sweeps = (30s × 3) + 7s = 97s
        
        Returns:
            (absolute_times, method_used)
        """
        if self.mode == "csv":
            return relative_times, "csv_native"
        
        if self.abf is None:
            return relative_times, "no_abf"
        
        # Method 1: Try sweepTimesSec (most accurate)
        if hasattr(self.abf, 'sweepTimesSec') and len(self.abf.sweepTimesSec) > sweep_num:
            try:
                sweep_start = self.abf.sweepTimesSec[sweep_num]
                return sweep_start + relative_times, "sweepTimesSec"
            except (IndexError, TypeError):
                pass
        
        # Method 2: Try sweepLengthSec
        if hasattr(self.abf, 'sweepLengthSec'):
            try:
                sweep_start = sweep_num * self.abf.sweepLengthSec
                return sweep_start + relative_times, "sweepLengthSec"
            except (AttributeError, TypeError):
                pass
        
        # Method 3: Calculate from sweep data
        try:
            sweep_duration = len(self.abf.sweepX) / self.abf.dataRate
            sweep_start = sweep_num * sweep_duration
            return sweep_start + relative_times, "calculated"
        except (AttributeError, TypeError, ZeroDivisionError):
            pass
        
        # Fallback: return relative times
        return relative_times, "relative_only"
    
    def _get_current_peaks_data(self) -> dict:
        """Get comprehensive data for current peaks."""
        if self.curated_peaks is None or len(self.curated_peaks) == 0:
            return {}
        
        # Get current trace data
        t_relative, v_original = self._get_current_trace()
        if len(t_relative) == 0:
            return {}
        
        # Apply complete signal processing pipeline (same as display)
        v_processed = self._process_signal(v_original)
        
        # Peak times from relative trace
        peak_times_rel = t_relative[self.curated_peaks]
        
        # Calculate amplitudes from processed signal (matches display)
        peak_amplitudes_corrected = self._calculate_peak_amplitudes(v_processed, self.curated_peaks)
        
        # Calculate peak widths
        peak_widths = self._calculate_peak_widths(v_processed, self.curated_peaks)
        
        # Apply units conversion to amplitudes
        peak_amplitudes_converted, units_label = self._convert_units(peak_amplitudes_corrected)
        
        # Calculate absolute timing
        current_sweep = self.sb_sweep.value() if self.mode == "abf" else 0
        peak_times_abs, timing_method = self._get_absolute_timing(peak_times_rel, current_sweep)
        
        # Build comprehensive data dictionary
        peaks_data = {
            'Peak_Index': self.curated_peaks,
            'Time_Relative_s': peak_times_rel,
            'Time_Absolute_s': peak_times_abs,
            f'Amplitude_{units_label}': peak_amplitudes_converted,
            'Width_ms': peak_widths * 1000,  # Convert to milliseconds
            'Timing_Method': [timing_method] * len(self.curated_peaks)
        }
        
        # Add ABF-specific information
        if self.mode == "abf":
            peaks_data['Sweep_Number'] = [current_sweep] * len(self.curated_peaks)
            peaks_data['Channel_Number'] = [self.sb_chan.value()] * len(self.curated_peaks)
            peaks_data['Sampling_Rate_Hz'] = [self.fs] * len(self.curated_peaks)
        
        return peaks_data
    
    def _calculate_peak_widths(self, signal: np.ndarray, peak_indices: np.ndarray) -> np.ndarray:
        """Calculate peak widths at half maximum (FWHM) in seconds."""
        if len(peak_indices) == 0:
            return np.array([])
        
        widths = []
        
        for peak_idx in peak_indices:
            peak_value = signal[peak_idx]
            
            # Calculate local baseline around peak
            baseline_window = max(20, int(0.1 * self.fs))  # 100ms window
            baseline_distance = max(10, baseline_window // 4)
            
            # Get baseline regions
            left_start = max(0, peak_idx - baseline_window - baseline_distance)
            left_end = max(0, peak_idx - baseline_distance)
            right_start = min(len(signal), peak_idx + baseline_distance)
            right_end = min(len(signal), peak_idx + baseline_window + baseline_distance)
            
            # Calculate baseline
            baseline_values = []
            if left_end > left_start:
                baseline_values.extend(signal[left_start:left_end])
            if right_end > right_start:
                baseline_values.extend(signal[right_start:right_end])
            
            if baseline_values:
                baseline = np.median(baseline_values)
            else:
                baseline = np.mean(signal[max(0, peak_idx-5):min(len(signal), peak_idx+6)])
            
            # Half maximum level
            half_max = baseline + (peak_value - baseline) / 2
            
            # Find points where signal crosses half maximum
            # Search window around peak
            search_window = min(peak_idx, len(signal) - peak_idx - 1, int(0.5 * self.fs))  # 500ms max
            
            left_idx = peak_idx
            right_idx = peak_idx
            
            # Find left crossing
            for i in range(peak_idx, max(0, peak_idx - search_window), -1):
                if signal[i] <= half_max:
                    left_idx = i
                    break
            
            # Find right crossing  
            for i in range(peak_idx, min(len(signal), peak_idx + search_window)):
                if signal[i] <= half_max:
                    right_idx = i
                    break
            
            # Calculate width in seconds
            width_samples = right_idx - left_idx
            width_seconds = width_samples / self.fs if self.fs else 0
            
            widths.append(width_seconds)
        
        return np.array(widths)
    
    def _calculate_peak_amplitudes(self, signal: np.ndarray, peak_indices: np.ndarray) -> np.ndarray:
        """Calculate baseline-corrected peak amplitudes.
        
        Uses local baseline estimation around each peak for more accurate amplitude measurement.
        """
        if len(peak_indices) == 0:
            return np.array([])
        
        amplitudes = []
        
        # Window size for baseline calculation (in samples)
        baseline_window = max(10, int(0.1 * self.fs))  # 100ms or 10 samples, whichever is larger
        
        for peak_idx in peak_indices:
            peak_value = signal[peak_idx]
            
            # Define baseline region (before and after peak, but not too close)
            baseline_distance = max(5, baseline_window // 4)
            
            # Get baseline regions (avoiding the peak itself)
            left_start = max(0, peak_idx - baseline_window - baseline_distance)
            left_end = max(0, peak_idx - baseline_distance)
            right_start = min(len(signal), peak_idx + baseline_distance)
            right_end = min(len(signal), peak_idx + baseline_window + baseline_distance)
            
            # Calculate baseline from regions around the peak
            baseline_values = []
            if left_end > left_start:
                baseline_values.extend(signal[left_start:left_end])
            if right_end > right_start:
                baseline_values.extend(signal[right_start:right_end])
            
            if baseline_values:
                # Use median for robust baseline estimation
                baseline = np.median(baseline_values)
                amplitude = peak_value - baseline
            else:
                # Fallback: use local mean if no baseline region available
                window_start = max(0, peak_idx - 5)
                window_end = min(len(signal), peak_idx + 6)
                local_baseline = np.mean(signal[window_start:window_end])
                amplitude = peak_value - local_baseline
            
            amplitudes.append(amplitude)
        
        return np.array(amplitudes)
    
    def _convert_units(self, values: np.ndarray, to_unit: str = None) -> Tuple[np.ndarray, str]:
        """Convert amplitude units and return (converted_values, unit_label).
        
        Auto mode tries to detect appropriate units based on signal range.
        """
        if to_unit is None:
            to_unit = self.cb_units.currentText()
        
        if to_unit == "Auto":
            # Auto-detect based on signal magnitude
            max_val = np.max(np.abs(values)) if len(values) > 0 else 1.0
            
            if max_val > 1000:  # Likely µV, convert to mV
                return values / 1000, "mV"
            elif max_val > 10:  # Likely mV, keep as is
                return values, "mV"  
            elif max_val > 0.01:  # Likely V, convert to mV
                return values * 1000, "mV"
            else:  # Very small values, might be V
                return values * 1000, "mV"
        
        elif to_unit == "µV":
            return values, "µV"
        elif to_unit == "mV": 
            return values, "mV"
        elif to_unit == "V":
            return values, "V"
        
        return values, "units"
    
    def _debug_signal_info(self, signal: np.ndarray, label: str = "Signal"):
        """Print debugging information about signal characteristics."""
        if len(signal) == 0:
            return
            
        print(f"\n=== {label} Debug Info ===")
        print(f"  Length: {len(signal)}")
        print(f"  Range: {np.min(signal):.6f} to {np.max(signal):.6f}")
        print(f"  Mean: {np.mean(signal):.6f}")
        print(f"  Std: {np.std(signal):.6f}")
        print(f"  RMS: {np.sqrt(np.mean(signal**2)):.6f}")
        print(f"  Units suggestion: ", end="")
        
        max_val = np.max(np.abs(signal))
        if max_val > 1000:
            print("Likely µV (very large values)")
        elif max_val > 10:
            print("Likely mV (moderate values)")
        elif max_val > 0.01:
            print("Good mV range")
        else:
            print("Likely V (very small values)")
        print("========================\n")
    
    def _get_current_trace(self) -> Tuple[np.ndarray, np.ndarray]:
        """Get current trace data based on UI selections."""
        try:
            if self.mode == "csv":
                idx = max(0, min(self.cb_trace.currentIndex(), len(self.traces) - 1))
                return self.traces[idx]
            
            # ABF: Use simple relative timing for display
            chan, sweep = self.sb_chan.value(), self.sb_sweep.value()
            if self.abf is None:
                return np.array([]), np.array([])
                
            self.abf.setSweep(sweep, channel=chan)
            return self.abf.sweepX, self.abf.sweepY
            
        except Exception as e:
            print(f"Error getting trace data: {e}")
            return np.array([]), np.array([])

    @staticmethod
    def _highpass(x: np.ndarray, fs: float, cutoff: float, order: int = 3) -> np.ndarray:
        """Apply high-pass Butterworth filter."""
        if cutoff >= fs / 2:
            cutoff = fs / 2 - 0.1  # Avoid Nyquist frequency issues
        b, a = signal.butter(order, cutoff / (0.5 * fs), "highpass")
        return signal.filtfilt(b, a, x)

    @staticmethod
    def _notch_filter(x: np.ndarray, fs: float, freq: float, quality: float = 30.0) -> np.ndarray:
        """Apply notch filter to remove specific frequency (e.g., 50Hz power line noise)."""
        if freq >= fs / 2:
            return x  # Can't filter above Nyquist
        
        # Calculate filter parameters
        w0 = freq / (fs / 2)  # Normalized frequency
        b, a = signal.iirnotch(w0, quality)
        return signal.filtfilt(b, a, x)

    @staticmethod
    def _smooth_signal(x: np.ndarray, window_length: int = 5, polyorder: int = 2) -> np.ndarray:
        """Apply Savitzky-Golay smoothing filter."""
        if len(x) < window_length:
            return x  # Can't smooth if signal is shorter than window
        
        # Ensure window length is odd
        if window_length % 2 == 0:
            window_length += 1
        
        # Ensure polynomial order is less than window length
        polyorder = min(polyorder, window_length - 1)
        
        return signal.savgol_filter(x, window_length, polyorder)

    def _process_signal(self, x: np.ndarray) -> np.ndarray:
        """Apply complete signal processing pipeline."""
        processed = x.copy()
        
        # Step 1: High-pass filter (always applied)
        cutoff = self.sb_cut.value()
        processed = self._highpass(processed, self.fs, cutoff)
        
        # Step 2: Notch filter (if enabled)
        if self.chk_notch.isChecked():
            notch_freq = self.sb_notch_freq.value()
            notch_q = self.sb_notch_q.value()
            processed = self._notch_filter(processed, self.fs, notch_freq, notch_q)
        
        # Step 3: Smoothing (if enabled)
        if self.chk_smooth.isChecked():
            smooth_window = self.sb_smooth_window.value()
            processed = self._smooth_signal(processed, smooth_window)
        
        return processed

    def _detect_peaks(self, trace_processed: np.ndarray, prom: float, dist_ms: int):
        """Detect peaks with polarity and width filtering."""
        if self.fs is None:
            return np.array([]), {}
        
        dist = int(dist_ms / 1000 * self.fs)
        polarity = self.cb_polarity.currentText()
        
        if polarity == "Positive":
            # Detect positive peaks
            peaks, properties = signal.find_peaks(trace_processed, prominence=prom, distance=dist)
        elif polarity == "Negative":
            # Detect negative peaks (invert signal)
            peaks, properties = signal.find_peaks(-trace_processed, prominence=prom, distance=dist)
        else:  # Both
            # Detect both positive and negative peaks
            pos_peaks, pos_props = signal.find_peaks(trace_processed, prominence=prom, distance=dist)
            neg_peaks, neg_props = signal.find_peaks(-trace_processed, prominence=prom, distance=dist)
            
            # Combine peaks and sort by position
            all_peaks = np.concatenate([pos_peaks, neg_peaks])
            sort_idx = np.argsort(all_peaks)
            peaks = all_peaks[sort_idx]
            
            # Combine properties (simplified)
            properties = {'prominences': np.concatenate([pos_props.get('prominences', []), 
                                                       neg_props.get('prominences', [])])[sort_idx]}
        
        # Filter by width if we have peaks
        if len(peaks) > 0:
            peaks = self._filter_peaks_by_width(trace_processed, peaks)
        
        return peaks, properties

    def _filter_peaks_by_width(self, signal: np.ndarray, peaks: np.ndarray) -> np.ndarray:
        """Filter peaks based on width criteria."""
        if len(peaks) == 0:
            return peaks
        
        min_width_ms = self.sb_min_width.value()
        max_width_ms = self.sb_max_width.value()
        
        # Convert to seconds
        min_width_s = min_width_ms / 1000
        max_width_s = max_width_ms / 1000
        
        # Calculate widths for all peaks
        widths = self._calculate_peak_widths(signal, peaks)
        
        # Filter peaks based on width
        width_mask = (widths >= min_width_s) & (widths <= max_width_s)
        filtered_peaks = peaks[width_mask]
        
        return filtered_peaks

    def _compute_spectrogram(self, trace_hp: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Compute spectrogram with caching."""
        current_params = (len(trace_hp), self.fs)
        
        if (self._cached_spectrogram is not None and 
            self._cached_params == current_params):
            return self._cached_spectrogram
        
        if self.fs is None:
            return np.array([]), np.array([]), np.array([[]])
        
        nperseg = min(int(0.2 * self.fs), len(trace_hp) // 4)
        if nperseg < 4:
            nperseg = 4
            
        f, tt, Sxx = signal.spectrogram(trace_hp, self.fs, nperseg=nperseg)
        
        # Cache results
        self._cached_spectrogram = (f, tt, Sxx)
        self._cached_params = current_params
        
        return f, tt, Sxx

    def _compute_band_power(self, f: np.ndarray, tt: np.ndarray, Sxx: np.ndarray, 
                           low_f: float, hi_f: float) -> np.ndarray:
        """Compute band power in frequency range."""
        if len(f) == 0 or len(Sxx) == 0:
            return np.array([])
        
        # Find frequency indices
        f_mask = (f >= low_f) & (f <= hi_f)
        if not np.any(f_mask):
            return np.zeros(len(tt))
        
        # Average power in frequency band
        band_power = np.mean(Sxx[f_mask, :], axis=0)
        return band_power

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _param_changed(self, *_):
        """Handle parameter changes."""
        self.peaks_removed.clear()
        self._update_plots()

    def _ensure_odd_window(self):
        """Ensure smoothing window is always odd."""
        value = self.sb_smooth_window.value()
        if value % 2 == 0:
            self.sb_smooth_window.setValue(value + 1)
        else:
            self._param_changed()

    def _reset_peaks(self):
        """Reset all removed peaks."""
        self.peaks_removed.clear()
        self._update_plots()

    def _peak_clicked(self, scatter, points):
        """Handle peak clicks for removal."""
        for pt in points:
            peak_idx = int(pt.data())
            if peak_idx in self.peaks_removed:
                self.peaks_removed.remove(peak_idx)  # Un-remove if clicked again
            else:
                self.peaks_removed.add(peak_idx)
        self._update_plots()

    def _toggle_spectrogram(self):
        """Toggle spectrogram visibility."""
        if self.chk_spec.isChecked():
            self.plot_spec.show()
        else:
            self.plot_spec.hide()
        self._update_plots()

    # ------------------------------------------------------------------
    # Main plot refresh
    # ------------------------------------------------------------------

    def _update_plots(self):
        """Main plotting function - updates all plots."""
        if self.fs is None:
            return

        try:
            # Get parameters
            prom = self.sb_prom.value()
            dist_ms = self.sb_dist.value()
            lowF = self.sb_lowF.value()
            hiF = self.sb_hiF.value()

            # Get and process data through complete pipeline
            t, v_original = self._get_current_trace()
            if len(t) == 0 or len(v_original) == 0:
                self.plot_trace.clear()
                self.plot_power.clear()
                return
                
            # Apply complete signal processing pipeline
            v_processed = self._process_signal(v_original)
            
            # Detect peaks on processed signal
            peaks, properties = self._detect_peaks(v_processed, prom, dist_ms)
            
            # Apply peak removal
            keep = np.ones_like(peaks, dtype=bool)
            for idx in self.peaks_removed:
                if idx < len(keep):
                    keep[idx] = False
            self.curated_peaks = peaks[keep]

            # Update plots
            self._update_trace_plot(t, v_processed, peaks, keep)
            self._update_frequency_plots(t, v_processed, lowF, hiF)
            self._update_info(len(peaks), len(self.curated_peaks))
            
            # Auto-refresh table if it's open and auto-refresh is enabled
            self._maybe_refresh_table()
            
        except Exception as e:
            print(f"Error updating plots: {e}")
            # Clear plots on error to prevent further issues
            self.plot_trace.clear()
            self.plot_power.clear()
    
    def _maybe_refresh_table(self):
        """Refresh table dialog if it's open and auto-refresh is enabled."""
        if (self._table_dialog is not None and 
            self._table_dialog.isVisible() and 
            self._table_dialog.chk_auto_refresh.isChecked()):
            self._table_dialog.refresh_data()

    def _update_trace_plot(self, t: np.ndarray, v_processed: np.ndarray, 
                          peaks: np.ndarray, keep: np.ndarray):
        """Update the main trace plot."""
        self.plot_trace.clear()
        self.plot_trace.addItem(self.scatter)
        
        # Plot processed trace
        self.plot_trace.plot(t, v_processed, pen=pg.mkPen("#268bd2", width=1))
        
        # Plot peaks with different colors for kept/removed
        if len(peaks) > 0:
            kept_spots = []
            removed_spots = []
            
            for i, p in enumerate(peaks):
                spot_data = {"pos": (t[p], v_processed[p]), "data": i}
                if keep[i]:
                    kept_spots.append(spot_data)
                else:
                    removed_spots.append(spot_data)
            
            # Set scatter data for kept peaks
            self.scatter.setData(kept_spots, 
                               brush=pg.mkBrush(255, 0, 0, 180), 
                               size=8, 
                               pen=pg.mkPen(255, 255, 255, 200))
            
            # Add removed peaks as separate scatter
            if removed_spots:
                removed_scatter = pg.ScatterPlotItem()
                removed_scatter.setData(removed_spots,
                                      brush=pg.mkBrush(128, 128, 128, 100),
                                      size=6,
                                      pen=pg.mkPen(128, 128, 128, 150))
                self.plot_trace.addItem(removed_scatter)
        
        # Update y-axis label to show active filters
        _, units_label = self._convert_units(np.array([0]))
        filter_desc = self._get_filter_description()
        self.plot_trace.setLabel("left", f"{units_label} ({filter_desc})")

    def _get_filter_description(self) -> str:
        """Generate description of active filters for plot labels."""
        filters = []
        
        # High-pass filter (always active)
        cutoff = self.sb_cut.value()
        filters.append(f"HP {cutoff}Hz")
        
        # Notch filter
        if self.chk_notch.isChecked():
            notch_freq = self.sb_notch_freq.value()
            filters.append(f"Notch {notch_freq}Hz")
        
        # Smoothing
        if self.chk_smooth.isChecked():
            smooth_window = self.sb_smooth_window.value()
            filters.append(f"Smooth {smooth_window}")
        
        # Peak type
        polarity = self.cb_polarity.currentText()
        if polarity != "Positive":
            filters.append(f"{polarity} peaks")
        
        return ", ".join(filters)

    def _update_frequency_plots(self, t: np.ndarray, v_hp: np.ndarray, 
                               lowF: float, hiF: float):
        """Update spectrogram and band power plots."""
        try:
            # Compute spectrogram
            f, tt, Sxx = self._compute_spectrogram(v_hp)
            
            if len(f) == 0 or len(tt) == 0:
                return
            
            # Update band power plot
            band_power = self._compute_band_power(f, tt, Sxx, lowF, hiF)
            if len(band_power) > 0 and len(tt) > 1:
                # Interpolate to match time base
                t_interp = np.interp(tt, [0, len(v_hp) / self.fs], [t[0], t[-1]])
                self.plot_power.clear()
                self.plot_power.plot(t_interp, band_power, 
                                   pen=pg.mkPen("#d33682", width=2))
            
            # Update spectrogram if visible
            if self.chk_spec.isChecked() and len(Sxx) > 0 and len(tt) > 1:
                # Time interpolation for spectrogram
                t_spec = np.interp(tt, [0, len(v_hp) / self.fs], [t[0], t[-1]])
                
                # Set image data
                self._spec_img.setImage(10 * np.log10(Sxx + 1e-10))  # dB scale
                
                # Set proper scaling and positioning
                self._spec_img.setRect(pg.QtCore.QRectF(
                    t_spec[0], f[0], 
                    t_spec[-1] - t_spec[0], f[-1] - f[0]
                ))
                
        except Exception as e:
            print(f"Error updating frequency plots: {e}")
            # Clear plots on error
            self.plot_power.clear()

    def _update_info(self, total_peaks: int, curated_peaks: int):
        """Update window title with peak count info."""
        if self.current_file_path:
            title = f"Peak Curator — {self.current_file_path.name} "
            title += f"[{curated_peaks}/{total_peaks} peaks]"
            self.setWindowTitle(title)
    
    def _show_signal_info(self):
        """Show detailed signal information for debugging amplitude issues."""
        if self.fs is None:
            QMessageBox.information(self, "No Data", "No file currently loaded.")
            return
        
        try:
            # Get current trace data
            t_relative, v_original = self._get_current_trace()
            if len(v_original) == 0:
                QMessageBox.warning(self, "No Data", "No trace data available.")
                return
            
            # Get processed signal (what's displayed)
            v_processed = self._process_signal(v_original)
            
            # Calculate statistics
            orig_stats = {
                'Min': np.min(v_original),
                'Max': np.max(v_original), 
                'Mean': np.mean(v_original),
                'Std': np.std(v_original),
                'Range': np.ptp(v_original),
                'RMS': np.sqrt(np.mean(v_original**2))
            }
            
            proc_stats = {
                'Min': np.min(v_processed),
                'Max': np.max(v_processed),
                'Mean': np.mean(v_processed), 
                'Std': np.std(v_processed),
                'Range': np.ptp(v_processed),
                'RMS': np.sqrt(np.mean(v_processed**2))
            }
            
            # Units suggestions
            max_orig = np.max(np.abs(v_original))
            if max_orig > 1000:
                units_suggestion = "µV (convert to mV by dividing by 1000)"
            elif max_orig > 10:
                units_suggestion = "mV (good range)"
            elif max_orig > 0.01:
                units_suggestion = "mV or V (check source)"
            else:
                units_suggestion = "V (convert to mV by multiplying by 1000)"
            
            # Build info text
            info_text = f"Signal Analysis\n"
            info_text += f"{'='*50}\n\n"
            info_text += f"File: {self.current_file_path.name if self.current_file_path else 'Unknown'}\n"
            info_text += f"Mode: {self.mode.upper()}\n"
            if self.mode == "abf":
                info_text += f"Channel: {self.sb_chan.value()}, Sweep: {self.sb_sweep.value()}\n"
            info_text += f"Sampling Rate: {self.fs:.1f} Hz\n"
            info_text += f"Duration: {len(v_original)/self.fs:.2f} s\n\n"
            
            info_text += f"ORIGINAL SIGNAL STATISTICS:\n"
            info_text += f"{'─'*30}\n"
            for key, value in orig_stats.items():
                info_text += f"{key:>8}: {value:>12.6f}\n"
            
            filter_desc = self._get_filter_description()
            info_text += f"\nPROCESSED SIGNAL STATISTICS ({filter_desc}):\n"
            info_text += f"{'─'*30}\n"
            for key, value in proc_stats.items():
                info_text += f"{key:>8}: {value:>12.6f}\n"
            
            info_text += f"\nUNITS RECOMMENDATION:\n"
            info_text += f"{'─'*30}\n"
            info_text += f"Based on signal range: {units_suggestion}\n"
            info_text += f"Current units setting: {self.cb_units.currentText()}\n\n"
            
            # Peak filtering info
            info_text += f"PEAK DETECTION SETTINGS:\n"
            info_text += f"{'─'*30}\n"
            info_text += f"Peak type: {self.cb_polarity.currentText()}\n"
            info_text += f"Prominence: {self.sb_prom.value()}\n"
            info_text += f"Min distance: {self.sb_dist.value()} ms\n"
            info_text += f"Width range: {self.sb_min_width.value()}-{self.sb_max_width.value()} ms\n\n"
            
            if self.curated_peaks is not None and len(self.curated_peaks) > 0:
                # Peak amplitude analysis - now from processed signal
                peak_amps_corrected = self._calculate_peak_amplitudes(v_processed, self.curated_peaks)
                peak_amps_converted, units_label = self._convert_units(peak_amps_corrected)
                peak_widths = self._calculate_peak_widths(v_processed, self.curated_peaks)
                
                info_text += f"PEAK MEASUREMENTS ({len(self.curated_peaks)} peaks):\n"
                info_text += f"{'─'*30}\n"
                info_text += f"Measured from: PROCESSED signal (displayed)\n"
                info_text += f"Min amplitude: {np.min(peak_amps_converted):.4f} {units_label}\n"
                info_text += f"Max amplitude: {np.max(peak_amps_converted):.4f} {units_label}\n"
                info_text += f"Mean amplitude: {np.mean(peak_amps_converted):.4f} {units_label}\n"
                info_text += f"Std amplitude: {np.std(peak_amps_converted):.4f} {units_label}\n"
                info_text += f"Min width: {np.min(peak_widths)*1000:.2f} ms\n"
                info_text += f"Max width: {np.max(peak_widths)*1000:.2f} ms\n"
                info_text += f"Mean width: {np.mean(peak_widths)*1000:.2f} ms\n"
                info_text += f"Std width: {np.std(peak_widths)*1000:.2f} ms\n"
            
            # Show in dialog
            msg = QMessageBox(self)
            msg.setWindowTitle("Signal Information")
            msg.setText(info_text)
            msg.setDetailedText("Use this information to check if amplitude units are correct.\n"
                              "If values seem too large/small, change the Units dropdown.")
            msg.exec_()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to analyze signal:\n{str(e)}")

    def closeEvent(self, event):
        """Handle main window close event."""
        # Close table dialog if open
        if self._table_dialog is not None:
            self._table_dialog.close()
        event.accept()

    # ------------------------------------------------------------------
    # Export functionality
    # ------------------------------------------------------------------

    def _show_peaks_table(self):
        """Show peaks in a non-modal table dialog."""
        # Create or show existing table dialog
        if self._table_dialog is None or not self._table_dialog.isVisible():
            self._table_dialog = PeaksTableDialog(self)
            self._table_dialog.show()
        else:
            # Bring existing dialog to front and refresh
            self._table_dialog.raise_()
            self._table_dialog.activateWindow()
            self._table_dialog.refresh_data()
    
    def _show_timeline(self):
        """Show peaks timeline plot."""
        peaks_data = self._get_current_peaks_data()
        
        if not peaks_data:
            QMessageBox.warning(self, "No Peaks", "No peaks detected for timeline!")
            return
        
        # Use absolute timing for timeline
        peak_times = peaks_data['Time_Absolute_s']
        timing_method = peaks_data['Timing_Method'][0]
        
        # Show timeline plot
        self.plot_peaks.show()
        spots = [{"pos": (t, 0.5)} for t in peak_times]
        self._peak_timeline.setData(spots)
        self.plot_peaks.setYRange(0, 1)
        self.plot_peaks.getAxis('left').setTicks([[(0.5, 'Peaks')]])
        
        # Update timeline title to show timing method
        self.plot_peaks.setTitle(f"Peaks Timeline (Timing: {timing_method})")
        
        QMessageBox.information(
            self, "Timeline Displayed", 
            f"Timeline shown with {len(peak_times)} peaks using {timing_method} timing."
        )
    
    def _export_csv(self):
        """Export detected peaks to CSV."""
        peaks_data = self._get_current_peaks_data()
        
        if not peaks_data:
            QMessageBox.warning(self, "No Peaks", "No peaks detected to export!")
            return

        try:
            # Ask for save location
            if self.current_file_path:
                default_name = self.current_file_path.stem + "_peaks.csv"
            else:
                default_name = "peaks.csv"
                
            fname, _ = QFileDialog.getSaveFileName(
                self, "Export Peaks CSV", default_name, "CSV files (*.csv)"
            )
            
            if not fname:
                return

            # Convert to DataFrame
            df = pd.DataFrame(peaks_data)
            
            # Generate metadata
            metadata = self._generate_export_metadata(peaks_data)
            
            # Write file with metadata
            with open(fname, 'w') as f:
                f.write('\n'.join(metadata))
                df.to_csv(f, index=False)
            
            QMessageBox.information(
                self, "Export Complete", 
                f"Exported {len(df)} peaks to:\n{fname}"
            )
            
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export peaks:\n{str(e)}")
    
    def _generate_export_metadata(self, peaks_data: dict) -> list:
        """Generate metadata comments for export file."""
        n_peaks = len(list(peaks_data.values())[0]) if peaks_data else 0
        timing_method = peaks_data.get('Timing_Method', ['unknown'])[0] if peaks_data else 'unknown'
        
        # Get current units and filter description
        _, units_label = self._convert_units(np.array([0]))
        filter_desc = self._get_filter_description()
        
        metadata = [
            f"# Peak Detection Results",
            f"# Generated by: Low-Mg²⁺ Peak Curator v1.4.1",
            f"# Export time: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"# Source file: {self.current_file_path.name if self.current_file_path else 'Unknown'}",
            f"#",
            f"# Signal Processing Pipeline:",
            f"# - High-pass filter: {self.sb_cut.value()} Hz",
        ]
        
        if self.chk_notch.isChecked():
            metadata.append(f"# - Notch filter: {self.sb_notch_freq.value()} Hz (Q={self.sb_notch_q.value()})")
        
        if self.chk_smooth.isChecked():
            metadata.append(f"# - Smoothing: Savitzky-Golay window={self.sb_smooth_window.value()}")
        
        metadata.extend([
            f"#",
            f"# Peak Detection Parameters:",
            f"# - Peak polarity: {self.cb_polarity.currentText()}",
            f"# - Prominence threshold: {self.sb_prom.value()} {units_label}",
            f"# - Minimum distance: {self.sb_dist.value()} ms",
            f"# - Width range: {self.sb_min_width.value()}-{self.sb_max_width.value()} ms",
            f"# - Sampling rate: {self.fs} Hz",
            f"# - Amplitude units: {units_label} (from processed signal)",
            f"# - Units conversion: {self.cb_units.currentText()}",
            f"#",
            f"# Results:",
            f"# - Total peaks exported: {n_peaks}",
            f"# - Peaks removed by user: {len(self.peaks_removed)}",
            f"# - Timing method: {timing_method}",
            f"#",
            f"# Measurement Details:",
            f"# - Processing: {filter_desc}",
            f"# - Amplitudes: Baseline-corrected from processed signal",
            f"# - Width: FWHM (Full Width at Half Maximum) with local baseline",
            f"# - Only peaks within width range [{self.sb_min_width.value()}-{self.sb_max_width.value()}ms] are included",
        ])
        
        if self.mode == "abf":
            metadata.extend([
                f"#",
                f"# ABF File Details:",
                f"# - Current sweep: {self.sb_sweep.value()}",
                f"# - Current channel: {self.sb_chan.value()}",
                f"# - Total sweeps: {self.abf.sweepCount if self.abf else 'Unknown'}",
                f"# - Total channels: {self.abf.channelCount if self.abf else 'Unknown'}",
                f"#",
                f"# Timing Explanation:",
                f"# - Time_Relative_s: Time within current sweep",
                f"# - Time_Absolute_s: Absolute time from experiment start",
                f"#   Example: Peak at 7s in sweep 4 with 30s sweeps = (30×3)+7 = 97s",
            ])
        
        metadata.append("")  # Empty line before data
        return metadata
        """Export detected peaks to CSV with comprehensive timing information."""
        if self.curated_peaks is None or len(self.curated_peaks) == 0:
            QMessageBox.warning(self, "No peaks", "No peaks detected to export!")
            return

        try:
            # Get current data
            t, v_hp = self._get_current_trace()
            peak_times = t[self.curated_peaks]
            peak_amplitudes = v_hp[self.curated_peaks]

            # Ask for save location
            if self.current_file_path:
                default_name = self.current_file_path.stem + "_peaks.csv"
            else:
                default_name = "peaks.csv"
                
            fname, _ = QFileDialog.getSaveFileName(
                self, "Export Peaks", default_name, "CSV files (*.csv)"
            )
            
            if not fname:
                return

            # Create base export data
            export_data = {
                'peak_index': self.curated_peaks,
                'time_relative_s': peak_times,
                'amplitude_mV': peak_amplitudes,
            }
            
            # Add comprehensive timing for ABF files
            if self.mode == "abf" and self.abf is not None:
                current_sweep = self.sb_sweep.value()
                current_channel = self.sb_chan.value()
                
                # Add sweep/channel info
                export_data['sweep_number'] = np.full_like(self.curated_peaks, current_sweep)
                export_data['channel_number'] = np.full_like(self.curated_peaks, current_channel)
                
                # Calculate absolute timing using multiple methods
                absolute_times = self._calculate_absolute_timing(peak_times, current_sweep)
                export_data.update(absolute_times)
                
            # Convert to DataFrame
            df = pd.DataFrame(export_data)
            
            # Add metadata as comments
            metadata = self._generate_export_metadata()
            
            # Write file with metadata
            with open(fname, 'w') as f:
                f.write('\n'.join(metadata))
                df.to_csv(f, index=False)

            # Show peaks timeline
            self._show_peaks_timeline(peak_times)
            
            QMessageBox.information(
                self, "Export Complete", 
                f"Exported {len(self.curated_peaks)} peaks to:\n{fname}"
            )
            
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export peaks:\n{str(e)}")

    def _calculate_absolute_timing(self, peak_times: np.ndarray, current_sweep: int) -> dict:
        """Calculate absolute timing for ABF peaks using multiple methods."""
        timing_data = {}
        
        if self.abf is None:
            return timing_data
        
        try:
            # Method 1: Using sweepTimesSec if available
            if hasattr(self.abf, 'sweepTimesSec') and len(self.abf.sweepTimesSec) > current_sweep:
                sweep_start = self.abf.sweepTimesSec[current_sweep]
                timing_data['time_absolute_method1_s'] = sweep_start + peak_times
        except (IndexError, TypeError, AttributeError):
            pass
        
        try:
            # Method 2: Using sweepLengthSec if available  
            if hasattr(self.abf, 'sweepLengthSec'):
                sweep_start = current_sweep * self.abf.sweepLengthSec
                timing_data['time_absolute_method2_s'] = sweep_start + peak_times
        except (AttributeError, TypeError):
            pass
        
        try:
            # Method 3: Manual calculation from data points
            sweep_start = current_sweep * len(self.abf.sweepX) / self.abf.dataRate
            timing_data['time_absolute_method3_s'] = sweep_start + peak_times
        except (AttributeError, TypeError, ZeroDivisionError):
            pass
        
        # Add sampling info for reference
        timing_data['sampling_rate_hz'] = np.full_like(peak_times, self.fs)
        
        return timing_data

    def _generate_export_metadata(self) -> list:
        """Generate metadata comments for export file."""
        metadata = [
            f"# Peak detection results",
            f"# Generated by: Low-Mg²⁺ Peak Curator v1.4.1",
            f"# Export time: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"# Source file: {self.current_file_path.name if self.current_file_path else 'Unknown'}",
            f"#",
            f"# Detection parameters:",
            f"# - High-pass cutoff: {self.sb_cut.value()} Hz",
            f"# - Prominence threshold: {self.sb_prom.value()} mV", 
            f"# - Minimum distance: {self.sb_dist.value()} ms",
            f"# - Sampling rate: {self.fs} Hz",
            f"#",
            f"# Results:",
            f"# - Total peaks found: {len(self.curated_peaks)}",
            f"# - Peaks removed: {len(self.peaks_removed)}",
        ]
        
        if self.mode == "abf":
            metadata.extend([
                f"#",
                f"# ABF file details:",
                f"# - Current sweep: {self.sb_sweep.value()}",
                f"# - Current channel: {self.sb_chan.value()}",
                f"# - Total sweeps: {self.abf.sweepCount if self.abf else 'Unknown'}",
                f"# - Total channels: {self.abf.channelCount if self.abf else 'Unknown'}",
                f"#",
                f"# Timing columns explanation:",
                f"# - time_relative_s: Time within current sweep (for display consistency)",
                f"# - time_absolute_method*_s: Different methods to calculate absolute experiment time",
                f"# - Use the absolute timing method that makes sense for your experiment",
            ])
        
        metadata.append("")  # Empty line before data
        return metadata

    def _show_peaks_timeline(self, peak_times: np.ndarray):
        """Show the peaks timeline plot."""
        self.plot_peaks.show()
        spots = [{"pos": (t, 0.5)} for t in peak_times]
        self._peak_timeline.setData(spots)
        self.plot_peaks.setYRange(0, 1)
        self.plot_peaks.getAxis('left').setTicks([[(0.5, 'Peaks')]])

    # ------------------------------------------------------------------
    # File information dialog
    # ------------------------------------------------------------------

    def _show_file_info(self):
        """Show detailed information about the loaded file."""
        if self.current_file_path is None:
            QMessageBox.information(self, "No File", "No file currently loaded.")
            return
            
        info_text = f"File: {self.current_file_path.name}\n"
        info_text += f"Path: {self.current_file_path}\n"
        info_text += f"Mode: {self.mode.upper()}\n"
        info_text += f"Sampling Rate: {self.fs:.1f} Hz\n\n"
        
        if self.mode == "abf" and self.abf is not None:
            info_text += "=== ABF File Details ===\n"
            
            # Basic properties
            attrs_to_show = [
                ('Protocol', 'protocol'),
                ('Channels', 'channelCount'), 
                ('Sweeps', 'sweepCount'),
                ('Data Points per Sweep', 'dataPointsPerSweep'),
                ('Recording Duration (s)', 'recordingLengthSec'),
                ('Sweep Length (s)', 'sweepLengthSec'),
                ('Data Rate (Hz)', 'dataRate'),
            ]
            
            for label, attr in attrs_to_show:
                if hasattr(self.abf, attr):
                    value = getattr(self.abf, attr)
                    info_text += f"{label}: {value}\n"
            
            # Timing information
            info_text += "\n=== Timing Information ===\n"
            timing_attrs = ['sweepTimesSec', 'sweepTimesMin', 'sweepStartSec']
            
            for attr in timing_attrs:
                if hasattr(self.abf, attr):
                    value = getattr(self.abf, attr)
                    if hasattr(value, '__len__') and not isinstance(value, str):
                        if len(value) > 0:
                            info_text += f"{attr}: [{value[0]:.3f}, {value[1]:.3f}, ...] (length={len(value)})\n"
                        else:
                            info_text += f"{attr}: empty array\n"
                    else:
                        info_text += f"{attr}: {value}\n"
                else:
                    info_text += f"{attr}: Not available\n"
            
            # Channel information
            info_text += "\n=== Channel Information ===\n"
            for i in range(self.abf.channelCount):
                if hasattr(self.abf, 'channelList'):
                    info_text += f"Channel {i}: {self.abf.channelList[i]}\n"
                else:
                    info_text += f"Channel {i}: Available\n"
                    
        elif self.mode == "csv":
            info_text += "=== CSV File Details ===\n"
            info_text += f"Available traces: {len(self.traces)}\n"
            for i, (t, v) in enumerate(self.traces):
                info_text += f"  Trace {i+1}: {len(t)} points, duration {t[-1]-t[0]:.2f}s\n"
        
        # Current analysis state
        if self.curated_peaks is not None:
            info_text += f"\n=== Current Analysis ===\n"
            info_text += f"Detected peaks: {len(self.curated_peaks)}\n"
            info_text += f"Removed peaks: {len(self.peaks_removed)}\n"
            info_text += f"HP filter: {self.sb_cut.value()} Hz\n"
            info_text += f"Prominence: {self.sb_prom.value()} mV\n"
            info_text += f"Min distance: {self.sb_dist.value()} ms\n"
        
        # Show in message box with monospace font for better formatting
        msg = QMessageBox(self)
        msg.setWindowTitle("File Information")
        msg.setText(info_text)
        msg.setFont(msg.font())  # Use monospace if available
        msg.exec_()


def main():
    """Main application entry point."""
    app = QApplication(sys.argv)
    app.setApplicationName("Peak Curator")
    app.setOrganizationName("Lab Tools")
    
    # Set application style
    app.setStyle('Fusion')
    
    window = PeakApp()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()