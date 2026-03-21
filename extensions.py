# extensions.py
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from argon2 import PasswordHasher

db = SQLAlchemy()
migrate = Migrate()
ph = PasswordHasher()

# Оваа функција го иницијализира сè (ако ја користиш)
def init_extensions(app):
    db.init_app(app)
    migrate.init_app(app, db)