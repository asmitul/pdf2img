#!/usr/bin/env python3
import os
import uuid
import time
import threading
import json
import shutil
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
        # Get current status to preserve custom fields
        current_status = {}
        if os.path.exists(status_file):
            with open(status_file, 'r') as f:
                current_status = json.load(f)
        
        # Update status to processing while preserving other fields
        update_status(file_id, "processing", "PDF processing started", 
                     **{k: v for k, v in current_status.items() 
                        if k not in ['id', 'status', 'message', 'timestamp']})
        
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
        update_status(file_id, "completed", "PDF processed successfully", 
                     **{k: v for k, v in current_status.items() 
                        if k not in ['id', 'status', 'message', 'timestamp']})
    except Exception as e:
        # Update status to error
        update_status(file_id, "error", f"Error processing PDF: {str(e)}",
                     **{k: v for k, v in current_status.items() 
                        if k not in ['id', 'status', 'message', 'timestamp']})
        print(f"Error processing {file_id}: {str(e)}")
    finally:
        # Remove task from tracking
        if file_id in processing_tasks:
            del processing_tasks[file_id]

def update_status(file_id, status, message, **kwargs):
    """Update the status of a processing task"""
    status_data = {
        "id": file_id,
        "status": status,
        "message": message,
        "timestamp": time.time(),
        **kwargs
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
        original_filename = secure_filename(file.filename)
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
        update_status(unique_id, "pending", "PDF upload completed, waiting for processing", 
                     original_filename=original_filename, dpi=dpi, split_pages=split_pages,
                     rotation=rotation, crop_margin=crop_margin)
        
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

@app.route('/cleanup', methods=['POST'])
def cleanup():
    """Clean up uploads, output, and status folders"""
    try:
        # Get list of items to keep (e.g., currently processing files)
        active_tasks = list(processing_tasks.keys())
        
        # Clean up output folder
        output_count = 0
        for item in os.listdir(app.config['OUTPUT_FOLDER']):
            item_path = os.path.join(app.config['OUTPUT_FOLDER'], item)
            
            # Skip if it's an active task
            skip = False
            for task_id in active_tasks:
                if task_id in item:
                    skip = True
                    break
            
            if skip:
                continue
                
            # Remove the item
            if os.path.isdir(item_path):
                shutil.rmtree(item_path)
            else:
                os.remove(item_path)
            output_count += 1
        
        # Clean up uploads folder
        upload_count = 0
        for item in os.listdir(app.config['UPLOAD_FOLDER']):
            item_path = os.path.join(app.config['UPLOAD_FOLDER'], item)
            
            # Skip if it's an active task
            skip = False
            for task_id in active_tasks:
                if task_id in item:
                    skip = True
                    break
            
            if skip:
                continue
                
            # Remove the item
            os.remove(item_path)
            upload_count += 1
        
        # Clean up status folder
        status_count = 0
        for item in os.listdir(app.config['STATUS_FOLDER']):
            if not item.endswith('.json'):
                continue
                
            item_path = os.path.join(app.config['STATUS_FOLDER'], item)
            
            # Skip if it's an active task
            skip = False
            for task_id in active_tasks:
                if task_id in item:
                    skip = True
                    break
            
            if skip:
                continue
                
            # Remove the item
            os.remove(item_path)
            status_count += 1
        
        message = f"清理完成: 已删除 {output_count} 个输出文件夹, {upload_count} 个上传文件, 和 {status_count} 个状态文件"
        return jsonify({'success': True, 'message': message})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/disk-usage')
def disk_usage():
    """Get disk usage information for the app folders"""
    try:
        def get_size(path):
            total_size = 0
            item_count = 0
            for dirpath, dirnames, filenames in os.walk(path):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    if os.path.exists(fp):
                        total_size += os.path.getsize(fp)
                        item_count += 1
            return total_size, item_count
        
        # Get sizes
        upload_size, upload_count = get_size(app.config['UPLOAD_FOLDER'])
        output_size, output_count = get_size(app.config['OUTPUT_FOLDER'])
        status_size, status_count = get_size(app.config['STATUS_FOLDER'])
        
        # Format sizes
        def format_size(size_bytes):
            if size_bytes < 1024:
                return f"{size_bytes} B"
            elif size_bytes < 1024 * 1024:
                return f"{size_bytes/1024:.1f} KB"
            elif size_bytes < 1024 * 1024 * 1024:
                return f"{size_bytes/(1024*1024):.1f} MB"
            else:
                return f"{size_bytes/(1024*1024*1024):.2f} GB"
        
        # Return usage info
        return jsonify({
            'success': True,
            'uploads': {
                'size': format_size(upload_size),
                'count': upload_count,
                'raw_size': upload_size
            },
            'output': {
                'size': format_size(output_size),
                'count': output_count,
                'raw_size': output_size
            },
            'status': {
                'size': format_size(status_size),
                'count': status_count,
                'raw_size': status_size
            },
            'total': {
                'size': format_size(upload_size + output_size + status_size),
                'count': upload_count + output_count + status_count,
                'raw_size': upload_size + output_size + status_size
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/history')
def conversion_history():
    """Show history of all PDF conversions"""
    try:
        conversions = []
        
        # Get list of status files
        for status_file in os.listdir(app.config['STATUS_FOLDER']):
            if not status_file.endswith('.json'):
                continue
                
            file_path = os.path.join(app.config['STATUS_FOLDER'], status_file)
            try:
                with open(file_path, 'r') as f:
                    status_data = json.load(f)
                
                file_id = status_data.get('id', status_file.replace('.json', ''))
                
                # Check if output directory exists and count images
                output_dir = os.path.join(app.config['OUTPUT_FOLDER'], file_id)
                image_count = 0
                thumbnail = None
                
                if os.path.exists(output_dir):
                    images = [f for f in os.listdir(output_dir) if f.endswith(('.png', '.jpg'))]
                    image_count = len(images)
                    if images:
                        # Get first image as thumbnail
                        thumbnail = images[0]
                
                # Get PDF filename if it exists
                pdf_filename = None
                pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}.pdf")
                if os.path.exists(pdf_path):
                    pdf_filename = f"{file_id}.pdf"
                
                # Format timestamp
                timestamp = status_data.get('timestamp', 0)
                converted_date = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
                
                # Get original filename
                original_filename = status_data.get('original_filename', '未知文件名')
                
                # Get processing parameters
                dpi = status_data.get('dpi', 300)
                split_pages = status_data.get('split_pages', False)
                rotation = status_data.get('rotation', '自动')
                crop_margin = status_data.get('crop_margin', 0)
                
                # Only include completed conversions that have images
                if status_data.get('status') == 'completed' and image_count > 0:
                    conversions.append({
                        'id': file_id,
                        'date': converted_date,
                        'timestamp': timestamp,
                        'status': status_data.get('status', 'unknown'),
                        'message': status_data.get('message', ''),
                        'image_count': image_count,
                        'thumbnail': thumbnail,
                        'pdf_filename': pdf_filename,
                        'original_filename': original_filename,
                        'dpi': dpi,
                        'split_pages': split_pages,
                        'rotation': rotation,
                        'crop_margin': crop_margin
                    })
            except Exception as e:
                print(f"Error reading status file {status_file}: {str(e)}")
        
        # Sort by timestamp, newest first
        conversions.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
        
        return render_template('history.html', conversions=conversions)
    except Exception as e:
        return f"Error retrieving conversion history: {str(e)}", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8090, debug=False) 