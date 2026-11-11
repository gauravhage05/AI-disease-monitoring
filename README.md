# GraniteCare AI — Chronic Disease Monitoring Agent

**IBM SkillsBuild Hackathon — Problem Statement No. 27**

An AI-powered Chronic Disease Monitoring Agent built with **IBM Granite 3.0** and **IBM WatsonX.ai**, helping patients and healthcare professionals manage long-term conditions.

---

## 🏥 Features

- **Patient Dashboard** — Real-time health vitals overview with IBM Granite AI insights
- **Health Monitoring** — Log 13+ health parameters (glucose, BP, HR, SpO2, temp, HbA1c, etc.)
- **AI Health Assistant** — IBM Granite 3.0 powered chatbot with patient-specific context
- **Risk Engine** — Rule-based health risk scoring (Normal / Needs Attention / Concerning / Critical)
- **Smart Alerts** — Automatic alerts for abnormal readings and critical symptoms
- **Medication Management** — Track medications, set reminders, log adherence
- **Health History** — Interactive trend charts (Chart.js) for all vitals
- **PDF Reports** — Professional health reports with AI-generated summaries
- **Doctor Portal** — Clinician dashboard with triage, patient monitoring, clinical notes
- **Admin Panel** — User management, audit logs, system configuration, ZIP export

## 🔧 Technology Stack

| Layer | Technology |
|---|---|
| AI Model | IBM Granite 3.0 (`granite-3.0-8b-instruct`) |
| AI Platform | IBM WatsonX.ai |
| Authentication | IBM IAM OAuth 2.0 |
| Backend | Python 3.x + Flask 3.x |
| Database | SQLite + SQLAlchemy ORM |
| Auth | Flask-Login + Bcrypt |
| Frontend | HTML5 + CSS3 + Chart.js |
| PDF | ReportLab |

## 👥 User Roles

| Role | Credentials (Demo) |
|---|---|
| Patient | eleanor@granitecare.ai / Patient@1234 |
| Doctor | doctor@granitecare.ai / Doctor@1234 |
| Admin | admin@granitecare.ai / Admin@1234 |

## ⚙️ Setup & Installation

### 1. Clone the repository
```bash
git clone https://github.com/YOUR_USERNAME/granitecare-ai.git
cd granitecare-ai
```

### 2. Create a virtual environment
```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure environment variables
```bash
cp example.env .env
```
Edit `.env` and add your IBM WatsonX credentials:
```
IBM_WATSONX_API_KEY=your_ibm_watsonx_api_key
IBM_WATSONX_PROJECT_ID=your_ibm_watsonx_project_id
SECRET_KEY=your_random_flask_secret_key
```

### 5. Run the application
```bash
python app.py
```

Open your browser at: **http://localhost:5000**

The database and demo data are automatically created on first run.

## 🔑 IBM WatsonX Configuration

1. Log in to [IBM Cloud](https://cloud.ibm.com)
2. Open **IBM WatsonX.ai** (Lite plan supported)
3. Create a project and note the **Project ID**
4. Go to **Manage → Access → API Keys** and create an API key
5. Set both values in your `.env` file

## 📁 Project Structure

```
granitecare-ai/
├── app.py                  # Main Flask application
├── requirements.txt        # Python dependencies
├── example.env             # Environment variable template
├── README.md
├── templates/
│   ├── base.html           # Base HTML template
│   ├── layout.html         # App layout (sidebar + topbar)
│   ├── auth/               # Login & Register pages
│   ├── patient/            # Patient portal pages
│   ├── doctor/             # Doctor portal pages
│   ├── admin/              # Admin pages
│   └── errors/             # Error pages
└── static/
    ├── css/style.css       # Complete stylesheet
    └── js/main.js          # JavaScript utilities
```

## 🏗️ Architecture

```
Patient/Doctor → Flask App → IBM WatsonX (Granite 3.0)
                     ↕
              SQLite Database
                     ↕
          Rule-Based Risk Engine
```

## ⚠️ Disclaimer

This application is intended for demonstration and educational purposes as part of IBM SkillsBuild. AI-generated health insights are informational only and do not replace professional medical advice.

---

**Built with IBM Granite 3.0 · IBM WatsonX.ai · IBM Cloud Lite**
