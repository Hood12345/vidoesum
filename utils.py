import os
import subprocess
import logging
import time
import shutil
from typing import List, Dict, Optional
from scenedetect import VideoManager, SceneManager
from scenedetect.detectors import ContentDetector
from scenedetect.video_splitter import split_video_ffmpeg

logger = logging.getLogger(__name__)

def run_pyscenedetect(video_path: str, threshold: float = 30.0) -> List[Dict[str, str]]:
    """
    Detect scenes in video using PySceneDetect
    
    Args:
        video_path: Path to video file
        threshold: Scene detection threshold (higher = less sensitive)
    
    Returns:
        List of scene dictionaries with start, end, and duration
    """
    try:
        video_manager = VideoManager([video_path])
        scene_manager = SceneManager()
        scene_manager.add_detector(ContentDetector(threshold=threshold))
        
        # Optimize for speed vs accuracy
        video_manager.set_downscale_factor(2)
        video_manager.start()
        
        # Detect scenes
        scene_manager.detect_scenes(frame_source=video_manager)
        scene_list = scene_manager.get_scene_list()
        
        if not scene_list:
            logger.warning(f"No scenes detected in {video_path}")
            # Return entire video as single scene if no cuts found
            video_manager.reset()
            duration = video_manager.get_duration()
            scene_list = [(video_manager.get_base_timecode(), duration)]
        
        scene_list.sort(key=lambda s: s[0].get_seconds())

        result = []
        for start, end in scene_list:
            duration_sec = end.get_seconds() - start.get_seconds()
            result.append({
                "start": str(start.get_timecode()),
                "end": str(end.get_timecode()),
                "duration": f"{duration_sec:.3f}"
            })
        
        logger.info(f"Detected {len(result)} scenes in {video_path}")
        return result
        
    except Exception as e:
        logger.error(f"Scene detection failed for {video_path}: {str(e)}")
        raise Exception(f"Scene detection failed: {str(e)}")

def extract_frames(video_path: str, start: str, end: str, num_frames: int, 
                  output_dir: str, scene_id: int) -> List[str]:
    """
    Extract frames from video segment using FFmpeg
    
    Args:
        video_path: Path to source video
        start: Start timecode (HH:MM:SS.mmm)
        end: End timecode (HH:MM:SS.mmm)
        num_frames: Number of frames to extract
        output_dir: Directory to save frames
        scene_id: Scene identifier for filename
    
    Returns:
        List of extracted frame filenames
    """
    try:
        start_sec = time_to_seconds(start)
        end_sec = time_to_seconds(end)
        duration = end_sec - start_sec
        
        if duration <= 0.1:  # Skip very short scenes
            logger.warning(f"Scene {scene_id} too short ({duration:.3f}s), skipping")
            return []

        # Calculate evenly spaced timestamps
        if duration < num_frames * 0.5:  # If scene is very short, extract fewer frames
            actual_frames = max(1, int(duration * 2))
            logger.info(f"Scene {scene_id}: Reducing frames from {num_frames} to {actual_frames}")
        else:
            actual_frames = num_frames

        interval = duration / (actual_frames + 1)
        timestamps = [start_sec + (i + 1) * interval for i in range(actual_frames)]

        frames = []
        for idx, ts in enumerate(timestamps, 1):
            output_file = os.path.join(output_dir, f"scene_{scene_id:02d}_{idx:02d}.jpg")
            
            # Use more efficient FFmpeg parameters
            cmd = [
                "ffmpeg",
                "-v", "quiet",  # Reduce verbose output
                "-ss", f"{ts:.3f}",
                "-i", video_path,
                "-frames:v", "1",
                "-q:v", "3",  # Slightly lower quality for smaller files
                "-vf", "scale=640:-1",  # Resize for smaller files
                "-y",  # Overwrite existing files
                output_file
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0 and os.path.exists(output_file):
                frames.append(os.path.basename(output_file))
                logger.debug(f"Extracted frame: {os.path.basename(output_file)}")
            else:
                logger.warning(f"FFmpeg failed for scene {scene_id} at {ts:.3f}s: {result.stderr}")
        
        logger.info(f"Scene {scene_id}: Extracted {len(frames)}/{actual_frames} frames")
        return frames
        
    except subprocess.TimeoutExpired:
        logger.error(f"FFmpeg timeout for scene {scene_id}")
        return []
    except Exception as e:
        logger.error(f"Frame extraction failed for scene {scene_id}: {str(e)}")
        return []

def time_to_seconds(time_str: str) -> float:
    """Convert HH:MM:SS.mmm format to seconds"""
    try:
        parts = time_str.split(':')
        if len(parts) != 3:
            raise ValueError(f"Invalid time format: {time_str}")
        
        hours, minutes, seconds = map(float, parts)
        return hours * 3600 + minutes * 60 + seconds
    except Exception as e:
        logger.error(f"Time conversion failed for '{time_str}': {str(e)}")
        raise ValueError(f"Invalid time format: {time_str}")

def validate_video_file(video_path: str) -> bool:
    """
    Validate video file using FFprobe
    
    Args:
        video_path: Path to video file
    
    Returns:
        True if valid video file
    """
    try:
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            video_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.returncode == 0 and "video" in result.stdout.lower()
        
    except subprocess.TimeoutExpired:
        logger.error(f"Video validation timeout for {video_path}")
        return False
    except Exception as e:
        logger.error(f"Video validation failed for {video_path}: {str(e)}")
        return False

def get_video_info(video_path: str) -> Optional[Dict]:
    """
    Get video metadata using FFprobe
    
    Args:
        video_path: Path to video file
    
    Returns:
        Dictionary with video info or None if failed
    """
    try:
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            video_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return None
            
        import json
        data = json.loads(result.stdout)
        
        # Extract video stream info
        video_streams = [s for s in data.get('streams', []) if s.get('codec_type') == 'video']
        if not video_streams:
            return None
            
        video_stream = video_streams[0]
        format_info = data.get('format', {})
        
        return {
            'duration': float(format_info.get('duration', 0)),
            'width': video_stream.get('width'),
            'height': video_stream.get('height'),
            'codec': video_stream.get('codec_name'),
            'fps': eval(video_stream.get('r_frame_rate', '0/1')),
            'bitrate': int(format_info.get('bit_rate', 0))
        }
        
    except Exception as e:
        logger.error(f"Failed to get video info for {video_path}: {str(e)}")
        return None

def cleanup_old_files(base_dir: str, max_age_hours: int = 1):
    """
    Clean up old request folders
    
    Args:
        base_dir: Base upload directory
        max_age_hours: Maximum age of folders to keep
    """
    try:
        if not os.path.exists(base_dir):
            return
            
        current_time = time.time()
        cutoff_time = current_time - (max_age_hours * 3600)
        removed_count = 0
        
        for item in os.listdir(base_dir):
            item_path = os.path.join(base_dir, item)
            
            if os.path.isdir(item_path):
                # Check if it's a UUID-like directory
                try:
                    import uuid
                    uuid.UUID(item)  # Validate UUID format
                    
                    # Check age
                    if os.path.getctime(item_path) < cutoff_time:
                        shutil.rmtree(item_path, ignore_errors=True)
                        removed_count += 1
                        logger.debug(f"Cleaned up old request: {item}")
                        
                except ValueError:
                    # Not a UUID directory, skip
                    continue
                except Exception as e:
                    logger.warning(f"Failed to cleanup {item}: {str(e)}")
        
        if removed_count > 0:
            logger.info(f"Cleaned up {removed_count} old request folders")
            
    except Exception as e:
        logger.error(f"Cleanup failed: {str(e)}")
