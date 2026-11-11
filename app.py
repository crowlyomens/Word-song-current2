import random
import re
import os 
from flask import Flask, render_template, request, session, redirect, url_for
from init_db import create_app
from models import db, Album, Track, Verse
from admin_panel import init_admin

app = create_app()
app.secret_key = 'word-song-super-secret-key'
init_admin(app)


# Шансы бота ответить правильно в зависимости от сложности
BOT_DIFFICULTY = {
    'easy': 0.40,    # Легкий (ошибается часто)
    'normal': 0.65,  # Средний (по умолчанию)
    'hard': 0.85     # Сложный (почти всегда прав)
}
# Специальное значение: игра без бота
BOT_OFF = 'off' 


def hide_word(text, word):
    # прячем слово целиком (а не кусок другого слова), только первое вхождение
    pattern = r"(?<!\w)" + re.escape(word) + r"(?!\w)"
    hidden, count = re.subn(pattern, "______", text, count=1)
    if count == 0:
        # запасной вариант: слово нашлось только внутри другого слова
        hidden = text.replace(word, "______", 1)
    return hidden


def missing_word_options(verse, all_words):
    correct = verse.missing_word
    wrong = []
    if verse.distractors:
        wrong = [w.strip() for w in verse.distractors.split(";") if w.strip()]
        wrong = [w for w in wrong if w != correct]
        if len(wrong) > 3:
            wrong = random.sample(wrong, 3)
    # если подготовленных вариантов не хватает, добираем случайными, как раньше
    if len(wrong) < 3:
        others = [w for w in all_words if w != correct and w not in wrong]
        wrong.extend(random.sample(others, min(3 - len(wrong), len(others))))
    while len(wrong) < 3:
        wrong.append("Слово")
    options = [correct] + wrong
    random.shuffle(options)
    return correct, options


def clean_display_title(title):
    """Убирает переводы в скобках из названия трека для показа в игре."""
    if not title:
        return title
    # Убираем всё в круглых скобках (...) или квадратных [...] в конце строки
    # (включая пробел перед ними)
    cleaned = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]\s*$", "", title)
    return cleaned.strip()


def generate_questions(album_id, mode):
    if album_id == 'random':
        verses = Verse.query.all()
    else:
        verses = Verse.query.join(Track).filter(Track.album_id == album_id).all()
    
    sample_size = min(len(verses), 10)
    selected_verses = random.sample(verses, sample_size)
    questions = []
    
    all_track_titles = [t.title for t in Track.query.all()]
    all_words = list(set([v.missing_word for v in Verse.query.all() if v.missing_word]))

    # --- НОВАЯ ЛОГИКА ВЫБОРА ФОНОВ ---
    # Указываем путь к папке с картинками
    bg_folder = os.path.join(app.static_folder, 'backgrounds')
    available_bgs = []
    
    # Если папка существует, собираем все картинки (jpg, png, jpeg, webp)
    if os.path.exists(bg_folder):
        available_bgs = [
            f for f in os.listdir(bg_folder) 
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))
        ]

    # Выбираем уникальные фоны (без повторов)
    if len(available_bgs) >= sample_size:
        # Если картинок больше или столько же, сколько вопросов — берем уникальные
        selected_bgs = random.sample(available_bgs, sample_size)
    else:
        # Если картинок меньше, чем вопросов (например, 3 картинки на 10 вопросов)
        # Берем все картинки, а остальным вопросам ставим None (без фона), чтобы избежать повторов
        selected_bgs = random.sample(available_bgs, len(available_bgs))
        selected_bgs.extend([None] * (sample_size - len(available_bgs)))
    # ----------------------------------

    for index, verse in enumerate(selected_verses):
        # Берем фон для текущего вопроса по его порядковому номеру
        selected_bg = selected_bgs[index]

        if mode == 'guess_track':
            correct = clean_display_title(verse.track.title) if verse.track else "Без альбома"
            options = [correct]
            other_tracks = [
                clean_display_title(t) for t in all_track_titles
                if clean_display_title(t) != correct
            ]
            if len(other_tracks) >= 3:
                options.extend(random.sample(other_tracks, 3))
            else:
                options.extend(["Неизвестный трек"] * (4 - len(options)))
            random.shuffle(options)
            
            questions.append({
                'verse_id': verse.id, 'text': verse.text, 'options': options, 
                'correct': correct, 'mode': 'guess_track', 
                'background': selected_bg # <-- Передаем уникальный фон
            })
            
        elif mode == 'missing_word':
            correct, options = missing_word_options(verse, all_words)
            hidden_text = hide_word(verse.text, correct)
            
            questions.append({
                'verse_id': verse.id, 'text': hidden_text, 'options': options, 
                'correct': correct, 'mode': 'missing_word',
                'background': selected_bg # <-- Передаем уникальный фон
            })
            
    return questions


def get_bot_answer(options, correct_answer, difficulty):
    """Генерирует ответ бота с заданной вероятностью."""
    chance = BOT_DIFFICULTY.get(difficulty, 0.65)
    if random.random() < chance:
        return correct_answer
    wrong_options = [opt for opt in options if opt != correct_answer]
    return random.choice(wrong_options) if wrong_options else correct_answer


@app.route('/')
def index():
    session.clear()
    return render_template('index.html')


@app.route('/setup', methods=['GET', 'POST'])
def setup():
    if request.method == 'POST':
        album_id = request.form.get('album_id')
        mode = request.form.get('mode')
        difficulty = request.form.get('difficulty', 'normal')

        session['questions'] = generate_questions(album_id, mode)
        session['current_q'] = 0

        # Очки игрока
        session['score'] = 0
        session['correct_count'] = 0
        session['incorrect_count'] = 0

        # Настройки бота (off — игра без бота)
        session['bot_difficulty'] = difficulty
        session['with_bot'] = (difficulty != BOT_OFF)
        session['bot_score'] = 0

        session['history'] = []  # Список для разбора ответов
        return redirect(url_for('game'))
    
    albums = Album.query.all()
    
    # Создаем новый список с очищенными названиями
    clean_albums = []
    for album in albums:
        # 1. Убираем скобки
        clean_title = clean_display_title(album.title)
        # 2. Делаем все слова с большой буквы (.title())
        formatted_title = clean_title.title() 
        
        clean_albums.append({
            'id': album.id, 
            'title': formatted_title
        })
        
    return render_template('setup.html', albums=clean_albums)


@app.route('/game', methods=['GET', 'POST'])
def game():
    if 'questions' not in session or session['current_q'] >= len(session['questions']):
        return redirect(url_for('result'))

    if request.method == 'POST':
        user_answer = request.form.get('answer')
        current_q_index = session['current_q']
        q_data = session['questions'][current_q_index]

        # --- ЛОГИКА БОТА (если он включен) ---
        with_bot = session.get('with_bot', True)
        if with_bot:
            bot_answer = get_bot_answer(
                q_data['options'],
                q_data['correct'],
                session.get('bot_difficulty', 'normal')
            )
            bot_is_correct = (bot_answer == q_data['correct'])
            if bot_is_correct:
                session['bot_score'] += 1
        else:
            bot_answer = None
            bot_is_correct = None
        # -------------------

        is_correct = (user_answer == q_data['correct'])

        if is_correct:
            session['score'] += 1
            session['correct_count'] += 1
        else:
            session['incorrect_count'] += 1

        # Сохраняем историю ответа для отчета
        history = session['history']
        history.append({
            'question': q_data['text'],
            'correct_answer': q_data['correct'],
            'user_answer': user_answer,
            'is_correct': is_correct,
            'bot_answer': bot_answer,
            'bot_is_correct': bot_is_correct
        })
        session['history'] = history

        session['current_q'] += 1
        return redirect(url_for('game'))

    current_q_index = session['current_q']
    q_data = session['questions'][current_q_index]
    return render_template(
        'game.html',
        question=q_data,
        q_number=current_q_index + 1,
        total=len(session['questions'])
    )


@app.route('/result')
def result():
    if 'score' not in session:
        return redirect(url_for('index'))

    total_questions = len(session.get('questions', []))
    user_score = session.get('score', 0)
    with_bot = session.get('with_bot', True)

    if with_bot:
        bot_score = session.get('bot_score', 0)
        if user_score > bot_score:
            winner = 'user'
        elif bot_score > user_score:
            winner = 'bot'
        else:
            winner = 'draw'
    else:
        bot_score = None
        winner = None

    return render_template(
        'result.html',
        score=user_score,
        bot_score=bot_score,
        winner=winner,
        with_bot=with_bot,
        correct=session.get('correct_count', 0),
        incorrect=session.get('incorrect_count', 0),
        history=session.get('history', []),
        total=total_questions
    )


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

