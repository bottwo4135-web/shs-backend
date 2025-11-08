MediBridge - Hospital Chat Platform

Stack
- Backend: Python (Flask)
- Frontend: HTML, CSS, JavaScript
- DB: SQLite (simple to host; single file)
- Real-time: long-polling with incremental updates (no external brokers)

Features
- Landing page with brand theme and animations
- Signup/Login for Doctors and Patients (with profile picture upload)
- Doctor dashboard: toggle availability, set free time, chat with patients
- Patient dashboard: list doctors, filter by availability/specialty, start chat and view history
- Floating AI assistant on patient list page (stub using simple rules; easy to wire to an external API)
- Message persistence with timestamps and read indicators
- Typing indicators and optimistic UI
- Secure password hashing (werkzeug)
- Basic input validation and XSS prevention on render
- Responsive layout and accessible color contrasts

Running locally
1) Create a virtual environment and install requirements:
   - Windows (cmd):
     python -m venv .venv
     .venv\\Scripts\\activate
     pip install -r requirements.txt

2) Initialize the database (first run auto-creates DB):
   python app.py

3) Visit:
   http://127.0.0.1:5000

Admin notes
- Uploaded profile pictures saved under static/uploads
- To reset database, delete instance/medibridge.db

Deploying
- SQLite file stored under instance/; ensure write permissions
- Use `waitress`/`gunicorn` equivalent for Windows/Linux respectively
- Set FLASK_ENV=production and configure a proper SECRET_KEY via env var

Environment variables (optional)
- SECRET_KEY: overrides default dev key
- AI_PROVIDER_URL: if integrating a real AI backend (POST endpoint expected)

