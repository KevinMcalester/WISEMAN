"""
from ultralytics import YOLO

model = YOLO(r"/testing_area/opencv-examples/model testing/yolov8n.pt")      # or your plant model .pt file
model.export(format="onnx")  # creates best.onnx
"""



from ultralytics import YOLO

model = YOLO("yolov8n.pt")
model.export(format="weights", opset=11, simplify=True)