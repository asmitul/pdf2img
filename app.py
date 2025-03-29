#!/usr/bin/env python3
import os
import uuid
import time
import threading
import json
import shutil
from datetime import datetime
from flask import Flask, request, render_template, send_from_directory, redirect, url_for, jsonify, flash, session
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import pdf_to_image

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['OUTPUT_FOLDER'] = 'output'
app.config['STATUS_FOLDER'] = 'status'
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32MB max file size
app.config['SECRET_KEY'] = 'your-secret-key-change-in-production'  # For session/login security
app.config['USERS_FILE'] = 'users.json'  # File to store user data

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = "请先登录再访问此页面"

# Create required directories if they don't exist
for folder in [app.config['UPLOAD_FOLDER'], app.config['OUTPUT_FOLDER'], app.config['STATUS_FOLDER']]:
    os.makedirs(folder, exist_ok=True)

# Dictionary to track processing tasks
processing_tasks = {}

# User class for Flask-Login
class User(UserMixin):
    def __init__(self, id, username, password_hash, is_admin=False):
        self.id = id
        self.username = username
        self.password_hash = password_hash
        self.is_admin = is_admin

    @staticmethod
    def check_password(password_hash, password):
        return check_password_hash(password_hash, password)

    def get_id(self):
        return self.id

# Load users from JSON file
def load_users():
    if not os.path.exists(app.config['USERS_FILE']):
        # Create default admin if no users file exists
        users = {
            'admin': {
                'id': 'admin',
                'username': 'admin',
                'password_hash': generate_password_hash('admin'),
                'is_admin': True
            }
        }
        with open(app.config['USERS_FILE'], 'w') as f:
            json.dump(users, f)
        print("Created default admin user (username: admin, password: admin)")
    
    with open(app.config['USERS_FILE'], 'r') as f:
        return json.load(f)

# Save users to JSON file
def save_users(users):
    with open(app.config['USERS_FILE'], 'w') as f:
        json.dump(users, f)

# User loader for Flask-Login
@login_manager.user_loader
def load_user(user_id):
    users = load_users()
    if user_id in users:
        user_data = users[user_id]
        return User(
            id=user_id,
            username=user_data['username'],
            password_hash=user_data['password_hash'],
            is_admin=user_data.get('is_admin', False)
        )
    return None

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
    # Redirect to login if not logged in
    if not current_user.is_authenticated:
        return redirect(url_for('login'))
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        users = load_users()
        user_found = None
        
        # Find user by username
        for user_id, user_data in users.items():
            if user_data['username'] == username:
                user_found = User(
                    id=user_id,
                    username=user_data['username'],
                    password_hash=user_data['password_hash'],
                    is_admin=user_data.get('is_admin', False)
                )
                break
        
        if user_found and User.check_password(user_found.password_hash, password):
            login_user(user_found)
            flash('登录成功！', 'success')
            return redirect(url_for('index'))
        else:
            flash('用户名或密码错误', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('您已成功登出', 'success')
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        password_confirm = request.form.get('password_confirm')
        
        # Validate input
        users = load_users()
        
        # Check if username exists
        for user_data in users.values():
            if user_data['username'] == username:
                flash('用户名已存在', 'danger')
                return render_template('register.html')
        
        # Check if passwords match
        if password != password_confirm:
            flash('两次密码输入不一致', 'danger')
            return render_template('register.html')
        
        # Create new user
        user_id = str(uuid.uuid4())
        users[user_id] = {
            'id': user_id,
            'username': username,
            'password_hash': generate_password_hash(password),
            'is_admin': False
        }
        
        save_users(users)
        flash('注册成功，现在可以登录', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/admin', methods=['GET', 'POST'])
@login_required
def admin():
    if not current_user.is_admin:
        flash('您没有管理员权限', 'danger')
        return redirect(url_for('index'))
    
    users = load_users()
    user_list = []
    
    for user_id, user_data in users.items():
        user_list.append({
            'id': user_id,
            'username': user_data['username'],
            'is_admin': user_data.get('is_admin', False)
        })
    
    return render_template('admin.html', users=user_list)

@app.route('/admin/user/delete/<user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        flash('您没有管理员权限', 'danger')
        return redirect(url_for('index'))
    
    users = load_users()
    
    # Don't allow deleting yourself
    if user_id == current_user.id:
        flash('不能删除自己的账户', 'danger')
        return redirect(url_for('admin'))
    
    if user_id in users:
        del users[user_id]
        save_users(users)
        flash('用户已删除', 'success')
    else:
        flash('用户不存在', 'danger')
    
    return redirect(url_for('admin'))

@app.route('/admin/user/toggle-admin/<user_id>', methods=['POST'])
@login_required
def toggle_admin(user_id):
    if not current_user.is_admin:
        flash('您没有管理员权限', 'danger')
        return redirect(url_for('index'))
    
    users = load_users()
    
    if user_id in users:
        users[user_id]['is_admin'] = not users[user_id].get('is_admin', False)
        save_users(users)
        flash('管理员权限已更改', 'success')
    else:
        flash('用户不存在', 'danger')
    
    return redirect(url_for('admin'))

@app.route('/user/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        users = load_users()
        if current_user.id in users:
            user_data = users[current_user.id]
            
            # Verify current password
            if not User.check_password(user_data['password_hash'], current_password):
                flash('当前密码不正确', 'danger')
                return render_template('profile.html')
            
            # Check if new passwords match
            if new_password != confirm_password:
                flash('新密码两次输入不一致', 'danger')
                return render_template('profile.html')
            
            # Update password
            users[current_user.id]['password_hash'] = generate_password_hash(new_password)
            save_users(users)
            flash('密码已更新', 'success')
        
    return render_template('profile.html')

@app.route('/upload', methods=['POST'])
@login_required
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
                     rotation=rotation, crop_margin=crop_margin,
                     user_id=current_user.id, username=current_user.username)
        
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
@login_required
def check_status(file_id):
    """API endpoint to check processing status"""
    status = get_status(file_id)
    
    # Check if user has access to this file
    if 'user_id' in status and status['user_id'] != current_user.id and not current_user.is_admin:
        return jsonify({"error": "Access denied", "status": "error", "message": "您没有权限查看此文件"}), 403
    
    return jsonify(status)

@app.route('/view/<file_id>')
@login_required
def view_results(file_id):
    output_dir = os.path.join(app.config['OUTPUT_FOLDER'], file_id)
    
    # Check if processing is still ongoing
    status = get_status(file_id)
    
    # Check if user has access to this file
    if 'user_id' in status and status['user_id'] != current_user.id and not current_user.is_admin:
        flash('您没有权限查看此文件', 'danger')
        return redirect(url_for('index'))
    
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
    
    # Get original filename for display
    original_filename = status.get('original_filename', '未知文件名')
        
    return render_template('view.html', file_id=file_id, images=images, original_filename=original_filename)

@app.route('/download/<file_id>/<filename>')
@login_required
def download_file(file_id, filename):
    # Check if user has access to this file
    status = get_status(file_id)
    if 'user_id' in status and status['user_id'] != current_user.id and not current_user.is_admin:
        flash('您没有权限下载此文件', 'danger')
        return redirect(url_for('index'))
    
    output_dir = os.path.join(app.config['OUTPUT_FOLDER'], file_id)
    return send_from_directory(output_dir, filename)

@app.route('/download-all/<file_id>')
@login_required
def download_all(file_id):
    # Check if user has access to this file
    status = get_status(file_id)
    if 'user_id' in status and status['user_id'] != current_user.id and not current_user.is_admin:
        flash('您没有权限下载此文件', 'danger')
        return redirect(url_for('index'))
    
    # Check if processing is complete
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
@login_required
def cleanup():
    """Clean up uploads, output, and status folders"""
    # Only admins can clean everything
    is_admin = current_user.is_admin
    user_id = current_user.id
    
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
            
            # For non-admins, only clean their own files
            if not is_admin:
                # Check if this is a conversion directory with a status file
                if os.path.isdir(item_path):
                    status_file = os.path.join(app.config['STATUS_FOLDER'], f"{item}.json")
                    if os.path.exists(status_file):
                        with open(status_file, 'r') as f:
                            status = json.load(f)
                            if status.get('user_id') != user_id:
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
            
            # For non-admins, only clean their own files
            if not is_admin:
                item_id = item.split('.')[0]  # Get ID without extension
                status_file = os.path.join(app.config['STATUS_FOLDER'], f"{item_id}.json")
                if os.path.exists(status_file):
                    with open(status_file, 'r') as f:
                        status = json.load(f)
                        if status.get('user_id') != user_id:
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
            
            # For non-admins, only clean their own files
            if not is_admin:
                with open(item_path, 'r') as f:
                    status = json.load(f)
                    if status.get('user_id') != user_id:
                        continue
            
            # Remove the item
            os.remove(item_path)
            status_count += 1
        
        message = f"清理完成: 已删除 {output_count} 个输出文件夹, {upload_count} 个上传文件, 和 {status_count} 个状态文件"
        return jsonify({'success': True, 'message': message})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/disk-usage')
@login_required
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
@login_required
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
                
                # Debug output
                print(f"Status data for {status_file}: {status_data}")
                
                file_id = status_data.get('id', status_file.replace('.json', ''))
                
                # For non-admins, only show their own files
                if not current_user.is_admin:
                    if status_data.get('user_id') != current_user.id:
                        continue
                
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
                print(f"Original filename: {original_filename}")
                
                # Get processing parameters
                dpi = status_data.get('dpi', 300)
                split_pages = status_data.get('split_pages', False)
                rotation = status_data.get('rotation', '自动')
                crop_margin = status_data.get('crop_margin', 0)
                
                # Get user info
                username = status_data.get('username', '未知用户')
                
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
                        'crop_margin': crop_margin,
                        'username': username
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