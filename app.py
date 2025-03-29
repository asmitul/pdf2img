#!/usr/bin/env python3
import os
import uuid
import time
import threading
import json
from datetime import datetime
from flask import Flask, request, render_template, send_from_directory, redirect, url_for, jsonify
from werkzeug.utils import secure_filename
import pdf_to_image

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['OUTPUT_FOLDER'] = 'output'
app.config['STATUS_FOLDER'] = 'status'
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32MB max file size

# Create required directories if they don't exist
for folder in [app.config['UPLOAD_FOLDER'], app.config['OUTPUT_FOLDER'], app.config['STATUS_FOLDER']]:
    os.makedirs(folder, exist_ok=True)

# Dictionary to track processing tasks
processing_tasks = {}

def process_pdf_in_background(file_id, filepath, output_dir, dpi, split_pages, rotation, crop_margin):
    """Process PDF in a background thread and update status"""
    status_file = os.path.join(app.config['STATUS_FOLDER'], f"{file_id}.json")
    
    try:
        # Update status to processing
        update_status(file_id, "processing", "PDF processing started")
        
        # Process the PDF
        pdf_to_image.process_pdf(
            filepath, 
            output_dir, 
            dpi=dpi, 
            split_pages=split_pages, 
            rotation=rotation, 
            crop_margin=crop_margin
        )
        
        # Update status to completed
        update_status(file_id, "completed", "PDF processed successfully")
    except Exception as e:
        # Update status to error
        update_status(file_id, "error", f"Error processing PDF: {str(e)}")
        print(f"Error processing {file_id}: {str(e)}")
    finally:
        # Remove task from tracking
        if file_id in processing_tasks:
            del processing_tasks[file_id]

def update_status(file_id, status, message):
    """Update the status of a processing task"""
    status_data = {
        "id": file_id,
        "status": status,
        "message": message,
        "timestamp": time.time()
    }
    
    status_file = os.path.join(app.config['STATUS_FOLDER'], f"{file_id}.json")
    with open(status_file, 'w') as f:
        json.dump(status_data, f)
    
    return status_data

def get_status(file_id):
    """Get the status of a processing task"""
    status_file = os.path.join(app.config['STATUS_FOLDER'], f"{file_id}.json")
    
    if not os.path.exists(status_file):
        return {"id": file_id, "status": "unknown", "message": "Status not found"}
    
    with open(status_file, 'r') as f:
        return json.load(f)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'pdf_file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['pdf_file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if file and file.filename.lower().endswith('.pdf'):
        # Generate unique filename
        unique_id = str(uuid.uuid4())
        filename = unique_id + '.pdf'
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # Get parameters from form
        dpi = int(request.form.get('dpi', 300))
        split_pages = 'split' in request.form
        rotation = request.form.get('rotation')
        crop_margin = int(request.form.get('crop_margin', 0))
        
        # Convert rotation to int if provided
        if rotation and rotation != 'auto':
            rotation = int(rotation)
        else:
            rotation = None
            
        # Create output directory
        output_dir = os.path.join(app.config['OUTPUT_FOLDER'], unique_id)
        os.makedirs(output_dir, exist_ok=True)
        
        # Initialize status
        update_status(unique_id, "pending", "PDF upload completed, waiting for processing")
        
        # Start background processing
        process_thread = threading.Thread(
            target=process_pdf_in_background,
            args=(unique_id, filepath, output_dir, dpi, split_pages, rotation, crop_margin)
        )
        process_thread.daemon = True
        process_thread.start()
        
        # Keep track of the task
        processing_tasks[unique_id] = process_thread
        
        return jsonify({
            'success': True,
            'id': unique_id,
            'message': 'PDF upload successful, processing started',
            'status': 'pending'
        })
    
    return jsonify({'error': 'Invalid file type'}), 400

@app.route('/status/<file_id>')
def check_status(file_id):
    """API endpoint to check processing status"""
    status = get_status(file_id)
    return jsonify(status)

@app.route('/view/<file_id>')
def view_results(file_id):
    output_dir = os.path.join(app.config['OUTPUT_FOLDER'], file_id)
    
    # Check if processing is still ongoing
    status = get_status(file_id)
    if status['status'] == 'pending' or status['status'] == 'processing':
        return render_template('processing.html', file_id=file_id, status=status)
    
    if status['status'] == 'error':
        error_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return render_template('error.html', file_id=file_id, status=status, error_time=error_time)
    
    if not os.path.exists(output_dir):
        return "Results not found", 404
    
    # Get list of images
    images = sorted([f for f in os.listdir(output_dir) if f.endswith(('.png', '.jpg'))])
    
    if not images:
        return "No images found", 404
        
    return render_template('view.html', file_id=file_id, images=images)

@app.route('/download/<file_id>/<filename>')
def download_file(file_id, filename):
    output_dir = os.path.join(app.config['OUTPUT_FOLDER'], file_id)
    return send_from_directory(output_dir, filename)

@app.route('/download-all/<file_id>')
def download_all(file_id):
    import shutil
    
    # Check if processing is complete
    status = get_status(file_id)
    if status['status'] != 'completed':
        return jsonify({'error': 'Processing not completed'}), 400
    
    output_dir = os.path.join(app.config['OUTPUT_FOLDER'], file_id)
    if not os.path.exists(output_dir):
        return "Results not found", 404
    
    # Create a zip file with all images
    zip_filename = f"{file_id}_images.zip"
    zip_path = os.path.join(app.config['OUTPUT_FOLDER'], zip_filename)
    
    shutil.make_archive(
        os.path.join(app.config['OUTPUT_FOLDER'], file_id + "_images"), 
        'zip', 
        output_dir
    )
    
    return send_from_directory(app.config['OUTPUT_FOLDER'], zip_filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8090, debug=False) 