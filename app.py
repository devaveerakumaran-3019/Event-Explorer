import os
import csv
import io
import cloudinary
import cloudinary.uploader
import cloudinary.api
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, make_response
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

# --- CONFIGURE CLOUDINARY ---
# Replace these with your actual keys from your Cloudinary Dashboard
cloudinary.config(
  cloud_name = "dl86ju3ug",
  api_key = "589724683827838",
  api_secret = "8g6A9WbcElIVAxvwVTH8-ruoQLw",
  secure = True
)

# Configure Local Uploads (Backup/Temp)
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
    users_col = db['staff']
    alumni_col = db['alumni']

    print("✅ Connected to MongoDB")
except Exception as e:
    print(f"❌ DB Connection Error: {e}")

# --- HELPERS ---
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            if request.path.startswith('/api/'):
                return jsonify({"error": "Unauthorized"}), 401
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

    # 3. Process Events
    clean_events = []
    today = datetime.now().strftime('%Y-%m-%d')

    for e in raw_events:
        event_id = str(e['_id'])

        # Count BOTH Students and Alumni
        student_count = registrations_col.count_documents({"event_id": event_id})
        alumni_count = alumni_col.count_documents({"event_id": event_id})
        total_count = student_count + alumni_count

        clean_events.append({
            "_id": event_id,
            "title": e['title'],
            "date": e['date'],
            "category": e.get('category', 'General'),
            "image": e.get('image'),
            "is_active": (e['date'] >= today),
            "max_capacity": int(e.get('max_capacity', 100)),
            "registrations_count": total_count
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
        # 1. Handle Event Banner
        image = request.files.get('image')
        image_url = ""

        if image and image.filename != "":
            try:
                upload_result = cloudinary.uploader.upload(image, folder="event_banners")
                image_url = upload_result['secure_url']
            except Exception as cloud_err:
                print(f"Cloudinary Error: {cloud_err}")
                image_url = ""

        # 2. Get Max Capacity (Default to 100 if empty)
        try:
            capacity_input = request.form.get('max_capacity')
            # Convert to int, fallback to 100 if missing or invalid
            max_capacity = int(capacity_input) if capacity_input else 100
        except ValueError:
            max_capacity = 100

        # 3. Insert into DB
        events_col.insert_one({
            "title": request.form.get('title'),
            "date": request.form.get('date'),
            "time": request.form.get('time'),
            "venue": request.form.get('venue'),
            "category": request.form.get('category'),
            "description": request.form.get('description'),

            "max_capacity": max_capacity,  # <--- NEW FIELD ADDED HERE

            "image": image_url,
            "created_by": session.get('username'),
            "created_at": datetime.now(),
            "status": "active",
            "registrations": [], # Initialize empty list for future signups
            "registrations_count": 0 # Initialize count at 0
        })

        return jsonify({"message": "Event created successfully!"}), 201
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/events/delete/<event_id>', methods=['DELETE'])
@login_required
def delete_event_api(event_id):
    current_user = session.get('username')
    result = events_col.delete_one({
        "_id": ObjectId(event_id),
        "created_by": current_user
    })

    if result.deleted_count > 0:
        return jsonify({"success": True})
    return jsonify({"error": "Event not found or unauthorized"}), 403

@app.route('/api/events', methods=['GET'])
def get_public_events():
    # Sort by date
    raw_events = list(events_col.find().sort("date", 1))
    clean_events = []

    print(f"Checking {len(raw_events)} events for registrations...") # Debug print

    for e in raw_events:
        # Get ID in both formats
        event_obj_id = e['_id']       # The original ObjectId
        event_str_id = str(e['_id'])  # The String version

        # 1. Create a "Bulletproof" Query
        # This looks for the ID as a String OR as an ObjectId
        query = {"event_id": {"$in": [event_str_id, event_obj_id]}}

        # 2. Count using the bulletproof query
        student_count = registrations_col.count_documents(query)
        alumni_count = alumni_col.count_documents(query)

        total_count = student_count + alumni_count

        # Debugging: Print to your terminal to see if it finds them
        if total_count > 0:
            print(f"Event: {e.get('title')} -> Found {total_count} registrations!")

        # 3. Get Max Capacity (Default to 100)
        max_cap = e.get('max_capacity', 100)

        clean_events.append({
            "id": event_str_id,
            "title": e.get('title'),
            "date": e.get('date'),
            "time": e.get('time', 'TBA'),
            "venue": e.get('venue'),
            "category": e.get('category'),
            "description": e.get('description'),
            "image": e.get('image', ''),
            "max_capacity": int(max_cap),
            "registrations_count": total_count  # <--- Ensure this key matches your JS
        })

    return jsonify(clean_events)

# --- 4. REGISTRATION APIs (UPDATED WITH CLOUDINARY) ---

@app.route('/api/register', methods=['POST'])
def register_student():
    try:
        # SCENARIO 1: ALUMNI (Multipart/Form-Data)
        if 'multipart/form-data' in request.content_type:

            # A. Handle Photo Upload (To Cloudinary)
            photo = request.files.get('alum_photo')
            photo_url = "No Photo Uploaded" # Default

            if photo and photo.filename != "":
                try:
                    # Upload to Cloudinary
                    upload_result = cloudinary.uploader.upload(photo, folder="alumni_photos")
                    photo_url = upload_result['secure_url']
                except Exception as cloud_err:
                    print(f"Cloudinary Error: {cloud_err}")
                    photo_url = "Error Uploading Photo"

            # B. Save Data
            alumni_col.insert_one({
                "event_id": request.form.get('event_id'),
                "name": request.form.get('alum_name'),
                "batch": request.form.get('alum_batch'),
                "dept": request.form.get('alum_dept'),
                "company": request.form.get('alum_company'),
                "designation": request.form.get('alum_designation'),
                "mobile": request.form.get('alum_mobile'),
                "email": request.form.get('alum_email'),
                "address": request.form.get('alum_address'),
                "message": request.form.get('alum_message'),
                "contribution": request.form.get('alum_contribution'),
                "photo": photo_url, # Saves the HTTPS Cloudinary Link
                "type": "alumni",
                "date": datetime.now()
            })
            return jsonify({"message": "Alumni registered successfully!"}), 200

        # SCENARIO 2: STUDENT (JSON)
        else:
            data = request.get_json()
            registrations_col.insert_one({
                "event_id": data.get('event_id'),
                "type": data.get('type'),
                "team_name": data.get('team_name'),
                "participants": data.get('members', []),
                "status": "confirmed",
                "date": datetime.now()
            })
            return jsonify({"message": "Student registered!"}), 200

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/staff/registrations/<event_id>', methods=['GET'])
@login_required
def get_event_registrations(event_id):
    try:
        event = events_col.find_one({"_id": ObjectId(event_id)})
        if not event: return jsonify({"error": "Event not found"}), 404

        student_regs = list(registrations_col.find({"event_id": event_id}))
        alumni_regs = list(alumni_col.find({"event_id": event_id}))

        combined_list = []

        # Process Students
        for r in student_regs:
            combined_list.append({
                "type": r.get('type', 'individual'),
                "team_name": r.get('team_name'),
                "participants": r.get('participants', [])
            })

        # Process Alumni
        for a in alumni_regs:
            combined_list.append({
                "type": "alumni",
                "participants": [{
                    "name": a.get('name'),
                    "reg_no": a.get('batch'),
                    "dept": a.get('dept'),
                    "year": "Alumni",
                    "company": a.get('company'),
                    "designation": a.get('designation'),
                    "contribution": a.get('contribution', 'No'),
                    "phone": a.get('mobile'),
                    "email": a.get('email'),
                    "address": a.get('address'),    # New
                    "message": a.get('message'),    # New
                    "photo": a.get('photo')         # New (URL)
                }]
            })

        return jsonify({
            "event_title": event.get('title'),
            "registrations": combined_list
        })

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500

# --- 5. NEW: CSV EXPORT ROUTE ---
@app.route('/api/staff/export/<event_id>')
@login_required
def export_csv(event_id):
    try:
        # Fetch Registrations
        student_regs = list(registrations_col.find({"event_id": event_id}))
        alumni_regs = list(alumni_col.find({"event_id": event_id}))

        # Create CSV in Memory
        si = io.StringIO()
        writer = csv.writer(si)

        # Updated Headers
        writer.writerow([
            'Registration Date', 'Type', 'Team Name', 'Name', 'Reg No/Batch',
            'Dept', 'Year', 'Mobile', 'Email',
            'Company', 'Designation', 'Address', 'Contribution', 'Testimonial', 'Photo Link'
        ])

        # Write Student Rows
        for reg in student_regs:
            date_str = reg.get('date', datetime.now()).strftime("%Y-%m-%d")
            reg_type = reg.get('type')
            team_name = reg.get('team_name', 'N/A')

            for p in reg.get('participants', []):
                writer.writerow([
                    date_str, reg_type, team_name,
                    p.get('name'), p.get('reg_no'), p.get('dept'), p.get('year'),
                    p.get('phone'), p.get('email'),
                    '-', '-', '-', '-', '-', '-' # Empty alumni fields
                ])

        # Write Alumni Rows
        for alum in alumni_regs:
            date_str = alum.get('date', datetime.now()).strftime("%Y-%m-%d")
            writer.writerow([
                date_str, 'Alumni', 'N/A',
                alum.get('name'), alum.get('batch'), alum.get('dept'), 'Alumni',
                alum.get('mobile'), alum.get('email'),
                alum.get('company', 'N/A'),
                alum.get('designation', 'N/A'),
                alum.get('address', 'N/A'),
                alum.get('contribution', 'No'),
                alum.get('message', 'N/A'),
                alum.get('photo', 'No Photo') # Contains Cloudinary URL
            ])

        # Return File
        output = make_response(si.getvalue())
        output.headers["Content-Disposition"] = f"attachment; filename=registrations_{event_id}.csv"
        output.headers["Content-type"] = "text/csv"
        return output

    except Exception as e:
        return f"Error exporting CSV: {str(e)}"

if __name__ == '__main__':
    app.run(debug=True, port=5000)