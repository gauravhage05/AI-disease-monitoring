"""
GraniteCare AI — Chronic Disease Monitoring Agent
IBM SkillsBuild Problem Statement No. 27
Backend: Flask + SQLAlchemy + Flask-Login + IBM WatsonX Granite
"""

import os, json, random, zipfile, io
from datetime import datetime, date, timedelta
from flask import Flask, render_template, jsonify, request, redirect, url_for, flash, session, send_file, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
import requests

# ─────────────────────────────────────────────
# APP CONFIGURATION
# ─────────────────────────────────────────────
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "granite-care-ai-secret-2024")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "granitecare.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = "auth_login"
login_manager.login_message = "Please log in to access this page."
login_manager.login_message_category = "info"

# ─────────────────────────────────────────────
# IBM WATSONX CONFIGURATION
# ─────────────────────────────────────────────
IBM_WATSONX_API_KEY   = os.environ.get("IBM_WATSONX_API_KEY",   "Mjx_LY8EYY7M7zYMBPZ3sLOrHQNlKfjoba--fVjgdEzt")
IBM_WATSONX_PROJECT_ID= os.environ.get("IBM_WATSONX_PROJECT_ID","c0bcbcf2-fa43-43a8-960e-06ad40facc5c")
IBM_WATSONX_URL       = "https://us-south.ml.cloud.ibm.com"
GRANITE_MODEL_ID      = "ibm/granite-3-0-8b-instruct"

_watsonx_token_cache = {"token": None, "expires": 0}

# ─────────────────────────────────────────────
# DATABASE MODELS
# ─────────────────────────────────────────────

class User(UserMixin, db.Model):
    __tablename__ = "users"
    id            = db.Column(db.Integer, primary_key=True)
    email         = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role          = db.Column(db.String(20), nullable=False, default="patient")  # patient|doctor|admin
    full_name     = db.Column(db.String(100), nullable=False)
    phone         = db.Column(db.String(20))
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    is_active_account = db.Column(db.Boolean, default=True)

    patient_profile = db.relationship("Patient", back_populates="user", uselist=False, cascade="all, delete-orphan")
    doctor_profile  = db.relationship("Doctor",  back_populates="user", uselist=False, cascade="all, delete-orphan")

    def set_password(self, pw): self.password_hash = bcrypt.generate_password_hash(pw).decode("utf-8")
    def check_password(self, pw): return bcrypt.check_password_hash(self.password_hash, pw)


class Patient(db.Model):
    __tablename__ = "patients"
    id              = db.Column(db.Integer, primary_key=True)
    patient_code    = db.Column(db.String(10), unique=True, nullable=False)
    user_id         = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    date_of_birth   = db.Column(db.Date)
    gender          = db.Column(db.String(10))
    address         = db.Column(db.Text)
    height_cm       = db.Column(db.Float)
    weight_kg       = db.Column(db.Float)
    blood_group     = db.Column(db.String(5))
    emergency_contact = db.Column(db.String(100))
    primary_disease = db.Column(db.String(100))
    secondary_diseases = db.Column(db.Text)   # JSON list
    allergies       = db.Column(db.Text)
    family_history  = db.Column(db.Text)
    previous_history= db.Column(db.Text)
    assigned_doctor_id = db.Column(db.Integer, db.ForeignKey("doctors.id"), nullable=True)

    user            = db.relationship("User", back_populates="patient_profile")
    assigned_doctor = db.relationship("Doctor", foreign_keys=[assigned_doctor_id])
    readings        = db.relationship("HealthReading", back_populates="patient", cascade="all, delete-orphan", order_by="desc(HealthReading.recorded_at)")
    medications     = db.relationship("Medication",    back_populates="patient", cascade="all, delete-orphan")
    alerts          = db.relationship("HealthAlert",   back_populates="patient", cascade="all, delete-orphan")
    ai_analyses     = db.relationship("AIAnalysis",    back_populates="patient", cascade="all, delete-orphan")
    health_targets  = db.relationship("HealthTarget",  back_populates="patient", cascade="all, delete-orphan", uselist=False)
    conditions      = db.relationship("MedicalCondition", back_populates="patient", cascade="all, delete-orphan")

    @property
    def age(self):
        if self.date_of_birth:
            today = date.today()
            return today.year - self.date_of_birth.year - ((today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day))
        return None

    @property
    def bmi(self):
        if self.height_cm and self.weight_kg and self.height_cm > 0:
            h = self.height_cm / 100
            return round(self.weight_kg / (h * h), 1)
        return None

    @property
    def latest_reading(self):
        return self.readings[0] if self.readings else None

    @property
    def unread_alerts(self):
        return [a for a in self.alerts if not a.is_read]


class Doctor(db.Model):
    __tablename__ = "doctors"
    id            = db.Column(db.Integer, primary_key=True)
    user_id       = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    specialization= db.Column(db.String(100))
    license_number= db.Column(db.String(50))
    hospital      = db.Column(db.String(150))

    user    = db.relationship("User", back_populates="doctor_profile")
    patients= db.relationship("Patient", foreign_keys=[Patient.assigned_doctor_id], back_populates="assigned_doctor")
    notes   = db.relationship("ClinicalNote", back_populates="doctor", cascade="all, delete-orphan")


class MedicalCondition(db.Model):
    __tablename__ = "medical_conditions"
    id          = db.Column(db.Integer, primary_key=True)
    patient_id  = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False)
    name        = db.Column(db.String(150), nullable=False)
    diagnosed_on= db.Column(db.Date)
    notes       = db.Column(db.Text)
    is_active   = db.Column(db.Boolean, default=True)
    patient     = db.relationship("Patient", back_populates="conditions")


class Medication(db.Model):
    __tablename__ = "medications"
    id            = db.Column(db.Integer, primary_key=True)
    patient_id    = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False)
    name          = db.Column(db.String(150), nullable=False)
    dosage        = db.Column(db.String(50))
    frequency     = db.Column(db.String(100))
    start_date    = db.Column(db.Date)
    end_date      = db.Column(db.Date)
    prescribing_doctor = db.Column(db.String(100))
    reminder_time = db.Column(db.String(10))   # HH:MM
    is_active     = db.Column(db.Boolean, default=True)
    patient       = db.relationship("Patient", back_populates="medications")
    adherence_records = db.relationship("MedicationAdherence", back_populates="medication", cascade="all, delete-orphan")


class MedicationAdherence(db.Model):
    __tablename__ = "medication_adherence"
    id            = db.Column(db.Integer, primary_key=True)
    medication_id = db.Column(db.Integer, db.ForeignKey("medications.id"), nullable=False)
    taken_date    = db.Column(db.Date, nullable=False)
    was_taken     = db.Column(db.Boolean, default=False)
    taken_at      = db.Column(db.Time)
    notes         = db.Column(db.String(200))
    medication    = db.relationship("Medication", back_populates="adherence_records")


class HealthReading(db.Model):
    __tablename__ = "health_readings"
    id                = db.Column(db.Integer, primary_key=True)
    patient_id        = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False)
    recorded_at       = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    # Vitals
    heart_rate        = db.Column(db.Float)
    bp_systolic       = db.Column(db.Float)
    bp_diastolic      = db.Column(db.Float)
    blood_glucose     = db.Column(db.Float)
    glucose_type      = db.Column(db.String(20))   # fasting|post_meal|random
    spo2              = db.Column(db.Float)
    temperature       = db.Column(db.Float)
    weight_kg         = db.Column(db.Float)
    height_cm         = db.Column(db.Float)
    respiratory_rate  = db.Column(db.Float)
    hba1c             = db.Column(db.Float)
    cholesterol       = db.Column(db.Float)
    # Lifestyle
    symptoms          = db.Column(db.Text)
    physical_activity = db.Column(db.String(50))
    sleep_hours       = db.Column(db.Float)
    water_intake_ml   = db.Column(db.Float)
    medication_taken  = db.Column(db.Boolean)
    notes             = db.Column(db.Text)
    # Computed
    bmi               = db.Column(db.Float)
    risk_level        = db.Column(db.String(20))   # normal|attention|concerning|critical
    risk_score        = db.Column(db.Integer, default=0)
    patient           = db.relationship("Patient", back_populates="readings")


class HealthAlert(db.Model):
    __tablename__ = "health_alerts"
    id            = db.Column(db.Integer, primary_key=True)
    patient_id    = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False)
    alert_type    = db.Column(db.String(50))
    severity      = db.Column(db.String(20))   # info|warning|critical
    title         = db.Column(db.String(200), nullable=False)
    description   = db.Column(db.Text)
    recommended_action = db.Column(db.Text)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    is_read       = db.Column(db.Boolean, default=False)
    reading_id    = db.Column(db.Integer, db.ForeignKey("health_readings.id"), nullable=True)
    patient       = db.relationship("Patient", back_populates="alerts")


class AIAnalysis(db.Model):
    __tablename__ = "ai_analysis_history"
    id            = db.Column(db.Integer, primary_key=True)
    patient_id    = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False)
    analysis_type = db.Column(db.String(50))   # dashboard|chat|report
    prompt        = db.Column(db.Text)
    response      = db.Column(db.Text)
    model_used    = db.Column(db.String(100))
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    patient       = db.relationship("Patient", back_populates="ai_analyses")


class ClinicalNote(db.Model):
    __tablename__ = "clinical_notes"
    id         = db.Column(db.Integer, primary_key=True)
    doctor_id  = db.Column(db.Integer, db.ForeignKey("doctors.id"), nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False)
    note       = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    doctor     = db.relationship("Doctor", back_populates="notes")


class HealthTarget(db.Model):
    __tablename__ = "patient_health_targets"
    id               = db.Column(db.Integer, primary_key=True)
    patient_id       = db.Column(db.Integer, db.ForeignKey("patients.id"), unique=True)
    glucose_min      = db.Column(db.Float, default=70)
    glucose_max      = db.Column(db.Float, default=140)
    bp_systolic_max  = db.Column(db.Float, default=130)
    bp_diastolic_max = db.Column(db.Float, default=80)
    hr_min           = db.Column(db.Float, default=60)
    hr_max           = db.Column(db.Float, default=100)
    spo2_min         = db.Column(db.Float, default=95)
    hba1c_max        = db.Column(db.Float, default=7.0)
    patient          = db.relationship("Patient", back_populates="health_targets")


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    action     = db.Column(db.String(100))
    resource   = db.Column(db.String(100))
    details    = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# ─────────────────────────────────────────────
# IBM GRANITE HELPERS
# ─────────────────────────────────────────────

def get_watsonx_token():
    import time as _time
    now = _time.time()
    if _watsonx_token_cache["token"] and now < _watsonx_token_cache["expires"] - 60:
        return _watsonx_token_cache["token"]
    try:
        r = requests.post("https://iam.cloud.ibm.com/identity/token",
            data={"grant_type": "urn:ibm:params:oauth:grant-type:apikey", "apikey": IBM_WATSONX_API_KEY},
            headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=15)
        if r.status_code == 200:
            d = r.json()
            _watsonx_token_cache["token"] = d["access_token"]
            _watsonx_token_cache["expires"] = now + d.get("expires_in", 3600)
            return _watsonx_token_cache["token"]
    except Exception as e:
        print(f"[WatsonX] Token error: {e}")
    return None


def call_granite(prompt, max_tokens=500):
    token = get_watsonx_token()
    if not token:
        return None, "IBM WatsonX token unavailable — check API key configuration."
    try:
        url = f"{IBM_WATSONX_URL}/ml/v1/text/generation?version=2023-05-29"
        payload = {
            "model_id": GRANITE_MODEL_ID,
            "input": prompt,
            "parameters": {"decoding_method": "greedy", "max_new_tokens": max_tokens, "repetition_penalty": 1.1},
            "project_id": IBM_WATSONX_PROJECT_ID
        }
        r = requests.post(url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json=payload, timeout=40)
        if r.status_code == 200:
            text = r.json()["results"][0]["generated_text"].strip()
            return text, None
        return None, f"WatsonX API error {r.status_code}"
    except Exception as e:
        return None, str(e)


def build_patient_context(patient):
    """Build a medical context string for a patient."""
    conditions = [c.name for c in patient.conditions if c.is_active]
    meds = [f"{m.name} {m.dosage} ({m.frequency})" for m in patient.medications if m.is_active]
    r = patient.latest_reading
    ctx = f"Patient: {patient.user.full_name}, Age: {patient.age}, Gender: {patient.gender}\n"
    ctx += f"Primary Condition: {patient.primary_disease or 'Not specified'}\n"
    if conditions: ctx += f"Active Conditions: {', '.join(conditions)}\n"
    if meds: ctx += f"Medications: {', '.join(meds)}\n"
    if r:
        ctx += f"\nLatest Health Reading ({r.recorded_at.strftime('%Y-%m-%d %H:%M')}):\n"
        if r.heart_rate: ctx += f"- Heart Rate: {r.heart_rate} bpm\n"
        if r.bp_systolic: ctx += f"- Blood Pressure: {r.bp_systolic}/{r.bp_diastolic} mmHg\n"
        if r.blood_glucose: ctx += f"- Blood Glucose ({r.glucose_type}): {r.blood_glucose} mg/dL\n"
        if r.spo2: ctx += f"- SpO2: {r.spo2}%\n"
        if r.temperature: ctx += f"- Temperature: {r.temperature}°C\n"
        if r.hba1c: ctx += f"- HbA1c: {r.hba1c}%\n"
        if r.symptoms: ctx += f"- Symptoms: {r.symptoms}\n"
        ctx += f"- Risk Level: {r.risk_level} (Score: {r.risk_score}/100)\n"
    return ctx

# ─────────────────────────────────────────────
# HEALTH RISK ENGINE
# ─────────────────────────────────────────────

def evaluate_reading(reading, patient):
    """Rule-based health risk scoring. Returns (score, level, alerts list)."""
    score = 0
    alerts = []

    t = patient.health_targets

    def tgt(attr, default): return getattr(t, attr) if t else default

    g = reading.blood_glucose
    if g is not None:
        g_type = reading.glucose_type or "random"
        fasting_max = 100 if g_type == "fasting" else 140
        if g < 54:
            score += 40; alerts.append(("critical","Low Blood Glucose (Hypoglycemia)", f"Glucose {g} mg/dL — EMERGENCY: take fast-acting sugar immediately and seek medical help.", "Eat 15g fast-acting sugar, recheck in 15 min. If < 70 again, repeat. Call emergency if unconscious."))
        elif g < 70:
            score += 25; alerts.append(("warning","Low Blood Glucose Warning", f"Glucose {g} mg/dL — below safe threshold.", "Have a small snack. Monitor closely."))
        elif g > 300:
            score += 40; alerts.append(("critical","Very High Blood Glucose (Hyperglycemia)", f"Glucose {g} mg/dL — dangerously high.", "Seek immediate medical attention. Drink water, do not exercise."))
        elif g > tgt("glucose_max", 140):
            score += 15; alerts.append(("warning","Elevated Blood Glucose", f"Glucose {g} mg/dL exceeds target of {tgt('glucose_max',140)} mg/dL.", "Review diet and medication adherence. Follow up with your doctor."))

    h = reading.hba1c
    if h is not None:
        if h > 9.0:
            score += 30; alerts.append(("critical","Very High HbA1c", f"HbA1c {h}% — indicates poor long-term glucose control.", "Immediate medication review with your doctor is needed."))
        elif h > tgt("hba1c_max", 7.0):
            score += 15; alerts.append(("warning","High HbA1c", f"HbA1c {h}% above target {tgt('hba1c_max',7.0)}%.", "Discuss medication or lifestyle adjustments with your doctor."))

    sys = reading.bp_systolic
    dia = reading.bp_diastolic
    if sys is not None:
        if sys >= 180 or (dia and dia >= 120):
            score += 40; alerts.append(("critical","Hypertensive Crisis", f"Blood pressure {sys}/{dia} mmHg — EMERGENCY.", "Seek emergency care immediately. Do not drive yourself."))
        elif sys >= 160:
            score += 25; alerts.append(("warning","Stage 2 Hypertension", f"Blood pressure {sys}/{dia} mmHg.", "Contact your doctor today. Avoid salt, stress, caffeine."))
        elif sys >= tgt("bp_systolic_max", 130):
            score += 12; alerts.append(("info","Elevated Blood Pressure", f"Blood pressure {sys}/{dia} mmHg above target.", "Rest, reduce salt. Monitor again in 30 min."))

    hr = reading.heart_rate
    if hr is not None:
        if hr > 150:
            score += 35; alerts.append(("critical","Dangerous Tachycardia", f"Heart rate {hr} bpm — very high.", "Seek immediate medical attention."))
        elif hr > tgt("hr_max", 100):
            score += 15; alerts.append(("warning","High Heart Rate (Tachycardia)", f"Heart rate {hr} bpm above target.", "Rest, stay hydrated. Contact doctor if persists."))
        elif hr < tgt("hr_min", 50):
            score += 15; alerts.append(("warning","Low Heart Rate (Bradycardia)", f"Heart rate {hr} bpm below target.", "Contact your doctor if you feel dizzy or faint."))

    spo2 = reading.spo2
    if spo2 is not None:
        if spo2 < 90:
            score += 40; alerts.append(("critical","Critically Low Oxygen Saturation", f"SpO2 {spo2}% — EMERGENCY.", "Seek emergency care immediately. Sit upright and try to stay calm."))
        elif spo2 < tgt("spo2_min", 95):
            score += 20; alerts.append(("warning","Low Oxygen Saturation", f"SpO2 {spo2}% below target of {tgt('spo2_min',95)}%.", "Rest, avoid exertion, contact your doctor."))

    temp = reading.temperature
    if temp is not None:
        if temp >= 39.5: score += 20; alerts.append(("warning","High Fever", f"Temperature {temp}°C.", "Stay hydrated, take fever reducer. See doctor if > 40°C."))
        elif temp >= 38.0: score += 10; alerts.append(("info","Mild Fever", f"Temperature {temp}°C.", "Rest and stay hydrated. Monitor."))

    syms = (reading.symptoms or "").lower()
    if any(w in syms for w in ["chest pain","chest tightness","crushing"]):
        score += 50; alerts.append(("critical","Chest Pain Reported", "Patient reports chest pain — possible cardiac event.", "Call emergency services (112/911) immediately."))
    if any(w in syms for w in ["breathless","short of breath","difficulty breathing"]):
        score += 30; alerts.append(("critical","Breathing Difficulty Reported", "Patient reports breathing difficulty.", "Sit upright, seek emergency care if severe."))
    if any(w in syms for w in ["dizzy","dizziness","fainting","faint","syncope"]):
        score += 20; alerts.append(("warning","Dizziness/Fainting Reported", "Patient reports dizziness.", "Lie down, stay hydrated. Contact doctor."))

    score = min(score, 100)
    if score >= 50: level = "critical"
    elif score >= 30: level = "concerning"
    elif score >= 15: level = "attention"
    else: level = "normal"

    return score, level, alerts

# ─────────────────────────────────────────────
# UTILITY
# ─────────────────────────────────────────────

def log_audit(action, resource="", details=""):
    try:
        log = AuditLog(user_id=current_user.id if current_user.is_authenticated else None,
                       action=action, resource=resource, details=details,
                       ip_address=request.remote_addr)
        db.session.add(log)
        db.session.commit()
    except: pass

def generate_patient_code():
    import random as _r
    while True:
        code = "P" + str(_r.randint(10000, 99999))
        if not Patient.query.filter_by(patient_code=code).first():
            return code

def require_role(*roles):
    from functools import wraps
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role not in roles:
                abort(403)
            return f(*args, **kwargs)
        return wrapper
    return decorator

# ─────────────────────────────────────────────
# AUTH ROUTES
# ─────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def auth_login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password) and user.is_active_account:
            login_user(user, remember=request.form.get("remember"))
            log_audit("login", "auth", f"User {email} logged in")
            next_page = request.args.get("next")
            return redirect(next_page or url_for("dashboard"))
        flash("Invalid email or password.", "danger")
    return render_template("auth/login.html")


@app.route("/register", methods=["GET", "POST"])
def auth_register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        name  = request.form.get("full_name","").strip()
        email = request.form.get("email","").strip().lower()
        pw    = request.form.get("password","")
        pw2   = request.form.get("confirm_password","")
        role  = request.form.get("role", "patient")

        if not name or not email or not pw:
            flash("All fields are required.", "danger")
        elif pw != pw2:
            flash("Passwords do not match.", "danger")
        elif len(pw) < 8:
            flash("Password must be at least 8 characters.", "danger")
        elif User.query.filter_by(email=email).first():
            flash("Email already registered.", "danger")
        elif role not in ["patient", "doctor"]:
            flash("Invalid role.", "danger")
        else:
            user = User(full_name=name, email=email, role=role)
            user.set_password(pw)
            db.session.add(user)
            db.session.flush()
            if role == "patient":
                code = generate_patient_code()
                p = Patient(patient_code=code, user_id=user.id)
                db.session.add(p)
                t = HealthTarget(patient_id=p.id)
                db.session.add(t)
            elif role == "doctor":
                d = Doctor(user_id=user.id,
                           specialization=request.form.get("specialization",""),
                           hospital=request.form.get("hospital",""))
                db.session.add(d)
            db.session.commit()
            flash("Account created! Please log in.", "success")
            return redirect(url_for("auth_login"))
    return render_template("auth/register.html")


@app.route("/logout")
@login_required
def auth_logout():
    log_audit("logout","auth",f"{current_user.email} logged out")
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth_login"))

# ─────────────────────────────────────────────
# MAIN DASHBOARD ROUTER
# ─────────────────────────────────────────────

@app.route("/")
@login_required
def dashboard():
    if current_user.role == "patient":
        return redirect(url_for("patient_dashboard"))
    elif current_user.role == "doctor":
        return redirect(url_for("doctor_dashboard"))
    elif current_user.role == "admin":
        return redirect(url_for("admin_dashboard"))
    abort(403)

# ─────────────────────────────────────────────
# PATIENT ROUTES
# ─────────────────────────────────────────────

@app.route("/patient/dashboard")
@login_required
@require_role("patient")
def patient_dashboard():
    p = current_user.patient_profile
    if not p: return redirect(url_for("patient_profile_setup"))
    recent = p.readings[:10]
    unread_alerts = p.unread_alerts
    active_meds = [m for m in p.medications if m.is_active]
    return render_template("patient/dashboard.html", patient=p, recent=recent,
                           alerts=unread_alerts, medications=active_meds)


@app.route("/patient/profile", methods=["GET","POST"])
@login_required
@require_role("patient")
def patient_profile():
    p = current_user.patient_profile
    if not p:
        p = Patient(patient_code=generate_patient_code(), user_id=current_user.id)
        db.session.add(p)
        db.session.commit()
    if request.method == "POST":
        f = request.form
        current_user.full_name = f.get("full_name", current_user.full_name)
        current_user.phone     = f.get("phone","")
        dob_str = f.get("date_of_birth","")
        if dob_str:
            try: p.date_of_birth = datetime.strptime(dob_str, "%Y-%m-%d").date()
            except: pass
        p.gender       = f.get("gender","")
        p.address      = f.get("address","")
        p.height_cm    = float(f.get("height_cm") or 0) or None
        p.weight_kg    = float(f.get("weight_kg") or 0) or None
        p.blood_group  = f.get("blood_group","")
        p.emergency_contact = f.get("emergency_contact","")
        p.primary_disease   = f.get("primary_disease","")
        p.allergies    = f.get("allergies","")
        p.family_history    = f.get("family_history","")
        p.previous_history  = f.get("previous_history","")
        db.session.commit()
        flash("Profile updated successfully.", "success")
        return redirect(url_for("patient_profile"))
    return render_template("patient/profile.html", patient=p)


@app.route("/patient/profile/setup")
@login_required
@require_role("patient")
def patient_profile_setup():
    return redirect(url_for("patient_profile"))


@app.route("/patient/conditions", methods=["GET","POST"])
@login_required
@require_role("patient")
def patient_conditions():
    p = current_user.patient_profile
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            name = request.form.get("name","").strip()
            if name:
                dstr = request.form.get("diagnosed_on","")
                ddate = None
                if dstr:
                    try: ddate = datetime.strptime(dstr, "%Y-%m-%d").date()
                    except: pass
                c = MedicalCondition(patient_id=p.id, name=name,
                                     diagnosed_on=ddate, notes=request.form.get("notes",""))
                db.session.add(c)
                db.session.commit()
                flash(f"Condition '{name}' added.", "success")
        elif action == "toggle":
            cid = int(request.form.get("condition_id",0))
            c = MedicalCondition.query.get(cid)
            if c and c.patient_id == p.id:
                c.is_active = not c.is_active
                db.session.commit()
    return render_template("patient/conditions.html", patient=p)


@app.route("/patient/readings", methods=["GET","POST"])
@login_required
@require_role("patient")
def patient_readings():
    p = current_user.patient_profile
    if request.method == "POST":
        f = request.form
        def flt(k): v = f.get(k,""); return float(v) if v else None

        r = HealthReading(
            patient_id=p.id,
            recorded_at=datetime.now(),
            heart_rate=flt("heart_rate"),
            bp_systolic=flt("bp_systolic"), bp_diastolic=flt("bp_diastolic"),
            blood_glucose=flt("blood_glucose"), glucose_type=f.get("glucose_type","random"),
            spo2=flt("spo2"), temperature=flt("temperature"),
            weight_kg=flt("weight_kg"), height_cm=flt("height_cm"),
            respiratory_rate=flt("respiratory_rate"),
            hba1c=flt("hba1c"), cholesterol=flt("cholesterol"),
            symptoms=f.get("symptoms",""), physical_activity=f.get("physical_activity",""),
            sleep_hours=flt("sleep_hours"), water_intake_ml=flt("water_intake_ml"),
            medication_taken=f.get("medication_taken") == "yes",
            notes=f.get("notes","")
        )
        # BMI
        wt = r.weight_kg or p.weight_kg
        ht = r.height_cm or p.height_cm
        if wt and ht and ht > 0:
            h = ht / 100; r.bmi = round(wt / (h*h), 1)

        score, level, alert_list = evaluate_reading(r, p)
        r.risk_score = score; r.risk_level = level
        db.session.add(r)
        db.session.flush()

        for sev, title, desc, action in alert_list:
            a = HealthAlert(patient_id=p.id, alert_type="health_reading",
                            severity=sev, title=title, description=desc,
                            recommended_action=action, reading_id=r.id)
            db.session.add(a)

        db.session.commit()
        flash(f"Reading saved. Risk level: {level.upper()}.", "success" if level == "normal" else "warning")
        return redirect(url_for("patient_readings"))

    page = request.args.get("page",1,type=int)
    filter_days = request.args.get("days","30")
    q = HealthReading.query.filter_by(patient_id=p.id)
    if filter_days != "all":
        since = datetime.now() - timedelta(days=int(filter_days))
        q = q.filter(HealthReading.recorded_at >= since)
    readings = q.order_by(HealthReading.recorded_at.desc()).paginate(page=page, per_page=20)
    return render_template("patient/readings.html", patient=p, readings=readings, filter_days=filter_days)


@app.route("/patient/history")
@login_required
@require_role("patient")
def patient_history():
    p = current_user.patient_profile
    days = request.args.get("days","30")
    q = HealthReading.query.filter_by(patient_id=p.id)
    if days != "all":
        since = datetime.now() - timedelta(days=int(days))
        q = q.filter(HealthReading.recorded_at >= since)
    readings = q.order_by(HealthReading.recorded_at.asc()).all()
    return render_template("patient/history.html", patient=p, readings=readings, days=days)


@app.route("/patient/medications", methods=["GET","POST"])
@login_required
@require_role("patient")
def patient_medications():
    p = current_user.patient_profile
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            f = request.form
            def dt(k):
                v = f.get(k,"")
                try: return datetime.strptime(v, "%Y-%m-%d").date() if v else None
                except: return None
            m = Medication(patient_id=p.id, name=f.get("name",""),
                           dosage=f.get("dosage",""), frequency=f.get("frequency",""),
                           start_date=dt("start_date"), end_date=dt("end_date"),
                           prescribing_doctor=f.get("prescribing_doctor",""),
                           reminder_time=f.get("reminder_time",""))
            db.session.add(m); db.session.commit()
            flash(f"Medication '{m.name}' added.", "success")
        elif action == "mark_taken":
            mid = int(request.form.get("med_id",0))
            med = Medication.query.get(mid)
            if med and med.patient_id == p.id:
                today = date.today()
                existing = MedicationAdherence.query.filter_by(medication_id=mid, taken_date=today).first()
                if existing:
                    existing.was_taken = True; existing.taken_at = datetime.now().time()
                else:
                    adh = MedicationAdherence(medication_id=mid, taken_date=today,
                                              was_taken=True, taken_at=datetime.now().time())
                    db.session.add(adh)
                db.session.commit()
                flash(f"'{med.name}' marked as taken.", "success")
        elif action == "deactivate":
            mid = int(request.form.get("med_id",0))
            med = Medication.query.get(mid)
            if med and med.patient_id == p.id:
                med.is_active = False; db.session.commit()
                flash("Medication deactivated.", "info")
    return render_template("patient/medications.html", patient=p, today=date.today())


@app.route("/patient/alerts")
@login_required
@require_role("patient")
def patient_alerts():
    p = current_user.patient_profile
    alerts = HealthAlert.query.filter_by(patient_id=p.id).order_by(HealthAlert.created_at.desc()).limit(50).all()
    for a in alerts:
        if not a.is_read: a.is_read = True
    db.session.commit()
    return render_template("patient/alerts.html", patient=p, alerts=alerts)


@app.route("/patient/ai-assistant", methods=["GET","POST"])
@login_required
@require_role("patient")
def patient_ai_assistant():
    p = current_user.patient_profile
    history = []
    if request.method == "POST":
        question = request.form.get("question","").strip()
        if question:
            ctx = build_patient_context(p)
            prompt = (f"You are a compassionate AI health assistant powered by IBM Granite 3.0. "
                      f"You help patients understand their chronic disease management.\n\n"
                      f"PATIENT CONTEXT:\n{ctx}\n\n"
                      f"PATIENT QUESTION: {question}\n\n"
                      f"Provide a clear, empathetic, patient-friendly answer. "
                      f"Use simple language. Do not diagnose or prescribe. "
                      f"Recommend consulting a doctor for clinical decisions. "
                      f"Answer in 3-5 bullet points where appropriate.")
            response, err = call_granite(prompt, max_tokens=400)
            if err or not response:
                response = ("I'm unable to reach the IBM Granite AI service right now. "
                            "Please check your internet connection. For urgent health concerns, "
                            "contact your doctor directly.")
            ai_rec = AIAnalysis(patient_id=p.id, analysis_type="chat",
                                prompt=question, response=response, model_used=GRANITE_MODEL_ID)
            db.session.add(ai_rec); db.session.commit()
        history = AIAnalysis.query.filter_by(patient_id=p.id, analysis_type="chat")\
                                  .order_by(AIAnalysis.created_at.desc()).limit(20).all()
        return render_template("patient/ai_assistant.html", patient=p, history=history,
                               last_question=question)
    history = AIAnalysis.query.filter_by(patient_id=p.id, analysis_type="chat")\
                              .order_by(AIAnalysis.created_at.desc()).limit(20).all()
    return render_template("patient/ai_assistant.html", patient=p, history=history)


@app.route("/patient/reports")
@login_required
@require_role("patient")
def patient_reports():
    p = current_user.patient_profile
    return render_template("patient/reports.html", patient=p)


# ─────────────────────────────────────────────
# PATIENT API ENDPOINTS
# ─────────────────────────────────────────────

@app.route("/api/patient/chart-data")
@login_required
@require_role("patient")
def api_chart_data():
    p = current_user.patient_profile
    days = request.args.get("days","30")
    q = HealthReading.query.filter_by(patient_id=p.id)
    if days != "all":
        since = datetime.now() - timedelta(days=int(days))
        q = q.filter(HealthReading.recorded_at >= since)
    readings = q.order_by(HealthReading.recorded_at.asc()).all()
    data = {
        "labels": [r.recorded_at.strftime("%m/%d %H:%M") for r in readings],
        "heart_rate": [r.heart_rate for r in readings],
        "bp_systolic": [r.bp_systolic for r in readings],
        "bp_diastolic": [r.bp_diastolic for r in readings],
        "glucose": [r.blood_glucose for r in readings],
        "spo2": [r.spo2 for r in readings],
        "weight": [r.weight_kg for r in readings],
    }
    return jsonify(data)


@app.route("/api/patient/ai-insight")
@login_required
@require_role("patient")
def api_ai_insight():
    p = current_user.patient_profile
    ctx = build_patient_context(p)
    prompt = (f"You are an IBM Granite 3.0 clinical AI assistant for chronic disease monitoring.\n\n"
              f"PATIENT DATA:\n{ctx}\n\n"
              f"Provide a comprehensive health insight in this format:\n"
              f"**Overall Health Status**: (one sentence)\n"
              f"**Key Observations**:\n• (vital sign observations)\n"
              f"**Warning Signs** (if any):\n• (list concerning findings or 'None currently')\n"
              f"**Personalized Recommendations**:\n• (lifestyle, diet, activity tips)\n"
              f"**Medication Reminder**: (brief adherence reminder)\n"
              f"**Next Steps**: (when to see doctor, what to monitor)\n"
              f"Be warm, clear, and patient-friendly. Use simple language.")
    response, err = call_granite(prompt, max_tokens=500)
    if not response:
        response = None
    ai_rec = AIAnalysis(patient_id=p.id, analysis_type="dashboard",
                        prompt="Dashboard insight", response=response or err or "Unavailable",
                        model_used=GRANITE_MODEL_ID)
    db.session.add(ai_rec); db.session.commit()
    return jsonify({"insight": response, "error": err, "model": GRANITE_MODEL_ID,
                    "timestamp": datetime.now().strftime("%H:%M:%S")})


@app.route("/api/patient/pdf-report")
@login_required
@require_role("patient")
def api_pdf_report():
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.enums import TA_CENTER, TA_LEFT

    p = current_user.patient_profile
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm,
                            leftMargin=2*cm, rightMargin=2*cm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", parent=styles["Heading1"], alignment=TA_CENTER,
                                  textColor=colors.HexColor("#1d4ed8"), fontSize=18)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=colors.HexColor("#0f172a"), fontSize=13)
    body = styles["Normal"]
    muted = ParagraphStyle("muted", parent=body, textColor=colors.HexColor("#6b7280"), fontSize=9)

    story = []
    story.append(Paragraph("GraniteCare AI — Health Report", title_style))
    story.append(Paragraph(f"Generated: {datetime.now().strftime('%B %d, %Y at %H:%M')} | IBM Granite 3.0", muted))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e5e7eb")))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("Patient Information", h2))
    info_data = [
        ["Name", current_user.full_name, "Patient ID", p.patient_code],
        ["Age", str(p.age or "N/A"), "Gender", p.gender or "N/A"],
        ["Blood Group", p.blood_group or "N/A", "Primary Condition", p.primary_disease or "N/A"],
        ["BMI", str(p.bmi or "N/A"), "Phone", current_user.phone or "N/A"],
    ]
    t = Table(info_data, colWidths=[4*cm, 6*cm, 4*cm, 6*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#f8fafc")),
        ("TEXTCOLOR", (0,0), (0,-1), colors.HexColor("#374151")),
        ("TEXTCOLOR", (2,0), (2,-1), colors.HexColor("#374151")),
        ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"),
        ("FONTNAME", (2,0), (2,-1), "Helvetica-Bold"),
        ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#e5e7eb")),
        ("PADDING", (0,0), (-1,-1), 6),
        ("FONTSIZE", (0,0), (-1,-1), 10),
    ]))
    story.append(t); story.append(Spacer(1, 0.4*cm))

    conds = [c.name for c in p.conditions if c.is_active]
    if conds:
        story.append(Paragraph("Active Medical Conditions", h2))
        for c in conds: story.append(Paragraph(f"• {c}", body))
        story.append(Spacer(1, 0.3*cm))

    meds = [m for m in p.medications if m.is_active]
    if meds:
        story.append(Paragraph("Current Medications", h2))
        med_data = [["Medication", "Dosage", "Frequency", "Prescribing Doctor"]]
        for m in meds: med_data.append([m.name, m.dosage or "N/A", m.frequency or "N/A", m.prescribing_doctor or "N/A"])
        mt = Table(med_data, colWidths=[5*cm, 4*cm, 4*cm, 7*cm])
        mt.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1d4ed8")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#e5e7eb")),
            ("PADDING", (0,0), (-1,-1), 5),
            ("FONTSIZE", (0,0), (-1,-1), 9),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f8fafc")]),
        ]))
        story.append(mt); story.append(Spacer(1, 0.3*cm))

    recent = p.readings[:10]
    if recent:
        story.append(Paragraph("Recent Health Readings (Last 10)", h2))
        rdg_data = [["Date/Time","HR","BP","Glucose","SpO2","Temp","Risk"]]
        for r in recent:
            rdg_data.append([
                r.recorded_at.strftime("%m/%d %H:%M"),
                f"{r.heart_rate} bpm" if r.heart_rate else "-",
                f"{r.bp_systolic}/{r.bp_diastolic}" if r.bp_systolic else "-",
                f"{r.blood_glucose} mg/dL" if r.blood_glucose else "-",
                f"{r.spo2}%" if r.spo2 else "-",
                f"{r.temperature}°C" if r.temperature else "-",
                r.risk_level.upper() if r.risk_level else "N/A"
            ])
        rt = Table(rdg_data, colWidths=[3.5*cm,2.5*cm,2.5*cm,3.5*cm,2*cm,2.5*cm,2.5*cm])
        rt.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#0f172a")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#e5e7eb")),
            ("PADDING", (0,0), (-1,-1), 4),
            ("FONTSIZE", (0,0), (-1,-1), 8),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f8fafc")]),
        ]))
        story.append(rt); story.append(Spacer(1, 0.4*cm))

    ctx = build_patient_context(p)
    prompt = (f"You are IBM Granite 3.0, a clinical AI. Generate a professional health report summary.\n"
              f"PATIENT DATA:\n{ctx}\n\n"
              f"Write a 200-word health report summary including: overall health status, key findings, "
              f"recommendations, and when to seek medical care. Use clinical but patient-friendly language.")
    ai_summary, _ = call_granite(prompt, max_tokens=400)
    story.append(Paragraph("AI-Generated Health Summary (IBM Granite 3.0)", h2))
    story.append(Paragraph("⚠️ This AI summary is informational only and does not replace clinical diagnosis.", muted))
    story.append(Spacer(1, 0.2*cm))
    if ai_summary:
        for line in ai_summary.split("\n"):
            if line.strip(): story.append(Paragraph(line.strip(), body))
    else:
        story.append(Paragraph("AI summary unavailable — IBM WatsonX service not reachable.", muted))

    story.append(Spacer(1, 0.5*cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e5e7eb")))
    story.append(Paragraph("GraniteCare AI | IBM Granite 3.0 | IBM Cloud Lite | Confidential Medical Record", muted))

    doc.build(story)
    buf.seek(0)
    fname = f"health_report_{p.patient_code}_{date.today()}.pdf"
    return send_file(buf, as_attachment=True, download_name=fname, mimetype="application/pdf")

# ─────────────────────────────────────────────
# DOCTOR ROUTES
# ─────────────────────────────────────────────

@app.route("/doctor/dashboard")
@login_required
@require_role("doctor")
def doctor_dashboard():
    doc = current_user.doctor_profile
    patients = doc.patients if doc else []
    return render_template("doctor/dashboard.html", doctor=doc, patients=patients)


@app.route("/doctor/patient/<int:pid>")
@login_required
@require_role("doctor")
def doctor_patient_view(pid):
    doc = current_user.doctor_profile
    p = Patient.query.get_or_404(pid)
    if p.assigned_doctor_id != doc.id:
        abort(403)
    readings = p.readings[:30]
    alerts = p.alerts[:20]
    return render_template("doctor/patient_view.html", patient=p, doctor=doc, readings=readings, alerts=alerts)


@app.route("/doctor/patient/<int:pid>/note", methods=["POST"])
@login_required
@require_role("doctor")
def doctor_add_note(pid):
    doc = current_user.doctor_profile
    p = Patient.query.get_or_404(pid)
    if p.assigned_doctor_id != doc.id: abort(403)
    note_text = request.form.get("note","").strip()
    if note_text:
        note = ClinicalNote(doctor_id=doc.id, patient_id=pid, note=note_text)
        db.session.add(note); db.session.commit()
        flash("Clinical note saved.", "success")
    return redirect(url_for("doctor_patient_view", pid=pid))


@app.route("/doctor/patient/<int:pid>/targets", methods=["POST"])
@login_required
@require_role("doctor")
def doctor_set_targets(pid):
    doc = current_user.doctor_profile
    p = Patient.query.get_or_404(pid)
    if p.assigned_doctor_id != doc.id: abort(403)
    t = p.health_targets
    if not t:
        t = HealthTarget(patient_id=pid); db.session.add(t)
    f = request.form
    def flt(k, default): v = f.get(k,""); return float(v) if v else default
    t.glucose_min = flt("glucose_min", 70); t.glucose_max = flt("glucose_max", 140)
    t.bp_systolic_max = flt("bp_systolic_max", 130); t.bp_diastolic_max = flt("bp_diastolic_max", 80)
    t.hr_min = flt("hr_min", 60); t.hr_max = flt("hr_max", 100)
    t.spo2_min = flt("spo2_min", 95); t.hba1c_max = flt("hba1c_max", 7.0)
    db.session.commit()
    flash("Health targets updated.", "success")
    return redirect(url_for("doctor_patient_view", pid=pid))


@app.route("/doctor/patient/<int:pid>/ai-summary")
@login_required
@require_role("doctor")
def doctor_ai_summary(pid):
    doc = current_user.doctor_profile
    p = Patient.query.get_or_404(pid)
    if p.assigned_doctor_id != doc.id: abort(403)
    ctx = build_patient_context(p)
    prompt = (f"You are IBM Granite 3.0, a clinical decision support AI. "
              f"Provide a concise clinical summary for a healthcare provider:\n\n"
              f"PATIENT DATA:\n{ctx}\n\n"
              f"Format as:\n**Clinical Summary**: (2-3 sentences)\n"
              f"**Abnormal Findings**: (bullet list)\n"
              f"**Risk Assessment**: (Low/Moderate/High with reasoning)\n"
              f"**Suggested Clinical Actions**: (bullet list)\n"
              f"**Follow-up Recommendation**: (timeline and tests)")
    response, err = call_granite(prompt, max_tokens=500)
    return jsonify({"summary": response, "error": err, "model": GRANITE_MODEL_ID})

# ─────────────────────────────────────────────
# ADMIN ROUTES
# ─────────────────────────────────────────────

@app.route("/admin/dashboard")
@login_required
@require_role("admin")
def admin_dashboard():
    users = User.query.all()
    patients = Patient.query.all()
    doctors = Doctor.query.all()
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(50).all()
    return render_template("admin/dashboard.html", users=users, patients=patients,
                           doctors=doctors, logs=logs)


@app.route("/admin/assign-doctor", methods=["POST"])
@login_required
@require_role("admin")
def admin_assign_doctor():
    pid = int(request.form.get("patient_id",0))
    did = int(request.form.get("doctor_id",0))
    p = Patient.query.get_or_404(pid)
    p.assigned_doctor_id = did or None
    db.session.commit()
    flash("Doctor assigned.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/architecture")
@login_required
@require_role("admin")
def admin_architecture():
    return render_template("admin/architecture.html")


@app.route("/admin/download-zip")
@login_required
@require_role("admin")
def admin_download_zip():
    buf = io.BytesIO()
    exclude_ext = {".pyc", ".db", ".sqlite", ".env"}
    exclude_dirs = {"__pycache__", ".git", "venv", "env", ".venv"}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(BASE_DIR):
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            for fname in files:
                if any(fname.endswith(e) for e in exclude_ext): continue
                if fname == ".env": continue
                fpath = os.path.join(root, fname)
                arcname = os.path.relpath(fpath, BASE_DIR)
                zf.write(fpath, arcname)
        zf.writestr("example.env",
                    "IBM_WATSONX_API_KEY=your_api_key_here\n"
                    "IBM_WATSONX_PROJECT_ID=your_project_id_here\n"
                    "SECRET_KEY=your_flask_secret_key\n")
    buf.seek(0)
    return send_file(buf, as_attachment=True,
                     download_name=f"granitecare_ai_{date.today()}.zip",
                     mimetype="application/zip")

# ─────────────────────────────────────────────
# ERROR HANDLERS
# ─────────────────────────────────────────────

@app.errorhandler(403)
def forbidden(e):
    return render_template("errors/403.html"), 403

@app.errorhandler(404)
def not_found(e):
    return render_template("errors/404.html"), 404

# ─────────────────────────────────────────────
# DATABASE INIT + DEMO DATA SEEDING
# ─────────────────────────────────────────────

def seed_demo_data():
    """Seed synthetic demonstration users and data — clearly labelled as DEMO."""
    if User.query.filter_by(email="admin@granitecare.ai").first():
        return  # already seeded

    # Admin
    admin = User(full_name="System Admin", email="admin@granitecare.ai", role="admin")
    admin.set_password("Admin@1234")
    db.session.add(admin)

    # Demo Doctor
    doc_user = User(full_name="Dr. Priya Sharma", email="doctor@granitecare.ai", role="doctor", phone="+91-9800000001")
    doc_user.set_password("Doctor@1234")
    db.session.add(doc_user); db.session.flush()
    doc = Doctor(user_id=doc_user.id, specialization="Cardiology & Diabetology",
                 license_number="MCI-2024-DEMO", hospital="GraniteCare Demo Hospital")
    db.session.add(doc); db.session.flush()

    # Demo Patients
    demo_patients_data = [
        {
            "name": "Eleanor Vance [DEMO]", "email": "eleanor@granitecare.ai", "pw": "Patient@1234",
            "dob": date(1963, 4, 12), "gender": "Female", "blood": "B+",
            "height": 165, "weight": 74.5, "primary": "Type 2 Diabetes Mellitus",
            "conditions": ["Type 2 Diabetes Mellitus", "Essential Hypertension (Stage 2)"],
            "meds": [("Metformin", "500mg", "Twice daily"), ("Amlodipine", "5mg", "Once daily")],
            "readings": [
                {"hr": 72, "sys": 126, "dia": 78, "gluc": 118, "spo2": 98, "temp": 36.6},
                {"hr": 75, "sys": 129, "dia": 80, "gluc": 145, "spo2": 97, "temp": 36.8},
                {"hr": 68, "sys": 122, "dia": 76, "gluc": 108, "spo2": 99, "temp": 36.5},
            ]
        },
        {
            "name": "Marcus Chen [DEMO]", "email": "marcus@granitecare.ai", "pw": "Patient@1234",
            "dob": date(1970, 9, 23), "gender": "Male", "blood": "O+",
            "height": 172, "weight": 89.2, "primary": "Coronary Artery Disease",
            "conditions": ["Coronary Artery Disease", "Type 2 Diabetes Mellitus"],
            "meds": [("Aspirin", "75mg", "Once daily"), ("Atorvastatin", "20mg", "Once daily at night")],
            "readings": [
                {"hr": 88, "sys": 138, "dia": 88, "gluc": 165, "spo2": 96, "temp": 36.9},
                {"hr": 92, "sys": 142, "dia": 90, "gluc": 180, "spo2": 95, "temp": 37.1},
            ]
        },
        {
            "name": "Sarah Mitchell [DEMO]", "email": "sarah@granitecare.ai", "pw": "Patient@1234",
            "dob": date(1954, 11, 5), "gender": "Female", "blood": "A-",
            "height": 158, "weight": 64.5, "primary": "Chronic Heart Failure",
            "conditions": ["Chronic Heart Failure (Stage III)", "Atrial Fibrillation"],
            "meds": [("Furosemide", "40mg", "Once daily"), ("Warfarin", "5mg", "Once daily")],
            "readings": [
                {"hr": 95, "sys": 148, "dia": 92, "gluc": 105, "spo2": 93, "temp": 36.4},
            ]
        },
    ]

    for pd in demo_patients_data:
        u = User(full_name=pd["name"], email=pd["email"], role="patient", phone="+91-9800000099")
        u.set_password(pd["pw"]); db.session.add(u); db.session.flush()
        p = Patient(patient_code=generate_patient_code(), user_id=u.id,
                    date_of_birth=pd["dob"], gender=pd["gender"], blood_group=pd["blood"],
                    height_cm=pd["height"], weight_kg=pd["weight"],
                    primary_disease=pd["primary"], assigned_doctor_id=doc.id)
        db.session.add(p); db.session.flush()
        db.session.add(HealthTarget(patient_id=p.id))
        for cname in pd["conditions"]:
            db.session.add(MedicalCondition(patient_id=p.id, name=cname,
                                             diagnosed_on=date(2020,1,1), is_active=True))
        for mname, mdose, mfreq in pd["meds"]:
            db.session.add(Medication(patient_id=p.id, name=mname, dosage=mdose,
                                       frequency=mfreq, start_date=date(2023,1,1),
                                       prescribing_doctor="Dr. Priya Sharma", is_active=True))
        for i, rv in enumerate(pd["readings"]):
            when = datetime.now() - timedelta(days=len(pd["readings"])-i-1, hours=random.randint(0,6))
            r = HealthReading(patient_id=p.id, recorded_at=when,
                              heart_rate=rv["hr"], bp_systolic=rv["sys"], bp_diastolic=rv["dia"],
                              blood_glucose=rv["gluc"], glucose_type="random",
                              spo2=rv["spo2"], temperature=rv["temp"],
                              weight_kg=pd["weight"], height_cm=pd["height"],
                              medication_taken=True, notes="[DEMO DATA]")
            h = pd["height"] / 100
            r.bmi = round(pd["weight"] / (h*h), 1)
            score, level, alert_list = evaluate_reading(r, p)
            r.risk_score = score; r.risk_level = level
            db.session.add(r); db.session.flush()
            for sev, title, desc, action in alert_list:
                db.session.add(HealthAlert(patient_id=p.id, alert_type="health_reading",
                    severity=sev, title=title, description=desc,
                    recommended_action=action, reading_id=r.id))

    db.session.commit()
    print("[GraniteCare] Demo data seeded successfully.")


with app.app_context():
    db.create_all()
    seed_demo_data()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
