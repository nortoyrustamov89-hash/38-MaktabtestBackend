"""Local Gemini backend for the Informatika olimpiada quiz.

1. Set GEMINI_API_KEY and GEMINI_MODEL below.
2. Start with: python backend.py
3. Open http://127.0.0.1:8000/ in a browser. This server also serves the quiz page.

Store API credentials only in environment variables or an untracked local .env
file. Never commit credentials to this repository. For Render, use the service
environment settings; the server binds to the hosting-provided port.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

def load_local_env():
    """Load simple KEY=VALUE entries from a private local .env file."""
    env_path = Path(__file__).with_name(".env")
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip("\"'")
        if name and name not in os.environ:
            os.environ[name] = value


load_local_env()

# Configure these as environment variables in the backend hosting dashboard.
# Never put the Gemini API key in frontend files or commit it to source control.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash").strip()

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))
ALLOWED_ORIGINS = {
    origin.strip().rstrip("/")
    for origin in os.environ.get("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
}
GRADES = {"9", "10", "11"}
TIERS = ((0.9, 10), (1.5, 10), (2.6, 10))
LETTERS = {"A", "B", "C", "D"}
QUESTION_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "tiers": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "ball": {"type": "NUMBER"},
                    "questions": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "text": {"type": "ARRAY", "items": {"type": "STRING"}},
                                "correct": {"type": "STRING", "enum": ["A", "B", "C", "D"]},
                                "explanation": {"type": "STRING"},
                                "options": {
                                    "type": "OBJECT",
                                    "properties": {
                                        letter: {"type": "STRING"} for letter in ("A", "B", "C", "D")
                                    },
                                    "required": ["A", "B", "C", "D"],
                                },
                            },
                            "required": ["text", "correct", "explanation", "options"],
                        },
                    },
                },
                "required": ["ball", "questions"],
            },
        }
    },
    "required": ["tiers"],
}


class BackendError(Exception):
    """An error that can safely be returned to the browser."""


def make_prompt(grade):
    tier_instructions = "\n".join(
        f'- Aynan 10 ta savol; har bir savolda "ball": {ball} bo\'lsin.'
        for ball, _count in TIERS
    )
    return f"""Siz O‘zbekiston maktablari uchun informatika va axborot texnologiyalari o‘qituvchisisiz.
{grade}-sinf darajasiga mos, o‘zbek tilida, aniq va tekshiriladigan olimpiada testini tuzing.
Jami 30 ta turli savol bo‘lsin. Mavzular: algoritmlar, dasturlash asoslari, kompyuter qurilmalari,
ma'lumotlar va fayllar, tarmoqlar, axborot xavfsizligi va raqamli savodxonlik.
Qiyinlikni sinf darajasiga moslang. Har savol uchun faqat bitta to‘g‘ri javob bo‘lsin;
chalg‘ituvchi variantlar ishonarli, ammo noto‘g‘ri bo‘lsin. Savollar va javob variantlari takrorlanmasin.

Ball darajalari va har biridagi savollar soni:
{tier_instructions}
Har savolda text (satrlar ro‘yxati), correct (A/B/C/D), options (A, B, C, D variantlari)
va explanation (to‘g‘ri javob sababini 1–2 sodda o‘zbekcha jumlada tushuntirish) bo‘lsin.
Izoh aynan savol va to‘g‘ri variantga mos, o‘quvchi tushunadigan va qisqa bo‘lsin.
Faqat JSON qaytaring. Kod savollarida kod qatorlarini text massivida alohida satrlar sifatida bering.
"""


def extract_generated_json(gemini_response):
    candidates = gemini_response.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        feedback = gemini_response.get("promptFeedback", {})
        if feedback.get("blockReason"):
            raise BackendError("Gemini so‘rovni xavfsizlik filtri sabab blokladi. Savol matnini qayta urinib ko‘ring.")
        raise BackendError("Gemini bo‘sh javob qaytardi. Model nomi va API kalitini tekshiring.")

    candidate = candidates[0]
    finish_reason = candidate.get("finishReason")
    if finish_reason == "MAX_TOKENS":
        raise BackendError("Gemini javobi uzunlik cheklovida uzildi. Qayta urinib ko‘ring.")
    if finish_reason in {"SAFETY", "RECITATION"}:
        raise BackendError("Gemini javobni xavfsizlik qoidalari sabab to‘xtatdi. Qayta urinib ko‘ring.")

    parts = candidate.get("content", {}).get("parts", [])
    text = "\n".join(
        part["text"] for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str) and not part.get("thought")
    ).strip()
    if not text:
        raise BackendError("Gemini matnli JSON qaytarmadi. Tanlangan modelni tekshiring.")

    # Accept JSON enclosed in Markdown fences or preceded by a short sentence.
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text, flags=re.IGNORECASE)
    start = text.find("{")
    if start < 0:
        raise BackendError("Gemini javobida JSON obyekti topilmadi. Qayta urinib ko‘ring.")
    try:
        parsed, _end = json.JSONDecoder().raw_decode(text[start:])
        return parsed
    except json.JSONDecodeError:
        raise BackendError("Gemini JSON javobi to‘liq yoki to‘g‘ri emas. Qayta urinib ko‘ring.") from None


def validate_questions(data):
    if not isinstance(data, dict) or not isinstance(data.get("tiers"), list):
        raise BackendError("Gemini javobi kutilgan JSON formatida emas.")
    if len(data["tiers"]) != len(TIERS):
        raise BackendError("Gemini uchta ball darajasini qaytarmadi.")

    for tier, (expected_ball, expected_count) in zip(data["tiers"], TIERS):
        if not isinstance(tier, dict) or tier.get("ball") != expected_ball:
            raise BackendError("Gemini ball darajalarini noto‘g‘ri qaytardi.")
        questions = tier.get("questions")
        if not isinstance(questions, list) or len(questions) != expected_count:
            raise BackendError("Har bir ball darajasida 10 tadan savol bo‘lishi kerak.")
        for question_index, question in enumerate(questions, start=1):
            if not isinstance(question, dict):
                raise BackendError("Savol formati noto‘g‘ri.")

            # Models can return equivalent JSON with slightly different field
            # names/shapes; normalize those common variants to the quiz schema.
            text = question.get("text", question.get("question"))
            if isinstance(text, str):
                text = [text]
            if isinstance(text, list):
                question["text"] = text
            options = question.get("options", question.get("choices"))
            if isinstance(options, list) and len(options) == 4:
                options = dict(zip(("A", "B", "C", "D"), options))
                question["options"] = options
            elif isinstance(options, dict):
                normalized_options = {str(key).upper(): value for key, value in options.items()}
                if set(normalized_options) == LETTERS:
                    options = normalized_options
                    question["options"] = options
            correct = question.get(
                "correct",
                question.get("correctAnswer", question.get("correct_answer", question.get("answer"))),
            )
            if isinstance(correct, str):
                correct = correct.strip()
                if isinstance(options, dict) and correct in options.values():
                    correct = next(letter for letter, value in options.items() if value == correct)
                correct = correct.upper()
            elif isinstance(correct, int) and 0 <= correct < 4:
                correct = ("A", "B", "C", "D")[correct]
            question["correct"] = correct
            explanation = question.get("explanation", question.get("explanationText", ""))
            if isinstance(explanation, str):
                question["explanation"] = explanation.strip()

            if (
                not isinstance(text, list)
                or not text
                or not all(isinstance(line, str) and line.strip() for line in text)
                or not isinstance(options, dict)
                or set(options) != LETTERS
                or not all(isinstance(value, str) and value.strip() for value in options.values())
                or correct not in LETTERS
                or not isinstance(explanation, str)
                or not explanation.strip()
            ):
                raise BackendError(
                    f"AI {expected_ball} ballik savollarning {question_index}-savolini noto‘g‘ri formatda qaytardi. Qayta urinib ko‘ring."
                )
    return data


def generate_questions(grade):
    if not GEMINI_API_KEY or GEMINI_API_KEY == "PASTE_YOUR_GEMINI_API_KEY_HERE":
        raise BackendError("Backend hostingidagi GEMINI_API_KEY sozlamasini kiriting.")
    if not GEMINI_MODEL.strip():
        raise BackendError("backend.py ichiga Gemini model nomini kiriting.")

    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        + quote(GEMINI_MODEL.strip(), safe="")
        + ":generateContent"
    )
    payload = {
        "contents": [{"parts": [{"text": make_prompt(grade)}]}],
        "generationConfig": {
            "temperature": 0.8,
            "responseMimeType": "application/json",
            "responseSchema": QUESTION_RESPONSE_SCHEMA,
            "maxOutputTokens": 8192,
        },
    }
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_API_KEY.strip(),
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=90) as response:
            gemini_response = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        # Do not send upstream details to the client; they may reveal configuration.
        if error.code in (401, 403):
            raise BackendError("Gemini API kaliti yoki API ruxsatlarini tekshiring.") from None
        if error.code == 429:
            raise BackendError("Gemini so‘rovlari limiti tugadi. Birozdan keyin urinib ko‘ring.") from None
        raise BackendError(f"Gemini so‘rovi bajarilmadi (HTTP {error.code}).") from None
    except (URLError, TimeoutError):
        raise BackendError("Gemini xizmatiga ulanib bo‘lmadi. Internetni tekshiring.") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise BackendError("Gemini xizmatidan noto‘g‘ri javob keldi.") from None

    return validate_questions(extract_generated_json(gemini_response))


class QuizHandler(BaseHTTPRequestHandler):
    @staticmethod
    def _is_allowed_origin(origin):
        if not origin:
            return True
        if origin.rstrip("/") in ALLOWED_ORIGINS:
            return True
        try:
            parsed = urlsplit(origin)
            return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
        except ValueError:
            return False

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        origin = self.headers.get("Origin")
        if origin and self._is_allowed_origin(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path not in ("/", "/health"):
            self._send_json(404, {"error": "Sahifa topilmadi."})
            return
        self._send_json(200, {"status": "ok", "service": "quiz-api"})

    def do_OPTIONS(self):
        origin = self.headers.get("Origin")
        if not self._is_allowed_origin(origin) or not origin:
            self._send_json(403, {"error": "Bu manbadan so‘rovga ruxsat yo‘q."})
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_POST(self):
        if self.path != "/api/questions":
            self._send_json(404, {"error": "API manzili topilmadi."})
            return
        origin = self.headers.get("Origin")
        if not self._is_allowed_origin(origin):
            self._send_json(403, {"error": "Bu manbadan so‘rovga ruxsat yo‘q."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 2048:
                raise BackendError("So‘rov hajmi noto‘g‘ri.")
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            grade = str(body.get("grade", "")) if isinstance(body, dict) else ""
            if grade not in GRADES:
                raise BackendError("Sinf 9, 10 yoki 11 bo‘lishi kerak.")
            result = generate_questions(grade)
            self._send_json(200, result)
        except BackendError as error:
            self._send_json(400, {"error": str(error)})
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"error": "So‘rov JSON formati noto‘g‘ri."})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self._send_json(500, {"error": "Serverda kutilmagan xatolik yuz berdi."})

    def log_message(self, format_string, *args):
        # Avoid logging request bodies or API credentials.
        super().log_message(format_string, *args)


if __name__ == "__main__":
    print(f"Gemini test API ishga tushdi: {HOST}:{PORT}")
    print("To‘xtatish uchun Ctrl+C bosing.")
    ThreadingHTTPServer((HOST, PORT), QuizHandler).serve_forever()
