import csv
import os
import re
import sys

from init_db import create_app, BASE_DIR
from models import db, Album, Track, Verse


def read_csv(name, required=True):
    path = os.path.join(BASE_DIR, name)
    if not os.path.exists(path):
        if required:
            print(f"Не найден файл {name}")
            sys.exit(1)
        return []
    # utf-8-sig убирает BOM, delimiter=";" как сохраняет Excel
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def clean_text(text):
    # в тексте куплета кавычки не нужны: убираем их, чистим пробелы и пустые строки
    text = text.replace('"', "")
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def word_in_text(word, text):
    # ищем слово целиком, с тем же регистром
    pattern = r"(?<!\w)" + re.escape(word) + r"(?!\w)"
    return re.search(pattern, text) is not None


def main():
    albums = read_csv("albums.csv")
    tracks = read_csv("tracks.csv")
    verses = read_csv("verses.csv")
    distractor_rows = read_csv("distractors.csv", required=False)

    errors = []

    album_ids = {int(a["id"]) for a in albums}
    track_album = {int(t["id"]): int(t["album_id"]) for t in tracks}

    for track_id, album_id in track_album.items():
        if album_id not in album_ids:
            errors.append(f"Трек {track_id}: нет альбома с id={album_id}")

    for album_id in album_ids:
        count = sum(1 for a in track_album.values() if a == album_id)
        if count < 4:
            errors.append(f"Альбом {album_id}: треков {count}, нужно минимум 4")

    clean_verses = []
    missing_words = {}
    for v in verses:
        verse_id = int(v["id"])
        track_id = int(v["track_id"])
        text = clean_text(v["text"])
        word = v["missing_word"].strip()

        if track_id not in track_album:
            errors.append(f"Куплет {verse_id}: нет трека с id={track_id}")
        if not word_in_text(word, text):
            errors.append(f"Куплет {verse_id}: слова «{word}» нет в тексте")
        clean_verses.append((verse_id, text, word, track_id))
        missing_words[verse_id] = word

    # неверные варианты: файл distractors.csv с колонками verse_id;d1;d2;d3
    distractors = {}
    for row in distractor_rows:
        verse_id = int(row["verse_id"])
        words = [(row.get(k) or "").strip() for k in ("d1", "d2", "d3")]

        if verse_id not in missing_words:
            errors.append(f"distractors.csv: нет куплета с id={verse_id}")
            continue
        if any(not w for w in words):
            errors.append(f"distractors.csv, куплет {verse_id}: нужно ровно 3 слова")
        if any(";" in w for w in words):
            errors.append(f"distractors.csv, куплет {verse_id}: в словах нельзя ставить «;»")
        lowered = [w.lower() for w in words]
        if len(set(lowered)) != len(lowered):
            errors.append(f"distractors.csv, куплет {verse_id}: слова повторяются")
        if missing_words[verse_id].lower() in lowered:
            errors.append(f"distractors.csv, куплет {verse_id}: среди неверных есть правильное слово")
        distractors[verse_id] = ";".join(words)

    if errors:
        print("Нашлись ошибки, база не тронута:")
        for e in errors:
            print(" -", e)
        sys.exit(1)

    app = create_app()
    with app.app_context():
        db.create_all()

        # полностью перезаписываем данные из CSV
        db.session.execute(db.delete(Verse))
        db.session.execute(db.delete(Track))
        db.session.execute(db.delete(Album))
        db.session.commit()

        for a in albums:
            year = a["year"].strip()
            db.session.add(Album(
                id=int(a["id"]),
                title=a["title"].strip(),
                year=int(year) if year else None,
            ))
        db.session.commit()

        for t in tracks:
            db.session.add(Track(
                id=int(t["id"]),
                title=t["title"].strip(),
                album_id=int(t["album_id"]),
            ))
        db.session.commit()

        for verse_id, text, word, track_id in clean_verses:
            db.session.add(Verse(
                id=verse_id,
                text=text,
                missing_word=word,
                track_id=track_id,
                distractors=distractors.get(verse_id),
            ))
        db.session.commit()

    print(
        f"Готово: альбомов {len(albums)}, треков {len(tracks)}, "
        f"куплетов {len(clean_verses)}, с вариантами ответа {len(distractors)}."
    )


if __name__ == "__main__":
    main()