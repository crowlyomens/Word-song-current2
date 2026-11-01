"""Подтягивает из Genius названия песен и альбомов артиста и добавляет их в базу.

Что берется: только названия треков, альбомы и годы. Тексты песен Genius через
API не отдает, куплеты вы добавляете сами (через админку).

Подготовка (один раз):
  1. На https://genius.com/api-clients создайте приложение (New API Client)
     и нажмите «Generate Access Token».
  2. В папке проекта создайте файл .env с одной строкой:
         GENIUS_TOKEN=ваш_токен
     Файл .env уже в .gitignore, на GitHub он не попадет.

Запуск:
    python genius_import.py

Сначала скрипт покажет, что будет добавлено, и спросит подтверждение.
"""
import argparse
import os
import re
import sys
import time
from collections import Counter

import requests

API_URL = "https://api.genius.com"
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
PAUSE = 0.3  # пауза между запросами, чтобы не перегружать Genius

# Если эти слова есть в названии «альбома», он похож на раунд рэп-баттла:
# такой альбом и его треки не добавляются. Список можно менять.
SKIP_ALBUM_WORDS = ["battle", "баттл", "rapbitva", "slovo", "rap olympics", "17ib", " — "]
# Если у альбома меньше стольких новых треков, сам альбом не создается:
# его треки добавляются без альбома (так бывает с синглами).
MIN_ALBUM_TRACKS = 3


def load_token():
    token = os.environ.get("GENIUS_TOKEN")
    if token:
        return token.strip()
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line.startswith("GENIUS_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def norm(text):
    """Название для сравнения: без регистра, пробелов и знаков препинания."""
    text = (text or "").lower().replace("ё", "е")
    return re.sub(r"[\W_]+", "", text)


def clean_title(title):
    title = (title or "").replace(" ", " ").replace("​", "")
    return re.sub(r"\s+", " ", title).strip()


def api_get(session, token, path, params=None):
    headers = {"Authorization": f"Bearer {token}"}
    for attempt in range(4):
        try:
            resp = session.get(API_URL + path, params=params, headers=headers, timeout=20)
        except requests.RequestException as e:
            if attempt == 3:
                sys.exit(f"Не удалось связаться с Genius: {e}")
            time.sleep(2 * (attempt + 1))
            continue
        if resp.status_code == 200:
            return resp.json()["response"]
        if resp.status_code == 401:
            sys.exit("Genius ответил 401: токен не подошел. Проверьте GENIUS_TOKEN в файле .env")
        if resp.status_code in (429, 500, 502, 503, 504):
            time.sleep(3 * (attempt + 1))
            continue
        sys.exit(f"Genius ответил ошибкой {resp.status_code} на запрос {path}")
    sys.exit("Genius не отвечает или просит подождать. Попробуйте запустить позже.")


def find_artist(session, token, name):
    resp = api_get(session, token, "/search", {"q": name})
    counts = Counter()
    names = {}
    for hit in resp.get("hits", []):
        artist = (hit.get("result") or {}).get("primary_artist") or {}
        if (artist.get("name") or "").lower() == name.lower():
            counts[artist["id"]] += 1
            names[artist["id"]] = artist["name"]
    if not counts:
        return None, None
    artist_id = counts.most_common(1)[0][0]
    return artist_id, names[artist_id]


def fetch_artist_songs(session, token, artist_id):
    songs = []
    page = 1
    while page:
        resp = api_get(
            session, token, f"/artists/{artist_id}/songs",
            {"per_page": 50, "page": page, "sort": "title"},
        )
        songs.extend(resp.get("songs", []))
        page = resp.get("next_page")
        time.sleep(PAUSE)
    return songs


def extract_year(*sources):
    """Год выпуска из данных песни Genius (пробует несколько полей)."""
    for data in sources:
        data = data or {}
        year = (data.get("release_date_components") or {}).get("year")
        if year:
            return int(year)
        for field in ("release_date", "release_date_for_display"):
            match = re.search(r"\b(19|20)\d{2}\b", str(data.get(field) or ""))
            if match:
                return int(match.group(0))
    return None


def fetch_plan(session, token, artist_id, with_features=False):
    """Возвращает (список песен [{title, album, year}], сколько чужих песен пропущено)."""
    songs = fetch_artist_songs(session, token, artist_id)
    if with_features:
        own = songs
    else:
        # песни, где артист только приглашенный гость, пропускаем
        own = [s for s in songs if (s.get("primary_artist") or {}).get("id") == artist_id]
    skipped = len(songs) - len(own)

    plan = []
    for i, song in enumerate(own, 1):
        # альбом в списке песен не приходит, его отдает только запрос по одной песне
        detail = api_get(session, token, f"/songs/{song['id']}")["song"]
        album = detail.get("album") or {}
        plan.append({
            "title": clean_title(detail.get("title") or song.get("title")),
            "album": clean_title(album.get("name")) or None,
            "year": extract_year(detail, song),
        })
        print(f"\r  читаю песни: {i}/{len(own)}", end="", flush=True)
        time.sleep(PAUSE)
    print()
    return plan, skipped


def build_additions(plan, existing_albums, existing_tracks, skip_words=(), min_tracks=1):
    """Что добавлять в базу.

    existing_albums, existing_tracks: множества нормализованных (norm) названий.
    skip_words: если слово есть в названии альбома, альбом и его треки пропускаются.
    min_tracks: альбомы с меньшим числом новых треков не создаются, их треки идут без альбома.
    Возвращает (новые альбомы, новые треки, сколько треков уже было, сводка).
    """
    skip_words = [w.lower() for w in skip_words]
    info = {"skipped_albums": [], "demoted_albums": []}

    # год альбома: самый ранний год среди его песен
    album_years = {}
    for item in plan:
        if item["album"] and item["year"]:
            key = norm(item["album"])
            album_years[key] = min(item["year"], album_years.get(key, item["year"]))

    seen = set(existing_tracks)
    new_tracks = []
    already = 0
    for item in plan:
        if item["album"] and any(w in item["album"].lower() for w in skip_words):
            if item["album"] not in info["skipped_albums"]:
                info["skipped_albums"].append(item["album"])
            continue
        key = norm(item["title"])
        if not key:
            continue
        if key in seen:
            already += 1
            continue
        seen.add(key)
        new_tracks.append(dict(item))

    # маленькие альбомы не создаем: их треки остаются без альбома
    counts = Counter(norm(t["album"]) for t in new_tracks if t["album"])
    for t in new_tracks:
        if not t["album"]:
            continue
        key = norm(t["album"])
        if key not in existing_albums and counts[key] < min_tracks:
            if t["album"] not in info["demoted_albums"]:
                info["demoted_albums"].append(t["album"])
            t["album"] = None

    new_albums = []
    album_seen = set(existing_albums)
    for item in new_tracks:
        if not item["album"]:
            continue
        key = norm(item["album"])
        if key in album_seen:
            continue
        album_seen.add(key)
        new_albums.append({"title": item["album"], "year": album_years.get(key)})
    return new_albums, new_tracks, already, info


def print_plan(new_albums, new_tracks, already, skipped_features, info):
    print()
    if new_albums:
        print("Новые альбомы:")
        for a in new_albums:
            print(f"  + {a['title']} ({a['year'] or 'год неизвестен'})")
    by_album = {}
    for t in new_tracks:
        by_album.setdefault(t["album"] or "— без альбома —", []).append(t["title"])
    print("Новые треки:")
    for album, titles in by_album.items():
        print(f"  {album}:")
        for title in sorted(titles):
            print(f"    + {title}")
    print()
    print(f"Итого новых треков: {len(new_tracks)}, новых альбомов: {len(new_albums)}.")
    print(f"Уже есть в базе (пропущено): {already}.")
    if info["skipped_albums"]:
        print(f"Пропущены альбомы, похожие на рэп-баттлы ({len(info['skipped_albums'])}), "
              "их треки не добавлены: " + "; ".join(info["skipped_albums"]) + ".")
    if info["demoted_albums"]:
        print(f"Альбомы, где меньше {MIN_ALBUM_TRACKS} новых треков, не созданы, "
              "их треки добавлены без альбома: " + "; ".join(info["demoted_albums"]) + ".")
    if skipped_features:
        print(f"Пропущено песен, где артист только гость: {skipped_features} "
              "(чтобы добавить и их, запустите с --with-features).")


def main():
    parser = argparse.ArgumentParser(description="Импорт треков и альбомов из Genius")
    parser.add_argument("--artist", default="Pyrokinesis", help="имя артиста на Genius")
    parser.add_argument("--artist-id", type=int, help="id артиста на Genius, если поиск по имени не нашел")
    parser.add_argument("--with-features", action="store_true", help="добавлять и песни, где артист гость")
    parser.add_argument("--all", action="store_true",
                        help="ничего не пропускать: добавить и баттлы, и маленькие альбомы как есть")
    args = parser.parse_args()

    token = load_token()
    if not token:
        sys.exit("Не найден токен Genius. Создайте файл .env со строкой GENIUS_TOKEN=ваш_токен "
                 "(инструкция в начале файла genius_import.py).")

    # модели подключаем здесь, чтобы остальной код можно было проверять без базы
    from init_db import create_app
    from models import db, Album, Track

    session = requests.Session()
    artist_id, artist_name = args.artist_id, args.artist
    if not artist_id:
        artist_id, artist_name = find_artist(session, token, args.artist)
        if not artist_id:
            sys.exit(f"Артист «{args.artist}» не найден. Укажите его id: --artist-id 12345")
    print(f"Артист на Genius: {artist_name} (id {artist_id})")

    plan, skipped_features = fetch_plan(session, token, artist_id, args.with_features)
    if not plan:
        sys.exit("Genius не вернул ни одной песни.")
    if not any(p["album"] for p in plan):
        print("Внимание: ни у одной песни Genius не указал альбом, все треки будут без альбома.")

    app = create_app()
    with app.app_context():
        db.create_all()
        albums_by_key = {norm(a.title): a for a in Album.query.all()}
        existing_tracks = {norm(t.title) for t in Track.query.all()}

        new_albums, new_tracks, already, info = build_additions(
            plan, set(albums_by_key), existing_tracks,
            skip_words=[] if args.all else SKIP_ALBUM_WORDS,
            min_tracks=1 if args.all else MIN_ALBUM_TRACKS,
        )
        print_plan(new_albums, new_tracks, already, skipped_features, info)
        if not new_tracks:
            print("Добавлять нечего.")
            return

        answer = input("\nПроверьте список. Названия альбомов совпадают с вашими? Добавить в базу? [y/N] ")
        if answer.strip().lower() not in ("y", "yes", "д", "да"):
            print("Отменено, база не изменена.")
            return

        for a in new_albums:
            album = Album(title=a["title"], year=a["year"])
            db.session.add(album)
            albums_by_key[norm(a["title"])] = album
        db.session.flush()  # чтобы у новых альбомов появились id

        for t in new_tracks:
            album = albums_by_key.get(norm(t["album"])) if t["album"] else None
            db.session.add(Track(title=t["title"], album_id=album.id if album else None))
        db.session.commit()

    print("Готово. Дальше добавьте куплеты в админке (/admin), "
          "а перед отправкой на GitHub выполните: python export_csv.py")


if __name__ == "__main__":
    main()
