from flask import Flask
from flask_mysqldb import MySQL
from flask_login import LoginManager
from dotenv import load_dotenv
import os

load_dotenv()

app = Flask(__name__, template_folder='../templates')
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['MYSQL_HOST'] = os.getenv('MYSQL_HOST')
app.config['MYSQL_USER'] = os.getenv('MYSQL_USER')
app.config['MYSQL_PASSWORD'] = os.getenv('MYSQL_PASSWORD')
app.config['MYSQL_DB'] = os.getenv('MYSQL_DB')

mysql = MySQL(app)
login_manager = LoginManager(app)
login_manager.login_view = 'auth.login'

from app.auth import auth as auth_blueprint
app.register_blueprint(auth_blueprint, url_prefix='')

@login_manager.user_loader
def load_user(user_id):
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    cur.close()
    return user

from app.dashboard import dashboard as dashboard_blueprint
app.register_blueprint(dashboard_blueprint, url_prefix='/dashboard')