import csv
import os
import random
import re
import sys
from collections import Counter

import pymorphy3

from import_csv import read_csv, clean_text
from init_db import BASE_DIR

OUT_FILE = os.path.join(BASE_DIR, "distractors.csv")
WORD_RE = re.compile(r"[А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)*")
# по каким признакам сравниваем форму слова
FEATURES = ("case", "number", "gender", "tense", "person", "mood")

morph = pymorphy3.MorphAnalyzer()


def split_lines(text):
    # список строк куплета, каждая строка это список слов
    return [WORD_RE.findall(line) for line in text.splitlines()]


def describe(word):
    parsed = morph.parse(word.lower())[0]
    info = {"pos": parsed.tag.POS, "lemma": parsed.normal_form}
    for name in FEATURES:
        info[name] = getattr(parsed.tag, name)
    return info


def is_name_in_text(word, text):
    # слово с заглавной буквы не в начале строки: скорее всего имя
    for line in split_lines(text):
        for i, w in enumerate(line):
            if i > 0 and w == word and w[0].isupper():
                return True
    return False


def main():
    if os.path.exists(OUT_FILE) and "--force" not in sys.argv:
        print("Файл distractors.csv уже есть, чтобы не потерять ваши правки, я его не трогаю.")
        print("Чтобы перезаписать: python make_distractors.py --force")
        sys.exit(1)

    verses = read_csv("verses.csv")
    texts = {int(v["id"]): clean_text(v["text"]) for v in verses}
    targets = {int(v["id"]): v["missing_word"].strip() for v in verses}

    # запас слов: все слова из всех куплетов
    vocab = set()
    name_words = set()
    for text in texts.values():
        for line in split_lines(text):
            for i, w in enumerate(line):
                low = w.lower()
                if len(low) >= 3:
                    vocab.add(low)
                    if i > 0 and w[0].isupper():
                        name_words.add(low)
    info = {w: describe(w) for w in vocab}

    rng = random.Random(42)  # фиксированный seed: результат повторяется
    used = Counter()
    rows = []
    to_check = []

    for verse_id in sorted(texts):
        word = targets[verse_id]
        text = texts[verse_id]
        target = describe(word)
        want_name = is_name_in_text(word, text)
        in_text = {w.lower() for line in split_lines(text) for w in line}

        scored = []
        for cand, cinfo in info.items():
            # не берем слова, которые видны в куплете, и однокоренные правильному
            if cand in in_text or cinfo["lemma"] == target["lemma"]:
                continue
            s = 0.0
            if cinfo["pos"] != target["pos"]:
                s -= 10
            for name in FEATURES:
                if target[name] is not None and target[name] == cinfo[name]:
                    s += 2
            s -= abs(len(word) - len(cand)) * 0.5
            if word.lower()[-2:] == cand[-2:]:
                s += 1
            if want_name != (cand in name_words):
                s -= 6
            s -= 0.5 * used[cand]  # чтобы одни и те же слова не повторялись
            scored.append((s, cand, cinfo))

        scored.sort(key=lambda x: (-x[0], x[1]))
        pool = scored[:12]
        chosen = rng.sample(pool, min(3, len(pool)))

        words = []
        for s, cand, cinfo in chosen:
            used[cand] += 1
            # регистр как у правильного слова, чтобы по заглавной не угадывали
            words.append(cand.capitalize() if word[0].isupper() else cand)
        while len(words) < 3:
            words.append("")
        rows.append((verse_id, words))

        if len(chosen) < 3 or any(c[2]["pos"] != target["pos"] for c in chosen):
            to_check.append(verse_id)

        print(f"{verse_id:>3}. {word} -> {', '.join(words)}")

    with open(OUT_FILE, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["verse_id", "d1", "d2", "d3"])
        for verse_id, words in rows:
            writer.writerow([verse_id, *words])

    print(f"\nГотово, файл создан: {OUT_FILE}")
    if to_check:
        print("Посмотрите внимательнее куплеты:", ", ".join(map(str, to_check)))


if __name__ == "__main__":
    main()