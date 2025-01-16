import sys
import os
import img2pdf
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QAction, QFileDialog, QMessageBox, 
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QToolBar, 
    QVBoxLayout, QWidget
)
from PyQt5.QtGui import QPixmap, QPen, QColor, QPainter
from PyQt5.QtCore import Qt, QRectF, QVariant, QPointF
from PyQt5.QtWidgets import QGraphicsItem
from PIL import Image

Image.MAX_IMAGE_PIXELS = 200000000

class DraggableLineItem(QGraphicsItem):
    """
    A horizontal red line that can be dragged up/down by the user.
    We implement this from QGraphicsItem so we can fully control painting and boundingRect.
    """
    def __init__(self, scene_width, y_pos=0):
        super().__init__()
        self._sceneWidth = scene_width
        self._lineHeight = 3       # 1.5 times thicker than the original 2
        self._color = QColor("red")
        self.setFlags(
            QGraphicsItem.ItemIsMovable | 
            QGraphicsItem.ItemIsSelectable
        )
        # place the line at (0, y_pos)
        self.setPos(0, y_pos)

    def boundingRect(self):
        """
        The bounding rectangle for this item 
        (full width, small height for the line).
        """
        return QRectF(0, -self._lineHeight/2, self._sceneWidth, self._lineHeight)

    def paint(self, painter, option, widget):
        pen = QPen(self._color, self._lineHeight)
        painter.setPen(pen)
        # horizontal line from x=0 to x=scene_width at local y=0
        painter.drawLine(0, 0, self._sceneWidth, 0)

    def itemChange(self, change, value):
        """
        Restrict movement so that only y coordinate changes (x=0 locked).
        """
        if change == QGraphicsItem.ItemPositionHasChanged:
            new_pos = value.toPointF()
            return QVariant(QPointF(0, new_pos.y()))
        return super().itemChange(change, value)


class GraphicsView(QGraphicsView):
    """
    A QGraphicsView that doesn't create lines on mouse, 
    but we can add lines from code and let the user drag them.
    """
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Split PNG to A3-Padded PDF (with auto lines + add line)")

        # Toolbar Actions
        openAction = QAction("Open", self)
        openAction.triggered.connect(self.openImage)

        addLineAction = QAction("Add Line", self)
        addLineAction.triggered.connect(self.addLineAtViewCenter)

        exportAction = QAction("Save PDF", self)
        exportAction.triggered.connect(self.exportPdf)

        # Toolbar
        toolbar = QToolBar("Main Toolbar")
        toolbar.addAction(openAction)
        toolbar.addAction(addLineAction)
        toolbar.addAction(exportAction)
        self.addToolBar(toolbar)

        # Scene & View
        self.scene = QGraphicsScene(self)
        self.view = GraphicsView(self.scene, self)
        self.view.setRenderHint(QPainter.Antialiasing)

        # Layout
        central_widget = QWidget(self)
        layout = QVBoxLayout(central_widget)
        layout.addWidget(self.view)
        self.setCentralWidget(central_widget)

        # Image info
        self.originalPixmap = None
        self.currentImgPath = None
        self.imageWidth = 0
        self.imageHeight = 0

        # Store lines
        self.draggableLines = []

    def openImage(self):
        """
        Open an image and display it in the scene.
        Auto-generate horizontal lines based on A3 ratio.
        """
        fileName, _ = QFileDialog.getOpenFileName(
            self, "Open PNG/JPEG image", "", "Images (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        if not fileName:
            return

        pixmap = QPixmap(fileName)
        if pixmap.isNull():
            QMessageBox.warning(self, "Error", "Cannot load the selected image.")
            return

        self.currentImgPath = fileName
        self.originalPixmap = pixmap

        # Clear scene & lines
        self.scene.clear()
        self.draggableLines.clear()

        # Add image to scene
        self.pixmapItem = QGraphicsPixmapItem(pixmap)
        self.scene.addItem(self.pixmapItem)
        self.scene.setSceneRect(self.pixmapItem.boundingRect())

        # Save image width/height
        original_image = Image.open(self.currentImgPath)
        self.imageWidth, self.imageHeight = original_image.size

        # Auto-generate lines for A3 ratio
        a3_ratio = 297/420  # ~0.707
        chunk_height = self.imageWidth / a3_ratio
        current_pos = chunk_height

        # 반복해서 세로축으로 chunk_height마다 선 추가
        while current_pos < self.imageHeight:
            line_item = DraggableLineItem(self.imageWidth, current_pos)
            self.scene.addItem(line_item)
            self.draggableLines.append(line_item)
            current_pos += chunk_height

    def addLineAtViewCenter(self):
        """
        Add a new red line at the vertical center of the current view (viewport).
        """
        if not self.currentImgPath or not self.originalPixmap:
            QMessageBox.warning(self, "Error", "Open an image first.")
            return

        # Find the viewport center in scene coordinates
        center_in_view = self.view.viewport().rect().center()
        center_in_scene = self.view.mapToScene(center_in_view)
        y_pos = center_in_scene.y()

        # Clamp to image range if needed
        if y_pos < 0:
            y_pos = 0
        elif y_pos > self.imageHeight:
            y_pos = self.imageHeight

        # Create a new draggable line
        line_item = DraggableLineItem(self.imageWidth, y_pos)
        self.scene.addItem(line_item)
        self.draggableLines.append(line_item)

    def exportPdf(self):
        """
        1) Collect line positions,
        2) Split the image at those y-positions,
        3) Pad each piece only at the bottom (to match A3 ratio),
        4) Export to PDF.
        """
        if not self.currentImgPath or not self.originalPixmap:
            QMessageBox.warning(self, "Error", "Please open an image first.")
            return

        outPdfPath, _ = QFileDialog.getSaveFileName(
            self, "Save as PDF", "", "PDF Files (*.pdf)"
        )
        if not outPdfPath:
            return

        # Load original image (PIL)
        original_image = Image.open(self.currentImgPath)
        width, height = original_image.size

        # Gather line positions
        line_y_positions = []
        for lineItem in self.draggableLines:
            # item.pos().y() is the actual Y in scene coords (center of line)
            y_val = lineItem.pos().y()
            if 0 < y_val < height:
                line_y_positions.append(y_val)
        line_y_positions.sort()

        # Determine cut positions
        cut_positions = [0] + line_y_positions + [height]

        # Crop pieces
        split_images = []
        for i in range(len(cut_positions) - 1):
            top = int(cut_positions[i])
            bottom = int(cut_positions[i+1])
            if bottom <= top:
                continue
            cropped = original_image.crop((0, top, width, bottom))
            split_images.append(cropped)

        if not split_images:
            # if no lines => one piece
            split_images = [original_image]

        # A3 ratio
        a3_ratio = 297 / 420

        # Warn if any piece is too tall
        tall_count = 0
        for im in split_images:
            w, h = im.size
            if (w / h) < a3_ratio:
                tall_count += 1
        if tall_count > 0:
            QMessageBox.warning(
                self,
                "Warning",
                f"{tall_count} piece(s) of the split image have an extremely tall ratio.\n"
                f"They might look tall compared to A3 ratio."
            )

        def pad_bottom_to_a3(img):
            """
            Pad image at the bottom only, so that final ratio is at least A3 ratio.
            We don't upscale the actual image width, only add vertical space if needed.
            """
            w, h = img.size
            ratio = w / h

            if ratio > a3_ratio:
                # wide => keep w, figure out new h
                new_w = w
                new_h = int(w / a3_ratio)
                if new_h < h:
                    # do not shrink the original
                    new_h = h
            else:
                # tall => keep h, compute new width => but we won't actually change width,
                # we just interpret we need more vertical space => so new_h
                new_w = w
                new_h = int(w / a3_ratio)
                if new_h < h:
                    new_h = h

            canvas = Image.new("RGB", (new_w, new_h), (255, 255, 255))
            canvas.paste(img, (0, 0))
            return canvas

        # Pad each piece
        padded_images = [pad_bottom_to_a3(im) for im in split_images]

        # Export to PDF
        temp_file_list = []
        try:
            for idx, p_img in enumerate(padded_images):
                temp_path = f"__temp_export_{idx}.png"
                p_img.save(temp_path, "PNG")
                temp_file_list.append(temp_path)

            with open(outPdfPath, "wb") as f:
                f.write(img2pdf.convert(temp_file_list))

            QMessageBox.information(self, "Done", f"PDF has been saved to:\n{outPdfPath}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"An error occurred while exporting PDF:\n{e}")
        finally:
            # Clean up temp files
            for temp_path in temp_file_list:
                if os.path.exists(temp_path):
                    os.remove(temp_path)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
