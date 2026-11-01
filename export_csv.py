"""Выгружает базу wordsong.db обратно в CSV-файлы.

Зачем: правки из админки и треки из Genius лежат только в вашей локальной базе.
Чтобы они попали к команде, их нужно выгрузить в CSV и отправить на GitHub:

    python export_csv.py
    git add *.csv
    git commit -m "Обновила данные"
    git push

Файлы получаются в том же формате, который читает import_csv.py.
"""
import csv
import os
import sqlite3
import sys

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "wordsong.db")


def write_csv(name, header, rows):
    path = os.path.join(BASE_DIR, name)
    # utf-8-sig и «;» как у Excel, чтобы файлы открывались без «кракозябр»
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(header)
        writer.writerows(rows)


def main():
    if not os.path.exists(DB_PATH):
        print("Не найден файл wordsong.db. Сначала создайте базу: python import_csv.py")
        sys.exit(1)

    con = sqlite3.connect(DB_PATH)
    try:
        albums = con.execute("SELECT id, title, year FROM albums ORDER BY id").fetchall()
        tracks = con.execute("SELECT id, title, album_id FROM tracks ORDER BY id").fetchall()
        verses = con.execute(
            "SELECT id, text, missing_word, track_id, distractors FROM verses ORDER BY id"
        ).fetchall()
    finally:
        con.close()

    write_csv("albums.csv", ["id", "title", "year"], albums)
    write_csv("tracks.csv", ["id", "title", "album_id"], tracks)
    write_csv(
        "verses.csv",
        ["id", "text", "missing_word", "track_id"],
        [(v[0], v[1], v[2], v[3]) for v in verses],
    )

    distractor_rows = []
    problems = []
    for verse_id, _text, _word, _track_id, distractors in verses:
        if not distractors:
            continue
        words = [w.strip() for w in distractors.split(";")]
        if len(words) != 3 or any(not w for w in words):
            problems.append(verse_id)
            words = (words + ["", "", ""])[:3]
        distractor_rows.append((verse_id, *words))
    write_csv("distractors.csv", ["verse_id", "d1", "d2", "d3"], distractor_rows)

    print(
        f"Готово: альбомов {len(albums)}, треков {len(tracks)}, куплетов {len(verses)}, "
        f"с вариантами ответа {len(distractor_rows)}."
    )
    if problems:
        print("Внимание: у этих куплетов неверных вариантов не 3 (import_csv.py на них остановится):")
        print("  " + ", ".join(map(str, problems)))


if __name__ == "__main__":
    main()
