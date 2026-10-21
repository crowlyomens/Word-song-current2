from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Album(db.Model):
    __tablename__ = "albums"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    year = db.Column(db.Integer)

    tracks = db.relationship("Track", back_populates="album")

    def __str__(self):
        return self.title


class Track(db.Model):
    __tablename__ = "tracks"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    # album_id может быть пустым: так можно хранить синглы без альбома
    album_id = db.Column(db.Integer, db.ForeignKey("albums.id"))

    album = db.relationship("Album", back_populates="tracks")
    verses = db.relationship(
        "Verse", back_populates="track", cascade="all, delete-orphan"
    )

    def __str__(self):
        return self.title


class Verse(db.Model):
    __tablename__ = "verses"

    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    # слово, которое прячем в режиме «Пропущенное слово»
    missing_word = db.Column(db.String(100), nullable=False)
    # неверные варианты для режима «Пропущенное слово»: слово1;слово2;слово3
    distractors = db.Column(db.String(300))
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.id"), nullable=False)

    track = db.relationship("Track", back_populates="verses")

    def __str__(self):
        return self.text[:40]