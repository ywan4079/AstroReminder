import sqlite3, hashlib, requests, csv
from bs4 import BeautifulSoup

CLOUD_THRESHOLD = 10
CLEAR_SKY_COUNT = 4
##create database
# conn = sqlite3.connect('users.db')
# c = conn.cursor()
# c.execute(
#     '''CREATE TABLE IF NOT EXISTS users
#     (id INTEGER PRIMARY KEY,
#     email TEXT NOT NULL,
#     password TEXT NOT NULL,
#     birthday TEXT NOT NULL,
#     character TEXT,
#     locations TEXT,
#     name TEXT)
#     ''')
# conn.commit()
# conn.close()

# conn = sqlite3.connect('users.db')
# c = conn.cursor()
# c.execute('''
#         DROP TABLE IF EXISTS users
#         ''')
# conn.commit()
# conn.close()

# conn = sqlite3.connect('users.db')
# c = conn.cursor()
# c.execute('''
#         UPDATE users
#           SET character = ?
#           WHERE name = ?;
#         ''', ('admin', 'Brian', ))
# conn.commit()
# conn.close()

# conn = sqlite3.connect('users.db')
# c = conn.cursor()
# c.execute('''
#         SELECT *
#           FROM users;
#         ''')
# users = c.fetchall()
# conn.close()

# for user in users:
#     print(user)
