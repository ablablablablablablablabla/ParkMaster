import os
import base64
import numpy as np
import tf_keras as keras
from tf_keras.models import load_model
from PIL import Image, ImageOps
from flask import Flask, request, jsonify
from flask_cors import CORS
import io

# Устанавливаем переменную окружения для совместимости
os.environ["TF_USE_LEGACY_KERAS"] = "1"

app = Flask(__name__)
CORS(app)

# Пути к файлам модели
MODEL_PATH = "keras_model.h5"
LABELS_PATH = "labels.txt"

# Загружаем модель один раз при старте сервера
print("Loading model...")
model = load_model(MODEL_PATH, compile=False)
class_names = open(LABELS_PATH, "r", encoding="utf-8").readlines()
print("Model loaded.")

# Tracks the most recent camera prediction; read by GET /status
LAST_PREDICTION = {
    "label": None,
    "is_occupied": False,
    "is_no_parking": False,
    "confidence": 0.0,
}

def predict_car(image):
    # Подготовка данных
    data = np.ndarray(shape=(1, 224, 224, 3), dtype=np.float32)
    
    # Предобработка изображения
    image = image.convert("RGB")
    size = (224, 224)
    image = ImageOps.fit(image, size, Image.Resampling.LANCZOS)
    image_array = np.asarray(image)
    normalized_image_array = (image_array.astype(np.float32) / 127.5) - 1
    data[0] = normalized_image_array

    # Предсказание
    prediction = model.predict(data)
    index = np.argmax(prediction)
    class_name = class_names[index]
    confidence_score = prediction[0][index]

    return class_name[2:].strip(), float(confidence_score)

@app.route("/predict", methods=["POST"])
def predict():
    try:
        data = request.json
        if "image" not in data:
            return jsonify({"error": "No image data"}), 400
        
        # Декодируем base64 изображение
        image_data = data["image"].split(",")[1]
        image_bytes = base64.b64decode(image_data)
        image = Image.open(io.BytesIO(image_bytes))
        
        label, confidence = predict_car(image)

        LAST_PREDICTION.update({
            "label": label,
            "confidence": confidence,
            "is_occupied": label.lower() == "occupated",
            "is_no_parking": label.lower() == "no parking",
        })
        return jsonify({
            "label": label,
            "confidence": confidence,
            "is_occupied": label.lower() == "occupated",
            "is_no_parking": label.lower() == "no parking"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/status")
def status():
    return jsonify(LAST_PREDICTION)


@app.route("/")
def index():
    return app.send_static_file("index.html")

if __name__ == "__main__":
    # Создаем папку static если её нет
    if not os.path.exists("static"):
        os.makedirs("static")
    app.run(host="0.0.0.0", port=5000)
