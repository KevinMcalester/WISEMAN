from ultralytics import YOLO
import cv2
import time

MODEL_PATH = r"C:\Users\kevin\CLionProjects\Smart_Farm\testing_area\opencv-examples\model testing\yolov3-tiny-10.onnx"
CONFIDENCE = 0.50
DETECTION_INTERVAL = 0.020   # run detection every 100 ms
SHOW_DEBUG_WINDOW = True    # set False for flight mode
CAMERA_INDEX = 0
FRAME_WIDTH = 640
FRAME_HEIGHT = 480

model = YOLO(MODEL_PATH)

cap = cv2.VideoCapture(CAMERA_INDEX)
if not cap.isOpened():
    print("Error: could not open webcam.")
    exit()

cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

last_detection_time = 0.0
latest_result = None
latest_frame = None

while True:
    ret, frame = cap.read()
    if not ret:
        print("Error: failed to grab frame.")
        break

    latest_frame = frame
    current_time = time.time()

    if current_time - last_detection_time >= DETECTION_INTERVAL:
        results = model(latest_frame, conf=CONFIDENCE, verbose=False)
        latest_result = results[0]
        last_detection_time = current_time

        # Example: extract detections without forcing plot every frame
        if latest_result.boxes is not None:
            for box in latest_result.boxes:
                cls_id = int(box.cls[0].item())
                conf = float(box.conf[0].item())
                xyxy = box.xyxy[0].tolist()
                print(f"Class: {cls_id}, Conf: {conf:.2f}, Box: {xyxy}")

    if SHOW_DEBUG_WINDOW and latest_result is not None:
        annotated_frame = latest_result.plot()
        cv2.imshow("YOLOv8 Live Detection", annotated_frame)
    elif SHOW_DEBUG_WINDOW:
        cv2.imshow("YOLOv8 Live Detection", latest_frame)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()