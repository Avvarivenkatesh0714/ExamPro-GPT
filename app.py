from flask import Flask, render_template, request, redirect, url_for, session, flash, Response
import sqlite3
import os
import openai
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from fpdf import FPDF
from flask import send_file
import io

# Load environment variables from .env
load_dotenv()

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# Setup OpenAI client for OpenRouter
client = openai.OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)

# Set your referer (required by OpenRouter)
HTTP_REFERER = os.getenv("HTTP_REFERER")

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'docx'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def init_db():
    with sqlite3.connect("users.db") as con:
        cur = con.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT
        )""")
        cur.execute("""CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            question TEXT,
            answer TEXT
        )""")
        con.commit()

@app.route('/')
def entry():
    return render_template('entry.html')

@app.route('/document')
def document():
    return render_template('document.html')

@app.route('/index')
def index():
    return render_template('index.html')
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        con = sqlite3.connect('users.db')
        cur = con.cursor()
        cur.execute("SELECT * FROM users WHERE username=? AND password=?", (username, password))
        user = cur.fetchone()
        if user:
            session['username'] = username
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid login details', 'error')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        con = sqlite3.connect('users.db')
        cur = con.cursor()
        try:
            cur.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
            con.commit()
            session['username'] = username
            return redirect(url_for('dashboard'))
        except sqlite3.IntegrityError:
            flash("Username already taken", "error")
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))

    answer = ""
    if request.method == 'POST':
        question = request.form.get('question')
        exam = request.form.get('exam')
        action = request.form.get('action')  # 'answer', 'summarize', or 'keywords'

        if question:
            # Add exam context to prompt
            exam_prefix = f"This is a question from the {exam}. " if exam else ""

            # Decide prompt based on action
            if action == "keywords":
                prompt = exam_prefix + question + " Extract keywords."
            elif action == "summarize":
                prompt = exam_prefix + question + " Summarize this content."
            elif action == "solution":
                prompt = exam_prefix + question + " Give the solution."
            elif action == "hint":
                prompt = exam_prefix + question + " Give only hint got the question."  
            elif action == "concept":
                prompt = exam_prefix + question + " Explain the whole concept behind this."
            elif action == "translate":
                prompt = exam_prefix + question + " Translate this."  
            elif action == "questions":
                prompt = exam_prefix + question + " Analyse the content and generate the questions."
            elif action == "tips":
                prompt = exam_prefix + question + " give the tips for me to boost."
            elif action == "shortnotes":
                prompt = exam_prefix + question + " give the short notes of this content."
            else:
                prompt = exam_prefix + question  # Default: get answer

            try:
                # Call OpenAI
                response = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[{"role": "user", "content": prompt}],
                    extra_headers={
                        "HTTP-Referer": HTTP_REFERER,
                        "X-Title": "Student Chat App"
                    }
                )
                answer = response.choices[0].message.content.strip()

                # ✅ Save only original question (not modified prompt)
                con = sqlite3.connect('users.db')
                cur = con.cursor()
                cur.execute("INSERT INTO history (username, question, answer) VALUES (?, ?, ?)",
                            (session['username'], question, answer))
                con.commit()
                con.close()
            except Exception as e:
                flash(f"Error: {str(e)}", "error")

        elif 'file' in request.files:
            uploaded_file = request.files['file']
            if uploaded_file and allowed_file(uploaded_file.filename):
                filename = secure_filename(uploaded_file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                uploaded_file.save(filepath)
                flash(f"Uploaded file: {filename}", "success")
            else:
                flash("Unsupported file type", "error")

    return render_template('dashboard.html', answer=answer)

@app.route('/download_history')
def download_history():
    if 'username' not in session:
        return redirect(url_for('login'))

    con = sqlite3.connect('users.db')
    cur = con.cursor()
    cur.execute("SELECT question, answer FROM history WHERE username=?", (session['username'],))
    records = cur.fetchall()
    con.close()

    if not records:
        return "No history found for this user."

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.set_auto_page_break(auto=True, margin=15)

    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, f"{session['username']}'s Q&A History", ln=True, align='C')
    pdf.ln(10)

    pdf.set_font("Arial", size=12)
    for i, (question, answer) in enumerate(records, start=1):
        pdf.multi_cell(0, 10, f"Q{i}: {question}")
        pdf.multi_cell(0, 10, f"A{i}: {answer}")
        pdf.ln(5)

    # Save to string, then encode to bytes
    pdf_output = io.BytesIO()
    pdf_bytes = pdf.output(dest='S').encode('latin1')  # Get PDF as string and encode
    pdf_output.write(pdf_bytes)
    pdf_output.seek(0)

    return send_file(
        pdf_output,
        as_attachment=True,
        download_name="history.pdf",
        mimetype="application/pdf"
    )
    
@app.route('/history')
def history():
    if 'username' not in session:
        return redirect(url_for('login'))

    con = sqlite3.connect('users.db')
    cur = con.cursor()
    cur.execute("SELECT id, question, answer FROM history WHERE username=? ORDER BY id DESC LIMIT 10", 
                (session['username'],))
    records = cur.fetchall()
    con.close()

    return render_template('history.html', records=records)

# Route to delete individual history record
@app.route('/delete_record/<int:record_id>', methods=['POST'])
def delete_record(record_id):
    if 'username' not in session:
        return redirect(url_for('login'))

    con = sqlite3.connect('users.db')
    cur = con.cursor()
    cur.execute("DELETE FROM history WHERE id = ? AND username = ?", (record_id, session['username']))
    con.commit()
    con.close()
    return redirect(url_for('history'))

# Route to delete all history records for the user
@app.route('/delete_all_history', methods=['POST'])
def delete_all_history():
    if 'username' not in session:
        return redirect(url_for('login'))

    con = sqlite3.connect('users.db')
    cur = con.cursor()
    cur.execute("DELETE FROM history WHERE username = ?", (session['username'],))
    con.commit()
    con.close()
    return redirect(url_for('history'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
