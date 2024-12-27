import os
import threading
import time
import schedule

from cs50 import SQL
from flask import Flask, redirect, render_template, request, session, jsonify, flash, url_for, make_response, send_file
from flask_apscheduler import APScheduler
from apscheduler.jobstores.base import JobLookupError
from flask_session import Session
from datetime import datetime, timedelta
from werkzeug.security import check_password_hash, generate_password_hash
import google.generativeai as genai
import json
from googlesearch import search

from helpers import apology, login_required

app = Flask(__name__, static_folder='static')

app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
app.config["SECRET_KEY"] = '\xfd{H\xe5<\x95\xf9\xe3\x96.5\xd1\x01O<!\xd5\xa2\xa0\x9fR"\xa1\xa8'
app.config["SESSION_COOKIE_SECURE"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=1)
app.config["SESSION_COOKIE_NAME"] = "study_buddy_session"
app.config["TEMPLATES_AUTO_RELOAD"] = True
os.environ["GOOGLE_AI_API_KEY"] = "AIzaSyC275T6LYWYWc341V8diXQNk8HxFGjtEy0"

Session(app)

db = SQL("sqlite:///database.db")


class GeminiChatbot:
    def __init__(self, api_key):
        if not api_key:
            raise ValueError("No API key provided")

        try:
            genai.configure(api_key=api_key)

            models = [m.name for m in genai.list_models(
            ) if 'generateContent' in m.supported_generation_methods]
            if not models:
                raise ValueError("No suitable generative models found")

            self.model = genai.GenerativeModel('gemini-pro')
            self.chat = self.model.start_chat(history=[])
            self.STUDY_CONTEXT = """
    You are an AI study assistant named Mr.Mind. Your primary goals are to:
    - If you feel like students need a mentor or tutor/teacher you are to be that mentor/tutor/teacher
    - Help students understand complex topics and encourage and motivate them to solve problems on their own
    - Provide clear, concise explanations
    - Break down difficult concepts
    - Offer study tips and learning strategies
    - Maintain a friendly, encouraging tone, do not be monotonous show some emotion
    - Try to match the students slang and tone and emotion, but dont be cringe
    - Dont introduce yourself as a AI study assistant explicitly that makes the user feel like they're talking to a robot and makes them feel uncomfortable
    """

        except Exception as e:
            print(f"Chatbot initialization error: {e}")
            raise

    def generate_response(self, message):
        try:
            full_prompt = f"{self.STUDY_CONTEXT}\n\nUser Question: {message}"
            response = self.chat.send_message(full_prompt)
            return response.text
        except Exception as e:
            print(f"Response generation error: {e}")
            return f"Sorry, I couldn't process your message. Error: {str(e)}"


@app.route('/chatbot', methods=['POST'])
def chatbot_endpoint():
    try:
        api_key = os.getenv('GOOGLE_AI_API_KEY')
        if not api_key:
            return jsonify({
                'error': 'Google AI API key is not configured',
                'details': 'Missing GOOGLE_AI_API_KEY environment variable'
            }), 500

        data = request.get_json()
        if not data:
            return jsonify({
                'error': 'No JSON data received',
                'details': 'Request body is empty or not in JSON format'
            }), 400

        message = data.get('message')
        if not message:
            return jsonify({
                'error': 'No message provided',
                'details': 'Message field is missing or empty'
            }), 400

        try:
            chatbot = GeminiChatbot(api_key)
            response = chatbot.generate_response(message)
            return jsonify({'response': response})
        except Exception as chatbot_error:
            return jsonify({
                'error': 'Chatbot initialization failed',
                'details': str(chatbot_error)
            }), 500

    except Exception as e:
        return jsonify({
            'error': 'Unexpected server error',
            'details': str(e)
        }), 500


def cleanup_expired_events():
    try:
        current_utc_time = datetime.now()
        current_datetime = current_utc_time + timedelta(hours=5, minutes=30)

        expired_events = db.execute("""
            SELECT id, event_name, event_date, event_time, event_duration, all_day
            FROM events
        """)

        for event in expired_events:
            try:
                event_date = datetime.strptime(event['event_date'], "%Y-%m-%d")

                if event['all_day']:
                    if event_date.date() < current_datetime.date():
                        db.execute("DELETE FROM events WHERE id = ?", (event['id']))
                        print(f"Deleted all-day expired event: {event['event_name']}")
                        continue

                if not event['all_day']:
                    try:
                        event_time = datetime.strptime(event['event_time'], "%H:%M")
                        event_datetime = datetime.combine(event_date.date(), event_time.time())

                        event_end = event_datetime + timedelta(minutes=event['event_duration'])

                        print(f"Event: {event['event_name']}")
                        print(f"Event Start: {event_datetime}")
                        print(f"Event End: {event_end}")
                        print(f"Current Time: {current_datetime}")
                        print(f"Type of Current Time: {type(current_datetime)}")
                        print(f"Type of Event End: {type(event_end)}")
                        print(f"Expired: {event_end <= current_datetime}")

                        if event_end <= current_datetime:
                            db.execute("DELETE FROM events WHERE id = ?", (event['id'],))
                            print(f"Deleted expired or ongoing event: {event['event_name']}")

                    except Exception as time_error:
                        print(f"Time parsing error for event {event['id']}: {time_error}")

            except Exception as event_error:
                print(f"Error processing event {event['id']}: {event_error}")

    except Exception as e:
        print(f"Error in event cleanup: {e}")


def start_event_cleanup():
    def run_cleanup():
        schedule.every(2).seconds.do(cleanup_expired_events)

        while True:
            schedule.run_pending()
            time.sleep(1)

    cleanup_thread = threading.Thread(target=run_cleanup, daemon=True)
    cleanup_thread.start()


start_event_cleanup()


@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()


def gametimer(user_id):
    with app.app_context():
        gametime = db.execute("SELECT gametime FROM users WHERE id = ?", user_id)[0]["gametime"]

        gametime -= 1
        db.execute("UPDATE users SET gametime = ? WHERE id = ?", gametime, user_id)

        if gametime == 0:
            db.execute("UPDATE users SET game = NULL, gametime = 0 WHERE id = ?", user_id)
            try:
                scheduler.remove_job('game_timer')
            except JobLookupError:
                pass


@app.route("/", methods=["GET"])
@login_required
def index():
    user = db.execute("SELECT username FROM users WHERE id = ?", session["user_id"])
    cash = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])[0]["cash"]
    username = user[0]["username"] if user else "User"

    user_data = db.execute("SELECT game, gametime FROM users WHERE id = ?", session["user_id"])
    game = user_data[0]["game"]
    gametime = user_data[0]["gametime"]

    if game == 'Gorilla Game':
        return redirect(url_for('gorilla'))
    elif game == 'Aviator':
        return redirect(url_for('aviator'))
    elif game == 'Astray':
        return redirect(url_for('astray'))

    if game and gametime > 0:
        db.execute("UPDATE users SET gametime = ? WHERE id = ?",
                   gametime, session["user_id"])

        scheduler.add_job(
            id='game_timer',
            func=gametimer,
            args=(session["user_id"],),
            trigger='interval',
            seconds=1,
            replace_existing=True
        )
    else:
        db.execute("UPDATE users SET game = NULL, gametime = 0 WHERE id = ?", session["user_id"])
        session['game-over'] = '1'
        try:
            scheduler.remove_job('game_timer')
        except JobLookupError:
            pass

    tasks = db.execute(
        "SELECT task_id, text, completed, priority, timer FROM todo WHERE user_id = ? ORDER BY priority ASC, task_id ASC",
        session["user_id"]
    )

    return render_template("index.html", username=username, tasks=tasks, cash=cash, game=game, minutes=gametime)


@app.route("/game_state", methods=["GET"])
@login_required
def game_state():
    user_id = session["user_id"]
    user_data = db.execute("SELECT game, gametime FROM users WHERE id = ?", user_id)
    game = user_data[0]["game"]
    gametime = user_data[0]["gametime"]
    return jsonify({"game": game, "gametime": gametime})


@app.route("/game_over", methods=["GET"])
@login_required
def game_over():
    user_id = session["user_id"]
    db.execute("UPDATE users SET game = NULL AND gametime = 0 WHERE id = ?", user_id)
    return jsonify({"success": True})


@app.route("/add_task", methods=["POST"])
@login_required
def add_task():
    data = request.get_json()
    task_text = data.get('task')
    user_id = session["user_id"]
    priority = data.get('priority')
    timer = data.get('timer')  # Optional timer in minutes

    result = db.execute("SELECT MAX(task_id) as max_id FROM todo WHERE user_id = ?", user_id)
    next_task_id = (result[0]['max_id'] or 0) + 1

    # Update the insert statement to include timer
    db.execute(
        "INSERT INTO todo (user_id, task_id, text, completed, priority, timer) VALUES (?, ?, ?, ?, ?, ?)",
        user_id, next_task_id, task_text, False, priority, timer
    )

    return jsonify({"success": True, "task_id": next_task_id})


@app.route("/toggle_task", methods=["POST"])
@login_required
def toggle_task():
    data = request.get_json()
    task_id = data.get('task_id')
    is_timed_task = data.get('is_timed_task', False)
    priority = data.get('priority')

    if not task_id:
        return jsonify({"success": False, "error": "Task ID is required"}), 400

    try:
        if priority == 3:
            db.execute("UPDATE users SET cash = cash + 10 WHERE id = ?", session["user_id"])
        elif priority == 2:
            db.execute("UPDATE users SET cash = cash + 20 WHERE id = ?", session["user_id"])
        elif priority == 1:
            db.execute("UPDATE users SET cash = cash + 30 WHERE id = ?", session["user_id"])

        task_id = int(task_id)
        task = db.execute(
            "SELECT completed, priority, timer FROM todo WHERE user_id = ? AND task_id = ?",
            session["user_id"], task_id
        )
        if not task:
            return jsonify({"success": False, "error": "Task not found"}), 404

        new_completed = not task[0]["completed"]
        db.execute(
            "UPDATE todo SET completed = ?, completed_at = ? WHERE user_id = ? AND task_id = ?",
            new_completed, datetime.now() if new_completed else None, session["user_id"], task_id
        )
        return jsonify({"success": True})

    except Exception as e:
        print(f"Error toggling task: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/delete_task", methods=["POST"])
@login_required
def delete_task():
    data = request.get_json()
    task_id = data.get('task_id')
    user_id = session["user_id"]

    try:
        task_id = int(task_id)

        db.execute("DELETE FROM todo WHERE user_id = ? AND task_id = ?", user_id, task_id)
        return jsonify({"success": True})
    except ValueError:
        return jsonify({"success": False, "error": "Invalid task ID format"}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/login", methods=["GET", "POST"])
def login():

    session.clear()

    if request.method == "POST":
        if not request.form.get("username"):
            return apology("must provide username", 403)

        elif not request.form.get("password"):
            return apology("must provide password", 403)

        rows = db.execute(
            "SELECT * FROM users WHERE username = ?", request.form.get("username")
        )

        if len(rows) != 1 or not check_password_hash(
            rows[0]["hash"], request.form.get("password")
        ):
            return apology("invalid username and/or password", 403)

        session["user_id"] = rows[0]["id"]

        return redirect("/")
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.route("/change", methods=["GET", "POST"])
@login_required
def change():
    if request.method == "POST":
        opassword = request.form.get("opassword")
        if not opassword:
            return apology("must provide old password", 400)
        npassword = request.form.get("npassword")
        if not npassword:
            return apology("must provide new password", 400)
        if npassword == opassword:
            return apology("new password must be unique", 400)
        if npassword != request.form.get("ncpassword"):
            return apology("new password not confirmed", 400)
        if len(npassword) < 6:
            return apology("new password must be atleast 7 characters", 400)
        password = db.execute("SELECT hash FROM users WHERE id = ?", session["user_id"])
        if check_password_hash(password[0]["hash"], opassword) == False:
            return apology("must provide correct password for confirmation", 403)
        db.execute("UPDATE users SET hash = ? WHERE id = ?",
                   generate_password_hash(npassword), session["user_id"])
        return redirect("/")
    else:
        return render_template("change.html")


@app.route("/add_subnote", methods=["POST"])
@login_required
def add_subnote():
    parent_id = request.form.get("parent_id")
    subnote_title = request.form.get("subnote_title")
    subnote_content = request.form.get("subnote_content")

    if not parent_id or not subnote_title:
        return jsonify({"success": False, "error": "Parent ID and subnote title are required"}), 400

    parent = db.execute("""
        SELECT id FROM notes
        WHERE id = ? AND user_id = ? AND is_deleted = 0
    """, parent_id, session["user_id"])

    if not parent:
        return jsonify({"success": False, "error": "Parent page not found"}), 404

    subnote_id = db.execute("""
        INSERT INTO notes (user_id, title, content, parent_id)
        VALUES (?, ?, ?, ?)
    """, session["user_id"], subnote_title, subnote_content, parent_id)

    return jsonify({
        "success": True,
        "subnote": {
            "id": subnote_id,
            "title": subnote_title,
            "content": subnote_content
        }
    })


@app.route("/edit_book/<int:book_id>", methods=["GET", "POST"])
@login_required
def edit_book(book_id):
    if request.method == "POST":
        new_title = request.form.get("book_title")
        if not new_title:
            return apology("Book title is required", 400)

        db.execute("""
            UPDATE notes
            SET title = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ?
        """, new_title, book_id, session["user_id"])

        return redirect("/notes")

    book = db.execute("""
        SELECT * FROM notes
        WHERE id = ? AND user_id = ? AND parent_id IS NULL
    """, book_id, session["user_id"])

    if not book:
        return apology("Book not found", 404)

    return render_template("edit_book.html", book=book[0])


@app.route("/delete_book/<int:book_id>", methods=["POST"])
@login_required
def delete_book(book_id):
    db.execute("""
        UPDATE notes
        SET is_deleted = 1
        WHERE (id = ? OR parent_id = ? OR EXISTS (
            SELECT 1 FROM notes AS child
            WHERE child.parent_id = notes.id AND notes.parent_id = ?
        )) AND user_id = ?
    """, book_id, book_id, book_id, session["user_id"])

    return redirect("/notes")


@app.route("/edit_page/<int:page_id>", methods=["GET", "POST"])
@login_required
def edit_page(page_id):
    if request.method == "POST":
        new_title = request.form.get("page_title")
        if not new_title:
            return apology("Page title is required", 400)

        db.execute("""
            UPDATE notes
            SET title = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ?
        """, new_title, page_id, session["user_id"])

        book = db.execute("""
            SELECT parent_id FROM notes WHERE id = ?
        """, page_id)
        return redirect(f"/book/{book[0]['parent_id']}")

    page = db.execute("""
        SELECT n.*, parent.title as book_title
        FROM notes n
        JOIN notes parent ON n.parent_id = parent.id
        WHERE n.id = ? AND n.user_id = ?
    """, page_id, session["user_id"])

    if not page:
        return apology("Page not found", 404)

    return render_template("edit_page.html", page=page[0])


@app.route("/delete_page/<int:page_id>", methods=["POST"])
@login_required
def delete_page(page_id):
    book = db.execute("""
        SELECT parent_id FROM notes WHERE id = ? AND user_id = ?
    """, page_id, session["user_id"])

    if not book:
        return apology("Page not found", 404)

    db.execute("""
        UPDATE notes
        SET is_deleted = 1
        WHERE (id = ? OR parent_id = ?) AND user_id = ?
    """, page_id, page_id, session["user_id"])

    return redirect(f"/book/{book[0]['parent_id']}")


@app.route("/edit_subnote/<int:subnote_id>", methods=["POST"])
@login_required
def edit_subnote(subnote_id):
    title = request.form.get("subnote_title")
    content = request.form.get("subnote_content")

    if not title:
        return jsonify({"success": False, "error": "Subnote title is required"}), 400

    db.execute("""
        UPDATE notes
        SET title = ?, content = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND user_id = ?
    """, title, content, subnote_id, session["user_id"])

    return jsonify({
        "success": True,
        "subnote": {
            "id": subnote_id,
            "title": title,
            "content": content
        }
    })


@app.route("/delete_subnote/<int:subnote_id>", methods=["POST"])
@login_required
def delete_subnote(subnote_id):
    db.execute("""
        UPDATE notes
        SET is_deleted = 1
        WHERE id = ? AND user_id = ?
    """, subnote_id, session["user_id"])

    return jsonify({"success": True})


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == 'POST':
        username = request.form.get("username")
        if not username:
            return apology("must provide username", 400)
        check = db.execute("SELECT * FROM users WHERE username = ?;", username)
        if len(check) > 0:
            return apology("username taken", 400)
        password = request.form.get("password")
        if not password:
            return apology("must provide password", 400)
        if password != request.form.get("confirmation"):
            return apology("password not confirmed properly", 400)
        db.execute("INSERT INTO users (username, hash, cash) VALUES (?, ?, ?);",
                   username, generate_password_hash(password), 0)
        user_id = db.execute("SELECT id FROM users WHERE username = ?;", username)
        session["user_id"] = user_id[0]["id"]
        return redirect("/")
    else:
        return render_template("register.html")


@app.route("/notes", methods=["GET"])
@login_required
def notes():
    books = db.execute("""
        SELECT id, title
        FROM notes
        WHERE user_id = ? AND parent_id IS NULL AND is_deleted = 0
    """, session["user_id"])
    return render_template("notes.html", books=books)


@app.route("/create_book", methods=["POST"])
@login_required
def create_book():
    book_title = request.form.get("book_title")
    if not book_title:
        return apology("Book title is required", 400)

    existing_book = db.execute("""
        SELECT id FROM notes
        WHERE user_id = ? AND title = ? AND parent_id IS NULL AND is_deleted = 0
    """, session["user_id"], book_title)

    if existing_book:
        return apology("A book with this name already exists", 400)

    db.execute("""
        INSERT INTO notes (user_id, title, parent_id)
        VALUES (?, ?, NULL)
    """, session["user_id"], book_title)

    return redirect("/notes")


@app.route("/book/<int:book_id>", methods=["GET"])
@login_required
def view_book(book_id):
    book = db.execute("""
        SELECT * FROM notes
        WHERE id = ? AND user_id = ? AND is_deleted = 0
    """, book_id, session["user_id"])

    if not book:
        return apology("Book not found", 404)

    pages = db.execute("""
        SELECT id, title
        FROM notes
        WHERE parent_id = ? AND is_deleted = 0
    """, book_id)

    return render_template("book.html", book=book[0], pages=pages)


@app.route("/add_page", methods=["POST"])
@login_required
def add_page():
    book_id = request.form.get("book_id")
    page_title = request.form.get("page_title")

    if not book_id or not page_title:
        return apology("Book ID and page title are required", 400)

    book = db.execute("""
        SELECT id FROM notes
        WHERE id = ? AND user_id = ? AND is_deleted = 0
    """, book_id, session["user_id"])

    if not book:
        return apology("Book not found", 404)

    db.execute("""
        INSERT INTO notes (user_id, title, parent_id)
        VALUES (?, ?, ?)
    """, session["user_id"], page_title, book_id)

    return redirect(f"/book/{book_id}")


@app.route("/page/<int:page_id>", methods=["GET"])
@login_required
def view_page(page_id):
    page = db.execute("""
        SELECT n.*, parent.title as book_title
        FROM notes n
        JOIN notes parent ON n.parent_id = parent.id
        WHERE n.id = ? AND n.user_id = ? AND n.is_deleted = 0
    """, page_id, session["user_id"])

    if not page:
        return apology("Page not found", 404)

    subnotes = db.execute("""
        SELECT id, title, content
        FROM notes
        WHERE parent_id = ? AND is_deleted = 0
    """, page_id)

    return render_template("page.html", page=page[0], subnotes=subnotes)


@app.route("/save_page_content", methods=["POST"])
@login_required
def save_page_content():
    page_id = request.form.get("page_id")
    content = request.form.get("content")

    page = db.execute("""
        SELECT parent_id FROM notes
        WHERE id = ? AND user_id = ? AND is_deleted = 0
    """, page_id, session["user_id"])

    if not page:
        return apology("Page not found", 404)

    db.execute("""
        UPDATE notes
        SET content = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, content, page_id)

    return redirect(f"/book/{page[0]['parent_id']}")


@app.route("/add_event", methods=["GET", "POST"])
@login_required
def add_event():
    if request.method == "POST":
        event_name = request.form.get("event_name").strip()
        event_date = request.form.get("event_date")
        event_time = request.form.get("event_time", '')
        all_day = request.form.get("all_day") == "on"

        if all_day:
            event_time = "00:00"
            event_duration = 1440
        else:
            event_duration = request.form.get("event_duration")
            if not event_time:
                return apology("Time is required for non-all-day events", 400)

        if not event_name or not event_date or not event_duration:
            return apology("All fields are required", 400)

        existing_event = db.execute(
            "SELECT * FROM events WHERE user_id = ? AND event_name = ?",
            session["user_id"], event_name
        )

        if existing_event:
            return apology("An event with this name already exists. Please choose a different name.", 400)

        try:
            db.execute("""
                INSERT INTO events (user_id, event_name, event_date, event_time, event_duration, all_day)
                VALUES (?, ?, ?, ?, ?, ?)
            """, session["user_id"], event_name, event_date, event_time, int(event_duration), all_day)
            return redirect("/")
        except Exception as e:
            return apology(f"Error adding event: {str(e)}", 500)

    return render_template("add_event.html")


@app.route("/get_upcoming_events")
@login_required
def get_upcoming_events():
    current_datetime = datetime.now()

    upcoming_events = db.execute("""
        SELECT event_name, event_date, event_time, event_duration, all_day
        FROM events
        WHERE user_id = ?
        AND (
            (all_day = 1 AND event_date = ?) OR  # All-day events on current date
            (all_day = 0 AND (event_date > ? OR (event_date = ? AND event_time > ?)))  # Regular events
        )
        ORDER BY event_date, event_time
    """, session["user_id"],
        current_datetime.date(),
        current_datetime.date(),
        current_datetime.date(),
        current_datetime.time())

    return jsonify(upcoming_events)


@app.route("/delete_active_events", methods=["POST"])
@login_required
def delete_active_events():
    data = request.get_json()
    events = data.get('events', [])
    current_datetime = datetime.now()

    for event in events:
        db.execute("""
            DELETE FROM events
            WHERE user_id = ?
            AND event_name = ?
            AND event_date = ?
            AND event_time = ?
        """, session["user_id"], event['event_name'], event['event_date'], event['event_time'])

    return jsonify({"success": True})


@app.route('/google_search', methods=['POST'])
def google_search():
    try:
        query = request.json.get('query', '')
        if not query:
            return jsonify({'error': 'No query provided'}), 400

        search_results = []
        seen_links = set()

        for result in search(query, num_results=10, advanced=True):
            if result.url not in seen_links:
                search_results.append({
                    'title': result.title,
                    'link': result.url,
                    'description': result.description or 'No description avaiable'
                })

            if len(search_results) == 5:
                break

        return jsonify({'results': search_results})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/save_study_session', methods=['POST'])
@login_required
def save_study_session():
    data = request.get_json()
    user_id = session["user_id"]

    session_start = data.get("session_start")
    session_end = data.get("session_end")
    time_spent = data.get("time_spent")
    completed_tasks = data.get("completed_tasks", [])
    completed_notes = data.get("completed_notes", [])
    
    # Clean and process notes
    processed_notes = []
    for note in completed_notes:
        if note and note.strip():  # Check if note is not empty
            # Remove any potential NULL bytes or problematic characters
            cleaned_note = note.replace('\x00', '').strip()
            if cleaned_note:  # Only add if there's content after cleaning
                processed_notes.append(cleaned_note)
    
    # Join notes with delimiter, or use default message if no valid notes
    summarized_notes = "\n=====\n".join(processed_notes) if processed_notes else "No notes/summary available"

    if not session_start or not session_end or time_spent is None:
        return jsonify({"success": False, "error": "Missing session data"}), 400

    try:
        # Print debug information
        print("Saving session with data:")
        print(f"Start: {session_start}")
        print(f"End: {session_end}")
        print(f"Time: {time_spent}")
        print(f"Tasks: {json.dumps(completed_tasks)}")
        print(f"Notes: {summarized_notes[:100]}...")  # Print first 100 chars of notes

        db.execute("""
            INSERT INTO study_sessions 
            (user_id, session_start, session_end, time_spent, completed_tasks, summarized_notes)
            VALUES (?, ?, ?, ?, ?, ?)
        """, user_id, session_start, session_end, time_spent, json.dumps(completed_tasks), summarized_notes)
        
        return jsonify({"success": True})
    except Exception as e:
        print(f"Error in save_study_session: {str(e)}")
        print(f"Error type: {type(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/study_history", methods=["GET"])
@login_required
def study_history():
    try:
        user_id = session["user_id"]

        sessions = db.execute("""
            SELECT session_start, session_end, time_spent, completed_tasks, created_at, summarized_notes
            FROM study_sessions
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT 10
        """, user_id)

        # Calculate statistics
        total_sessions = len(sessions)
        total_time_seconds = sum(session['time_spent'] for session in sessions)
        total_hours = total_time_seconds // 3600
        total_minutes = (total_time_seconds % 3600) // 60

        # Count total tasks completed
        total_tasks_completed = 0
        formatted_sessions = []
        for session_data in sessions:
            try:
                session_start = datetime.strptime(
                    session_data["session_start"], "%Y-%m-%dT%H:%M:%S.%fZ") + timedelta(hours=5, minutes=30)
                session_end = datetime.strptime(
                    session_data["session_end"], "%Y-%m-%dT%H:%M:%S.%fZ") + timedelta(hours=5, minutes=30)

                session_data["session_start"] = session_start.strftime("%d-%m-%y %H:%M:%S")
                session_data["session_end"] = session_end.strftime("%d-%m-%y %H:%M:%S")

                # Parse completed tasks
                completed_tasks = (
                    json.loads(session_data["completed_tasks"]
                               ) if session_data["completed_tasks"] else []
                )
                session_data["completed_tasks"] = completed_tasks
                session_data["summarized_notes"] = session_data.get("summarized_notes", "No notes/summary available")
                total_tasks_completed += len(completed_tasks)
            except json.JSONDecodeError:
                session_data["completed_tasks"] = []
                session_data["summarized_notes"] = "No notes/summary available"

            formatted_sessions.append(session_data)

        purchases = db.execute("SELECT purchases FROM users WHERE id = ?",
                               session["user_id"])[0]['purchases']

        return render_template("study_history.html",
                               sessions=formatted_sessions,
                               total_sessions=total_sessions,
                               total_hours=total_hours,
                               total_minutes=total_minutes,
                               total_tasks_completed=total_tasks_completed,
                               purchases=purchases)
    except Exception as e:
        print(f"Error loading study history: {e}")
        return apology(f"Error loading study history: {str(e)}")


@login_required
@app.route("/store")
def store():
    return render_template("store.html")


@login_required
@app.route('/purchase_game', methods=['POST'])
def purchase_game():
    try:
        game = request.form.get('game')
        minutes = int(request.form.get('minutes'))

        if game == 'Crossy Road':
            rate = 35
        elif game == 'Flappy Bird':
            rate = 30
        elif game == 'Snake':
            rate = 25
        elif game == 'Gorilla Game':
            rate = 45
        elif game == 'Aviator':
            rate = 40
        elif game == 'Astray':
            rate = 40
        else:
            flash('Invalid game selected', 'error')
            return redirect(url_for('store'))

        spent = (rate / 10) * minutes

        user_cash = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])[0]['cash']
        if user_cash < spent:
            flash('Not enough money to purchase the game!', 'error')
            return redirect(url_for('store'))

        db.execute("UPDATE users SET cash = cash - ? WHERE id = ?", spent, session["user_id"])
        db.execute("UPDATE users SET game = ? WHERE id = ?", game, session["user_id"])
        db.execute("UPDATE users SET gametime = ? WHERE id = ?", minutes * 60, session["user_id"])
        db.execute("UPDATE users SET purchases = purchases + 1 WHERE id = ?", session["user_id"])

        return redirect(url_for('index'))
    except Exception as e:
        flash('An error occurred while purchasing the game', 'error')
        return redirect(url_for('store'))


@app.route("/gorilla")
def gorilla():
    user_data = db.execute("SELECT game, gametime FROM users WHERE id = ?", session["user_id"])
    gametime = user_data[0]["gametime"]
    if gametime == 0:
        return redirect("/")
    db.execute("UPDATE users SET gametime = ? WHERE id = ?",
               gametime, session["user_id"])
    scheduler.add_job(
        id='game_timer',
        func=gametimer,
        args=(session["user_id"],),
        trigger='interval',
        seconds=1,
        replace_existing=True
    )
    return render_template("gorillagame.html")


@app.route("/aviator")
def aviator():
    user_data = db.execute("SELECT game, gametime FROM users WHERE id = ?", session["user_id"])
    gametime = user_data[0]["gametime"]
    if gametime == 0:
        return redirect("/")
    db.execute("UPDATE users SET gametime = ? WHERE id = ?",
               gametime, session["user_id"])
    scheduler.add_job(
        id='game_timer',
        func=gametimer,
        args=(session["user_id"],),
        trigger='interval',
        seconds=1,
        replace_existing=True
    )
    return render_template("aviator.html")


@app.route("/astray")
def astray():
    user_data = db.execute("SELECT game, gametime FROM users WHERE id = ?", session["user_id"])
    gametime = user_data[0]["gametime"]
    if gametime == 0:
        return redirect("/")
    db.execute("UPDATE users SET gametime = ? WHERE id = ?",
               gametime, session["user_id"])
    scheduler.add_job(
        id='game_timer',
        func=gametimer,
        args=(session["user_id"],),
        trigger='interval',
        seconds=1,
        replace_existing=True
    )
    return render_template("astray.html")


class GeminiSummarizer:
    def __init__(self, api_key):
        if not api_key:
            raise ValueError("No API key provided")

        try:
            genai.configure(api_key=api_key)

            models = [m.name for m in genai.list_models()
                     if 'generateContent' in m.supported_generation_methods]
            if not models:
                raise ValueError("No suitable generative models found")

            self.model = genai.GenerativeModel('gemini-pro')
            self.chat = self.model.start_chat(history=[])
            self.SUMMARY_CONTEXT = """
            Don't hesitate to bold, italicize, put quotes around text and use text effects for emphasising and demarcating; to symbolise bold text surround it with **, e.g. **bold text**. To symbolise italic text surround it with /*, e.g. /*italic text/*. To symbolise a line break use \\n, e.g. this is a line break\\nthis goes on the next line. To symbolise bulletin points use a single * and a space after it, e.g. '* this is now a bullet point which contains some ** bold ** text and /*italic text/*'
            Feel free to write up to 200 words, but don’t hesitate to reach the limit if necessary.
            Give a relevant and informative heading for the summary, not just 'Summary of xyz'.
            Create a detailed and informative summary of the following text (remember to make the summary actually worth taking a look at).
            Focus on key points and important details.
            If the text is unintelligible or too short, respond with 'Text was unintelligible or too short, summary wasn't generated'.
            Don't write down the names for sections, e.g. if you're writing the heading dont start with 'Heading: ' and if you're writing the main body don't write 'Summary: '.
            """

        except Exception as e:
            print(f"Summarizer initialization error: {e}")
            raise

    def generate_summary(self, text):
        try:
            # Basic validation
            if not text or len(text.strip()) < 10:
                return "Summary was not generated"

            full_prompt = f"{self.SUMMARY_CONTEXT}\n\nText to summarize: {text}"
            response = self.chat.send_message(full_prompt)
            return response.text if response.text else "Summary was not generated"

        except Exception as e:
            print(f"Summary generation error: {e}")
            return "Summary was not generated"


@app.route('/summarize', methods=['POST'])
def summarize_endpoint():
    try:
        api_key = os.getenv('GOOGLE_AI_API_KEY')
        if not api_key:
            return jsonify({
                'error': 'Google AI API key is not configured',
                'details': 'Missing GOOGLE_AI_API_KEY environment variable'
            }), 500

        data = request.get_json()
        if not data or 'text' not in data:
            return jsonify({
                'error': 'No text provided',
                'details': 'Text field is missing in request body'
            }), 400

        text = data['text']
        summarizer = GeminiSummarizer(api_key)
        summary = summarizer.generate_summary(text)
        #print(summary)

        return jsonify({
            'summary': summary
        })

    except Exception as e:
        print(f"Summarization endpoint error: {e}")
        return jsonify({
            'error': 'Summarization failed',
            'details': str(e)
        }), 500
    