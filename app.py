import os
import sys
import json
import subprocess
import threading
import time
from pathlib import Path
from collections import deque
from flask import Flask, render_template, request, Response, jsonify

# Global configuration
config = {}
app = Flask(__name__)

# Global state for the running job
running_job = {
    'process': None,
    'logs': deque(maxlen=500),  # Keep last 500 log lines (reduced for memory)
    'status': 'idle',  # idle, running, completed, failed, aborted
    'start_time': None
}
log_lock = threading.Lock()
log_event = threading.Event()  # Signal when new logs are available


def read_process_output(process):
    """Read process output line by line and store in logs"""
    try:
        for line in iter(process.stdout.readline, b''):
            with log_lock:
                log_line = line.decode('utf-8').rstrip()
                running_job['logs'].append(log_line)
                log_event.set()  # Signal that new logs are available
        
        # Wait for process to complete
        return_code = process.wait()
        
        with log_lock:
            if return_code == 0:
                running_job['status'] = 'completed'
                running_job['logs'].append(f"[{time.strftime('%H:%M:%S')}] Process completed successfully")
            elif return_code == -15:  # SIGTERM
                running_job['status'] = 'aborted'
                running_job['logs'].append(f"[{time.strftime('%H:%M:%S')}] Process aborted by user")
            else:
                running_job['status'] = 'failed'
                running_job['logs'].append(f"[{time.strftime('%H:%M:%S')}] Process failed with code {return_code}")
            
            running_job['process'] = None
            log_event.set()  # Signal final status change
    
    except Exception as e:
        with log_lock:
            running_job['status'] = 'failed'
            running_job['logs'].append(f"[{time.strftime('%H:%M:%S')}] Error: {str(e)}")
            running_job['process'] = None
            log_event.set()  # Signal error


@app.route('/')
def index():
    return render_template('index.html', config=config)


@app.route('/start', methods=['POST'])
def start_sync():
    with log_lock:
        if running_job['process'] is not None:
            return jsonify({'error': 'A job is already running'}), 400
        
        # Build command using sync_runner.py which accepts cookies directly
        script_path = Path(__file__).parent / 'sync_runner.py'
        cmd = [sys.executable, str(script_path)]
        
        cookies_string = config.get('cookies', '').strip()
        directory = config.get('directory', '').strip()
        format_type = config.get('format', 'flac').strip()
        ignore_file = config.get('ignore_file', '').strip()
        ignore_patterns = config.get('ignore_patterns', '').strip()
        temp_dir = config.get('temp_dir', '').strip()
        notify_url = config.get('notify_url', '').strip()
        
        if not cookies_string or not directory:
            return jsonify({'error': 'Cookies and directory must be configured in config file'}), 400
        
        # Expand paths properly
        directory = str(Path(directory).expanduser().resolve())
        if ignore_file:
            ignore_file = str(Path(ignore_file).expanduser().resolve())
        if temp_dir:
            temp_dir = str(Path(temp_dir).expanduser().resolve())
        
        # Create directories if they don't exist
        try:
            Path(directory).mkdir(parents=True, exist_ok=True)
            if temp_dir:
                Path(temp_dir).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return jsonify({'error': f'Failed to create directory: {str(e)}'}), 400
        
        try:
            # Pass cookies directly as argument (no temp file needed)
            cmd.extend(['-C', cookies_string, '-d', directory, '-f', format_type])
            
            if ignore_file:
                cmd.extend(['-I', ignore_file])
            if ignore_patterns:
                cmd.extend(['-i', ignore_patterns])
            if temp_dir:
                cmd.extend(['-t', temp_dir])
            if notify_url:
                cmd.extend(['-n', notify_url])
            
            # Start process
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=False,
                bufsize=1
            )
            
            # Update global state
            running_job['process'] = process
            running_job['logs'].clear()
            running_job['status'] = 'running'
            running_job['start_time'] = time.time()
            
            # Start background thread to read output
            thread = threading.Thread(target=read_process_output, args=(process,))
            thread.daemon = True
            thread.start()
            
            running_job['logs'].append(f"[{time.strftime('%H:%M:%S')}] Starting bandcampsync...")
            # Redact sensitive information from logged command
            redacted_cmd = []
            skip_next = False
            for arg in cmd:
                if skip_next:
                    redacted_cmd.append('[REDACTED]')
                    skip_next = False
                elif arg == '-C':
                    redacted_cmd.append(arg)
                    skip_next = True
                else:
                    redacted_cmd.append(arg)
            running_job['logs'].append(f"[{time.strftime('%H:%M:%S')}] Command: {' '.join(redacted_cmd)}")
            
            return jsonify({'success': True})
            
        except Exception as e:
            running_job['status'] = 'failed'
            return jsonify({'error': f'Failed to start process: {str(e)}'}), 500


@app.route('/abort', methods=['POST'])
def abort_sync():
    with log_lock:
        if running_job['process'] is None:
            return jsonify({'error': 'No job is running'}), 400
        
        try:
            running_job['process'].terminate()
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'error': f'Failed to abort process: {str(e)}'}), 500


@app.route('/status')
def get_status():
    with log_lock:
        return jsonify({
            'status': running_job['status'],
            'start_time': running_job['start_time'],
            'log_count': len(running_job['logs'])
        })


@app.route('/logs')
def stream_logs():
    def generate():
        last_sent = 0
        
        # Send existing logs first
        with log_lock:
            for i, log_line in enumerate(running_job['logs']):
                yield f"data: {log_line}\n\n"
                last_sent = i + 1
            yield f"data: __STATUS__{running_job['status']}\n\n"
            # Check if already done before entering loop
            if running_job['process'] is None and running_job['status'] in ['completed', 'failed', 'aborted']:
                return
        
        # Wait for new logs using events with timeout to prevent indefinite blocking
        while True:
            # Wait for the event to be set with timeout (prevents hanging if idle)
            event_set = log_event.wait(timeout=30)
            
            with log_lock:
                # Clear the event FIRST while holding the lock to avoid race condition
                log_event.clear()
                
                # Send any new logs
                current_logs = list(running_job['logs'])
                if len(current_logs) > last_sent:
                    for log_line in current_logs[last_sent:]:
                        yield f"data: {log_line}\n\n"
                    last_sent = len(current_logs)
                
                # Send status update (also serves as keepalive on timeout)
                yield f"data: __STATUS__{running_job['status']}\n\n"
                
                # Exit if job is done
                if running_job['process'] is None and running_job['status'] in ['completed', 'failed', 'aborted']:
                    break
                
                # If we're idle and timed out, exit to free the connection
                if not event_set and running_job['status'] == 'idle':
                    break
    
    response = Response(generate(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'
    return response


def load_config(config_path):
    """Load configuration from JSON file"""
    global config
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        print(f"Loaded configuration from {config_path}")
    except FileNotFoundError:
        print(f"Error: Configuration file not found: {config_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in configuration file: {e}")
        sys.exit(1)


def create_template_config():
    """Create a template config.json file in the current directory"""
    template_config = {
        "cookies": "your_bandcamp_cookies_string_here",
        "directory": "~/Music/Bandcamp",
        "format": "flac",
        "ignore_file": "",
        "ignore_patterns": "",
        "temp_dir": "",
        "notify_url": ""
    }
    
    config_filename = "config.json"
    if os.path.exists(config_filename):
        print(f"Config file '{config_filename}' already exists. Not overwriting.")
        return
    
    try:
        with open(config_filename, 'w') as f:
            json.dump(template_config, f, indent=2)
        print(f"Created template config file: {config_filename}")
        print("Please edit the file with your settings, then run:")
        print(f"python app.py {config_filename}")
    except Exception as e:
        print(f"Error creating config file: {e}")
        sys.exit(1)


def initialize_app():
    """Initialize the application by loading config from environment or argument"""
    # Check for config path in environment variable first (for Docker/gunicorn)
    config_path = os.environ.get('CONFIG_PATH')
    
    if config_path:
        load_config(config_path)
        return True
    
    # Fall back to command line argument for direct execution
    if len(sys.argv) >= 2:
        load_config(sys.argv[1])
        return True
    
    return False


# Initialize when imported by gunicorn
if os.environ.get('CONFIG_PATH'):
    initialize_app()


if __name__ == '__main__':
    if not initialize_app():
        print("No config file provided. Creating template config file...")
        create_template_config()
        sys.exit(0)
    
    app.run(debug=True, host='127.0.0.1', port=5000, threaded=True)