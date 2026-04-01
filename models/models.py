from extensions import db


class User(db.Model):
    """Minimal SQLAlchemy mirror of the live users table."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(255), unique=True, nullable=False)
    hashed_password = db.Column(db.String(512), nullable=False)
    is_admin = db.Column(db.Integer, default=0)
    user_group = db.Column(db.String(255), default="")
    allowed_modules = db.Column(db.Text, default="")
    email = db.Column(db.String(255), default="")


class Part(db.Model):
    """Subset of the parts table used by the app."""

    __tablename__ = "parts"

    id = db.Column(db.Integer, primary_key=True)
    part_number = db.Column(db.String(255), unique=True, nullable=False)
    ime = db.Column(db.String(255))
    kamin = db.Column(db.String(255))
    slika = db.Column(db.String(255))
    vid_artikal = db.Column(db.String(255))
    odobren = db.Column(db.Integer, default=0)


class ZalihaDodadi(db.Model):
    """Live stock-entry table. Replaces the old, stale `zaliha` model."""

    __tablename__ = "zaliha_dodadi"

    id = db.Column(db.Integer, primary_key=True)
    artikl_id = db.Column(db.Integer, nullable=False)
    kolicina = db.Column(db.Integer, nullable=False)
    cena = db.Column(db.Float, default=0)
    datum = db.Column(db.String(32), nullable=False)
    plateno = db.Column(db.Integer, default=0)
    username = db.Column(db.String(255), nullable=False)
    zabeleska = db.Column(db.Text)
