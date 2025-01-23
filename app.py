from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
from werkzeug.security import generate_password_hash, check_password_hash
import re
import sqlite3
import os
from werkzeug.utils import secure_filename
from io import StringIO, BytesIO
import csv
import json
import pandas as pd
import requests
import random
from calendar import month_name

app = Flask(__name__)
app.secret_key = 'This is the secret key for the project.'

# file uploads
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# SQLite database
db_file = 'users.db'

# email and password regex
EMAIL_REGEX = re.compile(r'^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$')
PASSWORD_REGEX = re.compile(r'(?=.*\d)(?=.*[a-z])(?=.*[A-Z])(?=.*[@$!%*?&.])[A-Za-z\d@$!%*?&]{8,}')

# weather API
WEATHER_API_URL = "https://api.openweathermap.org/data/2.5/weather"
WEATHER_API_KEY = "d56bbd18b9c3f34849ad8bb4a58c5083"


def init_db():
    # initiate database if it does not exist
    with sqlite3.connect(db_file) as conn:
        c = conn.cursor()

        # users table
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        ''')

        # houses table
        c.execute('''
            CREATE TABLE IF NOT EXISTS houses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                type_of_area TEXT NOT NULL,
                house_type TEXT NOT NULL,
                house_size TEXT NOT NULL,
                occupants TEXT NOT NULL,
                occupancy_patterns TEXT NOT NULL,
                insulation_level TEXT NOT NULL,
                solar_capacity REAL NOT NULL,
                location TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        ''')

        # energy data table
        c.execute('''
            CREATE TABLE IF NOT EXISTS energy_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                house_id INTEGER NOT NULL,
                file_id INTEGER,
                date TEXT,
                energy_consumption REAL,
                FOREIGN KEY(house_id) REFERENCES houses(id),
                FOREIGN KEY(file_id) REFERENCES uploaded_files(id)
            )
        ''')

        # uploaded files table
        c.execute('''
            CREATE TABLE IF NOT EXISTS uploaded_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                house_id INTEGER NOT NULL,
                filename TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(house_id) REFERENCES houses(id)
            )
        ''')

        conn.commit()

# initialize database
init_db()

@app.route('/')
def root():
    # redirect to dashboard if logged in
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # validate email
        if not EMAIL_REGEX.match(username):
            # send error if email is invalid and go back to registration page
            flash('Invalid email address. Please enter a valid email.', 'danger')
            return render_template('register.html')

        # validate password
        if not PASSWORD_REGEX.match(password):
            # send error if password is invalid and go back to registration page
            flash('Password must contain at least 8 characters, including uppercase, lowercase, number, and special character.', 'danger')
            return render_template('register.html')

        # hash the password
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')

        # save user to database
        with sqlite3.connect(db_file) as conn:
            c = conn.cursor()
            try:
                # save user and redirect to login page
                c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_password))
                conn.commit()
                return redirect(url_for('login'))
            except sqlite3.IntegrityError:
                # duplicate email send error message and redirects to registration page
                flash('Email already exists. Please choose a different one.', 'danger')
                return render_template('register.html')

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    # redirect to dashboard if user is already logged in
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # validate email format
        if not EMAIL_REGEX.match(username):
            # send error if email is invalid and go back to registration page
            flash('Invalid email address. Please enter a valid email.', 'danger')
            return render_template('login.html')

        # check credentials in database
        with sqlite3.connect(db_file) as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM users WHERE username = ?", (username,))
            user = c.fetchone()
            if user and check_password_hash(user[2], password):
                # store user info in session to be used later
                session['user_id'] = user[0]
                session['username'] = user[1]
                return redirect(url_for('dashboard'))
            else:
                # send error if username does not match passowrd or cannot be found in database
                flash('Invalid username or password.', 'danger')

    return render_template('login.html')

@app.route('/logout')
def logout():
    # clear session data
    session.pop('user_id', None)
    session.pop('username', None)

    return redirect(url_for('login'))

@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    # redirect to login page if user is not logged in
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']

    # fetch houses for the dropdown
    with sqlite3.connect(db_file) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM houses WHERE user_id = ?", (user_id,))
        houses = c.fetchall()

    # if no houses are found, render page without houses
    if not houses:
        return render_template('dashboard.html', houses=[], selected_house_id=None, energy_data=[])

    # selected house or default first house in database is none are selected
    selected_house_id = int(request.form['house_id']) if request.method == 'POST' else houses[0]['id']

    # fetch energy data for the selected house
    with sqlite3.connect(db_file) as conn:
        c = conn.cursor()
        c.execute('''
            SELECT date, energy_consumption 
            FROM energy_data 
            WHERE house_id = ? 
            ORDER BY date ASC
        ''', (selected_house_id,))
        energy_data = [{'date': row[0], 'energy_consumption': row[1]} for row in c.fetchall()]

    return render_template(
        'dashboard.html',
        houses=houses,
        selected_house_id=selected_house_id,
        energy_data=energy_data
    )

@app.route('/api/files/<int:house_id>', methods=['GET'])
def get_files(house_id):
    # redirect to login page if user is not logged in
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']

    # get files a specific house
    with sqlite3.connect(db_file) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('''
            SELECT uploaded_files.id, uploaded_files.filename
            FROM uploaded_files
            INNER JOIN houses ON houses.id = uploaded_files.house_id
            WHERE uploaded_files.house_id = ? AND houses.user_id = ?
        ''', (house_id, user_id))
        files = [{'id': row['id'], 'filename': row['filename']} for row in c.fetchall()]

    return {"files": files}, 200

@app.route('/visualize_data', methods=['GET', 'POST'])
def visualize_data():
    # redirect to login page if user is not logged in
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # filter options for dropdowns
    house_type = ["Detached", "Semi-detached", "Apartment"]
    area_type = ["Urban", "Suburban", "Rural"]
    house_size = ["0-50", "51-75", "76-100", "101-150", "151-200", "201-250", ">250"]
    insulation_level = ["None", "Low", "Medium", "High"]
    occupants = ["1-2", "3-4", "5+"]

    # features for energy data aggregation
    selectable_features = {
        "house_type": house_type,
        "area_type": area_type,
        "house_size": house_size,
        "insulation_level": insulation_level,
        "occupants": occupants,
    }

    # fetch selected filters
    selected_type = request.form.get('house_type', '')
    selected_area = request.form.get('type_of_area', '')
    selected_size = request.form.get('house_size', '')
    selected_occupants = request.form.get('occupants', '')
    selected_insulation = request.form.get('insulation_level', '')
    year_from = request.form.get('year_from', '')
    year_to = request.form.get('year_to', '')

    # fetch energy data with filters applied
    with sqlite3.connect(db_file) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        query = '''
            SELECT houses.name AS house_name, energy_data.date, energy_data.energy_consumption, 
            houses.house_type, houses.house_size, houses.occupants, houses.insulation_level,
            houses.solar_capacity, houses.type_of_area AS area_type
            FROM energy_data
            INNER JOIN houses ON houses.id = energy_data.house_id
        '''
        params = []
        filters = []

        # filters based on user input
        if selected_type:
            filters.append('houses.house_type = ?')
            params.append(selected_type)
        if selected_area:
            filters.append('houses.type_of_area = ?')
            params.append(selected_area)
        if selected_size:
            filters.append('houses.house_size = ?')
            params.append(selected_size)
        if selected_occupants:
            filters.append('houses.occupants = ?')
            params.append(selected_occupants)
        if selected_insulation:
            filters.append('houses.insulation_level = ?')
            params.append(selected_insulation)
        if year_from:
            filters.append('CAST(strftime("%Y", energy_data.date) AS INTEGER) >= ?')
            params.append(int(year_from))
        if year_to:
            filters.append('CAST(strftime("%Y", energy_data.date) AS INTEGER) <= ?')
            params.append(int(year_to))

        # add filters to the query
        if filters:
            query += " WHERE " + " AND ".join(filters)

        c.execute(query, params)
        data = c.fetchall()

    # data structures for aggregation
    energy_by_year = {}
    months_order = list(month_name[1:])
    energy_by_month = {month: 0 for month in month_name[1:]} 
    energy_by_feature = {feature: {category: {} for category in categories} for feature, categories in selectable_features.items()}

    # aggregate energy data
    for row in data:
        date = row['date']
        year = date[:4]
        month = month_name[int(date[5:7])] 

        energy_by_year[year] = energy_by_year.get(year, 0) + row['energy_consumption']
        energy_by_month[month] += row['energy_consumption']

        # aggregate by selected features
        for feature, categories in selectable_features.items():
            feature_value = row[feature]
            if feature_value in categories:
                # by year
                energy_by_feature[feature][feature_value].setdefault(year, 0)
                energy_by_feature[feature][feature_value][year] += row['energy_consumption']
                # by month
                energy_by_feature[feature][feature_value].setdefault(month, 0)
                energy_by_feature[feature][feature_value][month] += row['energy_consumption']

    return render_template(
        'visualize_data.html',
        energy_by_year=energy_by_year,
        energy_by_month=energy_by_month,
        energy_by_feature=energy_by_feature,
        selectable_features=list(selectable_features.keys()),
        house_type=house_type, 
        area_type=area_type, 
        house_size=house_size, 
        insulation_level=insulation_level,
        occupants=occupants,
        selected_type=selected_type,
        selected_area=selected_area,
        selected_size=selected_size,
        selected_occupants=selected_occupants,
        selected_insulation=selected_insulation,
        year_from=year_from,
        year_to=year_to
    )

@app.route('/upload_data', methods=['GET', 'POST'])
def upload():
    # redirect to login page if user is not logged in
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    error_messages = []

    # fetch houses
    with sqlite3.connect(db_file) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('SELECT * FROM houses WHERE user_id = ?', (session['user_id'],))
        houses = c.fetchall()

    # add energy datad to database
    if request.method == 'POST':
        house_id = request.form.get('house_id')
        datafile = request.files.get('datafile')

        # if no file uploaded send error message
        if not datafile:
            error_messages.append("Please select a file to upload.")
        else:
            # load the uploaded file
            if datafile.filename.endswith('.csv'):
                df = pd.read_csv(datafile)
            elif datafile.filename.endswith('.xlsx'):
                df = pd.read_excel(datafile)
            elif datafile.filename.endswith('.json'):
                df = pd.read_json(datafile)
            else:
                # error if file format is not supported
                error_messages.append("Unsupported file format. Please upload a CSV, Excel, or JSON file.")
                return render_template('upload.html', houses=houses, error_messages=error_messages)

            # validate required columns and send error if columns are missing or extra columns are added
            if 'date' not in df.columns or 'energy_consumption' not in df.columns:
                error_messages.append("The file must contain 'date' and 'energy_consumption' columns.")
                return render_template('upload.html', houses=houses, error_messages=error_messages)

            # make 'date' string format
            if not pd.api.types.is_string_dtype(df['date']):
                df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')

            # add data to database
            with sqlite3.connect(db_file) as conn:
                c = conn.cursor()
                c.execute('''
                    INSERT INTO uploaded_files (user_id, house_id, filename)
                    VALUES (?, ?, ?)
                ''', (session['user_id'], house_id, datafile.filename))
                file_id = c.lastrowid

                # insert energy data into the database
                for _, row in df.iterrows():
                    date = row['date']
                    energy_consumption = row['energy_consumption']
                    if pd.notnull(date) and pd.notnull(energy_consumption):
                        c.execute('''
                            INSERT INTO energy_data (house_id, file_id, date, energy_consumption)
                            VALUES (?, ?, ?, ?)
                        ''', (house_id, file_id, date, float(energy_consumption)))

                conn.commit()

        # show error messages
        if error_messages:
            return render_template('upload.html', houses=houses, error_messages=error_messages)

    return render_template('upload.html', houses=houses, error_messages=error_messages)

@app.route('/download', methods=['GET', 'POST'])
def download():
    # redirect to login page if user is not logged in
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    error_messages = []

    # filter options
    predefined_filters = {
        "house_types": ["Detached", "Semi-detached", "Apartment"],
        "area_types": ["Urban", "Suburban", "Rural"],
        "house_sizes": ["0-50", "51-75", "76-100", "101-150", "151-200", "201-250", ">250"],
        "insulation_levels": ["None", "Low", "Medium", "High"],
        "occupancy_patterns": ["Mostly home during the day", "Mostly away during the day"],
        "occupants": ["1-2", "3-4", "5+"]
    }

    # get input values from form
    if request.method == 'POST':
        # fetch filter values from form
        selected_filters = {
            "house_types": request.form.get('house_types', ''),
            "area_types": request.form.get('area_types', ''),
            "house_sizes": request.form.get('house_sizes', ''),
            "insulation_levels": request.form.get('insulation_levels', ''),
            "occupancy_patterns": request.form.get('occupancy_patterns', ''),
            "occupants": request.form.get('occupants', ''),
            "solar_capacity": request.form.get('solar_capacity', None),
            "include_all": request.form.get('include_all') == 'true',
            "file_format": request.form.get('file_format', 'csv')
        }

        # SQL query with filters
        query = '''
            SELECT houses.id AS house_id, houses.type_of_area, houses.house_size,
                   houses.house_type, houses.insulation_level, houses.occupants,
                   houses.occupancy_patterns, houses.solar_capacity, 
                   energy_data.date, energy_data.energy_consumption, houses.location
            FROM energy_data
            INNER JOIN houses ON energy_data.house_id = houses.id
        '''
        params = []
        if not selected_filters["include_all"]:
            query += " WHERE 1=1"
            if selected_filters["house_types"]:
                query += " AND houses.house_type = ?"
                params.append(selected_filters["house_types"])
            if selected_filters["area_types"]:
                query += " AND houses.type_of_area = ?"
                params.append(selected_filters["area_types"])
            if selected_filters["house_sizes"]:
                query += " AND houses.house_size = ?"
                params.append(selected_filters["house_sizes"])
            if selected_filters["insulation_levels"]:
                query += " AND houses.insulation_level = ?"
                params.append(selected_filters["insulation_levels"])
            if selected_filters["occupancy_patterns"]:
                query += " AND houses.occupancy_patterns = ?"
                params.append(selected_filters["occupancy_patterns"])
            if selected_filters["occupants"]:
                query += " AND houses.occupants = ?"
                params.append(selected_filters["occupants"])
            if selected_filters["solar_capacity"]:
                query += " AND houses.solar_capacity >= ?"
                params.append(float(selected_filters["solar_capacity"]))

       # query
        with sqlite3.connect(db_file) as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute(query, params)
            rows = c.fetchall()

        if not rows:
            error_messages.append('No data found for the selected filters.')
            return render_template('download.html', **predefined_filters, error_messages=error_messages)

        column_names = [
            'house_id', 'type_of_area', 'house_size', 'house_type', 
            'insulation_level', 'occupants', 'occupancy_patterns', 
            'solar_capacity', 'date', 'energy_consumption', 'location'
        ]

        df = pd.DataFrame(rows, columns=column_names)

        # rename columns
        column_mapping = {
            'house_id': 'Property ID',
            'type_of_area': 'Area type',
            'house_size': 'Property size',
            'house_type': 'Property type',
            'insulation_level': 'Insulation level',
            'occupants': 'Number of occupants',
            'occupancy_patterns': 'Occupancy pattern',
            'solar_capacity': 'Solar capacity',
            'date': 'Date',
            'energy_consumption': 'Energy consumption',
            'location': 'Location'
        }
        df.rename(columns=column_mapping, inplace=True)

        # weather data based on location
        def get_weather_data(location):
            url = f"{WEATHER_API_URL}?q={location}&appid={WEATHER_API_KEY}&units=metric"
            response = requests.get(url)
            if response.status_code == 200:
                weather = response.json()
                return {
                    'Precipitations': weather.get('rain', {}).get('1h', 0),
                    'UV Index': weather.get('current', {}).get('uvi', 0),
                    'Wind Speed': weather.get('wind', {}).get('speed', 0)
                }
            return {'Precipitations': None, 'UV Index': None, 'Wind Speed': None}

        # add weather data
        weather_data = []
        for location in df['Location']:
            weather = get_weather_data(location)
            weather_data.append(weather)

        weather_df = pd.DataFrame(weather_data)
        df = pd.concat([df, weather_df], axis=1)
        df.drop(columns=['Location'], inplace=True)

        # export selected format
        output = BytesIO()
        file_format = selected_filters["file_format"]

        if file_format == 'csv':
            df.to_csv(output, index=False)
            output.seek(0)
            return send_file(output, as_attachment=True, download_name='energy_data.csv', mimetype='text/csv')
        elif file_format == 'json':
            df.to_json(output, orient='records')
            output.seek(0)
            return send_file(output, as_attachment=True, download_name='energy_data.json', mimetype='application/json')
        elif file_format == 'excel':
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False)
            output.seek(0)
            return send_file(output, as_attachment=True, download_name='energy_data.xlsx',
                             mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    return render_template('download.html',
                           house_types=predefined_filters["house_types"],
                           area_types=predefined_filters["area_types"],
                           house_sizes=predefined_filters["house_sizes"],
                           insulation_levels=predefined_filters["insulation_levels"],
                           occupancy_patterns=predefined_filters["occupancy_patterns"],
                           occupants=predefined_filters["occupants"],
                           error_messages=error_messages)

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    # redirect to login page if user is not logged in
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']

    error_messages = []
    success_messages = []

    # fetch houses for the dropdown
    with sqlite3.connect(db_file) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT id, name FROM houses WHERE user_id = ?", (user_id,))
        houses = c.fetchall()

    # account deletion
    if request.method == 'POST':
        if 'delete_account' in request.form:
            with sqlite3.connect(db_file) as conn:
                c = conn.cursor()
                c.execute("DELETE FROM users WHERE id = ?", (user_id,))
                c.execute("DELETE FROM houses WHERE user_id = ?", (user_id,))
                c.execute("DELETE FROM uploaded_files WHERE user_id = ?", (user_id,))
                c.execute("""
                    DELETE FROM energy_data
                    WHERE house_id IN (SELECT id FROM houses WHERE user_id = ?)
                """, (user_id,))
                conn.commit()

            # clear session and redirect to login
            session.clear()
            return redirect(url_for('login'))

        # password change
        if 'current_password' in request.form and 'new_password' in request.form:
            current_password = request.form['current_password']
            new_password = request.form['new_password']

            with sqlite3.connect(db_file) as conn:
                c = conn.cursor()
                c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
                user = c.fetchone()

                # error messages if password does not match or does not respect requirements
                if not PASSWORD_REGEX.match(new_password):
                    error_messages.append(
                        'Password must be at least 8 characters long, and include uppercase, '
                        'lowercase, a number, and a special character.'
                    )
                elif not check_password_hash(user[2], current_password):
                    error_messages.append('Incorrect current password.')
                else:
                    # update password
                    hashed_password = generate_password_hash(new_password, method='pbkdf2:sha256')
                    c.execute("UPDATE users SET password = ? WHERE id = ?", (hashed_password, user_id))
                    conn.commit()
                    # success message
                    success_messages.append('Password updated successfully.')

        # delete file
        if 'file_id' in request.form:
            file_id = request.form['file_id']
            with sqlite3.connect(db_file) as conn:
                c = conn.cursor()
                # if the file belongs to the user
                c.execute('''
                    SELECT house_id, filename FROM uploaded_files
                    WHERE id = ? AND user_id = ?
                ''', (file_id, user_id))
                file_info = c.fetchone()
                # delete energy data and the file record
                if file_info:
                    c.execute("DELETE FROM energy_data WHERE file_id = ?", (file_id,))
                    c.execute("DELETE FROM uploaded_files WHERE id = ? AND user_id = ?", (file_id, user_id))
                    conn.commit()

    return render_template(
        'settings.html',
        houses=houses,
        error_messages=error_messages,
        success_messages=success_messages
    )

@app.route('/delete_account', methods=['POST'])
def delete_account():
    # redirect to login page if user is not logged in
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']

    # delete user data 
    with sqlite3.connect(db_file) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE id = ?", (user_id,))
        c.execute("DELETE FROM houses WHERE user_id = ?", (user_id,))
        c.execute("DELETE FROM uploaded_files WHERE user_id = ?", (user_id,))
        conn.commit()

    # clear session and log out
    session.pop('user_id', None)
    session.pop('username', None)

    return redirect(url_for('register'))

@app.route('/profile')
def profile():
    # redirect to login page if user is not logged in
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # fetch houses
    user_id = session['user_id']
    with sqlite3.connect(db_file) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('''
            SELECT id, user_id, name, type_of_area, house_size, house_type,
                   insulation_level, occupants, occupancy_patterns, solar_capacity, location
            FROM houses
            WHERE user_id = ?
        ''', (user_id,))
        houses = c.fetchall()

    return render_template('profile.html', houses=houses)

@app.route('/edit_house/<int:house_id>', methods=['GET', 'POST'])
def edit_house(house_id):
    # redirect to login page if user is not logged in
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # handle form submission for editing houses
    if request.method == 'POST':
        house_data = {
            'name': request.form['house_name'],
            'type_of_area': request.form['type_of_area'],
            'house_type': request.form['house_type'],
            'insulation_level': request.form['insulation_level'],
            'house_size': request.form['house_size'],
            'occupants': request.form['occupants'],
            'occupancy_patterns': request.form['occupancy_patterns'],
            'solar_capacity': request.form['solar_capacity'],
            'location': request.form['location']
        }

        # update house data 
        with sqlite3.connect(db_file) as conn:
            c = conn.cursor()
            c.execute('''
                UPDATE houses
                SET name = ?, type_of_area = ?, house_type = ?, insulation_level = ?, 
                    house_size = ?, occupants = ?, occupancy_patterns = ?, solar_capacity = ?, location = ?
                WHERE id = ?
            ''', (*house_data.values(), house_id))
            conn.commit()

        return redirect(url_for('profile'))

    # fetch house data to add to the form
    with sqlite3.connect(db_file) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('SELECT * FROM houses WHERE id = ?', (house_id,))
        house = c.fetchone()

    return render_template('edit_house.html', house=house)

@app.route('/add_house', methods=['GET', 'POST'])
def add_house():
    # redirect to login page if user is not logged in
    if 'user_id' not in session:
        return redirect(url_for('login'))

    error_messages = []

    # handle form submission for adding houses
    if request.method == 'POST':
        house_data = {
            'name': request.form['house_name'],
            'type_of_area': request.form['type_of_area'],
            'house_type': request.form['house_type'],
            'house_size': request.form['house_size'],
            'occupants': request.form['occupants'],
            'occupancy_patterns': request.form['occupancy_patterns'],
            'insulation_level': request.form['insulation_level'],
            'solar_capacity': request.form.get('solar_capacity', 0),
            'location': request.form.get('location', '').strip()
        }

        # error messages if solar capacity is left empty
        if not house_data['location']:
            error_messages.append('Location is required.')

        # check for duplicate house name
        with sqlite3.connect(db_file) as conn:
            c = conn.cursor()
            c.execute('''
                SELECT COUNT(*) FROM houses 
                WHERE user_id = ? AND name = ?
            ''', (session['user_id'], house_data['name']))
            # show error message
            if c.fetchone()[0] > 0:
                error_messages.append('A property with this name already exists.')

        if error_messages:
            return render_template('add_house.html', error_messages=error_messages)

        # add new house to the database
        with sqlite3.connect(db_file) as conn:
            c = conn.cursor()
            c.execute('''
                INSERT INTO houses 
                (user_id, name, type_of_area, house_type, house_size, occupants, 
                 occupancy_patterns, insulation_level, solar_capacity, location)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (session['user_id'], *house_data.values()))
            conn.commit()

        return redirect(url_for('profile'))

    return render_template('add_house.html', error_messages=error_messages)

@app.route('/delete_house/<int:house_id>', methods=['GET', 'POST'])
def delete_house(house_id):
    # redirect to login page if user is not logged in
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # delete house from database
    with sqlite3.connect(db_file) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM houses WHERE id = ? AND user_id = ?", (house_id, session['user_id']))
        conn.commit()

    return redirect(url_for('profile'))

@app.route('/faq')
def faq():
    # redirect to login page if user is not logged in
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    return render_template('faq.html')

if __name__ == '__main__':
    init_db()
    app.run(debug=True, use_reloader=True)
