conn = sqlite3.connect('users.db')
c = conn.cursor()
c.execute('''
        DROP TABLE IF EXISTS users
        ''')
conn.commit()
conn.close()