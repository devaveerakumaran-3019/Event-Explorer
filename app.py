import os
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from pymongo import MongoClient
from datetime import datetime
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from bson import ObjectId
from werkzeug.utils import secure_filename

# 1. Configuration
load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev_secret_key_change_this")

# Configure Uploads
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# 2. Database Connection
try:
    client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017/"))
    db = client['college_events']
    
    # Collections
    events_col = db['events']
    registrations_col = db['registrations']
    users_col = db['staff']  # Corrected to 'staff' as per your fix
    alumni_col = db['alumni']

    print("✅ Connected to MongoDB")
except Exception as e:
    print(f"❌ DB Connection Error: {e}")

# --- HELPERS ---
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            # If API call, return 401 JSON
            if request.path.startswith('/api/'):
                return jsonify({"error": "Unauthorized"}), 401
            # If Browser navigation, redirect to login
            return redirect('/auth/login')
        return f(*args, **kwargs)
    return decorated

# ==========================================
#  A. HTML PAGE ROUTES (Frontend Loaders)
# ==========================================

@app.route('/')
def home(): return render_template('public/index.html')

@app.route('/event/register')
def register_page(): return render_template('public/register.html')

@app.route('/success')
def success_page(): return render_template('public/success.html')

@app.route('/auth/login')
def login_page(): return render_template('auth/login.html')

@app.route('/auth/signup')
def signup_page(): return render_template('auth/signup.html')

@app.route('/auth/reset-password')
def reset_password_page(): return render_template('auth/reset_password.html')

# Staff Protected Pages
@app.route('/staff/dashboard')
@login_required
def dashboard_page(): return render_template('staff/dashboard.html')

@app.route('/staff/create-event')
@login_required
def create_event_page(): return render_template('staff/create_event.html')

@app.route('/staff/registrations/<event_id>')
@login_required
def view_registrations_page(event_id):
    # Pass event_id to HTML so JS can fetch specific data
    return render_template('staff/registrations.html', event_id=event_id)


# ==========================================
#  B. API ROUTES (Data & Logic)
# ==========================================

# --- 1. AUTH APIs ---

@app.route('/api/auth/signup', methods=['POST'])
def api_signup():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    admin_code = data.get('admin_code')

    if admin_code != "college_admin_2026": 
        return jsonify({"error": "Invalid Admin Code"}), 403

    if users_col.find_one({"username": username}):
        return jsonify({"error": "Username already exists"}), 400

    hashed_pw = generate_password_hash(password)
    users_col.insert_one({
        "username": username, 
        "password": hashed_pw,
        "name": data.get('name'),
        "dept": data.get('dept'),
        "dob": data.get('dob'),
        "role": "staff"
    })
    
    return jsonify({"message": "Account created! Please login."})

@app.route('/api/auth/login', methods=['POST'])
def api_login():
    data = request.json
    user = users_col.find_one({"username": data.get('username')})

    if user and check_password_hash(user['password'], data.get('password')):
        # SET SESSION
        session['user_id'] = str(user['_id'])
        session['username'] = user['username']
        session['role'] = user.get('role', 'staff')
        return jsonify({"success": True})
    
    return jsonify({"error": "Invalid credentials"}), 401

@app.route('/api/auth/logout')
def api_logout():
    session.clear()
    return redirect('/auth/login')

@app.route('/api/auth/reset', methods=['POST'])
def reset_password():
    data = request.json
    username = data.get('username')
    new_password = data.get('new_password')
    admin_code = data.get('admin_code')

    if admin_code != "college_admin_2026":
        return jsonify({'error': 'Invalid Admin Secret Code'}), 403

    hashed_pw = generate_password_hash(new_password)
    result = users_col.update_one(
        {'username': username},
        {'$set': {'password': hashed_pw}}
    )

    if result.matched_count == 0:
        return jsonify({'error': 'User not found'}), 404
        
    return jsonify({'success': True, 'message': 'Password reset successfully!'})


# --- 2. STAFF DASHBOARD APIs ---

@app.route('/api/staff/dashboard-data', methods=['GET'])
@login_required
def get_dashboard_data():
    current_username = session.get('username')
    
    # 1. Get Profile
    staff_user = users_col.find_one({"username": current_username}, {"_id": 0, "password": 0})
    
    # 2. Get Events created by THIS staff
    raw_events = list(events_col.find({"created_by": current_username}).sort("date", 1))
    
    # 3. Process Events (ObjectId -> String, Check Active)
    clean_events = []
    today = datetime.now().strftime('%Y-%m-%d')
    
    for e in raw_events:
        clean_events.append({
            "_id": str(e['_id']),
            "title": e['title'],
            "date": e['date'],
            "category": e.get('category', 'General'),
            "image": e.get('image'),
            "is_active": (e['date'] >= today)
        })

    return jsonify({
        "profile": staff_user,
        "events": clean_events
    })


# --- 3. EVENT MANAGEMENT APIs ---

@app.route('/api/events/create', methods=['POST'])
@login_required
def create_event_api():
    try:
        # 1. Handle Image
        image = request.files.get('image')
        filename = ""
        if image:
            filename = secure_filename(image.filename)
            image.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        # 2. Insert into DB (Added 'time' field)
        events_col.insert_one({
            "title": request.form.get('title'),
            "date": request.form.get('date'),
            "time": request.form.get('time'),    # <--- NEW FIELD
            "venue": request.form.get('venue'),
            "category": request.form.get('category'),
            "description": request.form.get('description'),
            "image": filename,
            "created_by": session.get('username'),
            "created_at": datetime.now(),
            "status": "active"
        })
        return jsonify({"message": "Event created successfully!"}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/events/delete/<event_id>', methods=['DELETE'])
@login_required
def delete_event_api(event_id):
    # Ensure staff can only delete their own events
    current_user = session.get('username')
    result = events_col.delete_one({
        "_id": ObjectId(event_id), 
        "created_by": current_user
    })
    
    if result.deleted_count > 0:
        return jsonify({"success": True})
    return jsonify({"error": "Event not found or unauthorized"}), 403

# Generic Public API (For Home Page)
@app.route('/api/events', methods=['GET'])
def get_public_events():
    # 1. Get all events
    raw_events = list(events_col.find())
    clean_events = []

    for e in raw_events:
        event_id = str(e['_id'])
        
        # 2. COUNT REGISTRATIONS (The Magic Step)
        # This checks the 'registrations_col' for matches with this event_id
        # Note: Make sure 'registrations_col' is the name of your registrations collection variable
        current_count = registrations_col.count_documents({"event_id": event_id})

        clean_events.append({
            "id": event_id,
            "title": e.get('title'),
            "date": e.get('date'),
            "time": e.get('time', 'TBA'), 
            "venue": e.get('venue'),
            "category": e.get('category'),
            "description": e.get('description'),
            "image": e.get('image', ''),
            
            # 3. SEND THE COUNT TO FRONTEND
            "registered_count": current_count 
        })
        
    return jsonify(clean_events)


# --- 4. REGISTRATION APIs ---

# --- 4. REGISTRATION & ALUMNI APIs ---

# --- UPDATE 1: MODIFY THE REGISTER API ---
@app.route('/api/register', methods=['POST'])
def register_student():
    try:
        # SCENARIO 1: ALUMNI (Multipart)
        if 'multipart/form-data' in request.content_type:
            # 1. Handle Photo
            photo = request.files.get('alum_photo')
            filename = ""
            if photo:
                filename = secure_filename(photo.filename)
                photo.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            
            # 2. Save Data (INCLUDING EVENT ID)
            alumni_col.insert_one({
                "event_id": request.form.get('event_id'),  # <--- CRITICAL UPDATE
                "name": request.form.get('alum_name'),
                "batch": request.form.get('alum_batch'),
                "dept": request.form.get('alum_dept'),
                "company": request.form.get('alum_company'),
                "designation": request.form.get('alum_designation'),
                "mobile": request.form.get('alum_mobile'),
                "email": request.form.get('alum_email'),
                "photo": filename,
                "type": "alumni",
                "date": datetime.now()
            })
            return jsonify({"message": "Alumni registered!"}), 200

        # SCENARIO 2: STUDENT (JSON) - No changes needed here
        else:
            data = request.get_json()
            registrations_col.insert_one({
                "event_id": data.get('event_id'),
                "type": data.get('type'),
                "team_name": data.get('team_name'),
                "participants": data.get('members', []), # Student list
                "status": "confirmed",
                "date": datetime.now()
            })
            return jsonify({"message": "Student registered!"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500



# NEW: API for Staff to view who registered for THEIR event
# --- UPDATE 2: MODIFY THE FETCH API ---
@app.route('/api/staff/registrations/<event_id>', methods=['GET'])
@login_required
def get_event_registrations(event_id):
    try:
        # 1. Fetch Event Details
        event = events_col.find_one({"_id": ObjectId(event_id)})
        if not event: return jsonify({"error": "Event not found"}), 404

        # 2. Fetch STUDENTS
        student_regs = list(registrations_col.find({"event_id": event_id}))
        
        # 3. Fetch ALUMNI
        # We search the alumni collection for this specific event_id
        alumni_regs = list(alumni_col.find({"event_id": event_id}))

        combined_list = []

        # Process Students
        for r in student_regs:
            combined_list.append({
                "type": r.get('type', 'individual'),
                "team_name": r.get('team_name'),
                "participants": r.get('participants', [])
            })

        # Process Alumni (Convert to similar format for frontend)
        for a in alumni_regs:
            combined_list.append({
                "type": "alumni",
                "participants": [{
                    "name": a.get('name'),
                    "reg_no": a.get('batch'),       # Mapping Batch to Reg No column
                    "dept": a.get('dept'),
                    "year": "Alumni",               # Hardcoded for display
                    "company": a.get('company'),    # New Field
                    "designation": a.get('designation'), # New Field
                    "phone": a.get('mobile'),
                    "email": a.get('email'),
                    "photo": a.get('photo')
                }]
            })

        return jsonify({
            "event_title": event.get('title'),
            "registrations": combined_list
        })

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)