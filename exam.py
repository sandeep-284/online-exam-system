from flask import Flask, request, jsonify, render_template
import sqlite3
import os
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
DB_FILE = 'exam_system.db'

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    
    # Create Users Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL
        )
    ''')
    
    # Create Questions Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_text TEXT NOT NULL,
            opt_a TEXT NOT NULL,
            opt_b TEXT NOT NULL,
            opt_c TEXT NOT NULL,
            opt_d TEXT NOT NULL,
            correct_opt TEXT NOT NULL
        )
    ''')
    
    # Create Results Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            score INTEGER,
            total INTEGER,
            remarks TEXT DEFAULT '',
            FOREIGN KEY(student_id) REFERENCES users(id)
        )
    ''')
    
    # Create default admin if not exists
    c.execute("SELECT * FROM users WHERE username = 'admin'")
    if not c.fetchone():
        hashed_pw = generate_password_hash('admin123')
        c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", 
                  ('admin', hashed_pw, 'admin'))
        
    conn.commit()
    conn.close()

# Initialize DB on startup
init_db()

# --- ROUTES ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/auth', methods=['POST'])
def auth():
    data = request.json
    action = data.get('action')
    username = data.get('username')
    password = data.get('password')
    
    conn = get_db()
    c = conn.cursor()
    
    if action == 'register':
        # Only students register via the UI
        try:
            hashed_pw = generate_password_hash(password)
            c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", 
                      (username, hashed_pw, 'student'))
            conn.commit()
            return jsonify({'success': True, 'message': 'Registration successful! You can now log in.'})
        except sqlite3.IntegrityError:
            return jsonify({'success': False, 'message': 'Username already exists.'})
        finally:
            conn.close()
            
    elif action == 'login':
        c.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = c.fetchone()
        conn.close()
        
        if user and check_password_hash(user['password'], password):
            return jsonify({
                'success': True, 
                'user': {'id': user['id'], 'username': user['username'], 'role': user['role']}
            })
        else:
            return jsonify({'success': False, 'message': 'Invalid username or password.'})

@app.route('/api/questions', methods=['GET', 'POST'])
def handle_questions():
    conn = get_db()
    c = conn.cursor()
    
    if request.method == 'GET':
        c.execute("SELECT * FROM questions")
        questions = [dict(row) for row in c.fetchall()]
        # Strip correct options if requested by a student (security best practice)
        role = request.args.get('role')
        if role == 'student':
            for q in questions:
                q.pop('correct_opt', None)
        conn.close()
        return jsonify(questions)
        
    elif request.method == 'POST':
        data = request.json
        c.execute('''
            INSERT INTO questions (question_text, opt_a, opt_b, opt_c, opt_d, correct_opt)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (data['question_text'], data['opt_a'], data['opt_b'], data['opt_c'], data['opt_d'], data['correct_opt']))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': 'Question added successfully.'})

@app.route('/api/exam/submit', methods=['POST'])
def submit_exam():
    data = request.json
    student_id = data.get('student_id')
    answers = data.get('answers') # Format: {"question_id": "A", ...}
    
    conn = get_db()
    c = conn.cursor()
    
    # Calculate score securely on the backend
    c.execute("SELECT id, correct_opt FROM questions")
    correct_answers = {str(row['id']): row['correct_opt'] for row in c.fetchall()}
    
    total = len(correct_answers)
    score = 0
    
    for q_id, ans in answers.items():
        if q_id in correct_answers and correct_answers[q_id] == ans:
            score += 1
            
    # Save result
    c.execute("INSERT INTO results (student_id, score, total) VALUES (?, ?, ?)", 
              (student_id, score, total))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'score': score, 'total': total})

@app.route('/api/results', methods=['GET'])
def get_results():
    role = request.args.get('role')
    student_id = request.args.get('student_id')
    
    conn = get_db()
    c = conn.cursor()
    
    if role == 'admin':
        c.execute('''
            SELECT r.id, r.score, r.total, r.remarks, u.username as student_name 
            FROM results r
            JOIN users u ON r.student_id = u.id
            ORDER BY r.id DESC
        ''')
    else:
        c.execute('''
            SELECT score, total, remarks 
            FROM results 
            WHERE student_id = ?
            ORDER BY id DESC
        ''', (student_id,))
        
    results = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(results)

@app.route('/api/leaderboard', methods=['GET'])
def get_leaderboard():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT u.username as student_name,
               COUNT(r.id) as attempts,
               MAX(CAST(r.score AS REAL) / r.total * 100) as best_pct,
               AVG(CAST(r.score AS REAL) / r.total * 100) as avg_pct,
               MAX(r.score) as best_score,
               MAX(r.total) as total_questions
        FROM results r
        JOIN users u ON r.student_id = u.id
        GROUP BY r.student_id, u.username
        ORDER BY best_pct DESC, avg_pct DESC
    ''')
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(rows)

@app.route('/api/results/<int:result_id>/remark', methods=['POST'])
def add_remark(result_id):
    data = request.json
    remark = data.get('remark')
    
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE results SET remarks = ? WHERE id = ?", (remark, result_id))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': 'Remark updated successfully.'})

if __name__ == '__main__':
    app.run(debug=True, port=5000)