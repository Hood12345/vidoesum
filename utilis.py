import os
import subprocess
from typing import List, Dict
from scenedetect import VideoManager, SceneManager
from scenedetect.detectors import ContentDetector
import math

def run_pyscenedetect(video_path: str) -> List[Dict[str, str]]:
    video_manager = VideoManager([video_path])
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector())
    video_manager.set_downscale_factor()
    video_manager.start()
    scene_manager.detect_scenes(frame_source=video_manager)
    scene_list = scene_manager.get_scene_list()

    result = []
    for start, end in scene_list:
        result.append({
            "start": str(start.get_timecode()),
            "end": str(end.get_timecode())
        })
    return result

def extract_frames(video_path: str, start: str, end: str, num_frames: int, output_dir: str, scene_id: int) -> List[str]:
    def time_to_seconds(t: str) -> float:
        h, m, s = map(float, t.split(':'))
        return h * 3600 + m * 60 + s

    start_sec = time_to_seconds(start)
    end_sec = time_to_seconds(end)
    duration = end_sec - start_sec
    if duration <= 0:
        return []

    interval = duration / (num_frames + 1)
    timestamps = [start_sec + (i + 1) * interval for i in range(num_frames)]

    frames = []
    for idx, ts in enumerate(timestamps, 1):
        output_file = os.path.join(output_dir, f"scene_{scene_id}_{idx}.jpg")
        cmd = [
            "ffmpeg",
            "-ss", f"{ts:.3f}",
            "-i", video_path,
            "-frames:v", "1",
            "-q:v", "2",
            output_file
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        frames.append(os.path.basename(output_file))
    return frames
