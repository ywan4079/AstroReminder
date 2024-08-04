def send_email():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''
            SELECT *
              FROM users;
            ''')
    data = c.fetchall()
    conn.close()

    for row in data:
        to_email = row[1]
        suitable_locations = weather_condition_decider(row)
        if len(suitable_locations) == 0:
            continue
        subject = "Astro Reminder"
        body = f"According to the forcast. You can see clear sky in {', '.join(suitable_locations)} tonight. It's suitable for star gazing. Wish you have a wonderful star gazing trip!"

        message = MIMEMultipart()
        message['From'] = FROM_EMAIL
        message['To'] = to_email
        message['Subject'] = subject
        message.attach(MIMEText(body, 'plain'))

        try:
            # Create SMTP session
            server = smtplib.SMTP('smtp.gmail.com', 587) 
            server.starttls()  # Enable security
            server.login(FROM_EMAIL, EMAIL_PASSWORD)  # Login to the server
            text = message.as_string()
            server.sendmail(FROM_EMAIL, to_email, text)  # Send the email
            server.quit()
        except Exception as e:
            print(f"Failed to send email: {e}")