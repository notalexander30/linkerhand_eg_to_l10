#!/usr/bin/env python3
"""Small GUI launcher for EG/right-glove to left LinkerHand L10 control."""

import sys
from pathlib import Path

from PyQt5.QtCore import QProcess
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "glove_to_l10.py"


class GloveToL10Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EG Glove to LinkerHand L10")
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.read_stdout)
        self.process.readyReadStandardError.connect(self.read_stderr)
        self.process.finished.connect(self.process_finished)

        self.glove_port = QLineEdit("/dev/ttyUSB0")
        self.hand_can = QLineEdit("can0")
        self.baud = QSpinBox()
        self.baud.setRange(1200, 2000000)
        self.baud.setValue(115200)
        self.rate = QSpinBox()
        self.rate.setRange(1, 100)
        self.rate.setValue(15)
        self.angle_max = QDoubleSpinBox()
        self.angle_max.setRange(1.0, 1000.0)
        self.angle_max.setValue(360.0)
        self.angle_max.setDecimals(1)

        self.hand = QComboBox()
        self.hand.addItems(["left", "right"])
        self.mapping = QComboBox()
        self.mapping.addItems(["angle", "calibrated"])

        self.send = QCheckBox("Send to hand")
        self.force = QCheckBox("Force SDK movement")

        self.output = QTextEdit()
        self.output.setReadOnly(True)

        start_button = QPushButton("Start")
        start_button.clicked.connect(self.start_bridge)
        raw_button = QPushButton("Raw")
        raw_button.clicked.connect(self.start_raw)
        open_button = QPushButton("Calibrate Open")
        open_button.clicked.connect(lambda: self.start_calibration("--calibrate-open"))
        fist_button = QPushButton("Calibrate Fist")
        fist_button.clicked.connect(lambda: self.start_calibration("--calibrate-fist"))
        stop_button = QPushButton("Stop")
        stop_button.clicked.connect(self.stop_process)

        form = QFormLayout()
        form.addRow("Glove port", self.glove_port)
        form.addRow("Hand CAN", self.hand_can)
        form.addRow("Baud", self.baud)
        form.addRow("Rate", self.rate)
        form.addRow("Angle max", self.angle_max)
        form.addRow("Hand side", self.hand)
        form.addRow("Mapping", self.mapping)
        form.addRow("", self.send)
        form.addRow("", self.force)

        buttons = QHBoxLayout()
        for button in (start_button, raw_button, open_button, fist_button, stop_button):
            buttons.addWidget(button)

        root = QVBoxLayout()
        root.addWidget(QLabel("Right EG glove USB -> laptop -> left LinkerHand L10 CAN"))
        root.addLayout(form)
        root.addLayout(buttons)
        root.addWidget(self.output)

        container = QWidget()
        container.setLayout(root)
        self.setCentralWidget(container)
        self.resize(760, 560)

    def base_args(self):
        args = [
            str(SCRIPT),
            "--glove-port",
            self.glove_port.text().strip(),
            "--hand-can",
            self.hand_can.text().strip(),
            "--hand",
            self.hand.currentText(),
            "--baud",
            str(self.baud.value()),
            "--rate",
            str(self.rate.value()),
            "--mapping",
            self.mapping.currentText(),
            "--angle-max",
            str(self.angle_max.value()),
        ]
        if self.send.isChecked():
            args.append("--send")
        if self.force.isChecked():
            args.append("--force")
        return args

    def start_bridge(self):
        self.start_process(self.base_args())

    def start_raw(self):
        self.start_process(self.base_args() + ["--raw"])

    def start_calibration(self, flag):
        self.start_process(self.base_args() + [flag])

    def start_process(self, args):
        if self.process.state() != QProcess.NotRunning:
            self.append("Process is already running. Stop it first.")
            return
        self.output.clear()
        self.append("$ " + " ".join([sys.executable] + args))
        self.process.start(sys.executable, args)

    def stop_process(self):
        if self.process.state() == QProcess.NotRunning:
            return
        self.process.terminate()
        if not self.process.waitForFinished(1500):
            self.process.kill()

    def read_stdout(self):
        self.append(bytes(self.process.readAllStandardOutput()).decode(errors="replace"))

    def read_stderr(self):
        self.append(bytes(self.process.readAllStandardError()).decode(errors="replace"))

    def process_finished(self):
        self.append("Process stopped.")

    def append(self, text):
        self.output.insertPlainText(text if text.endswith("\n") else text + "\n")
        scrollbar = self.output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())


def main():
    app = QApplication(sys.argv)
    window = GloveToL10Window()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
