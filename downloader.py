import os
import re
import json
import logging
import tempfile
import subprocess
import requests
from urllib.parse import parse_qs, urlparse, quote
from typing import Dict, Any, List, Tuple, Optional

import yt_dlp

# Configure logging
logging.basicConfig(level=logging.DEBUG)

# Global variables to track download progress
current_download_progress = 0
current_download_file = ""
current_download_phase = "Preparing"  # Phases: "Preparing", "Downloading", "Processing", "Complete"
download_eta = ""
post_processing_progress = 0

# Get YouTube API key from environment
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
if not YOUTUBE_API_KEY:
    logging.warning("YouTube API key not found in environment variables")

def clean_filename(filename: str) -> str:
    """Remove invalid characters from filename"""
    # Replace invalid characters with underscore
    return re.sub(r'[\\/*?:"<>|]', "_", filename)

def progress_hook(d):
    """Progress hook for yt-dlp"""
    global current_download_progress, current_download_phase, download_eta, post_processing_progress
    
    if d['status'] == 'downloading':
        current_download_phase = "Downloading"
        
        # Calculate progress percentage if available
        if 'total_bytes' in d and d['total_bytes'] > 0:
            current_download_progress = int(d['downloaded_bytes'] / d['total_bytes'] * 100)
        elif 'total_bytes_estimate' in d and d['total_bytes_estimate'] > 0:
            current_download_progress = int(d['downloaded_bytes'] / d['total_bytes_estimate'] * 100)
        
        # Get ETA if available
        if '_eta_str' in d:
            download_eta = d['_eta_str']
        
        logging.debug(f"Download progress: {current_download_progress}% ETA: {download_eta}")
    elif d['status'] == 'finished':
        current_download_phase = "Processing"
        current_download_progress = 100
        download_eta = ""
        logging.debug("Download finished, starting processing")
    elif d['status'] == 'postprocessing':
        current_download_phase = "Processing"
        if 'postprocessor' in d:
            if d['postprocessor'] == 'MoveFiles':
                post_processing_progress = 80
            elif d['postprocessor'] == 'FFmpegVideoConvertor':
                post_processing_progress = 90
            elif d['postprocessor'] == 'FFmpegExtractAudio':
                post_processing_progress = 95
        logging.debug(f"Post-processing: {d.get('postprocessor', 'unknown')}")

def extract_video_id(url: str) -> str:
    """Extract YouTube video ID from URL"""
    # Handle different URL formats
    if 'youtu.be' in url:
        # youtu.be format
        video_id = url.split('/')[-1].split('?')[0]
    elif 'youtube.com/watch' in url:
        # youtube.com/watch format
        parsed_url = urlparse(url)
        video_id = parse_qs(parsed_url.query).get('v', [''])[0]
    elif 'youtube.com/shorts' in url:
        # youtube.com/shorts format
        video_id = url.split('/')[-1].split('?')[0]
    elif 'youtube.com/embed' in url:
        # youtube.com/embed format
        video_id = url.split('/')[-1].split('?')[0]
    else:
        video_id = ''
    
    if not video_id:
        raise ValueError("Could not extract video ID from URL")
    
    return video_id

def get_video_info(url: str) -> Dict[str, Any]:
    """Get information about the YouTube video using YouTube Data API"""
    if not YOUTUBE_API_KEY:
        raise ValueError("YouTube API key is required but not set")
    
    try:
        # Extract video ID from URL
        video_id = extract_video_id(url)
        
        # Get video info from YouTube Data API
        api_url = f"https://www.googleapis.com/youtube/v3/videos?id={video_id}&key={YOUTUBE_API_KEY}&part=snippet,contentDetails,statistics"
        response = requests.get(api_url)
        
        if response.status_code != 200:
            logging.error(f"YouTube API error: {response.status_code}, {response.text}")
            raise ValueError(f"YouTube API error: {response.status_code}")
        
        data = response.json()
        if not data.get('items'):
            raise ValueError("Video not found or unavailable")
        
        video_data = data['items'][0]
        snippet = video_data.get('snippet', {})
        content_details = video_data.get('contentDetails', {})
        
        # Parse duration (in ISO 8601 format, e.g., "PT1H21M54S")
        duration_str = content_details.get('duration', 'PT0S')
        duration_seconds = parse_duration(duration_str)
        
        # Get best thumbnail
        thumbnails = snippet.get('thumbnails', {})
        thumbnail_url = ''
        for quality in ['maxres', 'high', 'medium', 'default']:
            if quality in thumbnails:
                thumbnail_url = thumbnails[quality]['url']
                break
        
        # Standard video resolutions and audio bitrates
        video_resolutions = ['1080p', '720p', '480p', '360p', '240p']
        audio_bitrates = ['320kbps', '256kbps', '192kbps', '128kbps', '96kbps']
        
        # Return standardized video information
        return {
            'title': snippet.get('title', 'Unknown Title'),
            'author': snippet.get('channelTitle', 'Unknown Author'),
            'length': duration_seconds,  # in seconds
            'thumbnail': thumbnail_url,
            'video_resolutions': video_resolutions,
            'audio_bitrates': audio_bitrates
        }
    
    except requests.RequestException as e:
        logging.error(f"Network error accessing YouTube API: {str(e)}")
        raise ValueError(f"Network error: {str(e)}")
    except Exception as e:
        logging.error(f"Error retrieving video info: {str(e)}")
        raise ValueError(f"Error retrieving video info: {str(e)}")

def parse_duration(duration_str: str) -> int:
    """Parse ISO 8601 duration format to seconds"""
    hours, minutes, seconds = 0, 0, 0
    
    # Remove 'PT' prefix
    duration = duration_str[2:]
    
    # Extract hours
    if 'H' in duration:
        hours_str, duration = duration.split('H')
        hours = int(hours_str)
    
    # Extract minutes
    if 'M' in duration:
        minutes_str, duration = duration.split('M')
        minutes = int(minutes_str)
    
    # Extract seconds
    if 'S' in duration:
        seconds_str = duration.split('S')[0]
        seconds = int(seconds_str)
    
    return hours * 3600 + minutes * 60 + seconds

def get_download_progress() -> Dict[str, Any]:
    """Get the current download progress"""
    global current_download_progress, current_download_file, current_download_phase, download_eta, post_processing_progress
    
    # Calculate overall progress
    overall_progress = current_download_progress
    if current_download_phase == "Processing":
        # If we're in processing phase, use post-processing progress
        if post_processing_progress > 0:
            overall_progress = post_processing_progress
    
    return {
        'progress': overall_progress,
        'file': current_download_file,
        'phase': current_download_phase,
        'eta': download_eta
    }

def download_media(url: str, format_type: str, quality: str) -> str:
    """
    Download YouTube video or audio using yt-dlp
    
    Args:
        url: YouTube URL
        format_type: 'mp3' or 'mp4'
        quality: resolution for mp4, bitrate for mp3
    
    Returns:
        Path to the downloaded file
    """
    global current_download_progress, current_download_file, current_download_phase, download_eta, post_processing_progress
    
    # Reset progress trackers
    current_download_progress = 0
    current_download_phase = "Preparing"
    download_eta = ""
    post_processing_progress = 0
    
    try:
        # Create temp directory for processing
        temp_dir = tempfile.mkdtemp()
        logging.debug(f"Using temp directory: {temp_dir}")
        
        # Get basic info to set filename (using the API)
        basic_info = get_video_info(url)
        video_title = clean_filename(basic_info['title'])
        current_download_file = video_title
        
        if format_type == 'mp4':
            return download_mp4(url, video_title, quality, temp_dir)
        elif format_type == 'mp3':
            return download_mp3(url, video_title, quality, temp_dir)
        else:
            raise ValueError(f"Unsupported format: {format_type}")
    
    except Exception as e:
        logging.error(f"Error in download_media: {str(e)}")
        raise ValueError(f"Download failed: {str(e)}")

def download_mp4(url: str, video_title: str, resolution: str, temp_dir: str) -> str:
    """Download YouTube video as MP4"""
    try:
        # Extract height from resolution (e.g., '720p' -> 720)
        height = int(resolution.replace('p', ''))
        output_file = f"{temp_dir}/{video_title}.mp4"
        
        # Configure yt-dlp options
        ydl_opts = {
            'format': f'bestvideo[height<={height}]+bestaudio/best[height<={height}]',
            'outtmpl': output_file,
            'progress_hooks': [progress_hook],
            'merge_output_format': 'mp4',
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
        }
        
        # Download video
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        return output_file
    
    except yt_dlp.utils.DownloadError as e:
        logging.error(f"yt-dlp error: {str(e)}")
        raise ValueError(f"Download failed: {str(e)}")
    except Exception as e:
        logging.error(f"Error in download_mp4: {str(e)}")
        raise ValueError(f"Download failed: {str(e)}")

def download_mp3(url: str, video_title: str, bitrate: str, temp_dir: str) -> str:
    """Download YouTube video as MP3"""
    try:
        # Extract bitrate value (e.g., '128kbps' -> 128)
        bitrate_value = bitrate.replace('kbps', '')
        output_file = f"{temp_dir}/{video_title}.mp3"
        
        # Configure yt-dlp options for MP3 download
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f"{temp_dir}/temp_{video_title}",
            'progress_hooks': [progress_hook],
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': bitrate_value,
            }],
        }
        
        # Download audio
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        # The output file will be generated with .mp3 extension by yt-dlp
        final_output = f"{temp_dir}/temp_{video_title}.mp3"
        
        # Move to the correct filename
        if os.path.exists(final_output):
            os.rename(final_output, output_file)
        else:
            logging.warning(f"Expected file not found: {final_output}")
            # Try to find the file with a similar name
            for file in os.listdir(temp_dir):
                if file.startswith("temp_") and file.endswith(".mp3"):
                    full_path = os.path.join(temp_dir, file)
                    os.rename(full_path, output_file)
                    break
        
        return output_file
    
    except yt_dlp.utils.DownloadError as e:
        logging.error(f"yt-dlp error: {str(e)}")
        raise ValueError(f"Download failed: {str(e)}")
    except Exception as e:
        logging.error(f"Error in download_mp3: {str(e)}")
        raise ValueError(f"Download failed: {str(e)}")
