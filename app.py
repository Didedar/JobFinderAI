from flask import Flask, render_template, redirect, request, jsonify, session, flash, url_for
from PyPDF2 import PdfReader
import os
from werkzeug.utils import secure_filename
import re
import requests
import logging
from werkzeug.exceptions import RequestEntityTooLarge
from docx import Document
import secrets
import psutil
from typing import Optional, Tuple
import magic
import chardet
import unicodedata
import google.generativeai as genai
import json
from dotenv import load_dotenv
from typing import TypedDict
import time
from tenacity import retry, stop_after_attempt, wait_exponential
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo

load_dotenv()

process = psutil.Process(os.getpid())
print(f"Memory used: {process.memory_info().rss / 1024 ** 2:.2f} MB")

class Keywords(TypedDict):
    keywords: list[str]
    areas: list[str]
    summary: str

class PDFHandler:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.mime = magic.Magic(mime=True)

    def validate_file(self, file) -> Optional[str]:
        if not file:
            return "No file provided"
        file.seek(0)
        file_bytes = file.read(2048)
        mime_type = self.mime.from_buffer(file_bytes)
        file.seek(0)
        allowed_mimes = {
            'application/pdf': '.pdf',
            'application/msword': '.doc',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx'
        }
        if mime_type not in allowed_mimes:
            return f"Invalid file type. Detected: {mime_type}"
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)
        if size > 16 * 1024 * 1024:
            return "File size exceeds 16MB limit"
        return None

    def extract_text_from_pdf(self, file_path: str) -> Tuple[Optional[str], Optional[str]]:
        try:
            with open(file_path, 'rb') as file:
                reader = PdfReader(file)
                if reader.is_encrypted:
                    return None, "PDF file is encrypted. Please provide an unencrypted PDF."
                extracted_text = []
                for page_num, page in enumerate(reader.pages, 1):
                    try:
                        page_text = page.extract_text()
                        if page_text:
                            encoding = chardet.detect(page_text.encode())['encoding']
                            if encoding and encoding.lower() != 'utf-8':
                                page_text = page_text.encode(encoding).decode('utf-8', errors='ignore')
                            extracted_text.append(page_text)
                    except Exception as e:
                        self.logger.warning(f"Error extracting text from page {page_num}: {str(e)}")
                        continue
                text = "\n".join(extracted_text)
                if not text.strip():
                    return None, "No readable text found in PDF. The file might be scanned or contain only images."
                text = " ".join(line.strip() for line in text.split("\n") if line.strip())
                if len(text) < 50:
                    return None, "Extracted text is too short to be a valid resume."
                return text, None
        except Exception as e:
            error_msg = str(e)
            if "file has not been decrypted" in error_msg.lower():
                return None, "PDF file is encrypted. Please provide an unencrypted PDF."
            elif "pdf header not found" in error_msg.lower():
                return None, "Invalid or corrupted PDF file."
            else:
                self.logger.error(f"Error processing PDF: {error_msg}")
                return None, f"Error processing PDF: {error_msg}"

app = Flask(__name__)

secret_key = secrets.token_hex(32)

app.config['SECRET_KEY'] = secret_key
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

uploads_dir = os.path.join(os.getcwd(), "uploads")
os.makedirs(uploads_dir, exist_ok=True)
app.config["UPLOADS_FOLDER"] = uploads_dir

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Конфигурация приложения
app.config['SECRET_KEY'] = secret_key # Use generated secret key
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///users.db')  # Use DATABASE_URL env var for Heroku etc.
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Инициализация базы данных
db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    user_type = db.Column(db.String(50), nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'

# Класс формы для регистрации
class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(message="Пожалуйста, введите имя пользователя")])
    email = StringField('Email', validators=[DataRequired(message="Пожалуйста, введите email"), Email(message="Неверный формат email")])
    user_type = SelectField('User Type', choices=[('job_seeker', 'Job Seeker'), ('employer', 'Employer')], validators=[DataRequired(message="Пожалуйста, выберите тип пользователя")])
    password = PasswordField('Password', validators=[DataRequired(message="Пожалуйста, введите пароль")])
    password2 = PasswordField('Confirm Password', validators=[DataRequired(message="Пожалуйста, подтвердите пароль"), EqualTo('password', message="Пароли не совпадают")])
    submit = SubmitField('Register')

# Класс формы для входа
class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(message="Пожалуйста, введите имя пользователя")])
    password = PasswordField('Password', validators=[DataRequired(message="Пожалуйста, введите пароль")])
    submit = SubmitField('Sign In')

class FavoriteVacancy(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    vacancy_id = db.Column(db.String(50), nullable=False)
    vacancy_title = db.Column(db.String(200), nullable=False)
    vacancy_company = db.Column(db.String(200), nullable=False)
    vacancy_url = db.Column(db.String(200), nullable=False)
    vacancy_snippet = db.Column(db.Text, nullable=True)
    salary_from = db.Column(db.Integer, nullable=True)
    salary_to = db.Column(db.Integer, nullable=True)
    salary_currency = db.Column(db.String(10), nullable=True)
    employment_type = db.Column(db.String(50), nullable=True)
    experience_level = db.Column(db.String(50), nullable=True)
    location = db.Column(db.String(100), nullable=True)
    similarity_score = db.Column(db.Float, nullable=True)

    def __repr__(self):
        return f'<FavoriteVacancy {self.vacancy_title} for user {self.user_id}>'

with app.app_context():
    db.create_all()

@app.route("/add_to_favorites", methods=["POST"])
def add_to_favorites():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.get_json()
    vacancy_id = data.get("vacancy_id")
    vacancy_title = data.get("vacancy_title")
    vacancy_company = data.get("vacancy_company")
    vacancy_url = data.get("vacancy_url")
    
    # Дополнительные данные для расширенной модели
    vacancy_snippet = data.get("vacancy_snippet")
    
    # Данные о зарплате
    salary = data.get("salary", {})
    salary_from = salary.get("from") if isinstance(salary, dict) else None
    salary_to = salary.get("to") if isinstance(salary, dict) else None
    salary_currency = salary.get("currency") if isinstance(salary, dict) else None
    
    # Дополнительная информация
    employment_type = data.get("employment_type")
    experience_level = data.get("experience_level")
    location = data.get("location")
    similarity_score = data.get("similarity_score")
    
    user = User.query.filter_by(username=session["user"]).first()
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    # Проверка, есть ли уже такая вакансия в избранном
    if FavoriteVacancy.query.filter_by(user_id=user.id, vacancy_id=vacancy_id).first():
        return jsonify({"message": "Vacancy already in favorites"}), 200
    
    # Создание новой записи в избранном
    new_favorite = FavoriteVacancy(
        user_id=user.id,
        vacancy_id=vacancy_id,
        vacancy_title=vacancy_title,
        vacancy_company=vacancy_company,
        vacancy_url=vacancy_url,
        vacancy_snippet=vacancy_snippet,
        salary_from=salary_from,
        salary_to=salary_to,
        salary_currency=salary_currency,
        employment_type=employment_type,
        experience_level=experience_level,
        location=location,
        similarity_score=similarity_score
    )
    
    db.session.add(new_favorite)
    db.session.commit()
    
    return jsonify({"message": "Vacancy added to favorites"}), 200

@app.route("/remove_from_favorites", methods=["POST"])
def remove_from_favorites():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    vacancy_id = data.get("vacancy_id")

    user = User.query.filter_by(username=session["user"]).first()
    if not user:
        return jsonify({"error": "User not found"}), 404

    favorite = FavoriteVacancy.query.filter_by(user_id=user.id, vacancy_id=vacancy_id).first()
    if favorite:
        db.session.delete(favorite)
        db.session.commit()
        return jsonify({"message": "Vacancy removed from favorites"}), 200
    else:
        return jsonify({"message": "Vacancy not found in favorites"}), 404


@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))

    user = User.query.filter_by(username=session["user"]).first()
    if not user:
        return redirect(url_for("login"))

    favorites = FavoriteVacancy.query.filter_by(user_id=user.id).all()
    return render_template("dashboard.html", user=user, favorites=favorites)        

# Replace existing registration route
@app.route("/register", methods=["GET", "POST"])
def register():
    form = RegistrationForm()
    if form.validate_on_submit():
        username = form.username.data
        email = form.email.data
        user_type = form.user_type.data
        password = form.password.data

        # Проверка наличия пользователя с таким именем или email
        existing_user = User.query.filter_by(username=username).first()
        existing_email = User.query.filter_by(email=email).first()
        if existing_user:
            flash("Пользователь с таким именем уже существует", "error")
            return render_template("register.html", form=form)
        if existing_email:
            flash("Email уже зарегистрирован", "error")
            return render_template("register.html", form=form)

        try:
            # Создание нового пользователя
            new_user = User(username=username, email=email, user_type=user_type)
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()
            flash("Регистрация прошла успешно. Теперь вы можете войти в систему.", "success")
            return redirect(url_for("login"))
        except Exception as e:
            db.session.rollback()
            flash("Произошла ошибка при регистрации. Попробуйте позже.", "error")
            return render_template("register.html", form=form)

    return render_template("register.html", form=form)

# Replace existing login route
@app.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data

        try:
            user = User.query.filter_by(username=username).first()
            if user and user.check_password(password):
                session["user"] = username
                flash("Вы успешно вошли в систему", "success")
                return redirect(url_for("index"))
            else:
                flash("Неверное имя пользователя или пароль", "error")
        except Exception as e:
            flash("Произошла ошибка при входе в систему. Попробуйте позже.", "error")

    return render_template("login.html", form=form)

@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("Вы вышли из системы", "success")
    return redirect(url_for("index"))

@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(error):
    return jsonify({"error": "File size exceeds the limit (16MB)"}), 413

@app.route("/")
def index():
    return render_template("index.html")

def preprocess_text(text):
    if not text or not isinstance(text, str):
        return ""

    text = text.translate(str.maketrans("", "", ''.join(chr(i) for i in range(32))))
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"<.*?>", "", text)
    text = re.sub(r"https?://\S+|www\.\S+", "", text)
    text = re.sub(r"[^a-zA-Zа-яА-ЯёЁ\s]", "", text)
    text = text.lower()

    return text

def retry_with_backoff(func):
    """Decorator for retrying functions with exponential backoff"""
    @retry(
        stop=stop_after_attempt(3),  # Maximum 3 attempts
        wait=wait_exponential(multiplier=1, min=4, max=10),  # Wait between 4-10 seconds
        reraise=True
    )
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if "quota" in str(e).lower() or "rate limit" in str(e).lower():
                logger.warning(f"API quota/rate limit hit, waiting before retry: {str(e)}")
                time.sleep(5)  # Additional delay for rate limits
                raise e
            raise e
    return wrapper

@retry_with_backoff
def generate_gemini_content(prompt, model):
    """Wrapper function for Gemini API calls with retry logic"""
    try:
        response = model.generate_content(prompt)
        return response
    except Exception as e:
        logger.error(f"Error in Gemini API call: {str(e)}")
        raise

def detect_profession(text):
    """
    Determines the profession based on the resume text using the Gemini API.
    """
    try:
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            logger.error("GEMINI_API_KEY not found in environment variables")
            return {"profession_ru": "Не определено", "profession_en": "Not determined"}

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.0-flash')

        prompt = f"""
        Analyze the following resume text and determine the most likely profession/job role.
        Return the result as a JSON object with profession name in Russian and English.

        Resume text:
        {text}

        Return only a valid JSON object in the format:
        {{
            "profession_ru": "название профессии",
            "profession_en": "profession name"
        }}

        No explanations, only pure JSON.
        """

        response = generate_gemini_content(prompt, model)
        try:
            result = json.loads(response.text.replace('```json', '').replace('```', ''))
            if not result or not isinstance(result, dict):
                return {"profession_ru": "Не определено", "profession_en": "Not determined"}

            # Проверка наличия обязательных полей
            if not result.get('profession_ru') or not result.get('profession_en'):
                result['profession_ru'] = result.get('profession_ru') or "Не определено"
                result['profession_en'] = result.get('profession_en') or "Not determined"

            return result
        except json.JSONDecodeError:
            logger.error("Failed to parse Gemini API response as JSON")
            logger.debug(f"Raw response: {response.text}")
            return {"profession_ru": "Не определено", "profession_en": "Not determined"}

    except Exception as e:
        logger.error(f"Error in Gemini profession detection: {str(e)}")
        return {"profession_ru": "Не определено", "profession_en": "Not determined"}

def search_vacancies(profession, filters=None):
    """
    Search for vacancies with optional filters including location
    """
    if not profession or not isinstance(profession, dict):
        logger.error("Invalid profession data")
        return []

    base_url = "https://api.hh.ru/vacancies"

    # Получаем текст профессии из объекта
    profession_text = profession.get('profession_ru') or profession.get('profession_en') or ""
    if not profession_text:
        logger.error("No profession text available")
        return []

    params = {
        "area": 40,  # Код для России
        "text": profession_text,
        "search_field": "name",
        "per_page": 100
    }

    # Добавляем фильтры, если они предоставлены
    if filters and isinstance(filters, dict):
        if filters.get('salary_from'):
            try:
                params['salary_from'] = int(filters['salary_from'])
            except (ValueError, TypeError):
                pass

        if filters.get('salary_to'):
            try:
                params['salary_to'] = int(filters['salary_to'])
            except (ValueError, TypeError):
                pass

        if filters.get('currency'):
            params['currency'] = filters['currency']
        if filters.get('employment'):
            params['employment'] = filters['employment']
        if filters.get('experience'):
            params['experience'] = filters['experience']
        if filters.get('location'):
            params['area'] = filters['location']

    try:
        response = requests.get(base_url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        vacancies = []
        for item in data.get("items", []):
            if not item:
                continue

            salary_data = item.get("salary") or {}
            salary = {
                "from": salary_data.get("from"),
                "to": salary_data.get("to"),
                "currency": salary_data.get("currency")
            }

            employer = item.get("employer") or {}
            snippet = item.get("snippet") or {}
            experience = item.get("experience") or {}
            area = item.get("area") or {}
            employment = item.get("employment") or {}

            vacancy = {
                "id": item.get("id"),
                "title": item.get("name"),
                "company": employer.get("name"),
                "url": item.get("alternate_url"),
                "snippet": snippet.get("requirement"),
                "salary": salary,
                "employment_type": employment.get("name"),
                "experience_level": experience.get("name"),
                "location": area.get("name"),
                "source": "hh"
            }
            vacancies.append(vacancy)

        return vacancies

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching vacancies: {str(e)}")
        return []


def compare_texts_with_gemini(resume_text, vacancy_texts):
    """
    Compares the resume text with a BATCH of job vacancy texts using the Gemini API.
    """
    try:
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            logger.error("GEMINI_API_KEY not found in environment variables")
            return {}

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.0-flash')

        vacancies_text_block = "\n\n".join([
            f"Vacancy {i+1}:\n{vacancy_text}"
            for i, vacancy_text in enumerate(vacancy_texts)
        ])

        prompt = f"""
    Compare the following resume with MULTIPLE job vacancies and provide only a similarity score for EACH vacancy.
    Consider the following aspects for each vacancy to determine the similarity score:
    - Required skills match
    - Experience level match
    - Job responsibilities match
    - Overall compatibility

    Resume:
    {resume_text}

    Job Vacancies:
    {vacancies_text_block}

    **IMPORTANT INSTRUCTIONS:**
    You **MUST** respond with **valid JSON ONLY**.
    Do **NOT** include any text, explanations, or any characters outside of the JSON structure.
    The JSON response **MUST** be in the following strict format:

    {{
        "Vacancy 1": {{
            "similarity_score": <score between 0 and 1>
        }},
        "Vacancy 2": {{
            "similarity_score": <score between 0 and 1>
        }},
        "Vacancy 3": {{
            "similarity_score": <score between 0 and 1>
        }},
        "Vacancy 4": {{
            "similarity_score": <score between 0 and 1>
        }},
        "Vacancy 5": {{
            "similarity_score": <score between 0 and 1>
        }}
    }}
    """

        response = generate_gemini_content(prompt, model)
        similarity_scores = {}

        try:
            response_text = response.text.strip()
            if response_text.startswith('```json'):
                response_text = response_text[7:]
            if response_text.endswith('```'):
                response_text = response_text[:-3]
            if response_text.endswith('.'):
                response_text = response_text[:-1]

            response_text = response_text.strip()

            result = json.loads(response_text)

            for i in range(1, len(vacancy_texts) + 1):
                vacancy_key = f"Vacancy {i}"
                if vacancy_key in result and 'similarity_score' in result[vacancy_key]:
                    similarity_scores[vacancy_key] = {'similarity_score': result[vacancy_key]['similarity_score']}
                else:
                    logger.warning(f"Key 'similarity_score' or '{vacancy_key}' not found in Gemini API response for vacancy {i}. Default value 0.0 set.")
                    similarity_scores[vacancy_key] = {'similarity_score': 0.0}

        except json.JSONDecodeError as e:
            logger.error(f"JSON decoding error: {e}, raw response: {response_text}")
            for i in range(len(vacancy_texts)):
                similarity_scores[f"Vacancy {i+1}"] = {'similarity_score': 0.0}

        return similarity_scores

    except Exception as e:
        logger.error(f"Error in Gemini API processing: {str(e)}")
        similarity_scores = {}
        for i in range(len(vacancy_texts)):
            similarity_scores[f"Vacancy {i+1}"] = {'similarity_score': 0.0}
        return similarity_scores

import requests
import logging

logger = logging.getLogger(__name__)


def compute_similarity_scores(resume_text, vacancies):
    """
    Вычисляет схожесть текста резюме с текстами вакансий через Gemini API.
    """
    try:
        if not resume_text or not vacancies:
            logger.error("Empty resume text or vacancies list")
            return {}

        vacancy_texts = []
        for vacancy in vacancies:
            # Check if vacancy is a dictionary
            if isinstance(vacancy, dict):
                title = (vacancy.get('title') or '').strip()
                snippet = (vacancy.get('snippet') or '').strip()
                combined_text = f"{title} {snippet}".strip()
            else:
                # If vacancy is a string, use it directly
                combined_text = str(vacancy).strip()
            
            if combined_text: 
                vacancy_texts.append(combined_text)

        if not vacancy_texts:
            logger.error("No valid vacancy texts found")
            return {}

        similarity_scores = compare_texts_with_gemini(resume_text, vacancy_texts)

        return similarity_scores
            
    except Exception as e:
        logger.error(f"Unexpected error in compute_similarity_scores: {str(e)}")
        return {}

@app.route("/upload", methods=["POST", "GET"])
def upload():
    if request.method == "POST":
        try:
            if "resume" not in request.files:
                return jsonify({"error": "No file part"}), 400

            file = request.files["resume"]
            location = request.form.get("location")
            if location:
                session['initial_location'] = location  # Save initial location

            if file.filename == '':
                return jsonify({"error": "No selected file"}), 400

            pdf_handler = PDFHandler()
            error = pdf_handler.validate_file(file)
            if error:
                return jsonify({"error": error}), 400

            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config["UPLOADS_FOLDER"], filename)

            try:
                file.save(file_path)

                if file.filename.endswith('.pdf'):
                    text, error = pdf_handler.extract_text_from_pdf(file_path)
                    if error:
                        return jsonify({"error": error}), 400
                elif file.filename.endswith(('.doc', '.docx')):
                    try:
                        doc = Document(file_path)
                        text = "\n".join([para.text for para in doc.paragraphs if para.text.strip()])
                        if not text.strip():
                            return jsonify({"error": "No readable text found in document"}), 400
                    except Exception as e:
                        return jsonify({"error": f"Error processing document: {str(e)}"}), 400

                # Сохраняем текст резюме в сессии для использования при фильтрации
                session['resume_text'] = text

                # Определение профессии с защитой от None
                profession = detect_profession(text)
                if not profession or not isinstance(profession, dict):
                    profession = {"profession_ru": "Не определено", "profession_en": "Not determined"}

                # Гарантируем наличие основных полей
                if not profession.get('profession_ru'):
                    profession['profession_ru'] = "Не определено"
                if not profession.get('profession_en'):
                    profession['profession_en'] = "Not determined"

                # Сохраняем профессию в сессии
                session['last_profession'] = profession

                # Поиск вакансий с учетом фильтра местоположения
                filters = {"location": location} if location else None
                vacancies = search_vacancies(profession, filters)

                # Проверка наличия вакансий
                if not vacancies:
                    return jsonify({
                        "message": f"No vacancies found for profession: {profession.get('profession_ru', 'Unknown')}",
                        "suggestions": [
                            "Try broadening your job search",
                            "Consider related positions",
                            "Check back later for new openings"
                        ]
                    }), 404

                # Ограничение количества вакансий
                limited_vacancies = vacancies[:100]  # Ограничиваем до 100, как указано в per_page

                # Подготовка текстов вакансий для сравнения
                vacancy_texts = []
                for v in limited_vacancies:
                    title = v.get('title', '')
                    snippet = v.get('snippet', '')
                    if title or snippet:
                        vacancy_texts.append(f"{title} {snippet}".strip())

                if not vacancy_texts:
                    return jsonify({
                        "error": "No valid vacancy data found"
                    }), 500

                # Сравнение текстов с защитой от ошибок
                similarity_scores = compare_texts_with_gemini(text, vacancy_texts)
                if not similarity_scores:
                    similarity_scores = {f"Vacancy {i+1}": {"similarity_score": 0.0} for i in range(len(limited_vacancies))}

                # Формирование списка вакансий с оценками
                vacancy_list = []
                for i, vacancy in enumerate(limited_vacancies):
                    if vacancy is None:
                        continue

                    vacancy_with_score = vacancy.copy()
                    score_key = f"Vacancy {i+1}"

                    if score_key in similarity_scores:
                        score_info = similarity_scores[score_key]
                        if isinstance(score_info, dict) and 'similarity_score' in score_info:
                            vacancy_with_score['similarity_score'] = float(score_info['similarity_score'])
                        else:
                            vacancy_with_score['similarity_score'] = 0.0
                    else:
                        vacancy_with_score['similarity_score'] = 0.0

                    vacancy_list.append(vacancy_with_score)

                if not vacancy_list:
                    return jsonify({
                        "error": "No valid vacancies could be processed"
                    }), 500

                # Сортировка вакансий по релевантности
                sorted_vacancies = sorted(
                    vacancy_list,
                    key=lambda x: x.get('similarity_score', 0.0),
                    reverse=True
                )

                return jsonify({
                    "profession": profession,
                    "vacancies": sorted_vacancies,
                    "similarity_scores": similarity_scores,
                    "resume_text": text
                })

            except Exception as e:
                logger.error(f"Unexpected error processing file: {str(e)}")
                return jsonify({"error": f"Unexpected error: {str(e)}"}), 500
            finally:
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except Exception as e:
                        logger.error(f"Error removing temporary file: {str(e)}")

        except Exception as e:
            logger.error(f"Unexpected error in upload route: {str(e)}")
            return jsonify({"error": f"Unexpected error: {str(e)}"}), 500

    return render_template("upload.html")

@app.route("/filter-vacancies", methods=["POST"])
def filter_vacancies():
    try:
        if not request.is_json:
            return jsonify({"error": "Invalid request format"}), 400

        filters = request.get_json()

        if filters.get('reset'):  # Сброс фильтров
            location = session.get('initial_location')
            profession = session.get('last_profession')
            params = {
                "per_page": 100,
                "only_with_salary": False
            }
            if profession and isinstance(profession, dict):
                params['text'] = profession.get('profession_ru', '')
            if location:
                params['area'] = location
        else:  # Применение фильтров
            params = {
                "per_page": 100,
                "only_with_salary": True if filters.get('salaryFrom') or filters.get('salaryTo') else False
            }
            if filters.get('salaryFrom'):
                try:
                    params['salary_from'] = int(filters['salaryFrom'])
                except ValueError:
                    pass
            if filters.get('salaryTo'):
                try:
                    params['salary_to'] = int(filters['salaryTo'])
                except ValueError:
                    pass
            if filters.get('salaryCurrency'):
                params['currency'] = filters['salaryCurrency']
            if filters.get('employmentType'):
                params['employment'] = filters['employmentType']
            if filters.get('experienceLevel'):
                params['experience'] = filters['experienceLevel']
            if filters.get('location'):
                params['area'] = filters['location']
            elif session.get('initial_location'):
                params['area'] = session['initial_location']
            if 'last_profession' in session:
                profession = session['last_profession']
                if isinstance(profession, dict):
                    params['text'] = profession.get('profession_ru', '')

        response = requests.get(
            "https://api.hh.ru/vacancies",
            params=params,
            headers={'User-Agent': 'JobFinder/1.0'}
        )
        response.raise_for_status()
        data = response.json()

        # Если есть текст резюме, вычисляем similarity_scores
        if 'resume_text' in session and data.get('items'):
            vacancy_texts = []
            for item in data['items']:
                title = item.get('name', '')
                snippet = item.get('snippet', {}).get('requirement', '')
                combined = f"{title} {snippet}".strip()
                if combined:
                    vacancy_texts.append(combined)

            if vacancy_texts:
                similarity_scores = compute_similarity_scores(session['resume_text'], vacancy_texts)
                for i, item in enumerate(data['items']):
                    score_key = f"Vacancy {i+1}"
                    if score_key in similarity_scores:
                        item['similarity_score'] = float(similarity_scores[score_key]['similarity_score'])
                    else:
                        item['similarity_score'] = 0.0  # Значение по умолчанию

        # Сортировка вакансий по убыванию similarity_score
        if data.get('items'):
            data['items'] = sorted(
                data['items'],
                key=lambda x: x.get('similarity_score', 0.0),
                reverse=True
            )

        return jsonify(data)

    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching vacancies: {str(e)}")
        return jsonify({"error": "Failed to fetch vacancies"}), 500
    except Exception as e:
        logger.error(f"Unexpected error in filter_vacancies: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

def get_area_code_by_country(country_name: str) -> str:
    """
    Функция ищет код area по названию страны.
    Если страна найдена, возвращает её код (str).
    Если нет – возвращает пустую строку.
    """
    url = "https://api.hh.ru/areas"
    response = requests.get(url)
    if (response.status_code != 200):
        raise Exception(f"Ошибка при получении регионов: {response.status_code}")

    areas_json = response.json()

    def search_area(areas, target_name):
        for area in areas:
            # Сравниваем имена без учета регистра и лишних пробелов
            if area.get("name", "").strip().lower() == target_name.strip().lower():
                return area.get("id", "")
            # Если есть вложенные регионы, обходим их рекурсивно
            sub_areas = area.get("areas", [])
            if sub_areas:
                found = search_area(sub_areas, target_name)
                if found:
                    return found
        return ""

    return search_area(areas_json, country_name)

@app.route("/vacancy/<int:vacancy_id>", methods=["GET"])
def get_vacancy_details(vacancy_id):
    try:
        url = f"https://api.hh.ru/vacancies/{vacancy_id}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        vacancy_data = response.json()
        return jsonify(vacancy_data)
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching vacancy details: {str(e)}")
        return jsonify({"error": "Failed to fetch vacancy details"}), 500

@app.route("/analyze-match", methods=["POST"])
def analyze_match():
    try:
        data = request.json
        vacancy = data.get('vacancy', {})
        similarity_score = data.get('similarity_score', 0)
        resume_text = data.get('resume_text', '')

        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            return jsonify({"error": "AI service configuration missing"}), 500

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.0-flash')

        prompt = f"""
Analyze the match between a job seeker's resume and the following job vacancy details. Provide a detailed, analytical, and lengthy evaluation with concrete, actionable insights. Focus on specific skills, experience gaps, and clear recommendations for improvement.

Resume Text:
{resume_text}

Job Vacancy Details:
{vacancy}

Analysis Instructions:
1. Thoroughly evaluate how the candidate's experience, skills, and background align with the job requirements.
2. Identify in detail any gaps in the candidate's qualifications or experience compared to the vacancy's expectations.
3. Provide clear, practical, and specific recommendations for bridging these gaps.
4. Include suggestions for skill development, relevant training, or additional experiences that could improve the candidate's fit.
5. Explain your reasoning in a comprehensive manner.

Output the analysis in the following JSON format:
{{
    "match_assessment": "A detailed evaluation of the candidate's fit (e.g., 'High', 'Moderate', 'Low'), with supporting arguments.",
    "recommendations": [
        "Detailed actionable recommendation 1",
        "Detailed actionable recommendation 2",
        "Detailed actionable recommendation 3"
    ]
}}

Make sure the analysis is extensive, well-structured, and provides a clear rationale for each recommendation.
        """

        response = generate_gemini_content(prompt, model)

        try:
            # Clean the response text by removing markdown code block markers if present
            cleaned_response = response.text.replace('```json', '').replace('```', '').strip()
            analysis = json.loads(cleaned_response)

            # Validate the response has the expected structure
            if not isinstance(analysis, dict):
                raise ValueError("Response is not a dictionary")

            if 'match_assessment' not in analysis or 'recommendations' not in analysis:
                raise ValueError("Missing required fields in response")

            return jsonify(analysis)

        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Invalid AI response format: {response.text}")
            logger.error(f"Error details: {str(e)}")
            return jsonify({
                "match_assessment": "Unable to assess match",
                "recommendations": ["Error processing response", "Please try again later"]
            }), 500

    except Exception as e:
        logger.error(f"Error in analyze_match: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, port=8080)
