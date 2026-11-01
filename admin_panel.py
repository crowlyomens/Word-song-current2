"""Админ-панель для базы: http://127.0.0.1:5000/admin

Доступ:
  * без пароля админка открыта только с этого же компьютера (127.0.0.1);
  * если задана переменная окружения ADMIN_PASSWORD, админка просит пароль
    (логин любой). Это нужно, когда игра выложена в интернет.
"""
import hmac
import os

from flask import Response, abort, request
from flask_admin import Admin, AdminIndexView
from flask_admin.contrib.sqla import ModelView
from wtforms.validators import ValidationError

from import_csv import clean_text, word_in_text
from models import db, Album, Track, Verse


def has_access():
    password = os.environ.get("ADMIN_PASSWORD")
    if password:
        auth = request.authorization
        if auth is None:
            return False
        return hmac.compare_digest((auth.password or "").encode("utf-8"), password.encode("utf-8"))
    return request.remote_addr in ("127.0.0.1", "::1")


class SecureMixin:
    def is_accessible(self):
        return has_access()

    def inaccessible_callback(self, name, **kwargs):
        if os.environ.get("ADMIN_PASSWORD"):
            return Response(
                "Нужен пароль", 401, {"WWW-Authenticate": 'Basic realm="word-song admin"'}
            )
        abort(403)


class SecureModelView(SecureMixin, ModelView):
    page_size = 50
    can_export = False


class SecureIndexView(SecureMixin, AdminIndexView):
    pass


def check_verse(verse):
    """Проверяет куплет перед сохранением. Бросает ValidationError с понятным текстом."""
    verse.text = clean_text(verse.text)
    verse.missing_word = (verse.missing_word or "").strip()

    if not verse.text:
        raise ValidationError("Текст куплета пустой.")
    if not verse.missing_word:
        raise ValidationError("Не указано пропущенное слово.")
    if not word_in_text(verse.missing_word, verse.text):
        raise ValidationError(
            f"Слова «{verse.missing_word}» нет в тексте куплета. "
            "Проверьте написание и заглавные буквы: оно должно совпадать с текстом."
        )

    raw = (verse.distractors or "").strip()
    if not raw:
        # без своих вариантов игра возьмет случайные слова из других куплетов
        verse.distractors = None
        return

    words = [w.strip() for w in raw.split(";")]
    if len(words) != 3 or any(not w for w in words):
        raise ValidationError(
            "Неверных вариантов должно быть ровно 3, через точку с запятой: слово1;слово2;слово3"
        )
    lowered = [w.lower() for w in words]
    if len(set(lowered)) != 3:
        raise ValidationError("Неверные варианты повторяются.")
    if verse.missing_word.lower() in lowered:
        raise ValidationError("Среди неверных вариантов есть правильное слово.")
    verse.distractors = ";".join(words)


def short_text(view, context, model, name):
    text = (model.text or "").replace("\n", " / ")
    return text if len(text) <= 70 else text[:70] + "…"


class AlbumView(SecureModelView):
    column_list = ("id", "title", "year")
    column_labels = {"id": "ID", "title": "Название", "year": "Год"}
    column_searchable_list = ("title",)
    form_excluded_columns = ("tracks",)


class TrackView(SecureModelView):
    column_list = ("id", "title", "album")
    column_labels = {"id": "ID", "title": "Название", "album": "Альбом"}
    column_searchable_list = ("title",)
    form_excluded_columns = ("verses",)


class VerseView(SecureModelView):
    column_list = ("id", "track", "text", "missing_word", "distractors")
    column_labels = {
        "id": "ID",
        "track": "Трек",
        "text": "Куплет",
        "missing_word": "Пропущенное слово",
        "distractors": "Неверные варианты",
    }
    column_searchable_list = ("text", "missing_word")
    column_formatters = {"text": short_text}
    column_descriptions = {
        "missing_word": "Слово из куплета, записанное точно так же, как в тексте.",
        "distractors": "Ровно 3 неверных слова через «;», например: щит;столб;венец. "
                       "Можно оставить пустым: тогда игра возьмет случайные слова.",
    }

    def on_model_change(self, form, model, is_created):
        check_verse(model)


def init_admin(app):
    admin = Admin(app, name="Word-Song: админка", index_view=SecureIndexView(name="Главная"))
    admin.add_view(AlbumView(Album, db.session, name="Альбомы"))
    admin.add_view(TrackView(Track, db.session, name="Треки"))
    admin.add_view(VerseView(Verse, db.session, name="Куплеты"))
    return admin
