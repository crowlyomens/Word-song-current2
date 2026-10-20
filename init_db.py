import os
from flask import Flask
from models import db, Album, Track, Verse

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = (
        "sqlite:///" + os.path.join(BASE_DIR, "wordsong.db")
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    return app


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        db.create_all()

        # тестовые данные добавляем, только если база пустая
        if db.session.scalar(db.select(Album).limit(1)) is None:
            album = Album(title="Тестовый альбом", year=2020)
            track1 = Track(title="Тестовый трек 1", album=album)
            track2 = Track(title="Тестовый трек 2", album=album)
            db.session.add_all([
                album, track1, track2,
                Verse(text="Это тестовый куплет номер один", missing_word="тестовый", track=track1),
                Verse(text="Это тестовый куплет номер два", missing_word="номер", track=track2),
            ])
            db.session.commit()
            print("База создана, тестовые данные добавлены.")
        else:
            print("База уже заполнена, ничего не меняю.")