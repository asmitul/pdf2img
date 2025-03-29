#!/usr/bin/env python3
import os
import uuid
from flask import Flask, request, render_template, send_from_directory, redirect, url_for, jsonify
from werkzeug.utils import secure_filename
import pdf_to_image

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['OUTPUT_FOLDER'] = 'output'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Ensure upload and output directories exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

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
            
        # Process PDF
        output_dir = os.path.join(app.config['OUTPUT_FOLDER'], unique_id)
        pdf_to_image.process_pdf(
            filepath, 
            output_dir, 
            dpi=dpi, 
            split_pages=split_pages, 
            rotation=rotation, 
            crop_margin=crop_margin
        )
        
        return jsonify({
            'success': True,
            'id': unique_id,
            'message': 'PDF processed successfully'
        })
    
    return jsonify({'error': 'Invalid file type'}), 400

@app.route('/view/<file_id>')
def view_results(file_id):
    output_dir = os.path.join(app.config['OUTPUT_FOLDER'], file_id)
    if not os.path.exists(output_dir):
        return "Results not found", 404
    
    # Get list of images
    images = sorted([f for f in os.listdir(output_dir) if f.endswith(('.png', '.jpg'))])
    return render_template('view.html', file_id=file_id, images=images)

@app.route('/download/<file_id>/<filename>')
def download_file(file_id, filename):
    output_dir = os.path.join(app.config['OUTPUT_FOLDER'], file_id)
    return send_from_directory(output_dir, filename)

@app.route('/download-all/<file_id>')
def download_all(file_id):
    import shutil
    
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