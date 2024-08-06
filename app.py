from flask import Flask, render_template, url_for, request, redirect, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from bs4 import BeautifulSoup

# ensure schedule can be loaded
# import sys
# sys.path.append('./.local/lib/python3.10/site-packages')

import csv, sqlite3, hashlib, smtplib, schedule, time, threading, requests, datetime, os, signal, pytz

FROM_EMAIL = 'astroreminderassistant@gmail.com'
EMAIL_PASSWORD = 'bumq fcfv zftb vazz'

CLOUD_THRESHOLD = 10
MOON_THRESHOLD = 10
CLEAR_SKY_COUNT = 4
base_dir = os.path.dirname(os.path.abspath(__file__))
australia_tz = pytz.timezone('Australia/Sydney')
shutdown_time = None
is_shutting_down = False

app = Flask(__name__)
app.secret_key = 'apple35952833'

# Configure Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Read city database
cities = dict()
with open(os.path.join(base_dir, 'AU_500.csv'), 'r') as f:
    data = csv.reader(f, delimiter=',')
    for row in data:
        name = row[0]
        lower_name = row[1].lower().replace(' ','-')
        code = int(row[2])
        cities[name] = [lower_name, code]

class User(UserMixin):
    def __init__(self, id, email, birthday, character, locations, name):
        self.id = id
        self.email = email
        self.birthday = birthday
        self.character = character
        self.locations = locations
        self.name = name

@login_manager.user_loader
def load_user(id):
    conn = sqlite3.connect(os.path.join(base_dir, 'users.db'))
    c = conn.cursor()
    c.execute(
        '''SELECT *
            FROM users
            WHERE id = ?
        ''', (id,))
    user = c.fetchall()
    conn.close()
    if user:
        user = user[0]
        return User(id, user[1], user[3], user[4], user[5], user[6])
    return None

@app.before_request
def check_shutdown():
    if is_shutting_down:
        return render_template('maintance.html')

def weather_condition_decider(row):
    locations = row[5]
    suitable_locations = []
    if locations == '':
        return []
    locations = locations.split(',')

    for city in locations:
        # the city here is uppercase
        url = f"https://www.meteoblue.com/en/weather/outdoorsports/seeing/{cities[city][0]}_australia_{cities[city][1]}"
        page = requests.get(url)
        soup = BeautifulSoup(page.text, "html.parser")

        table = soup.find("table", attrs={"class":"table-seeing"})

        # find the first day
        day_info = table.find("td", attrs={"class":"new-day"})
        date = day_info.span.next_sibling.strip()
        if len(date) == 0:
            print("ERROR")

        sun_moon_info = day_info.pre.contents[0].split(' ')
        # sunrise = sun_moon_info[1]
        # sunset = sun_moon_info[3]
        moonrise = sun_moon_info[5] #if moonrise is ----, moon rises tmr
        moonset = sun_moon_info[7]
        moonphase = int(sun_moon_info[9][:-1])

        # #Consider if tonight is clear enough to see star
        # if moonphase > 10:
        #     continue

        # grab the moonrise in the next day
        if moonrise == '----':
            moonrise = table.find_all("td", attrs={"class":"new-day"})[1].pre.contents[0].split(' ')[5]
            moonrise = str(int(moonrise[:2])+24) + moonrise[:2] #plus 24 hr

        # filter the forcast data
        rows = table.find("tr", attrs={"class":"hour-row"}).find_next_siblings()
        rows = [row for row in rows if row.has_attr('class') and row['class'][0] == "hour-row"]

        # filter the hour >= 12 because we send the email at 12pm everyday. we don't consider the data in the past
        first_day_night = [row for row in rows if row['class'][1] == "night" and row['data-day'] == "0" and int(row['data-hour']) >= 12]
        second_day_night = [row for row in rows if row['class'][1] == "night" and row['data-day'] == "1" and int(row['data-hour']) < 12]

        # get the forcast at night in the next 24 hr
        rows = first_day_night + second_day_night

        rows_dict = []
        for row in rows:
            cols = row.find_next().find_next_siblings()
            d = dict()
            if int(row['data-hour']) < 12:
                d['time'] = int(row['data-hour'])+24
            else:
                d['time'] = int(row['data-hour'])

            d['low_clouds'] = int(cols[0].text.strip())
            d['mid_clouds'] = int(cols[1].text.strip())
            d['high_clouds'] = int(cols[2].text.strip())
            d['index1'] = int(cols[4].text.strip())
            d['index2'] = int(cols[5].text.strip())
            d['jet_stream'] = int(cols[6].text.strip()[:-4])
            rows_dict.append(d)

        #if there are clear sky for 4 hrs in a row
        count = 0
        moonrise_hour = int(moonrise.split(':')[0])
        moonset_hour = int(moonset.split(':')[0])+1
        for row in rows_dict:
            if (row['low_clouds'] <= CLOUD_THRESHOLD and
                row['mid_clouds'] <= CLOUD_THRESHOLD and
                row['high_clouds'] <= CLOUD_THRESHOLD and
                (row['time'] >= moonset_hour or
                row['time'] <= moonrise_hour or  ##also after moonset or before moonrise
                moonphase <= MOON_THRESHOLD)):
                count += 1
            else:
                count = 0
            if count >= CLEAR_SKY_COUNT:
                suitable_locations.append(city)
                break

    return suitable_locations

def check_and_send_email():
    now = datetime.datetime.now(australia_tz)
    print(f"CHECKING TIME: {now.hour}:{now.minute}", flush=True)
    if now.hour == 12 and now.minute == 0:
        send_email()

def send_email():
    conn = sqlite3.connect(os.path.join(base_dir, 'users.db'))
    c = conn.cursor()
    c.execute('''
            SELECT *
              FROM users;
            ''')
    data = c.fetchall()
    conn.close()

    # Create SMTP session
    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.starttls()  # Enable security

    try:
        server.login(FROM_EMAIL, EMAIL_PASSWORD)  # Login to the server

        for row in data:
            to_email = row[1]
            suitable_locations = weather_condition_decider(row)
            if len(suitable_locations) == 0:
                continue
            subject = "Astro Reminder"
            body = f"According to the forecast, you can see a clear sky in {', '.join(suitable_locations)} tonight. It's suitable for stargazing. Wish you have a wonderful stargazing trip!"

            message = MIMEMultipart()
            message['From'] = FROM_EMAIL
            message['To'] = to_email
            message['Subject'] = subject
            message.attach(MIMEText(body, 'plain'))

            try:
                text = message.as_string()
                server.sendmail(FROM_EMAIL, to_email, text)  # Send the email
            except Exception as e:
                print(f"Failed to send email to {to_email}: {e}")

    except Exception as e:
        print(f"Failed to login: {e}")

    finally:
        server.quit()  # Close the SMTP session

def send_feedback(feedback):
    to_email = 'brian200392@gmail.com'
    subject = "User Feedback"

    message = MIMEMultipart()
    message['From'] = FROM_EMAIL
    message['To'] = to_email
    message['Subject'] = subject
    message.attach(MIMEText(feedback, 'plain'))

    try:
        # Create SMTP session
        server = smtplib.SMTP('smtp.gmail.com', 587)  # Replace with your SMTP server and port
        server.starttls()  # Enable security
        server.login(FROM_EMAIL, EMAIL_PASSWORD)  # Login to the server
        text = message.as_string()
        server.sendmail(FROM_EMAIL, to_email, text)  # Send the email
        server.quit()
    except Exception as e:
        print(f"Failed to send feedback: {e}")

def send_announcement(content):
    conn = sqlite3.connect(os.path.join(base_dir, 'users.db'))
    c = conn.cursor()
    c.execute('''
            SELECT *
              FROM users;
            ''')
    data = c.fetchall()
    conn.close()

    # Create SMTP session
    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.starttls()  # Enable security

    try:
        server.login(FROM_EMAIL, EMAIL_PASSWORD)  # Login to the server

        for row in data:
            to_email = row[1]
            subject = "Astro Reminder Announcement"
            body = f"Hi, {row[6]}.\n{content}"

            message = MIMEMultipart()
            message['From'] = FROM_EMAIL
            message['To'] = to_email
            message['Subject'] = subject
            message.attach(MIMEText(body, 'plain'))

            try:
                text = message.as_string()
                server.sendmail(FROM_EMAIL, to_email, text)  # Send the email
            except Exception as e:
                print(f"Failed to send email to {to_email}: {e}")

    except Exception as e:
        print(f"Failed to login: {e}")

    finally:
        server.quit()  # Close the SMTP session

#Freeze requests and deal with the ongoing requests
def shutdown_server():
    global is_shutting_down
    is_shutting_down = True
    time.sleep(5)  # Give some time for ongoing requests to finish
    os.kill(os.getpid(), signal.SIGINT)

# Schedule the send_email function to run every day at 12 PM
schedule.every().minute.do(check_and_send_email)

# Scheduler function to run in a separate thread
def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(1)  # Sleep for 1 second

def scheduled_shutdown():
    global shutdown_time
    while True:
        if shutdown_time:
            now = datetime.datetime.now(australia_tz)
            if now >= shutdown_time:
                print("Shutting down the server...")
                shutdown_server()
                break
        time.sleep(30)  # Check every 30 seconds


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'GET':
        return render_template('signup.html', locations=list(cities.keys()))
    else:
        email = request.form.get('email')
        name = request.form.get('name')

        password = request.form.get('password')
        password = hashlib.sha256(password.encode()).hexdigest()
        password2 = request.form.get('password2')
        password2 = hashlib.sha256(password2.encode()).hexdigest()

        birthday = request.form.get('birthday')

        locations = request.form.get('selected_locations')
        if not locations:
            locations = ""

        conn = sqlite3.connect(os.path.join(base_dir, 'users.db'))
        c = conn.cursor()
        c.execute('''
                SELECT COUNT(*)
                  FROM users
                  WHERE email = ?
                ''', (email,))
        count = int(c.fetchone()[0])
        conn.close()

        if count != 0:
            flash('This email has been used. Try another one or use forget password.', 'error')
            return redirect(url_for('signup'))

        if password != password2:
            flash('Two passwords are different. Please enter again.', 'error')
            return redirect(url_for('signup'))

        conn = sqlite3.connect(os.path.join(base_dir, 'users.db'))
        c = conn.cursor()
        c.execute('''
                INSERT INTO users (email, password, birthday, character, locations, name) VALUES
                  (?,?,?,?,?,?);
                ''', (email, password, birthday, 'user', locations, name, ))
        conn.commit()
        conn.close()

        flash('Successfully sign up. Please log in below.', 'success')
        return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')
    else:
        email = request.form.get('email')
        password = request.form.get('password')
        password = hashlib.sha256(password.encode()).hexdigest()

        conn = sqlite3.connect(os.path.join(base_dir, 'users.db'))
        c = conn.cursor()
        c.execute('''
                SELECT *
                  FROM users
                  WHERE email = ? AND password = ?
                ''', (email, password, ))
        user = c.fetchall()
        conn.close()

        if not user:
            flash('Invalid credentials.', 'error')
            return redirect(url_for('login'))

        user = user[0]
        # email: user[1]  locations: user[3]
        login_user(User(user[0], user[1], user[3], user[4], user[5], user[6]))

        return redirect(url_for('home', id=user[0]))

@app.route('/home/<int:id>', methods=['GET', 'POST'])
@login_required
def home(id):
    user = load_user(id)
    if user.locations == "":
        selected_locations = []
    else:
        selected_locations=user.locations.split(',')
    return render_template('home.html', locations=list(cities.keys()), selected_locations=selected_locations, id=id, email=user.email, birthday=user.birthday, character=user.character, name=user.name)

@app.route('/forget_pwd', methods=['GET', 'POST'])
def reset_pwd():
    if request.method == 'POST':
        email = request.form.get('email')
        birthday = request.form.get('birthday')

        password = request.form.get('password')
        password = hashlib.sha256(password.encode()).hexdigest()
        password2 = request.form.get('password2')
        password2 = hashlib.sha256(password2.encode()).hexdigest()

        conn = sqlite3.connect(os.path.join(base_dir, 'users.db'))
        c = conn.cursor()
        c.execute('''
                SELECT COUNT(*)
                  FROM users
                  WHERE email = ? AND birthday = ?
                ''', (email, birthday, ))
        count = int(c.fetchone()[0])
        conn.close()

        if count == 0:
            flash('Incorrect email or birthday.', 'error')
            return redirect(url_for('reset_pwd'))

        if password != password2:
            flash('Two passwords are different. Please enter again.', 'error')
            return redirect(url_for('reset_pwd'))

        conn = sqlite3.connect(os.path.join(base_dir, 'users.db'))
        c = conn.cursor()
        c.execute('''
                UPDATE users
                  SET password = ?
                  WHERE email = ? AND birthday = ?
                ''', (password, email, birthday))

        conn.commit()
        conn.close()

        flash('Successfully reset your password. Please log in below.', 'success')
        return redirect(url_for('login'))

    else:
        return render_template('forget_pwd.html')

@app.route('/update_locations/<int:id>', methods=['GET', 'POST'])
@login_required
def update_locations(id):
    if request.method == 'POST':
        locations = request.form.get('selected_locations')
        conn = sqlite3.connect(os.path.join(base_dir, 'users.db'))
        c = conn.cursor()
        c.execute('''
                UPDATE users
                  SET locations = ?
                  WHERE id = ?
                ''', (locations, id, ))

        conn.commit()
        conn.close()
        flash('Successfully update your locations.', 'success')
        if locations == '':
            return redirect(url_for('home', id=id))
        return redirect(url_for('home', id=id))
    else:
        user = load_user(id)
        if user.locations == '':
            selected_locations = []
        else:
            selected_locations = user.locations.split(',')
        return render_template('/update_locations.html', id=id, locations=list(cities.keys()), selected_locations=selected_locations)

@app.route('/update_email/<int:id>', methods=['GET', 'POST'])
@login_required
def update_email(id):
    if request.method == 'POST':
        email = request.form.get('email')
        conn = sqlite3.connect(os.path.join(base_dir, 'users.db'))
        c = conn.cursor()
        c.execute('''
                SELECT COUNT(*)
                  FROM users
                  WHERE email = ?;
                ''', (email, ))

        count = int(c.fetchone()[0])
        conn.close()
        if count != 0:
            flash('This email has been used. Try another one or use forget password.', 'error')
            return redirect(url_for('update_email', id=id))

        conn = sqlite3.connect(os.path.join(base_dir, 'users.db'))
        c = conn.cursor()
        c.execute('''
                UPDATE users
                  SET email = ?
                  WHERE id = ?
                ''', (email, id, ))
        conn.commit()
        conn.close()

        user = load_user(id)
        flash('Successfully update your email.', 'success')
        return redirect(url_for('home', id=id))

    else:
        return render_template('/update_email.html', id=id)

@app.route('/update_name/<int:id>', methods=['GET', 'POST'])
@login_required
def update_name(id):
    if request.method == 'POST':
        name = request.form.get('name')
        conn = sqlite3.connect(os.path.join(base_dir, 'users.db'))
        c = conn.cursor()
        c.execute('''
                UPDATE users
                  SET name = ?
                  WHERE id = ?
                ''', (name, id, ))
        conn.commit()
        conn.close()
        flash('Successfully update your name.', 'success')
        return redirect(url_for('home', id=id))

    else:
        return render_template('/update_name.html', id=id)

@app.route('/update_birthday/<int:id>', methods=['GET', 'POST'])
@login_required
def update_birthday(id):
    if request.method == 'POST':
        birthday = request.form.get('birthday')

        conn = sqlite3.connect(os.path.join(base_dir, 'users.db'))
        c = conn.cursor()
        c.execute('''
                UPDATE users
                  SET birthday = ?
                  WHERE id = ?
                ''', (birthday, id, ))
        conn.commit()
        conn.close()

        flash('Successfully update your birthday.', 'success')
        return redirect(url_for('home', id=id))

    else:
        return render_template('/update_birthday.html', id=id)


@app.route('/update_password/<int:id>', methods=['GET', 'POST'])
@login_required
def update_password(id):
    if request.method == 'POST':
        password = request.form.get('password')
        password = hashlib.sha256(password.encode()).hexdigest()
        password2 = request.form.get('password2')
        password2 = hashlib.sha256(password2.encode()).hexdigest()

        if password != password2:
            flash('Two passwords are different. Please enter again.', 'error')
            return redirect(url_for('update_password', id=id))

        conn = sqlite3.connect(os.path.join(base_dir, 'users.db'))
        c = conn.cursor()
        c.execute('''
                UPDATE users
                  SET password = ?
                  WHERE id = ?
                ''', (password, id, ))

        conn.commit()
        conn.close()
        flash('Successfully update your password.', 'success')
        return redirect(url_for('home', id=id))
    else:
        return render_template('/update_password.html', id=id, locations=list(cities.keys()))

@app.route('/feedback_visitor', methods=['GET', 'POST'])
def feedback_visitor():
    if request.method == 'POST':
        feedback = request.form.get('feedback')
        send_feedback(feedback)
        flash('Thanks for your feedback!', 'success')
        return redirect('/')
    else:
        return render_template('feedback_visitor.html')

@app.route('/feedback_user/<int:id>', methods=['GET', 'POST'])
@login_required
def feedback_user(id):
    user = load_user(id)
    if request.method == 'POST':
        feedback = request.form.get('feedback')
        send_feedback(feedback)
        flash('Thanks for your feedback!', 'success')
        return redirect(url_for('home', id=id))
    else:
        return render_template('feedback_user.html', id=id, name=user.name)

@app.route('/admin/<int:id>', methods=['GET', 'POST'])
@login_required
def admin(id):
    if request.method == 'POST':
        # to do
        return render_template('admin.html',id=id)
    else:
        conn = sqlite3.connect(os.path.join(base_dir, 'users.db'))
        c = conn.cursor()
        c.execute('''
                SELECT *
                FROM users
                ORDER BY character, id
                ''')
        users = c.fetchall()
        conn.close()
        number_users = len(users)
        return render_template('admin.html',id=id, users=users, number_users=number_users)

@app.route('/delete_user', methods=['POST'])
@login_required
def delete_user():
    delete_id = request.args.get('delete_id')
    admin_id = request.args.get('admin_id')
    deleted_user = load_user(delete_id)
    if deleted_user.character == 'admin':
        conn = sqlite3.connect(os.path.join(base_dir, 'users.db'))
        c = conn.cursor()
        c.execute('''
            UPDATE users
            SET character = ?
            WHERE id = ?
            ''', ('user', delete_id, ))
        conn.commit()
        conn.close()
        flash('Successfully remove the admin.', 'success')
    else:
        #delete the user
        conn = sqlite3.connect(os.path.join(base_dir, 'users.db'))
        c = conn.cursor()
        c.execute('''
                DELETE FROM users
                WHERE id = ?
                ''', (delete_id, ))
        conn.commit()
        conn.close()
        flash('Successfully delete the user.', 'success')
    return redirect(url_for('admin', id=admin_id))

@app.route('/add_admin', methods=['POST'])
@login_required
def add_admin():
    new_admin_id = request.args.get('new_admin_id')
    admin_id = request.args.get('admin_id')
    conn = sqlite3.connect(os.path.join(base_dir, 'users.db'))
    c = conn.cursor()
    c.execute('''
            UPDATE users
            SET character = ?
            WHERE id = ?
            ''', ('admin', new_admin_id, ))
    conn.commit()
    conn.close()
    return redirect(url_for('admin', id=admin_id))

@app.route('/announcement/<int:id>', methods=['GET', 'POST'])
@login_required
def announcement(id):
    if request.method == 'POST':
        content = request.form.get('content')
        send_announcement(content)
        flash('Successfully send announcement.', 'success')
        return redirect(url_for('admin', id=id))
    return render_template('announcement.html', id=id)

@app.route('/shutdown/<int:id>', methods=['GET', 'POST'])
@login_required
def shutdown(id): 
    global shutdown_time
    if request.method == 'POST':
        shutdown_datetime_str = request.form.get('datetime')
        shutdown_time = australia_tz.localize(datetime.datetime.strptime(shutdown_datetime_str, "%Y-%m-%dT%H:%M"))
        # shutdown_time = datetime.datetime.strptime(shutdown_datetime_str, '%Y-%m-%dT%H:%M')
        if shutdown_time <= datetime.datetime.now(australia_tz):
            shutdown_time = None
            flash('You can\'t shutdown the server before now.', 'error')
            return redirect(url_for('shutdown', id=id, shutdown_datetime="----"))
        else:
            flash('Successfully schedule a shutdown date time.', 'success')
            return redirect(url_for('admin', id=id))

    if shutdown_time == None:
        return render_template('shutdown.html', id=id, shutdown_datetime="----", now=datetime.datetime.now(australia_tz).strftime('%Y-%m-%d %H:%M:%S'))
    return render_template('shutdown.html', id=id, shutdown_datetime=shutdown_time.strftime('%Y-%m-%d %H:%M:%S'), now=datetime.datetime.now(australia_tz).strftime('%Y-%m-%d %H:%M:%S'))

@app.route('/logout', methods=['GET', 'POST'])
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

if __name__ == '__main__':
    # # Start the scheduler thread
    scheduler_thread = threading.Thread(target=run_scheduler)
    scheduler_thread.daemon = True
    scheduler_thread.start()

    # # Start the background thread for scheduled shutdown
    shutdown_thread = threading.Thread(target=scheduled_shutdown)
    shutdown_thread.daemon = True
    shutdown_thread.start()

    app.run(debug=True)
