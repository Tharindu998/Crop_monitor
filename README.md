# 🌾 Smart Paddy Crop Monitoring App

A Flask-based web application designed to help paddy farmers optimize their crop management by tracking **Accumulated Growing Degree Days (AGDD)** and sending **timely SMS alerts** with stage-specific recommendations.

## 🚀 Features

- 🌡️ **AGDD Tracking**: Automatically calculates daily Growing Degree Days using Open-Meteo weather data.
- 📲 **SMS Alerts**: Notifies farmers via SMS when important crop growth stages are reached.
- 📅 **Stage-Based Advice**: Provides agronomic tips at each stage—germination, tillering, panicle initiation, flowering, and maturity.
- 🧑‍🌾 **Farmer Registration**: Simple registration with name, planting date, location, and phone number.
- 📊 **Dashboard**: Interactive dashboard displaying AGDD progression over time.


## 🛠️ Tech Stack

- **Backend**: Flask (Python)
- **Database**: SQLite + SQLAlchemy ORM
- **Scheduler**: APScheduler (daily cron jobs)
- **APIs**: Open-Meteo (weather data), text.lk (SMS integration)
- **Frontend**: HTML/CSS (Jinja2 templates)

## 📝 Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/paddy-monitoring-app.git
   cd paddy-monitoring-app
   
1. Create a virtual environment
   ```bash
   python -m venv venv
   source venv/bin/activate  # or venv\Scripts\activate on Windows

3. Install dependencies
   ```bash
   pip install -r requirements.txt
   
5. Set environment variables
   ```bash
   TEXT_LK_API_TOKEN=your_textlk_api_key_here

6. Run the app
   ```bash
    python app.py

