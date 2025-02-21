# Copyright Contributors to the Rez project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from Qt import QtCore, QtWidgets, QtGui
from rezgui.util import create_pane
from rez.utils.graph_utils import save_graph, prune_graph
import tempfile
import threading
import os
import os.path


class Writer(QtCore.QObject):
    graph_written = QtCore.Signal(str, str)

    def __init__(self, graph_str, filepath, prune_to=None):
        super(Writer, self).__init__()
        self.graph_str = graph_str
        self.filepath = filepath
        self.prune_to = prune_to
        self.process = None

    def cancel(self):
        if self.process:
            self.process.terminate()

    def write_graph(self):
        if self.prune_to:
            graph_str = prune_graph(self.graph_str, self.prune_to)
        else:
            graph_str = self.graph_str

        error_msg = ''
        try:
            save_graph(graph_str, self.filepath)
        except Exception as e:
            error_msg = str(e)

        self.graph_written.emit(self.filepath, error_msg)


class WriteGraphDialog(QtWidgets.QDialog):
    def __init__(self, graph_str, filepath, parent=None, prune_to=None):
        super(WriteGraphDialog, self).__init__(parent)
        self.setWindowTitle("Rendering graph...")
        self.writer = Writer(graph_str, filepath, prune_to)
        self.thread = None
        self._finished = False
        self.success = False

        self.busy_cursor = QtGui.QCursor(QtCore.Qt.WaitCursor)
        self.bar = QtWidgets.QProgressBar()
        self.bar.setRange(0, 0)

        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        pane = create_pane([None, self.cancel_btn], True)
        create_pane([self.bar, pane], False, parent_widget=self)

        self.writer.graph_written.connect(self._graph_written)
        self.cancel_btn.clicked.connect(self._cancel)

    def sizeHint(self):
        return QtCore.QSize(300, 100)

    def write_graph(self):
        QtWidgets.QApplication.setOverrideCursor(self.busy_cursor)
        self.thread = threading.Thread(target=self.writer.write_graph)
        self.thread.daemon = True
        self.thread.start()
        self.exec_()
        self.thread.join()
        return self.success

    def reject(self):
        if self._finished:
            super(WriteGraphDialog, self).reject()
        else:
            self._cancel()

    def closeEvent(self, event):
        if self._finished:
            event.accept()
        else:
            self._cancel()
            event.ignore()

    def _cancel(self):
        self.bar.setMaximum(10)
        self.bar.setValue(10)
        self.cancel_btn.setText("Cancelling...")
        self.cancel_btn.setEnabled(False)
        self.writer.cancel()

    def _graph_written(self, filepath, error_message):
        self._finished = True
        self.bar.setMaximum(10)
        self.bar.setValue(10)
        QtWidgets.QApplication.restoreOverrideCursor()
        self.setWindowTitle("Rendered graph")

        if error_message:
            QtWidgets.QMessageBox.critical(self, "Failed rendering resolve graph",
                                       error_message)
        elif filepath:
            self.success = True
        self.close()


graph_file_lookup = {}


def view_graph(graph_str, parent=None, prune_to=None):
    """View a graph."""
    from rezgui.dialogs.ImageViewerDialog import ImageViewerDialog
    from rez.config import config

    # check for already written tempfile
    h = hash((graph_str, prune_to))
    filepath = graph_file_lookup.get(h)
    if filepath and not os.path.exists(filepath):
        filepath = None

    # write graph to tempfile
    if filepath is None:
        suffix = ".%s" % config.dot_image_format
        fd, filepath = tempfile.mkstemp(suffix=suffix, prefix="rez-graph-")
        os.close(fd)

        dlg = WriteGraphDialog(graph_str, filepath, parent, prune_to=prune_to)
        if not dlg.write_graph():
            return

    # display graph
    graph_file_lookup[h] = filepath
    dlg = ImageViewerDialog(filepath, parent)
    dlg.exec_()
