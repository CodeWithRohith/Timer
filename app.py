from flask import Flask, request, jsonify
from datetime import datetime, timedelta
import redis
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={
    r"/timer/*": {"origins": "*"},
    r"/users/*": {"origins": "*"}
})

# Redis configuration
redis_client = redis.Redis(
    host='redis-11218.crce174.ca-central-1-1.ec2.redns.redis-cloud.com',
    port=11218,
    password='8RnOTKOvdVDEY2c7Ukyd4WQMQRvHJ7M6',
    decode_responses=True
)

@app.route('/timer/start', methods=['POST', 'OPTIONS'])
def start_timer():
    """Start a new timer session with hourly pay rate."""
    if request.method == 'OPTIONS':
        return _build_cors_preflight_response()
    
    data = request.get_json()
    if not data or 'hourly_pay' not in data:
        return jsonify({"error": "Missing hourly_pay"}), 400
    
    try:
        hourly_pay = float(data['hourly_pay'])
    except ValueError:
        return jsonify({"error": "hourly_pay must be a number"}), 400

    # Check for an existing active session
    active_sessions = redis_client.smembers("active_sessions")
    if active_sessions:
        session_id = list(active_sessions)[0]
        session_data = redis_client.hgetall(f"session:{session_id}")

        return _corsify_actual_response(jsonify({
            "status": "already_running",
            "session_id": session_id,
            "hourly_pay": float(session_data["hourly_pay"]),
            "start_time": session_data["start_time"]
        }))

    # Create new session
    session_id = redis_client.incr("session_counter")
    session_data = {
        "start_time": datetime.utcnow().isoformat(),
        "hourly_pay": hourly_pay,
        "active": "true",
        "end_time": "",
        "total_pay": "0"
    }

    redis_client.hset(f"session:{session_id}", mapping=session_data)
    redis_client.sadd("active_sessions", session_id)
    
    return _corsify_actual_response(jsonify({
        "status": "started",
        "session_id": session_id,
        "hourly_pay": hourly_pay
    }))

@app.route('/timer/stop', methods=['POST', 'OPTIONS'])
def stop_timer():
    """Stop the active timer session."""
    if request.method == 'OPTIONS':
        return _build_cors_preflight_response()

    active_sessions = redis_client.smembers("active_sessions")
    if not active_sessions:
        return jsonify({"error": "No active timer session"}), 400

    session_id = list(active_sessions)[0]
    session_key = f"session:{session_id}"
    session_data = redis_client.hgetall(session_key)

    if not session_data or session_data.get("active") != "true":
        return jsonify({"error": "Invalid or already stopped session"}), 400

    # Calculate total pay
    start_time = datetime.fromisoformat(session_data["start_time"])
    end_time = datetime.utcnow()
    elapsed_hours = (end_time - start_time).total_seconds() / 3600
    total_pay = round(float(session_data["hourly_pay"]) * elapsed_hours, 2)

    # Update session
    redis_client.hset(session_key, mapping={
        "active": "false",
        "end_time": end_time.isoformat(),
        "total_pay": str(total_pay)
    })
    redis_client.srem("active_sessions", session_id)

    return _corsify_actual_response(jsonify({
        "status": "stopped",
        "session_id": session_id,
        "start_time": session_data["start_time"],
        "end_time": end_time.isoformat(),
        "total_pay": total_pay,
        "hours_worked": round(elapsed_hours, 4)
    }))

@app.route('/timer/active_status', methods=['GET', 'OPTIONS'])
def get_active_timer_status():
    """Check if there's an active timer session."""
    if request.method == 'OPTIONS':
        return _build_cors_preflight_response()
    
    active_sessions = redis_client.smembers("active_sessions")
    if not active_sessions:
        return _corsify_actual_response(jsonify({"active": False}))
    
    session_id = list(active_sessions)[0]
    session_key = f"session:{session_id}"
    session_data = redis_client.hgetall(session_key)
    
    if session_data.get("active", "false") != "true":
        return _corsify_actual_response(jsonify({"active": False}))
    
    start_time = datetime.fromisoformat(session_data["start_time"])
    elapsed_seconds = (datetime.utcnow() - start_time).total_seconds()
    
    return _corsify_actual_response(jsonify({
        "active": True,
        "session_id": session_id,
        "hourly_pay": float(session_data["hourly_pay"]),
        "start_time": session_data["start_time"],
        "elapsed_seconds": elapsed_seconds,
        "current_earnings": elapsed_seconds * float(session_data["hourly_pay"]) / 3600
    }))

@app.route('/timer/history', methods=['GET', 'OPTIONS'])
def get_history():
    """Get timer history."""
    if request.method == 'OPTIONS':
        return _build_cors_preflight_response()
    
    session_keys = redis_client.keys("session:*")
    history = []
    
    for key in session_keys:
        session_data = redis_client.hgetall(key)
        if session_data.get("active") == "false":
            history.append({
                "session_id": key.split(":")[1],
                "start_time": session_data["start_time"],
                "end_time": session_data["end_time"],
                "hourly_pay": float(session_data["hourly_pay"]),
                "total_pay": float(session_data["total_pay"])
            })
    
    history.sort(key=lambda x: x["end_time"], reverse=True)
    return _corsify_actual_response(jsonify(history))

def _build_cors_preflight_response():
    response = jsonify({"status": "preflight"})
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "*")
    response.headers.add("Access-Control-Allow-Methods", "*")
    return response

def _corsify_actual_response(response):
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)