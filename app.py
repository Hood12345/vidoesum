import os
import uuid
import logging
import tempfile
import atexit
import shutil
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from utils import run_pyscenedetect, extract_frames, cleanup_old_files
from werkzeug.utils import secure_filename

# Use system temp directory with cleanup
UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "video_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Register cleanup function
atexit.register(lambda: shutil.rmtree(UPLOAD_DIR, ignore_errors=True))

app = Flask(__name__)
CORS(app)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100 MB

# Configure logging with more detail
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Supported video formats
ALLOWED_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.webm'}

def allowed_file(filename):
    """Check if file extension is allowed"""
    return any(filename.lower().endswith(ext) for ext in ALLOWED_EXTENSIONS)

@app.route("/analyze", methods=["POST"])
def analyze_video():
    req_id = None
    try:
        # Validation
        if 'video' not in request.files:
            return jsonify({"error": "No video file provided"}), 400

        video = request.files['video']
        if video.filename == "":
            return jsonify({"error": "Empty filename"}), 400

        if not video.content_type.startswith("video/"):
            return jsonify({"error": "Invalid file type"}), 400

        filename = secure_filename(video.filename)
        if not allowed_file(filename):
            return jsonify({
                "error": f"Unsupported format. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
            }), 400

        # Create unique request folder
        req_id = str(uuid.uuid4())
        req_folder = os.path.join(UPLOAD_DIR, req_id)
        os.makedirs(req_folder, exist_ok=True)

        filepath = os.path.join(req_folder, filename)
        video.save(filepath)
        
        logger.info(f"Processing video: {filename} (Request ID: {req_id})")

        # Validate video file
        if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
            return jsonify({"error": "Failed to save video file"}), 500

        # Clean up old files periodically
        cleanup_old_files(UPLOAD_DIR, max_age_hours=1)

        # Scene detection
        scenes = run_pyscenedetect(filepath)
        if not scenes:
            return jsonify({"error": "No scenes detected in video"}), 400

        # Process scenes
        result = []
        for idx, scene in enumerate(scenes, 1):
            try:
                frames = extract_frames(filepath, scene['start'], scene['end'], 3, req_folder, idx)
                if frames:  # Only add scenes with successfully extracted frames
                    result.append({
                        "scene_id": idx,
                        "start": scene['start'],
                        "end": scene['end'],
                        "duration": scene.get('duration', '0.000'),
                        "frames": [f"/static/{req_id}/{f}" for f in frames if f]
                    })
            except Exception as e:
                logger.warning(f"Failed to process scene {idx}: {str(e)}")
                continue

        if not result:
            return jsonify({"error": "Failed to extract frames from any scenes"}), 500

        logger.info(f"Successfully processed {len(result)} scenes for request {req_id}")
        return jsonify({
            "request_id": req_id,
            "total_scenes": len(result),
            "scenes": result
        })

    except Exception as e:
        logger.exception(f"Error during analysis (Request ID: {req_id})")
        
        # Clean up on error
        if req_id:
            req_folder = os.path.join(UPLOAD_DIR, req_id)
            if os.path.exists(req_folder):
                shutil.rmtree(req_folder, ignore_errors=True)
        
        return jsonify({"error": "Internal server error"}), 500

@app.route("/static/<req_id>/<filename>")
def serve_frame(req_id, filename):
    """Serve extracted frame images"""
    try:
        # Validate request ID format
        uuid.UUID(req_id)  # Raises ValueError if invalid
        
        # Secure filename
        filename = secure_filename(filename)
        if not filename.lower().endswith('.jpg'):
            return jsonify({"error": "Invalid file type"}), 400
            
        file_path = os.path.join(UPLOAD_DIR, req_id)
        if not os.path.exists(file_path):
            return jsonify({"error": "Request not found"}), 404
            
        return send_from_directory(file_path, filename)
    except ValueError:
        return jsonify({"error": "Invalid request ID"}), 400
    except Exception as e:
        logger.error(f"Error serving file {req_id}/{filename}: {str(e)}")
        return jsonify({"error": "File not found"}), 404

@app.route("/status/<req_id>")
def get_status(req_id):
    """Check if request results are still available"""
    try:
        uuid.UUID(req_id)  # Validate UUID format
        req_folder = os.path.join(UPLOAD_DIR, req_id)
        if os.path.exists(req_folder):
            return jsonify({"status": "available"})
        else:
            return jsonify({"status": "expired"}), 404
    except ValueError:
        return jsonify({"error": "Invalid request ID"}), 400

@app.route("/cleanup/<req_id>", methods=["DELETE"])
def cleanup_request(req_id):
    """Manual cleanup of request data"""
    try:
        uuid.UUID(req_id)  # Validate UUID format
        req_folder = os.path.join(UPLOAD_DIR, req_id)
        if os.path.exists(req_folder):
            shutil.rmtree(req_folder, ignore_errors=True)
            return jsonify({"message": "Cleanup successful"})
        else:
            return jsonify({"message": "Request not found"}), 404
    except ValueError:
        return jsonify({"error": "Invalid request ID"}), 400

@app.route("/health")
def health_check():
    """Enhanced health check"""
    try:
        # Check if upload directory is writable
        test_file = os.path.join(UPLOAD_DIR, "health_test")
        with open(test_file, 'w') as f:
            f.write("test")
        os.remove(test_file)
        
        return jsonify({
            "status": "healthy",
            "upload_dir": UPLOAD_DIR,
            "disk_usage": shutil.disk_usage(UPLOAD_DIR)._asdict()
        })
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return jsonify({"status": "unhealthy", "error": str(e)}), 500

@app.route("/ping")
def ping():
    return "pong", 200

# Error handlers
@app.errorhandler(413)
def file_too_large(error):
    return jsonify({"error": "File too large. Maximum size: 100MB"}), 413

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {str(error)}")
    return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
