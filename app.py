import os
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory, flash
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import requests
from flask_cors import CORS

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, 'instance')
DB_PATH = os.path.join(INSTANCE_DIR, 'medibridge.db')
UPLOAD_DIR = os.path.join(BASE_DIR, 'static', 'uploads')
ALLOWED_EXT = {'.png', '.jpg', '.jpeg', '.gif'}

# Hugging Face configuration
HF_API_TOKEN = os.environ.get('HF_API_TOKEN')
HF_MODEL = os.environ.get('HF_MODEL', 'google/flan-t5-large')
HF_TIMEOUT = int(os.environ.get('HF_TIMEOUT', '15'))

os.makedirs(INSTANCE_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-me')

# ==================== CORS CONFIGURATION ====================
CORS(
    app,
    resources={r"/*": {"origins": [
        "http://127.0.0.1:5500",
        os.environ.get('FRONTEND_ORIGIN', 'https://your-frontend-domain.com')
    ]}},
    supports_credentials=True
)
# ===========================================================

def call_hf_inference(prompt: str) -> str:
    """Call Hugging Face Inference API and return a text reply. Returns empty string on failure."""
    if not HF_API_TOKEN:
        return ''
    url = f'https://api-inference.huggingface.co/models/{HF_MODEL}'
    headers = {
        'Authorization': f'Bearer {HF_API_TOKEN}',
        'Accept': 'application/json'
    }
    payload = {
        'inputs': prompt,
        'options': {'wait_for_model': True},
        'parameters': {'max_new_tokens': 256, 'temperature': 0.2}
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=HF_TIMEOUT)
        if resp.status_code != 200:
            return ''
        data = resp.json()
        if isinstance(data, list) and len(data) > 0 and 'generated_text' in data[0]:
            return data[0]['generated_text'].strip()
        if isinstance(data, dict):
            for k in ('generated_text', 'text', 'output'):
                if k in data and isinstance(data[k], str):
                    return data[k].strip()
        if isinstance(data, str):
            return data.strip()
    except Exception:
        return ''
    return ''

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        '''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT NOT NULL CHECK(role IN ("doctor","patient")),
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        specialty TEXT,
        availability INTEGER DEFAULT 0,
        free_at TEXT,
        avatar TEXT
        )'''
    )
    cur.execute(
        '''CREATE TABLE IF NOT EXISTS chats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        doctor_id INTEGER NOT NULL,
        patient_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(doctor_id, patient_id),
        FOREIGN KEY(doctor_id) REFERENCES users(id),
        FOREIGN KEY(patient_id) REFERENCES users(id)
        )'''
    )
    cur.execute(
        '''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        sender_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(chat_id) REFERENCES chats(id),
        FOREIGN KEY(sender_id) REFERENCES users(id)
        )'''
    )
    conn.commit()
    conn.close()

@app.before_request
def ensure_db():
    if not os.path.exists(DB_PATH):
        init_db()

def current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (uid,)).fetchone()
    conn.close()
    return user

# ---------- Auth (session-based) ----------
@app.route('/signup/<role>', methods=['POST'])
def signup(role):
    if role not in ('doctor', 'patient'):
        return jsonify({'ok': False, 'error': 'invalid role'}), 400
    name = request.form.get('name','').strip()
    email = request.form.get('email','').strip().lower()
    password = request.form.get('password','')
    specialty = request.form.get('specialty','').strip() if role == 'doctor' else None
    file = request.files.get('avatar')
    if not name or not email or not password:
        return jsonify({'ok': False, 'error': 'missing fields'}), 400
    avatar_path = None
    if file and file.filename:
        fname = secure_filename(file.filename)
        ext = os.path.splitext(fname)[1].lower()
        if ext not in ALLOWED_EXT:
            return jsonify({'ok': False, 'error': 'invalid image type'}), 400
        new_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}{ext}"
        dest = os.path.join(UPLOAD_DIR, new_name)
        file.save(dest)
        avatar_path = f"uploads/{new_name}"
    pw_hash = generate_password_hash(password)
    conn = get_db()
    try:
        conn.execute('INSERT INTO users(role, name, email, password_hash, specialty, avatar) VALUES (?, ?, ?, ?, ?, ?)',
            (role, name, email, pw_hash, specialty, avatar_path))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'ok': False, 'error': 'email exists'}), 409
    user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
    conn.close()
    session['user_id'] = user['id']
    return jsonify({'ok': True})

@app.route('/login', methods=['POST'])
def login():
    email = request.form.get('email','').strip().lower()
    password = request.form.get('password','')
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
    conn.close()
    if user and check_password_hash(user['password_hash'], password):
        session['user_id'] = user['id']
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'invalid credentials'}), 401

@app.route('/logout')
def logout():
    session.clear()
    return jsonify({'ok': True})

# ---------- JSON endpoints for frontend ----------
@app.route('/api/me')
def api_me():
    user = current_user()
    if not user:
        return jsonify({'error': 'unauthorized'}), 401
    def avatar_url(a):
        return url_for('uploaded_file', filename=os.path.basename(a)) if a else None
    return jsonify({
        'id': user['id'], 'role': user['role'], 'name': user['name'], 'email': user['email'],
        'specialty': user['specialty'], 'availability': user['availability'], 'free_at': user['free_at'],
        'avatar': avatar_url(user['avatar'])
    })

@app.route('/api/doctors')
def api_doctors():
    conn = get_db()
    rows = conn.execute('SELECT id, name, specialty, availability, free_at, avatar FROM users WHERE role = "doctor" ORDER BY availability DESC, name ASC').fetchall()
    conn.close()
    def avatar_url(a):
        return url_for('uploaded_file', filename=os.path.basename(a)) if a else None
    return jsonify([{ 'id': r['id'], 'name': r['name'], 'specialty': r['specialty'], 'availability': r['availability'], 'free_at': r['free_at'], 'avatar': avatar_url(r['avatar']) } for r in rows])

@app.route('/api/my_chats')
def api_my_chats():
    user = current_user()
    if not user or user['role'] != 'doctor':
        return jsonify([])
    conn = get_db()
    rows = conn.execute('SELECT c.id as chat_id, c.patient_id as patient_id, u.name as patient_name, u.avatar as patient_avatar, c.created_at FROM chats c JOIN users u ON c.patient_id = u.id WHERE c.doctor_id = ? ORDER BY c.created_at DESC', (user['id'],)).fetchall()
    conn.close()
    def avatar_url(a):
        return url_for('uploaded_file', filename=os.path.basename(a)) if a else None
    return jsonify([{ 'chat_id': r['chat_id'], 'patient_id': r['patient_id'], 'patient_name': r['patient_name'], 'patient_avatar': avatar_url(r['patient_avatar']), 'created_at': r['created_at'] } for r in rows])

@app.route('/api/chat_init/<int:other_id>')
def api_chat_init(other_id):
    user = current_user()
    if not user:
        return jsonify({'error':'unauthorized'}), 401
    conn = get_db()
    other = conn.execute('SELECT * FROM users WHERE id = ?', (other_id,)).fetchone()
    if not other:
        conn.close()
        return jsonify({'error':'not found'}), 404
    if user['role'] == 'doctor' and other['role'] != 'patient':
        conn.close(); return jsonify({'error':'invalid'}), 400
    if user['role'] == 'patient' and other['role'] != 'doctor':
        conn.close(); return jsonify({'error':'invalid'}), 400
    if user['role'] == 'doctor':
        doctor_id, patient_id = user['id'], other_id
    else:
        doctor_id, patient_id = other_id, user['id']
    cur = conn.cursor()
    cur.execute('SELECT * FROM chats WHERE doctor_id = ? AND patient_id = ?', (doctor_id, patient_id))
    chat = cur.fetchone()
    if not chat:
        created_at = datetime.utcnow().isoformat()
        cur.execute('INSERT INTO chats(doctor_id, patient_id, created_at) VALUES (?, ?, ?)', (doctor_id, patient_id, created_at))
        conn.commit()
        chat = cur.execute('SELECT * FROM chats WHERE doctor_id = ? AND patient_id = ?', (doctor_id, patient_id)).fetchone()
    def avatar_url(a):
        return url_for('uploaded_file', filename=os.path.basename(a)) if a else None
    payload = {
        'chat_id': chat['id'],
        'other': {
            'id': other['id'], 'role': other['role'], 'name': other['name'],
            'specialty': other['specialty'], 'avatar': avatar_url(other['avatar'])
        }
    }
    conn.close()
    return jsonify(payload)

@app.route('/api/messages/<int:chat_id>')
def api_get_messages(chat_id):
    user = current_user()
    if not user:
        return jsonify([])
    after = request.args.get('after')
    conn = get_db()
    params = [chat_id]
    query = 'SELECT m.*, u.name, u.avatar FROM messages m JOIN users u ON m.sender_id = u.id WHERE chat_id = ?'
    if after:
        query += ' AND m.created_at > ?'
        params.append(after)
    query += ' ORDER BY m.created_at ASC'
    rows = conn.execute(query, tuple(params)).fetchall()
    conn.close()
    def avatar_url(a):
        return url_for('uploaded_file', filename=os.path.basename(a)) if a else None
    return jsonify([
        {
            'id': r['id'],
            'sender_id': r['sender_id'],
            'name': r['name'],
            'avatar': avatar_url(r['avatar']),
            'message': r['message'],
            'created_at': r['created_at']
        } for r in rows
    ])

@app.route('/api/send', methods=['POST'])
def api_send():
    user = current_user()
    if not user:
        return jsonify({'ok': False, 'error': 'unauthorized'}), 401
    chat_id = request.form.get('chat_id')
    text = (request.form.get('message') or '').strip()
    if not chat_id or not text:
        return jsonify({'ok': False, 'error': 'invalid'}), 400
    created_at = datetime.utcnow().isoformat()
    conn = get_db()
    conn.execute('INSERT INTO messages(chat_id, sender_id, message, created_at) VALUES (?, ?, ?, ?)', (chat_id, user['id'], text, created_at))
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'created_at': created_at})

@app.route('/api/ai', methods=['POST'])
def api_ai():
    # Support both JSON and form
    prompt = ''
    if request.is_json:
        data = request.get_json(silent=True) or {}
        prompt = (data.get('message') or '').strip()
    else:
        prompt = (request.form.get('message') or '').strip()
    if not prompt:
        return jsonify({'reply': 'Please enter a question about your health.'})
    hf_reply = ''
    if HF_API_TOKEN:
        hf_reply = call_hf_inference(prompt)
    if hf_reply:
        return jsonify({'reply': hf_reply})
    lower = prompt.lower()
    if any(k in lower for k in ['emergency', 'bleeding', 'chest pain', 'stroke']):
        reply = 'This could be an emergency. Please call your local emergency number or go to the nearest emergency department immediately.'
    elif 'fever' in lower:
        reply = 'For fever, stay hydrated and consider acetaminophen if appropriate. Seek medical attention if it persists beyond 48 hours or is very high.'
    elif 'headache' in lower:
        reply = 'Headaches can have many causes. Rest, hydration, and OTC analgesics may help. Consult a doctor if severe, sudden, or accompanied by other symptoms.'
    else:
        reply = 'I am a virtual assistant and cannot provide a diagnosis. For specific concerns, please consult a licensed physician.'
    return jsonify({'reply': reply})

@app.route('/static/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
