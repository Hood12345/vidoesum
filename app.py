import os
import uuid
import logging
from flask import Flask, request, jsonify
from utils import run_pyscenedetect, extract_frames
from werkzeug.utils import secure_filename

UPLOAD_DIR = "/tmp/video_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG)

@app.route("/analyze", methods=["POST"])
def analyze_video():
    try:
        if 'video' not in request.files:
            return jsonify({"error": "No video file provided"}), 400
        
        video = request.files['video']
        if video.filename == "":
            return jsonify({"error": "Empty filename"}), 400
        
        req_id = str(uuid.uuid4())
        req_folder = os.path.join(UPLOAD_DIR, req_id)
        os.makedirs(req_folder, exist_ok=True)

        filename = secure_filename(video.filename)
        filepath = os.path.join(req_folder, filename)
        video.save(filepath)

        scenes = run_pyscenedetect(filepath)
        result = []
        for idx, scene in enumerate(scenes, 1):
            frames = extract_frames(filepath, scene['start'], scene['end'], 3, req_folder, idx)
            result.append({
                "start": scene['start'],
                "end": scene['end'],
                "frames": frames
            })

        return jsonify({"scenes": result})

    except Exception as e:
        logging.exception("Error during analysis")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
