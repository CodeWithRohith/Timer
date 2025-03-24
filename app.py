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
        "status": "success",
        "session_id": session_id,
        "hourly_pay": hourly_pay
    }))

@app.route('/timer/stop/<session_id>', methods=['POST', 'OPTIONS'])
def stop_timer(session_id):
    """Stop an active timer session."""
    if request.method == 'OPTIONS':
        return _build_cors_preflight_response()
    
    session_key = f"session:{session_id}"
    if not redis_client.exists(session_key):
        return jsonify({"error": "Session not found"}), 404
        
    session_data = redis_client.hgetall(session_key)
    start_time = datetime.fromisoformat(session_data["start_time"])
    end_time = datetime.utcnow()
    elapsed_seconds = (end_time - start_time).total_seconds()
    total_pay = elapsed_seconds * float(session_data["hourly_pay"]) / 3600

    redis_client.hset(session_key, "end_time", end_time.isoformat())
    redis_client.hset(session_key, "total_pay", total_pay)
    redis_client.hset(session_key, "active", "false")
    redis_client.srem("active_sessions", session_id)
    
    return _corsify_actual_response(jsonify({
        "status": "success",
        "session_id": session_id,
        "total_pay": round(total_pay, 2),
        "elapsed_seconds": elapsed_seconds
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

@app.route('/admin/clear_sessions', methods=['POST'])
def clear_sessions():
    """Admin endpoint to clear all sessions (for testing only)"""
    # Add basic security (optional but recommended)
    auth = request.headers.get('Password')
    if auth != 'rohith':
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        # Get all session keys
        session_keys = redis_client.keys("session:*")
        active_sessions = redis_client.smembers("active_sessions")
        
        # Delete all sessions
        for key in session_keys:
            redis_client.delete(key)
        
        # Clear active sessions set
        redis_client.delete("active_sessions")
        
        # Reset counters (optional)
        redis_client.set("session_counter", 0)
        
        return jsonify({
            "status": "success",
            "deleted_sessions": len(session_keys),
            "active_sessions_cleared": len(active_sessions)
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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