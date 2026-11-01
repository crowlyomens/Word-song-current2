import random
import re
from flask import Flask, render_template, request, session, redirect, url_for
from init_db import create_app
from models import db, Album, Track, Verse
from admin_panel import init_admin

app = create_app()
app.secret_key = 'word-song-super-secret-key'
app = create_app()
app.secret_key = 'word-song-super-secret-key'
init_admin(app)

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

    for verse in selected_verses:
        if mode == 'guess_track':
            correct = verse.track.title if verse.track else "Без альбома"
            options = [correct]
            other_tracks = [t for t in all_track_titles if t != correct]
            if len(other_tracks) >= 3:
                options.extend(random.sample(other_tracks, 3))
            else:
                options.extend(["Неизвестный трек"] * (4 - len(options)))
            random.shuffle(options)
            questions.append({'verse_id': verse.id, 'text': verse.text, 'options': options, 'correct': correct, 'mode': 'guess_track'})
            
        elif mode == 'missing_word':
            correct, options = missing_word_options(verse, all_words)
            hidden_text = hide_word(verse.text, correct)
            questions.append({'verse_id': verse.id, 'text': hidden_text, 'options': options, 'correct': correct, 'mode': 'missing_word'})
            
    return questions

@app.route('/')
def index():
    session.clear()
    return render_template('index.html')

@app.route('/setup', methods=['GET', 'POST'])
def setup():
    if request.method == 'POST':
        album_id = request.form.get('album_id')
        mode = request.form.get('mode')
        session['questions'] = generate_questions(album_id, mode)
        session['current_q'] = 0
        session['score'] = 0
        session['correct_count'] = 0
        session['incorrect_count'] = 0
        session['history'] = [] # Список для разбора ответов
        return redirect(url_for('game'))
    albums = Album.query.all()
    return render_template('setup.html', albums=albums)

@app.route('/game', methods=['GET', 'POST'])
def game():
    if 'questions' not in session or session['current_q'] >= len(session['questions']):
        return redirect(url_for('result'))

    if request.method == 'POST':
        user_answer = request.form.get('answer')
        current_q_index = session['current_q']
        q_data = session['questions'][current_q_index]
        
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
            'is_correct': is_correct
        })
        session['history'] = history # Обязательно сохраняем обратно в сессию!
        
        session['current_q'] += 1
        return redirect(url_for('game'))

    current_q_index = session['current_q']
    q_data = session['questions'][current_q_index]
    return render_template('game.html', question=q_data, q_number=current_q_index + 1, total=len(session['questions']))

@app.route('/result')
def result():
    if 'score' not in session:
        return redirect(url_for('index'))
    return render_template('result.html', score=session['score'], correct=session['correct_count'], incorrect=session['incorrect_count'], history=session.get('history', []))

if __name__ == '__main__':
    app.run(debug=True)