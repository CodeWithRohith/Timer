from flask import Flask, request, jsonify
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
# ⏱️ TIMER/PAY APIs (Simplified)
# -----------------------------------

@app.route('/timer/start', methods=['POST'])
def start_timer():
    """Start a new timer session with hourly pay rate."""
    data = request.json
    required_fields = ["hourly_pay"]
    
    if not all(field in data for field in required_fields):
        return generate_response("error", "Missing required field (hourly_pay)"), 400

    try:
        hourly_pay = float(data["hourly_pay"])
    except ValueError:
        return generate_response("error", "hourly_pay must be a number"), 400

    # Generate a unique session ID
    session_id = redis_client.incr("session_counter")
    
    session_data = {
        "start_time": datetime.utcnow().isoformat(),
        "hourly_pay": hourly_pay,
        "active": "true",
        "end_time": "",
        "total_pay": 0
    }

    # Save session data
    redis_client.hset(f"session:{session_id}", mapping=session_data)
    
    # Add to active sessions set
    redis_client.sadd("active_sessions", session_id)
    
    return generate_response("success", "Timer started", {
        "session_id": session_id,
        "hourly_pay": hourly_pay
    }), 201

@app.route('/timer/status/<session_id>', methods=['GET'])
def get_timer_status(session_id):
    """Get current timer status and earnings."""
    session_key = f"session:{session_id}"
    
    if not redis_client.exists(session_key):
        return generate_response("error", "Session not found"), 404
        
    session_data = redis_client.hgetall(session_key)
    
    if session_data["active"] == "true":
        start_time = datetime.fromisoformat(session_data["start_time"])
        current_time = datetime.utcnow()
        elapsed_seconds = (current_time - start_time).total_seconds()
        earned = elapsed_seconds * float(session_data["hourly_pay"]) / 3600
        
        return generate_response("success", "Timer is running", {
            "active": True,
            "elapsed_seconds": elapsed_seconds,
            "earned": round(earned, 2),
            "hourly_pay": float(session_data["hourly_pay"])
        }), 200
    else:
        return generate_response("success", "Timer is stopped", {
            "active": False,
            "total_pay": float(session_data["total_pay"]),
            "hourly_pay": float(session_data["hourly_pay"]),
            "start_time": session_data["start_time"],
            "end_time": session_data["end_time"]
        }), 200

@app.route('/timer/stop/<session_id>', methods=['POST'])
def stop_timer(session_id):
    """Stop an active timer session."""
    session_key = f"session:{session_id}"
    
    if not redis_client.exists(session_key):
        return generate_response("error", "Session not found"), 404
        
    session_data = redis_client.hgetall(session_key)
    
    if session_data["active"] != "true":
        return generate_response("error", "Timer is already stopped"), 400
    
    start_time = datetime.fromisoformat(session_data["start_time"])
    end_time = datetime.utcnow()
    elapsed_seconds = (end_time - start_time).total_seconds()
    total_pay = elapsed_seconds * float(session_data["hourly_pay"]) / 3600
    
    # Update session data
    redis_client.hset(session_key, "end_time", end_time.isoformat())
    redis_client.hset(session_key, "total_pay", total_pay)
    redis_client.hset(session_key, "active", "false")
    
    # Remove from active sessions
    redis_client.srem("active_sessions", session_id)
    
    return generate_response("success", "Timer stopped", {
        "session_id": session_id,
        "total_pay": round(total_pay, 2),
        "elapsed_seconds": elapsed_seconds,
        "hourly_pay": float(session_data["hourly_pay"])
    }), 200

@app.route('/timer/history', methods=['GET'])
def get_timer_history():
    """Get completed timer sessions, optionally limited by count."""
    limit = request.args.get('limit', default=None, type=int)
    
    # Get all session keys
    session_keys = []
    for key in redis_client.scan_iter("session:*"):
        session_data = redis_client.hgetall(key)
        if session_data["active"] == "false":
            session_keys.append(key)
    
    sessions = []
    for key in session_keys:
        session_data = redis_client.hgetall(key)
        sessions.append({
            "session_id": key.split(":")[1],
            "start_time": session_data["start_time"],
            "end_time": session_data["end_time"],
            "hourly_pay": float(session_data["hourly_pay"]),
            "total_pay": float(session_data["total_pay"])
        })
    
    # Sort by most recent first
    sessions.sort(key=lambda x: x["end_time"], reverse=True)
    
    # Apply limit if specified
    if limit is not None and limit > 0:
        sessions = sessions[:limit]
    
    return generate_response("success", "Timer history retrieved", sessions), 200

# -----------------------------------
# 🚀 APP RUN
# -----------------------------------

if __name__ == '__main__':
    app.run(debug=True)