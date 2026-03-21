# models/models.py
from extensions import db          # ← само ова, НЕ flask_sqlalchemy повторно!

class Zaliha(db.Model):
    __tablename__ = 'zaliha'
    id = db.Column(db.Integer, primary_key=True)
    pn = db.Column(db.String(50), unique=True, nullable=False)
    ime = db.Column(db.String(200), nullable=False)
    kolicina_platena = db.Column(db.Integer, default=0)
    kolicina_neplatena = db.Column(db.Integer, default=0)
    zabeleska = db.Column(db.Text, default='')
    
    def __repr__(self):
        return f"<Zaliha {self.pn} {self.ime}>"