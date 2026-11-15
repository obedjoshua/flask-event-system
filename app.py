from flask import Flask, render_template, request, redirect, url_for, flash, session
import sqlite3
import functools
import os
import hashlib
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "event_system_secret_key_prod"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "event_system.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")

def get_db():
    db_exists = os.path.exists(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    
    if not db_exists:
        with open(SCHEMA_PATH, "r") as f:
            conn.executescript(f.read())
        conn.execute(
            "INSERT OR IGNORE INTO users (username, password, role) VALUES (?, ?, ?)",
            ("admin", "admin123", "Admin")
        )
        conn.commit()
    return conn

def admin_required(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("is_admin"):
            flash("Admin login required to access that section.", "error")
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated_function

# Minimum Allowed Date Generator (Today + 2 Days)
def get_min_allowed_date():
    return (datetime.now() + timedelta(days=2)).strftime('%Y-%m-%d')

# 1. Main Dashboard & Events Page
@app.route("/", methods=["GET", "POST"])
@app.route("/events", methods=["GET", "POST"])
def events():
    conn = get_db()
    min_date = get_min_allowed_date()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        event_date = request.form.get("event_date", "").strip()
        venue = request.form.get("venue", "").strip()
        capacity = request.form.get("capacity", "").strip()
        host_id = request.form.get("host_id") or None

        if not (title and event_date and venue and capacity):
            flash("Please fill in all required fields.", "error")
        else:
            try:
                cap_int = int(capacity)
                if event_date < min_date:
                    flash(f"Event date must start at least 2 days from today ({min_date}).", "error")
                elif cap_int <= 0:
                    flash("Capacity must be greater than zero.", "error")
                else:
                    conn.execute(
                        "INSERT INTO events (title, event_date, venue, capacity, host_id) VALUES (?, ?, ?, ?, ?)",
                        (title, event_date, venue, cap_int, host_id)
                    )
                    conn.commit()
                    flash("Event created successfully!", "success")
                    return redirect(url_for("events"))
            except ValueError:
                flash("Capacity must be a valid number.", "error")

    events_list = conn.execute("""
        SELECT e.*, u.username AS host_name, COUNT(r.registration_id) AS total_registered
        FROM events e
        LEFT JOIN users u ON e.host_id = u.user_id
        LEFT JOIN registrations r ON e.event_id = r.event_id
        GROUP BY e.event_id
        ORDER BY e.event_date ASC
    """).fetchall()

    hosts_list = conn.execute("SELECT user_id, username FROM users WHERE role = 'Host'").fetchall()
    conn.close()
    return render_template("events.html", events=events_list, hosts=hosts_list, min_date=min_date, active_page="events")

# 2. Secret Admin Gateway Login Portal
@app.route("/secret-gateway-login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE username = ? AND password = ? AND role = 'Admin'",
            (username, password)
        ).fetchone()
        conn.close()

        if user:
            session["is_admin"] = True
            session["username"] = user["username"]
            flash("Logged in as Admin.", "success")
            return redirect(url_for("admin"))
        else:
            flash("Invalid admin credentials.", "error")

    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    session.pop("username", None)
    flash("Admin logged out.", "success")
    return redirect(url_for("events"))

# 3. Protected Admin Console
@app.route("/admin", methods=["GET", "POST"])
@admin_required
def admin():
    conn = get_db()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "create_user":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "").strip()
            role = request.form.get("role")

            if not (username and password and role):
                flash("All fields are required.", "error")
            else:
                try:
                    conn.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", (username, password, role))
                    conn.commit()
                    flash(f"Account '{username}' created successfully!", "success")
                except sqlite3.IntegrityError:
                    flash("Username already exists.", "error")

        elif action == "delete_user":
            user_id = request.form.get("user_id")
            conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            conn.commit()
            flash("User account removed.", "success")
            
        return redirect(url_for("admin"))

    users_list = conn.execute("""
        SELECT u.user_id, u.username, u.role, COUNT(e.event_id) AS assigned_event_count
        FROM users u
        LEFT JOIN events e ON u.user_id = e.host_id
        GROUP BY u.user_id
        ORDER BY u.role ASC
    """).fetchall()
    
    events_list = conn.execute("SELECT * FROM events").fetchall()
    conn.close()
    return render_template("admin.html", users_list=users_list, events_list=events_list, active_page="admin")

# 4. Single Event Management & Unregistration
@app.route("/events/<int:event_id>", methods=["GET", "POST"])
def event_detail(event_id):
    conn = get_db()
    event = conn.execute("SELECT e.*, u.username as host_name FROM events e LEFT JOIN users u ON e.host_id = u.user_id WHERE e.event_id = ?", (event_id,)).fetchone()
    min_date = get_min_allowed_date()

    if not event:
        conn.close()
        flash("Event not found.", "error")
        return redirect(url_for("events"))

    if request.method == "POST":
        action = request.form.get("action")
        if action == "update":
            title = request.form.get("title", "").strip()
            event_date = request.form.get("event_date", "").strip()
            venue = request.form.get("venue", "").strip()
            capacity = request.form.get("capacity", "").strip()
            host_id = request.form.get("host_id") or None

            try:
                cap_int = int(capacity)
                reg_count = conn.execute("SELECT COUNT(*) FROM registrations WHERE event_id = ?", (event_id,)).fetchone()[0]

                if cap_int < reg_count:
                    flash(f"Capacity cannot be lower than current registrations ({reg_count}).", "error")
                else:
                    conn.execute("UPDATE events SET title=?, event_date=?, venue=?, capacity=?, host_id=? WHERE event_id=?",
                                 (title, event_date, venue, cap_int, host_id, event_id))
                    conn.commit()
                    flash("Event updated successfully!", "success")
            except ValueError:
                flash("Invalid capacity.", "error")
            return redirect(url_for("event_detail", event_id=event_id))

        elif action == "delete":
            conn.execute("DELETE FROM events WHERE event_id = ?", (event_id,))
            conn.commit()
            conn.close()
            flash("Event removed.", "success")
            return redirect(url_for("events"))

    participants = conn.execute("""
        SELECT p.participant_id, p.name, p.contact, r.attendance_status, r.qr_code, r.registration_id
        FROM participants p
        JOIN registrations r ON p.participant_id = r.participant_id
        WHERE r.event_id = ?
    """, (event_id,)).fetchall()

    hosts_list = conn.execute("SELECT user_id, username FROM users WHERE role = 'Host'").fetchall()
    conn.close()
    return render_template("event_detail.html", event=event, participants=participants, hosts=hosts_list, min_date=min_date, active_page="events")

# 5. Unregister Action Route
@app.route("/unregister/<int:registration_id>", methods=["POST"])
def unregister_participant(registration_id):
    conn = get_db()
    reg = conn.execute("SELECT event_id, participant_id FROM registrations WHERE registration_id = ?", (registration_id,)).fetchone()
    if reg:
        conn.execute("DELETE FROM registrations WHERE registration_id = ?", (registration_id,))
        conn.commit()
        flash("Participant successfully unregistered from event.", "success")
        redirect_target = request.referrer or url_for("events")
        conn.close()
        return redirect(redirect_target)
    conn.close()
    flash("Registration record not found.", "error")
    return redirect(url_for("events"))

# 6. Register Participant & Unique QR Generation
@app.route("/register", methods=["GET", "POST"])
def register():
    conn = get_db()
    events_list = conn.execute("SELECT * FROM events").fetchall()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        contact = request.form.get("contact", "").strip()
        event_id = request.form.get("event_id")

        if not (name and contact and event_id):
            flash("Please complete all registration fields.", "error")
        else:
            try:
                cursor = conn.cursor()
                cursor.execute("BEGIN TRANSACTION;")

                event = cursor.execute("SELECT capacity FROM events WHERE event_id = ?", (event_id,)).fetchone()
                reg_count = cursor.execute("SELECT COUNT(*) FROM registrations WHERE event_id = ?", (event_id,)).fetchone()[0]

                if reg_count >= event["capacity"]:
                    flash("Registration closed: Event has reached full capacity.", "error")
                    conn.rollback()
                else:
                    participant = cursor.execute("SELECT participant_id FROM participants WHERE contact = ?", (contact,)).fetchone()

                    if participant:
                        participant_id = participant["participant_id"]
                    else:
                        cursor.execute("INSERT INTO participants (name, contact) VALUES (?, ?)", (name, contact))
                        participant_id = cursor.lastrowid

                    existing_reg = cursor.execute(
                        "SELECT registration_id FROM registrations WHERE event_id = ? AND participant_id = ?",
                        (event_id, participant_id)
                    ).fetchone()

                    if existing_reg:
                        flash("Participant is already registered for this event.", "error")
                        conn.rollback()
                    else:
                        # Generate unique QR token per attendant & event
                        raw_hash = f"EVT{event_id}-USR{participant_id}-{datetime.now().timestamp()}"
                        qr_token = "QR-" + hashlib.md5(raw_hash.encode()).hexdigest()[:12].upper()

                        cursor.execute(
                            "INSERT INTO registrations (event_id, participant_id, attendance_status, qr_code) VALUES (?, ?, 'Absent', ?)",
                            (event_id, participant_id, qr_token)
                        )
                        conn.commit()
                        flash("Participant registered successfully!", "success")
                        return redirect(url_for("register"))

            except sqlite3.Error as e:
                conn.rollback()
                flash(f"Database error: {e}", "error")

    conn.close()
    return render_template("register.html", events=events_list, active_page="register")

# 7. Attendance Marking
@app.route("/attendance", methods=["GET", "POST"])
def attendance():
    conn = get_db()
    selected_event_id = request.args.get("event_id", type=int)

    if request.method == "POST":
        event_id = request.form.get("event_id")
        for item in request.form:
            if item.startswith("status_"):
                participant_id = item.split("_")[1]
                status_val = request.form[item]
                conn.execute("UPDATE registrations SET attendance_status = ? WHERE event_id = ? AND participant_id = ?",
                             (status_val, event_id, participant_id))
        
        conn.commit()
        flash("Attendance statuses saved!", "success")
        return redirect(url_for("attendance", event_id=event_id))

    events_list = conn.execute("SELECT * FROM events").fetchall()
    participants = []
    if selected_event_id:
        participants = conn.execute("""
            SELECT p.participant_id, p.name, p.contact, r.attendance_status, r.qr_code
            FROM participants p
            JOIN registrations r ON p.participant_id = r.participant_id
            WHERE r.event_id = ?
        """, (selected_event_id,)).fetchall()

    conn.close()
    return render_template("attendance.html", events=events_list, participants=participants, selected_event_id=selected_event_id, active_page="attendance")

# 8. User Directory & Individual User Expandable Page Route
@app.route("/directory")
def directory():
    conn = get_db()
    participants_list = conn.execute("""
        SELECT p.participant_id, p.name, p.contact,
               COUNT(r.registration_id) AS events_registered,
               SUM(CASE WHEN r.attendance_status = 'Present' THEN 1 ELSE 0 END) AS events_attended
        FROM participants p
        LEFT JOIN registrations r ON p.participant_id = r.participant_id
        GROUP BY p.participant_id
        ORDER BY p.name ASC
    """).fetchall()
    conn.close()
    return render_template("user.html", participants_list=participants_list, active_page="directory")

@app.route("/user/<int:participant_id>")
def user_detail(participant_id):
    conn = get_db()
    participant = conn.execute("SELECT * FROM participants WHERE participant_id = ?", (participant_id,)).fetchone()
    
    if not participant:
        conn.close()
        flash("User not found.", "error")
        return redirect(url_for("directory"))

    registered_events = conn.execute("""
        SELECT e.event_id, e.title, e.event_date, e.venue, e.capacity,
               u.username AS host_name, r.attendance_status, r.qr_code, r.registration_id
        FROM registrations r
        JOIN events e ON r.event_id = e.event_id
        LEFT JOIN users u ON e.host_id = u.user_id
        WHERE r.participant_id = ?
        ORDER BY e.event_date ASC
    """, (participant_id,)).fetchall()

    conn.close()
    return render_template("user_detail.html", participant=participant, events=registered_events, active_page="directory")

# 9. Summary Analytics
@app.route("/summary")
def summary():
    conn = get_db()
    summary_data = conn.execute("""
        SELECT 
            e.event_id, e.title, e.event_date, e.capacity,
            COUNT(r.registration_id) AS total_registered,
            SUM(CASE WHEN r.attendance_status = 'Present' THEN 1 ELSE 0 END) AS total_present,
            SUM(CASE WHEN r.attendance_status = 'Absent' THEN 1 ELSE 0 END) AS total_absent
        FROM events e
        LEFT JOIN registrations r ON e.event_id = r.event_id
        GROUP BY e.event_id
        ORDER BY e.event_date DESC
    """).fetchall()

    total_events = len(summary_data)
    total_registrations = sum(item["total_registered"] for item in summary_data)
    total_present = sum(item["total_present"] for item in summary_data)
    total_capacity = sum(item["capacity"] for item in summary_data)
    
    turnout_rate = round((total_present / total_registrations * 100), 1) if total_registrations > 0 else 0
    capacity_usage = round((total_registrations / total_capacity * 100), 1) if total_capacity > 0 else 0

    recent_activity = conn.execute("""
        SELECT p.name AS participant_name, e.title AS event_title, r.attendance_status
        FROM registrations r
        JOIN participants p ON r.participant_id = p.participant_id
        JOIN events e ON r.event_id = e.event_id
        ORDER BY r.registration_id DESC LIMIT 6
    """).fetchall()

    conn.close()
    return render_template("summary.html", summary=summary_data, total_events=total_events,
                           total_registrations=total_registrations, total_present=total_present,
                           turnout_rate=turnout_rate, capacity_usage=capacity_usage,
                           recent_activity=recent_activity, active_page="summary")

if __name__ == "__main__":
    app.run(debug=True, port=5050)