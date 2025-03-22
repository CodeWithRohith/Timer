from flask import Flask, request, jsonify, make_response
from datetime import datetime, timedelta
import redis
from dotenv import load_dotenv
import os
from flask_cors import CORS

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
CORS(app, supports_credentials=True)

# Redis Cloud connection details
REDIS_HOST = "redis-11218.crce174.ca-central-1-1.ec2.redns.redis-cloud.com"
REDIS_PORT = 11218
REDIS_PASSWORD = "8RnOTKOvdVDEY2c7Ukyd4WQMQRvHJ7M6"

# Connect to Redis Cloud
redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    password=REDIS_PASSWORD,
    decode_responses=True
)

# Test Redis connection
try:
    redis_client.ping()
    print("Connected to Redis Cloud!")
except redis.ConnectionError as e:
    print(f"Failed to connect to Redis Cloud: {e}")

# Helper function for responses
def generate_response(status, message, data=None):
    response = {"status": status, "message": message}
    if data:
        response["data"] = data
    return jsonify(response)

# -----------------------------------
# 👤 USER APIs
# -----------------------------------

@app.route('/users/register', methods=['POST'])
def register_user():
    """Register a new user."""
    data = request.json
    required_fields = ["name", "email", "password"]

    if not all(field in data for field in required_fields):
        return generate_response("error", "Missing required fields (name, email, password)"), 400

    # Check if the email is already registered
    if redis_client.hexists("users", data["email"]):
        return generate_response("error", "Email already registered"), 400

    # Generate a unique user ID
    user_id = redis_client.incr("user_counter")
    user_data = {
        "user_id": user_id,
        "name": data["name"],
        "email": data["email"],
        "password": data["password"]  # In a real app, hash the password!
    }

    # Save user data in Redis
    redis_client.hset("users", data["email"], user_id)
    redis_client.hset(f"user:{user_id}", mapping=user_data)

    return generate_response("success", "User registered successfully", {"user_id": user_id}), 201

@app.route('/users/login', methods=['POST'])
def login():
    """Login a user."""
    data = request.json
    required_fields = ["email", "password"]

    if not all(field in data for field in required_fields):
        return generate_response("error", "Missing required fields (email, password)"), 400

    # Check if the user exists in Redis
    user_id = redis_client.hget("users", data["email"])
    if user_id:
        # Verify password (in a real app, use hashed passwords)
        stored_password = redis_client.hget(f"user:{user_id}", "password")
        if stored_password == data["password"]:
            # Create a response and set the user_id cookie
            response = make_response(generate_response("success", "Login successful", {"user_id": user_id}))
            response.set_cookie('user_id', str(user_id), max_age=timedelta(days=1))  # Cookie expires in 1 day
            return response
    return generate_response("error", "Invalid email or password"), 401

@app.route('/users/logout', methods=['POST'])
def logout():
    """Logout a user."""
    # Create a response and clear the user_id cookie
    response = make_response(generate_response("success", "Logout successful"))
    response.set_cookie('user_id', '', expires=0)  # Clear the cookie
    return response

# -----------------------------------
# ⏱️ TIMER/PAY APIs
# -----------------------------------

@app.route('/timer/pay/start', methods=['POST'])
def start_pay_timer():
    """Start a new pay timer session."""
    # Get user_id from the cookie
    user_id = request.cookies.get('user_id')
    if not user_id:
        return generate_response("error", "Unauthorized: Please log in"), 401

    data = request.json
    required_fields = ["hourly_pay", "deductions", "expected_pay"]

    if not all(field in data for field in required_fields):
        return generate_response("error", "Missing required fields (hourly_pay, deductions, expected_pay)"), 400

    # Ensure all fields have valid values
    session_data = {
        "user_id": user_id,
        "start_time": datetime.utcnow().isoformat(),
        "hourly_pay": data["hourly_pay"],
        "deductions": data["deductions"],
        "expected_pay": data["expected_pay"],
        "end_time": "",  # Replace None with an empty string
        "total_time": 0,  # Replace None with 0
        "total_money": 0  # Replace None with 0
    }

    # Generate a unique session ID
    session_id = redis_client.incr("session_counter")
    redis_client.hset(f"session:pay:{session_id}", mapping=session_data)

    return generate_response("success", "Pay timer session started", {"session_id": session_id}), 201

@app.route('/timer/pay/stop', methods=['POST'])
def stop_pay_timer():
    """Stop an existing pay timer session."""
    # Get user_id from the cookie
    user_id = request.cookies.get('user_id')
    if not user_id:
        return generate_response("error", "Unauthorized: Please log in"), 401

    data = request.json
    required_fields = ["session_id"]

    if not all(field in data for field in required_fields):
        return generate_response("error", "Missing required field (session_id)"), 400

    session_id = data["session_id"]
    session_key = f"session:pay:{session_id}"

    # Check if the session exists
    if not redis_client.exists(session_key):
        return generate_response("error", "Session not found"), 404

    # Get session data
    session_data = redis_client.hgetall(session_key)
    start_time = datetime.fromisoformat(session_data["start_time"])
    end_time = datetime.utcnow()

    # Calculate total time and money
    total_time = (end_time - start_time).total_seconds()
    total_money = (float(session_data["expected_pay"]) * total_time) / 3600

    # Update session data
    redis_client.hset(session_key, "end_time", end_time.isoformat())
    redis_client.hset(session_key, "total_time", total_time)
    redis_client.hset(session_key, "total_money", total_money)

    return generate_response("success", "Pay timer session stopped", {
        "total_time": total_time,
        "total_money": total_money
    }), 200

@app.route('/timer/pay/history', methods=['GET'])
def get_pay_timer_history():
    """Get all pay timer sessions for a user."""
    # Get user_id from the cookie
    user_id = request.cookies.get('user_id')
    if not user_id:
        return generate_response("error", "Unauthorized: Please log in"), 401

    # Find all pay sessions for the user
    session_keys = redis_client.keys("session:pay:*")
    sessions = []

    for key in session_keys:
        session_data = redis_client.hgetall(key)
        if session_data["user_id"] == user_id:
            sessions.append({
                "session_id": key.split(":")[2],  # Extract session ID from key
                "start_time": session_data["start_time"],
                "end_time": session_data["end_time"],
                "total_time": float(session_data.get("total_time", 0)),
                "total_money": float(session_data.get("total_money", 0))
            })

    return generate_response("success", "Pay timer sessions retrieved successfully", sessions), 200

# -----------------------------------
# 🚀 APP RUN
# -----------------------------------

if __name__ == '__main__':
    app.run(debug=True)