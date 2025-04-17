import os
import logging

from flask import Flask, render_template, request, jsonify, send_file, session
import downloader

# Configure logging
logging.basicConfig(level=logging.DEBUG)

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "youtube_downloader_secret")

@app.route('/')
def index():
    """Render the home page"""
    return render_template('index.html')

@app.route('/get_video_info', methods=['POST'])
def get_video_info():
    """Get information about the YouTube video"""
    url = request.form.get('url')
    
    if not url:
        return jsonify({'error': 'URL is required'}), 400
    
    try:
        # Try to fetch video info with retries
        video_info = downloader.get_video_info(url)
        session['last_url'] = url  # Store URL in session for later use
        return jsonify(video_info)
    except ValueError as e:
        # Format the error message to be more user-friendly
        error_msg = str(e)
        logging.error(f"Error getting video info: {error_msg}")
        
        # Send specific error messages for common problems
        if "HTML5 player" in error_msg or "HTTP Error 400" in error_msg:
            return jsonify({'error': 'YouTube API error. Please try again later or try a different video.'}), 400
        elif "live stream" in error_msg.lower():
            return jsonify({'error': 'Live streams are not supported for download.'}), 400
        else:
            return jsonify({'error': error_msg}), 400
    except Exception as e:
        # Catch any other unexpected exceptions
        logging.error(f"Unexpected error getting video info: {str(e)}")
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@app.route('/download', methods=['POST'])
def download_media():
    """Download YouTube video or audio"""
    url = request.form.get('url')
    format_type = request.form.get('format')  # 'mp3' or 'mp4'
    quality = request.form.get('quality')  # For MP4: resolution, For MP3: bitrate
    
    if not url or not format_type:
        return jsonify({'error': 'URL and format are required'}), 400
    
    if format_type not in ['mp3', 'mp4']:
        return jsonify({'error': 'Invalid format. Supported formats are mp3 and mp4'}), 400
    
    try:
        # Start download process
        download_path = downloader.download_media(url, format_type, quality)
        
        # Extract filename from the path
        filename = os.path.basename(download_path)
        
        # Get the file extension
        _, file_extension = os.path.splitext(download_path)
        
        # Set appropriate MIME type
        if file_extension.lower() == '.mp3':
            mimetype = 'audio/mpeg'
        elif file_extension.lower() == '.mp4':
            mimetype = 'video/mp4'
        else:
            mimetype = 'application/octet-stream'
        
        # Create a generator to stream the file in chunks
        def generate():
            with open(download_path, 'rb') as f:
                while True:
                    chunk = f.read(4096)  # Read in 4KB chunks
                    if not chunk:
                        break
                    yield chunk
        
        # Use streaming response for better performance
        response = app.response_class(
            generate(),
            mimetype=mimetype
        )
        
        # Set Content-Disposition header
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        # Set Content-Length header if file is not too large
        file_size = os.path.getsize(download_path)
        if file_size < 1024 * 1024 * 500:  # Only set for files smaller than 500MB
            response.headers['Content-Length'] = str(file_size)
        
        return response
        
    except ValueError as e:
        # Format the error message to be more user-friendly
        error_msg = str(e)
        logging.error(f"Error downloading media: {error_msg}")
        
        # Send specific error messages for common problems
        if "HTML5 player" in error_msg or "HTTP Error 400" in error_msg:
            return jsonify({'error': 'YouTube API error. Please try again later or try a different video.'}), 400
        elif "live stream" in error_msg.lower():
            return jsonify({'error': 'Live streams are not supported for download.'}), 400
        elif "ffmpeg" in error_msg.lower():
            return jsonify({'error': 'Error processing media. The video may be in an unsupported format.'}), 400
        else:
            return jsonify({'error': error_msg}), 400
    except Exception as e:
        # Catch any other unexpected exceptions
        logging.error(f"Unexpected error downloading media: {str(e)}")
        return jsonify({'error': 'An unexpected error occurred. Please try again later.'}), 500

@app.route('/download_progress')
def download_progress():
    """Get the download progress status"""
    try:
        progress = downloader.get_download_progress()
        return jsonify(progress)
    except Exception as e:
        logging.error(f"Error getting download progress: {str(e)}")
        return jsonify({'error': str(e)}), 400

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
