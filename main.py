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

# A3 용지 비율 (가로:세로 = 297:420)
a3_ratio = 297 / 420

class DraggableLineItem(QGraphicsItem):
    """
    사용자가 드래그하여 위치를 변경할 수 있는 빨간 수평선.
    마우스 드래그 종료 후(main_window가 지정되어 있으면)
    main_window의 adjustRedLinesBelow()를 호출하여
    그 아래 분할선들을 A3 비율 간격으로 재조정합니다.
    """
    def __init__(self, scene_width, y_pos=0, main_window=None):
        super().__init__()
        self._sceneWidth = scene_width
        self._lineHeight = 3  # 원래보다 약 1.5배 굵게
        self._color = QColor("red")
        self.setFlags(
            QGraphicsItem.ItemIsMovable | 
            QGraphicsItem.ItemIsSelectable
        )
        self.setPos(0, y_pos)
        self.main_window = main_window

    def boundingRect(self):
        """아이템의 전체 영역 (가로 전체, 세로는 선 두께)"""
        return QRectF(0, -self._lineHeight/2, self._sceneWidth, self._lineHeight)

    def paint(self, painter, option, widget):
        pen = QPen(self._color, self._lineHeight)
        painter.setPen(pen)
        painter.drawLine(0, 0, self._sceneWidth, 0)

    def itemChange(self, change, value):
        """x 좌표 고정 (x=0)하고 y좌표만 변경 허용"""
        if change == QGraphicsItem.ItemPositionHasChanged:
            new_pos = value.toPointF()
            return QVariant(QPointF(0, new_pos.y()))
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event):
        """드래그가 끝난 후 main_window에게 알림"""
        super().mouseReleaseEvent(event)
        if self.main_window:
            self.main_window.adjustRedLinesBelow(self)

class GraphicsView(QGraphicsView):
    """마우스 이벤트로 선을 그리지는 않고 코드로 추가하는 QGraphicsView"""
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

        # Image 정보
        self.originalPixmap = None
        self.currentImgPath = None
        self.imageWidth = 0
        self.imageHeight = 0
        self.chunk_height = 0  # A3 기준 조각 높이 (나중에 계산)

        # 분할선 저장
        self.draggableLines = []

    def openImage(self):
        """
        이미지를 열고 Scene에 표시.
        자동으로 A3 비율에 맞게 분할선을 생성.
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

        # Scene 및 분할선 초기화
        self.scene.clear()
        self.draggableLines.clear()

        # 이미지 추가
        self.pixmapItem = QGraphicsPixmapItem(pixmap)
        self.scene.addItem(self.pixmapItem)
        self.scene.setSceneRect(self.pixmapItem.boundingRect())

        # 이미지 크기 저장
        original_image = Image.open(self.currentImgPath)
        self.imageWidth, self.imageHeight = original_image.size

        # A3 기준 높이 = 이미지 가로길이 ÷ (297/420)
        self.chunk_height = self.imageWidth / a3_ratio

        # 이미지 높이를 기준으로 chunk_height마다 분할선 추가
        current_pos = self.chunk_height
        while current_pos < self.imageHeight:
            line_item = DraggableLineItem(self.imageWidth, current_pos, main_window=self)
            self.scene.addItem(line_item)
            self.draggableLines.append(line_item)
            current_pos += self.chunk_height

    def addLineAtViewCenter(self):
        """
        현재 뷰의 수직 중앙에 새로운 빨간 선 추가.
        """
        if not self.currentImgPath or not self.originalPixmap:
            QMessageBox.warning(self, "Error", "Open an image first.")
            return

        center_in_view = self.view.viewport().rect().center()
        center_in_scene = self.view.mapToScene(center_in_view)
        y_pos = center_in_scene.y()

        if y_pos < 0:
            y_pos = 0
        elif y_pos > self.imageHeight:
            y_pos = self.imageHeight

        line_item = DraggableLineItem(self.imageWidth, y_pos, main_window=self)
        self.scene.addItem(line_item)
        self.draggableLines.append(line_item)

    def adjustRedLinesBelow(self, moved_line):
        """
        사용자가 분할선을 드래그한 후 호출.
        드래그한 선 아래(들)의 위치를 A3 비율 간격으로 재설정합니다.
        즉, 현재 선의 위치로부터 chunk_height씩 떨어진 위치에
        나머지 분할선들을 재배치합니다.
        """
        # 현재 등록된 분할선들을 y 좌표 기준으로 정렬
        sorted_lines = sorted(self.draggableLines, key=lambda line: line.pos().y())
        try:
            idx = sorted_lines.index(moved_line)
        except ValueError:
            return

        # 드래그한 선 아래의 모든 선들을 재설정
        for i in range(idx + 1, len(sorted_lines)):
            # 이전 선의 위치에서 chunk_height 만큼 떨어뜨림
            new_y = sorted_lines[i - 1].pos().y() + self.chunk_height
            if new_y > self.imageHeight:
                new_y = self.imageHeight  # 이미지 범위를 벗어나지 않도록
            sorted_lines[i].setPos(0, new_y)

    def exportPdf(self):
        """
        1) 분할선 위치에 따라 원본 이미지를 자르고,
        2) 각 조각의 아래쪽에만 A3 비율에 맞도록 흰 배경 패딩을 추가한 후,
        3) PDF로 저장.
        """
        if not self.currentImgPath or not self.originalPixmap:
            QMessageBox.warning(self, "Error", "Please open an image first.")
            return

        outPdfPath, _ = QFileDialog.getSaveFileName(
            self, "Save as PDF", "", "PDF Files (*.pdf)"
        )
        if not outPdfPath:
            return

        original_image = Image.open(self.currentImgPath)
        width, height = original_image.size

        # 분할선 위치 수집 (0과 height 사이)
        line_y_positions = []
        for lineItem in self.draggableLines:
            y_val = lineItem.pos().y()
            if 0 < y_val < height:
                line_y_positions.append(y_val)
        line_y_positions.sort()

        cut_positions = [0] + line_y_positions + [height]

        # 이미지 조각으로 자르기
        split_images = []
        for i in range(len(cut_positions) - 1):
            top = int(cut_positions[i])
            bottom = int(cut_positions[i+1])
            if bottom <= top:
                continue
            cropped = original_image.crop((0, top, width, bottom))
            split_images.append(cropped)

        if not split_images:
            split_images = [original_image]

        # PDF 내보내기 시 A3 비율 맞추기 (너비는 그대로, 부족한 아래쪽은 흰색 패딩)
        def pad_bottom_to_a3(img):
            w, h = img.size
            ideal_h = int(w / a3_ratio)  # A3 비율에 맞는 높이
            if ideal_h < h:
                ideal_h = h  # 원본보다 작아지지 않도록
            canvas = Image.new("RGB", (w, ideal_h), (255, 255, 255))
            canvas.paste(img, (0, 0))
            return canvas

        padded_images = [pad_bottom_to_a3(im) for im in split_images]

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
