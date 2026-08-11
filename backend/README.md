# WebSense AI

WebSense AI is an AI-powered website auditing platform that automatically analyzes websites and generates comprehensive reports on their technical health, security, search engine optimization (SEO), accessibility, and user experience.

The platform combines deterministic website analysis with AI-generated explanations to provide accurate, reproducible, and easy-to-understand audit reports.

---

## Features

- Website crawling using Requests and BeautifulSoup4
- Technology stack detection
- Passive security analysis
- SEO analysis
- Accessibility and browser testing using Playwright
- AI-generated explanations and modernization recommendations using Groq Llama 3.3 70B
- Deterministic scoring for:
  - Technical Health
  - Security
  - SEO
  - Accessibility
- User authentication
- MySQL database integration using SQLAlchemy
- Automatic email report generation through SMTP

---

## Tech Stack

### Backend
- Flask
- SQLAlchemy
- MySQL
- Requests
- BeautifulSoup4
- Playwright
- Groq API (Llama 3.3 70B)

### Frontend
- HTML
- CSS
- JavaScript
- Jinja2 Templates

### Database
- MySQL

---

## Project Structure

```
backend/
│
├── app.py                  # Flask application entry point
├── config.py               # Application configuration
│
├── app/
│   ├── routes/
│   │   └── routes.py       # API endpoints
│   │
│   ├── services/
│   │   ├── pipeline.py
│   │   ├── crawl.py
│   │   ├── analyze.py
│   │   ├── scoring.py
│   │   ├── browser_tests.py
│   │   └── ai_insights.py
│   │
│   ├── agents/
│   │   └── promo_email_agent.py
│   │
│   ├── models/
│   │   └── user.py
│   │
│   └── utils/
│       ├── db.py
│       └── users_store.py
│
├── data/
└── README.md
```

---

## Workflow

```
User
   │
   ▼
Enter Website URL
   │
   ▼
Website Crawling
   │
   ▼
Website Analysis
   │
   ├── Technology Detection
   ├── Security Analysis
   ├── SEO Analysis
   ├── Accessibility Tests
   └── AI Content Review
   │
   ▼
Scoring Engine
   │
   ▼
Generate Report
   │
   ▼
Store Results
   │
   ▼
Send Email Summary
```

---

## Installation

### Clone Repository

```bash
git clone <repository-url>
cd WebsenseAI
```

### Create Virtual Environment

```bash
python -m venv venv
```

Windows

```bash
venv\Scripts\activate
```

Linux/macOS

```bash
source venv/bin/activate
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Configure Environment Variables

Create a `.env` file.

Example:

```env
SECRET_KEY=

MYSQL_HOST=
MYSQL_PORT=
MYSQL_USER=
MYSQL_PASSWORD=
MYSQL_DATABASE=

GROQ_API_KEY=

SMTP_SERVER=
SMTP_PORT=
SMTP_EMAIL=
SMTP_PASSWORD=
```

### Create Database

```sql
CREATE DATABASE websenseai;
```

### Run the Application

```bash
python app.py
```

---

## Modules

### Authentication
Handles user registration, login, password hashing, and session management.

### Website Crawler
Collects webpages using Requests and BeautifulSoup4.

### Website Analysis
Performs security, SEO, accessibility, and technology stack analysis.

### AI Insights
Uses Groq-hosted Llama 3.3 70B to generate explanations and recommendations.

### Scoring Engine
Calculates deterministic website scores based only on verified findings.

### Report Generation
Displays the final report and emails a personalized summary to the user.

---

## Design Principle

A key design principle of WebSense AI is that **AI never influences the website scores**.

Scores are calculated only from verified technical findings, ensuring that repeated scans of the same website always produce consistent and reproducible results. AI is used solely to explain findings and provide recommendations.

---

## Future Improvements

- Performance analysis
- Mobile responsiveness scoring
- Lighthouse integration
- Scheduled website monitoring
- PDF report export
- Multi-user dashboard
- Historical report comparison

---

## Contributors

BitString IT Internship Project

Backend Development:
- Ishan Kandari

Frontend Development:
- Team Members

Mentor:
- Mr. Ravi Deshmukh