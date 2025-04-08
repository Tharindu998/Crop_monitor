import os
from datetime import datetime, timedelta
import requests
from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Load environment variables
load_dotenv()

# Flask app configuration
app = Flask(__name__)
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, 'farmers.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DATABASE_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize rate limiter
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    storage_uri="memory://"
)
db = SQLAlchemy(app)

# Constants
BASE_TEMP = 10
STAGES = [
    {'name': 'Germination', 'threshold': 20, 'advice': 'Ensure proper seedling care—maintain moisture, temperature (20–35°C), and good soil contact for uniform germination.'},
    {'name': 'Maximum Tillering', 'threshold': 450, 'advice': 'Apply nitrogen fertilizer to boost tiller growth; ensure adequate water supply and weed control to maximize yield potential.'},
    {'name': 'Panicle Initiation', 'threshold': 1100, 'advice': 'Increase potassium and phosphorus fertilization; maintain consistent water levels to support panicle development.'},
    {'name': 'Flowering', 'threshold': 1600, 'advice': 'Avoid water stress; monitor pests/diseases closely and apply protective sprays if needed to safeguard grain setting.'},
    {'name': 'Maturity', 'threshold': 2500, 'advice': 'Reduce irrigation gradually; harvest on time to prevent shattering or quality loss for optimal grain yield and quality.'}
]

# Database Models
class Farmer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(20), unique=True, nullable=False, index=True)
    planting_date = db.Column(db.Date, nullable=False)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    gdd_accumulated = db.Column(db.Float, default=0)
    current_stage_index = db.Column(db.Integer, default=0)
    registration_date = db.Column(db.Date, nullable=False)
    last_processed_date = db.Column(db.Date)
    moisture_logs = db.relationship('SoilMoistureLog', backref='farmer', lazy=True)

class GDDLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    farmer_id = db.Column(db.Integer, db.ForeignKey('farmer.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    gdd = db.Column(db.Float, nullable=False)

class SoilMoistureLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    farmer_id = db.Column(db.Integer, db.ForeignKey('farmer.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    moisture = db.Column(db.Float)

# Initialize database
with app.app_context():
    db.create_all()

# Validate API keys at startup
REQUIRED_API_KEYS = ['TEXT_LK_API_TOKEN']
missing_keys = [key for key in REQUIRED_API_KEYS if not os.getenv(key)]
if missing_keys:
    raise EnvironmentError(f"Missing required API keys: {', '.join(missing_keys)}")

# Debugging: Check if environment variables exist
print("TEXT_LK_KEY exists?", 'TEXT_LK_API_TOKEN' in os.environ)

# Utility Functions
@limiter.limit("3/day")
def send_sms(phone_number, message):
    API_TOKEN = os.getenv('TEXT_LK_API_TOKEN')
    if not API_TOKEN:
        print("SMS API token missing")
        return
    payload = {"recipient": phone_number, "message": message, "sender_id": "Farm_Alert"}    
    headers = {"Authorization": f"Bearer {API_TOKEN}", "Content-Type": "application/json"}
    try:
        response = requests.post("https://app.text.lk/api/v3/sms/send", json=payload, headers=headers)
        response.raise_for_status()
    except Exception as e:
        print(f"SMS Error: {str(e)}")

def is_duplicate_sms(phone_number, message):
    # Implement logic to check if the same SMS was sent recently
    # Example: Use a cache or database table to track sent messages
    return False

def log_sms(phone_number, message):
    # Log SMS to a file or database for tracking
    with open("sms_log.txt", "a") as log_file:
        log_file.write(f"{datetime.now()}: {phone_number} - {message}\n")

def validate_date(date):
    max_valid_date = datetime.now().date() - timedelta(days=1)  # Exclude future dates
    if date > max_valid_date:
        print(f"Date {date} is in the future. Using the latest valid date: {max_valid_date}.")
        return max_valid_date
    return date

def get_mock_data(date, lat, lon):
    if date > datetime.now().date():
        print(f"Using mock data for future date: {date}")
        return {
            "soil_moisture_0_to_1cm": 0.1,  # Example soil moisture value
            "temperature_max": 25.0,  # Example max temperature
            "temperature_min": 20.0  # Example min temperature
        }
    return None

def fetch_soil_moisture(lat, lon, date):
    mock_data = get_mock_data(date, lat, lon)
    if mock_data:
        return mock_data.get("soil_moisture_0_to_7cm"), None  # Match the expected tuple format

    date = validate_date(date)
    try:
        response = requests.get(
            "https://archive-api.open-meteo.com/v1/archive",
            params={
                "latitude": lat,
                "longitude": lon,
                "start_date": date.strftime('%Y-%m-%d'),
                "end_date": date.strftime('%Y-%m-%d'),
                "hourly": "soil_moisture_0_to_7cm",  # Updated parameter
                "timezone": "auto"
            }
        )
        if response.status_code != 200:
            print(f"Soil Moisture API Error: {response.status_code}, Response: {response.text}")
            return None, None
        
        data = response.json()
        print("Soil Moisture Response:", data)  # Debugging
        
        hourly = data.get('hourly', {})
        moisture_values = hourly.get('soil_moisture_0_to_7cm', [])
        
        # Filter out None values and calculate the average
        valid_moisture_values = [value for value in moisture_values if value is not None]
        if valid_moisture_values:
            return sum(valid_moisture_values) / len(valid_moisture_values), None
        else:
            print(f"No valid soil moisture data available for {date} at location ({lat}, {lon}).")
            return None, None
    except Exception as e:
        print(f"Soil Moisture Error: {str(e)}")
        return None, None

def fetch_temperature(lat, lon, date):
    mock_data = get_mock_data(date, lat, lon)
    if mock_data:
        return mock_data["temperature_max"], mock_data["temperature_min"]

    date = validate_date(date)
    try:
        response = requests.get(
        
            "https://archive-api.open-meteo.com/v1/archive",

            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_max,temperature_2m_min",
                "start_date": date.strftime('%Y-%m-%d'),
                "end_date": date.strftime('%Y-%m-%d'),
                "timezone": "auto"
            }
        )
        if response.status_code == 200:
            data = response.json()
            daily = data.get('daily', {})
            return (
                daily.get('temperature_2m_max', [None])[0],
                daily.get('temperature_2m_min', [None])[0]
            )
        else:
            print(f"Temperature API Error: {response.status_code} - {response.text}")
            return None, None
    except Exception as e:
        print(f"Temperature Error: {str(e)}")
        return None, None

# Define thresholds for soil moisture
SOIL_MOISTURE_THRESHOLD = 0.1  # Updated threshold for soil moisture (in percentage)

def update_soil_moisture():
    with app.app_context():
        try:
            farmers = Farmer.query.all()
            current_date = datetime.now().date()
            for farmer in farmers:
                # Fetch soil moisture
                moisture_0_to_7cm, _ = fetch_soil_moisture(farmer.latitude, farmer.longitude, current_date)
                print(f"Fetched Soil Moisture (0-7 cm) for Farmer {farmer.id}: {moisture_0_to_7cm}")  # Debugging log

                # Process soil moisture (0-7 cm)
                if moisture_0_to_7cm is not None:
                    moisture_log = SoilMoistureLog(farmer_id=farmer.id, date=current_date, moisture=moisture_0_to_7cm)
                    db.session.add(moisture_log)
                    print(f"Soil Moisture Log (0-7 cm) Added: {moisture_log}")  # Debugging log
                    if moisture_0_to_7cm < SOIL_MOISTURE_THRESHOLD:
                        send_sms(farmer.phone, f"Alert: Soil moisture (0-7 cm) is critically low ({moisture_0_to_7cm:.2f}%) on {current_date}. Immediate irrigation is required.")
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Error updating Soil Moisture: {str(e)}")

def calculate_gdd(max_temp, min_temp):
    avg_temp = (max_temp + min_temp) / 2
    return max(0, avg_temp - BASE_TEMP)

def update_gdd_and_stages():
    with app.app_context():
        try:
            farmers = Farmer.query.all()
            current_date = datetime.now().date()
            for farmer in farmers:
                date_to_process = farmer.last_processed_date or farmer.planting_date
                print(f"Processing Farmer {farmer.id} from {date_to_process} to {current_date}")  # Debugging log

                while date_to_process <= current_date:
                    if date_to_process > datetime.now().date():
                        print(f"Skipping future date: {date_to_process}")
                        break

                    # Fetch temperature data
                    max_temp, min_temp = fetch_temperature(farmer.latitude, farmer.longitude, date_to_process)
                    print(f"Fetched Temperature for Farmer {farmer.id} on {date_to_process}: Max={max_temp}, Min={min_temp}")  # Debugging log

                    if max_temp is None or min_temp is None:
                        date_to_process += timedelta(days=1)
                        continue

                    # Calculate GDD for the day
                    gdd_today = calculate_gdd(max_temp, min_temp)
                    farmer.gdd_accumulated += gdd_today
                    print(f"GDD for Farmer {farmer.id} on {date_to_process}: {gdd_today}, Accumulated: {farmer.gdd_accumulated}")  # Debugging log

                    # Log GDD for the day
                    gdd_log = GDDLog(farmer_id=farmer.id, date=date_to_process, gdd=gdd_today)
                    db.session.add(gdd_log)

                    moisture_0_to_1cm, _ = fetch_soil_moisture(farmer.latitude, farmer.longitude, date_to_process)
                    if moisture_0_to_1cm is not None:
                        moisture_log = SoilMoistureLog(farmer_id=farmer.id, date=date_to_process, moisture=moisture_0_to_1cm)
                        db.session.add(moisture_log)
                        print(f"Soil Moisture Log Added for Farmer {farmer.id} on {date_to_process}: {moisture_0_to_1cm}")  # Debugging log

                        # Send SMS if soil moisture is below threshold
                        if moisture_0_to_1cm < SOIL_MOISTURE_THRESHOLD:
                            send_sms(
                                farmer.phone,
                                f"Alert: Soil moisture (0-1 cm) is low ({moisture_0_to_1cm:.2f}%) on {date_to_process}. Consider irrigation."
                            )

                    # Update crop stages
                    while farmer.current_stage_index < len(STAGES) - 1:
                        next_stage = STAGES[farmer.current_stage_index + 1]
                        if farmer.gdd_accumulated >= next_stage['threshold']:
                            send_sms(
                                farmer.phone,
                                f"Stage Update: {next_stage['name']} - {next_stage['advice']}"
                            )
                            farmer.current_stage_index += 1
                        else:
                            break

                    # Update last processed date
                    farmer.last_processed_date = date_to_process
                    date_to_process += timedelta(days=1)

            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Error updating GDD and stages: {str(e)}")

# Scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(update_soil_moisture, 'cron', hour=6, misfire_grace_time=3600, coalesce=True)
scheduler.add_job(update_gdd_and_stages, 'cron', hour=7, misfire_grace_time=3600, coalesce=True)
scheduler.start()

# Define the color palette
COLOR_PALETTE = {
    "primary": "#28A745",  # Green
    "secondary": "#F8F9FA",  # Light Beige
    "accent": "#007BFF",  # Dark Blue
    "text": "#FFFFFF",  # White
    "background": "#343A40"  # Dark Gray
}

# Routes
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        phone = request.form['phone']
        planting_date = datetime.strptime(request.form['planting_date'], '%Y-%m-%d').date()
        latitude = float(request.form['latitude'])
        longitude = float(request.form['longitude'])
        registration_date = datetime.now().date()
        farmer = Farmer(
            username=username,
            phone=phone,
            planting_date=planting_date,
            latitude=latitude,
            longitude=longitude,
            registration_date=registration_date
        )
        db.session.add(farmer)
        db.session.commit()

        # Trigger immediate updates for historical data
        update_soil_moisture()
        update_gdd_and_stages()

        # Send registration confirmation SMS
        send_sms(
            phone,
            "Registration complete! Monitoring has started for optimal crop growth. Stay tuned for updates."
        )

        # Fetch the most recent soil moisture log for the farmer
        recent_moisture_log = SoilMoistureLog.query.filter_by(farmer_id=farmer.id).order_by(SoilMoistureLog.date.desc()).first()
        recent_soil_moisture = recent_moisture_log.moisture if recent_moisture_log else "N/A"

        # Send additional SMS with AGDD and soil moisture details
        send_sms(
            phone,
            f"AGDD: {farmer.gdd_accumulated}, Soil Moisture: {recent_soil_moisture}. Stay updated for optimal crop growth!"
        )

        return render_template('success.html', colors=COLOR_PALETTE, login_url=url_for('login'), farmer_id=farmer.id)  # Pass farmer_id
    return render_template('register.html', colors=COLOR_PALETTE)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        farmer = Farmer.query.filter_by(username=username).first()
        if farmer:
            return redirect(url_for('dashboard', farmer_id=farmer.id))  # Redirect to dashboard
        return "Invalid username!", 401
    return render_template('login.html', colors=COLOR_PALETTE)

@app.route('/login.html')
def login_html():
    return render_template('login.html')

@app.route('/')
def home():
    # Updated to include only Register and Login buttons Latitude: 7.2525 Longitude: 80.5913
    return render_template(
        'home.html',
        sections=[
            {"title": "About Us", "content": "Learn about our mission to help farmers optimize crop growth."},
            {"title": "Features", "content": "Explore features like NDVI monitoring, soil moisture tracking, and GDD calculations."},
            {"title": "Contact Us", "content": "Reach out to us for support or inquiries."}
        ],
        buttons=[
            {"label": "Register", "url": url_for('register')},
            {"label": "Login", "url": url_for('login')}  # Removed "Predict" and "Data Visualization" buttons
        ],
        colors=COLOR_PALETTE
    )

@app.route('/chart-data/<int:farmer_id>')
def chart_data(farmer_id):
    farmer = db.session.get(Farmer, farmer_id)
    if not farmer:
        return jsonify({"error": "Farmer not found"}), 404

    # Prepare data for charts
    moisture_logs = SoilMoistureLog.query.filter_by(farmer_id=farmer_id).order_by(SoilMoistureLog.date).all()
    gdd_logs = GDDLog.query.filter_by(farmer_id=farmer_id).order_by(GDDLog.date).all()

    moisture_data = [
        {'date': log.date.strftime('%Y-%m-%d'), 'moisture': log.moisture}
        for log in moisture_logs if log.moisture is not None
    ]
    gdd_data = [
        {'date': log.date.strftime('%Y-%m-%d'), 'gdd': log.gdd}
        for log in gdd_logs if log.gdd is not None
    ]

    return jsonify({"moisture_data": moisture_data, "gdd_data": gdd_data})

@app.route('/dashboard/<int:farmer_id>')
def dashboard(farmer_id):
    farmer = db.session.get(Farmer, farmer_id)  # Updated to use SQLAlchemy 2.0 syntax
    if not farmer:
        return "Farmer not found!", 404

    # Pass chart data endpoint to the template
    chart_data_url = url_for('chart_data', farmer_id=farmer_id)

    # Fetch soil moisture logs
    moisture_logs = SoilMoistureLog.query.filter_by(farmer_id=farmer_id).order_by(SoilMoistureLog.date).all()
    moisture_data = [
        {'date': log.date.strftime('%Y-%m-%d'), 'moisture': log.moisture}
        for log in moisture_logs if log.moisture is not None
    ]
    # Fetch GDD accumulation data
    gdd_logs = GDDLog.query.filter_by(farmer_id=farmer_id).order_by(GDDLog.date).all()
    gdd_data = [
        {'date': log.date.strftime('%Y-%m-%d'), 'gdd': log.gdd}
        for log in gdd_logs if log.gdd is not None
    ]

    # Render the dashboard template
    return render_template(
        'dashboard.html',
        farmer=farmer,
        STAGES=STAGES,
        moisture_data=moisture_data,
        gdd_data=gdd_data,
        colors=COLOR_PALETTE,
        chart_data_url=chart_data_url
    )

@app.route('/test-updates')
def test_updates():
    update_soil_moisture()
    update_gdd_and_stages()
    return "Updates triggered"

@app.route('/predict', methods=['GET', 'POST'])
def predict():
    if request.method == 'POST':
        # Implement prediction logic here
        return "Prediction results will be displayed here."
    return render_template('predict.html', colors=COLOR_PALETTE)  # Ensure the 'predict.html' template exists

@app.route('/data-visualization')
def data_visualization():
    # Placeholder implementation
    return "Data visualization page coming soon!"

if __name__ == '__main__':
    app.run(debug=True)