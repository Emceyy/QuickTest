from __future__ import annotations

import argparse
import json
import os
import random
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

try:
    import pdfplumber
except ImportError as exc:  # pragma: no cover - user-facing startup check
    raise SystemExit(
        "pdfplumber bulunamadi. Codex bundled Python ile calistirmayi deneyin."
    ) from exc

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - pdfplumber fallback remains available
    PdfReader = None


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "kpss.db"

QUESTION_BANK_FILENAME = "soru bankası baskı.pdf"
TRIALS_FILENAME = "100 DENEME (1).pdf"

QUESTION_BANK_CATEGORY_RANGES = [
    (1, 168, "Kitap - Yazar"),
    (169, 193, "Türk İslam Bilginleri"),
    (194, 233, "Ressam - Tablo"),
    (234, 273, "Dünya Harikaları"),
    (274, 312, "Türkiye'nin UNESCO Dünya Mirası Alanları"),
    (313, 384, "Türkiye'nin UNESCO Dünya Mirası Geçici Listesi"),
    (385, 391, "Türkiye'nin UNESCO Somut Olmayan Kültürel Miras Listesi"),
    (392, 406, "TL Üzerindeki İsimler"),
    (407, 426, "Türkiye'nin Üyesi Olduğu Uluslararası Kuruluşlar"),
    (427, 446, "Güneş Sistemi Gezegenleri"),
    (447, 476, "Türkiye'de İlk Kadınlar"),
    (477, 740, "Genel Kültür Karışık"),
    (741, 777, "Sakin Şehirler, Milli Parklar ve Antik Kentler"),
]

NOISE_LINES = {
    "_",
    "S",
    "P",
    "K",
    "D",
    "O",
    "G",
    "DOK_SSPK",
    "RELEMENED",
    "LECNU",
}

CATEGORY_HEADING_TAILS = {
    "- yazar",
    "turk - islam bilginleri",
    "turk islam bilginleri",
    "dunya harikalari",
    "turkiyenin unesco dunya mirasi alanlari",
    "turkiyenin unesco dunya mirasi gecici listesi",
    "turkiyenin unesco somut olmayan kulturel miras listesi",
    "tl uzerindeki isimler",
    "turkiyenin uyesi oldugu uluslararasi kuruluslar",
    "gunes sistemi gezegenleri",
    "turkiyede ilk kadinlar",
    "genel kultur karisik",
    "sakin sehirler-milli parklar ve antik kentler",
}

TEXT_REPAIRS = [
    (r"(?<=[a-zçğıöşü])(?=[A-ZÇĞİÖŞÜ])", " "),
    (r"\bO\s+([a-zçğıöşü])", r"Ö\1"),
    (r"\bU\s+([a-zçğıöşü])", r"Ü\1"),
    (r"\bI\s+([a-zçğıöşü])", r"İ\1"),
    (r"\bO dü", "Ödü"),
    (r"\bIyi\b", "İyi"),
    (r"\bIyi(?=\s)", "İyi"),
    (r"\bIzmir\b", "İzmir"),
    (r"\bIstanbul\b", "İstanbul"),
    (r"\bIskoç\b", "İskoç"),
    (r"\bIngilizce\b", "İngilizce"),
    (r"\bIslam\b", "İslam"),
    (r"güçlütemsilcilerinden", "güçlü temsilcilerinden"),
    (r"karışkarış", "karış karış"),
    (r"karış karışgezen", "karış karış gezen"),
    (r"Gençyaşına", "Genç yaşına"),
    (r"kurtuluşgünükutlamaları", "kurtuluş günü kutlamaları"),
    (r"yürüyüşügerçekleştirilmiştir", "yürüyüşü gerçekleştirilmiştir"),
    (r"gelişmişekonomilerinden", "gelişmiş ekonomilerinden"),
    (r"gelişmişekonomilerine", "gelişmiş ekonomilerine"),
    (r"köklümedeniyetlerinden", "köklü medeniyetlerinden"),
    (r"Kahramanmaraşilinin", "Kahramanmaraş ilinin"),
    (r"Sarıkamışilçesinde", "Sarıkamış ilçesinde"),
    (r"geçişnoktalarından", "geçiş noktalarından"),
    (r"tanınmışanıtlarından", "tanınmış anıtlarından"),
    (r"kültürünüyaşatmayı", "kültürünü yaşatmayı"),
    (r"Ödülübulunmamaktadır", "Ödülü bulunmamaktadır"),
    (r"sembolüSalyangoz'dur", "sembolü Salyangoz'dur"),
    (r"ünlümonologlarından", "ünlü monologlarından"),
    (r"kötükarakterlerinden", "kötü karakterlerinden"),
    (r"ödülünükazanmıştır", "ödülünü kazanmıştır"),
    (r"Ödülü'nükazanmıştır", "Ödülü'nü kazanmıştır"),
    (r"dülü'nükazanmıştır", "dülü'nü kazanmıştır"),
    (r"düşünürüKınalızade", "düşünürü Kınalızade"),
    (r"statüsükazanmışolup", "statüsü kazanmış olup"),
    (r"girişcümlelerinden", "giriş cümlelerinden"),
    (r"güçlükalemlerinden", "güçlü kalemlerinden"),
    (r"dönüştüğünüanlatan", "dönüştüğünü anlatan"),
    (r"Endülüslüfilozoftur", "Endülüslü filozoftur"),
    (r"tanınmışisimlerinden", "tanınmış isimlerinden"),
    (r"üretilmişparçaların", "üretilmiş parçaların"),
    (r"Yanlışbatılılaşmayı", "Yanlış batılılaşmayı"),
    (r"Floransaşehrindeki", "Floransa şehrindeki"),
    (r"Kudüs’üHaçlılardan", "Kudüs’ü Haçlılardan"),
    (r"KurtuluşSavaşı'nın", "Kurtuluş Savaşı'nın"),
    (r"ÜçIstanbul", "Üç İstanbul"),
    (r"ÜçTelli", "Üç Telli"),
    (r"ÜnlüOsmanlı", "Ünlü Osmanlı"),
    (r"ÜnlüTürk", "Ünlü Türk"),
    (r"üstünlüğünüsürdürerek", "üstünlüğünü sürdürerek"),
    (r"figürlükompozisyonun", "figürlü kompozisyonun"),
    (r"figürlükompozisyonlarındaki", "figürlü kompozisyonlarındaki"),
    (r"öncüsüolan", "öncüsü olan"),
    (r"ölüdoğa", "ölü doğa"),
    (r"(mış|miş|muş|müş)ve\b", r"\1 ve"),
]


@dataclass
class ParsedQuestion:
    source: str
    question_key: str
    source_question_no: int | None
    category_id: int | None
    trial_no: int | None
    trial_question_no: int | None
    page_no: int
    prompt: str
    options: dict[str, str]
    correct_answer: str
    explanation: str
    raw_text: str
    needs_review: bool
    review_notes: list[str]


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = value.replace("\x00", "")
    value = unicodedata.normalize("NFC", value)
    value = value.replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")
    return value


def compact_spaces(value: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines).strip()


def clean_trial_noise(value: str) -> str:
    kept: list[str] = []
    for line in normalize_text(value).splitlines():
        line = line.strip()
        if not line:
            continue
        if line in NOISE_LINES:
            continue
        if re.fullmatch(r"Gü\s*ncel Bilgile", line, flags=re.I):
            continue
        if re.fullmatch(r"er Deneme\s+\d{1,3}", line, flags=re.I):
            continue
        kept.append(line)
    return "\n".join(kept)


def clean_pypdf_trial_text(value: str) -> str:
    kept: list[str] = []
    for line in normalize_text(value).splitlines():
        line = line.strip()
        if not line:
            continue
        if line in NOISE_LINES or line in {"P", "S"}:
            continue
        if re.fullmatch(r"KPSS_KOD\s+G.?NCEL\s+DENEMELER", line, flags=re.I):
            continue
        if re.fullmatch(r"Güncel Bilgiler Deneme\s+\d{1,3}", line, flags=re.I):
            continue
        kept.append(line)
    return "\n".join(kept)


def clean_pdf_spacing(value: str) -> str:
    value = compact_spaces(value)
    value = re.sub(r"([A-E])\)\s*", r"\1) ", value)
    value = re.sub(r"\s+([?.!,;:])", r"\1", value)
    value = repair_text(value)
    return value.strip()


def repair_text(value: str) -> str:
    for pattern, replacement in TEXT_REPAIRS:
        value = re.sub(pattern, replacement, value)
    return value


def normalized_tail(value: str) -> str:
    value = unicodedata.normalize("NFKD", normalize_text(value)).casefold()
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.replace("ı", "i")
    value = value.replace("’", "").replace("'", "")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def strip_category_heading_tail(value: str) -> tuple[str, bool]:
    lines = value.splitlines()
    changed = False
    while len(lines) > 1 and normalized_tail(lines[-1]) in CATEGORY_HEADING_TAILS:
        lines.pop()
        changed = True
    return "\n".join(lines).strip(), changed


def find_pdf(filename: str, env_name: str) -> Path:
    env_path = os.environ.get(env_name)
    if env_path and Path(env_path).exists():
        return Path(env_path)

    local_path = BASE_DIR / filename
    if local_path.exists():
        return local_path

    docs_dir = Path.home() / "Documents"
    if docs_dir.exists():
        for path in docs_dir.rglob(filename):
            return path

    raise FileNotFoundError(
        f"{filename} bulunamadi. {env_name} ortam degiskeniyle PDF yolunu verebilirsiniz."
    )


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def create_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        DROP TABLE IF EXISTS attempts;
        DROP TABLE IF EXISTS wrong_questions;
        DROP TABLE IF EXISTS study_state;
        DROP TABLE IF EXISTS import_report;
        DROP TABLE IF EXISTS questions;
        DROP TABLE IF EXISTS categories;

        CREATE TABLE categories (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            start_question INTEGER NOT NULL,
            end_question INTEGER NOT NULL
        );

        CREATE TABLE questions (
            id INTEGER PRIMARY KEY,
            question_key TEXT NOT NULL UNIQUE,
            source TEXT NOT NULL,
            source_question_no INTEGER,
            category_id INTEGER REFERENCES categories(id),
            trial_no INTEGER,
            trial_question_no INTEGER,
            page_no INTEGER NOT NULL,
            prompt TEXT NOT NULL,
            option_a TEXT NOT NULL,
            option_b TEXT NOT NULL,
            option_c TEXT NOT NULL,
            option_d TEXT NOT NULL,
            option_e TEXT NOT NULL,
            correct_answer TEXT NOT NULL,
            explanation TEXT NOT NULL DEFAULT '',
            raw_text TEXT NOT NULL,
            needs_review INTEGER NOT NULL DEFAULT 0,
            review_notes TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT NOT NULL
        );

        CREATE INDEX idx_questions_source ON questions(source);
        CREATE INDEX idx_questions_category ON questions(category_id);
        CREATE INDEX idx_questions_trial ON questions(trial_no, trial_question_no);
        CREATE INDEX idx_questions_review ON questions(needs_review);

        CREATE TABLE attempts (
            id INTEGER PRIMARY KEY,
            question_id INTEGER NOT NULL REFERENCES questions(id),
            session_id TEXT NOT NULL,
            mode TEXT NOT NULL,
            selected_answer TEXT,
            is_correct INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX idx_attempts_question ON attempts(question_id);
        CREATE INDEX idx_attempts_created_at ON attempts(created_at);

        CREATE TABLE wrong_questions (
            id INTEGER PRIMARY KEY,
            question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
            bucket TEXT NOT NULL CHECK(bucket IN ('test', 'trial')),
            wrong_count INTEGER NOT NULL DEFAULT 1,
            last_mode TEXT NOT NULL,
            last_selected_answer TEXT,
            last_wrong_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(question_id, bucket)
        );

        CREATE INDEX idx_wrong_questions_bucket ON wrong_questions(bucket);
        CREATE INDEX idx_wrong_questions_question ON wrong_questions(question_id);

        CREATE TABLE study_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE import_report (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )


def seed_categories(con: sqlite3.Connection) -> dict[int, int]:
    category_for_question: dict[int, int] = {}
    for idx, (start, end, title) in enumerate(QUESTION_BANK_CATEGORY_RANGES, start=1):
        con.execute(
            "INSERT INTO categories (id, title, start_question, end_question) VALUES (?, ?, ?, ?)",
            (idx, title, start, end),
        )
        for number in range(start, end + 1):
            category_for_question[number] = idx
    return category_for_question


def page_columns(page) -> tuple[str, str]:
    x0, top, x1, bottom = page.bbox
    mid = (x0 + x1) / 2
    left = page.crop((x0, top, mid, bottom)).extract_text(x_tolerance=1, y_tolerance=3)
    right = page.crop((mid, top, x1, bottom)).extract_text(x_tolerance=1, y_tolerance=3)
    return normalize_text(left), normalize_text(right)


def split_question_bank_blocks(text: str) -> list[tuple[int, str]]:
    pattern = re.compile(
        r"(?m)^\s*(?:Soru\s*)?(\d{1,3})\s*(?:\.|(?=[\"“A-ZÇĞİÖŞÜ]))"
    )
    matches = list(pattern.finditer(text))
    blocks: list[tuple[int, str]] = []
    for idx, match in enumerate(matches):
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        blocks.append((int(match.group(1)), text[match.start() : end].strip()))
    return blocks


def split_expected_blocks(text: str, numbers: Iterable[int]) -> list[tuple[int, str]]:
    expected = list(numbers)
    number_pattern = "|".join(str(number) for number in expected)
    raw_starts = [
        (int(match.group(1)), match.start())
        for match in re.finditer(rf"(?m)^\s*({number_pattern})(?!\d)\s*[\.\)]?", text)
    ]
    raw_starts.sort(key=lambda item: item[1])
    starts = raw_starts[: len(expected)]
    if len(starts) == len(expected):
        # Some PDF pages contain a typo such as two "2." labels. The visual order is still right.
        starts = [(expected[idx], start) for idx, (_, start) in enumerate(starts)]
    blocks: list[tuple[int, str]] = []
    for idx, (number, start) in enumerate(starts):
        end = starts[idx + 1][1] if idx + 1 < len(starts) else len(text)
        blocks.append((number, text[start:end].strip()))
    return blocks


def split_pypdf_trial_blocks(text: str, trial_no: int) -> list[tuple[int, str]]:
    if trial_no == 63:
        text = re.sub(r"(?m)^\s*11\.", "1.", text, count=1)
    matches = list(re.finditer(r"(?m)^\s*([1-6])(?!\d)\s*[\.\)]?", text))
    blocks: list[tuple[int, str]] = []
    for idx, match in enumerate(matches):
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        blocks.append((int(match.group(1)), text[match.start() : end].strip()))
    numbers = [number for number, _ in blocks]
    if len(blocks) == 6 and set(numbers) != {1, 2, 3, 4, 5, 6}:
        blocks = [(idx + 1, block) for idx, (_, block) in enumerate(blocks)]
    return sorted(blocks, key=lambda item: item[0])


def trial_blocks_are_complete(blocks: list[tuple[int, str]]) -> bool:
    if len(blocks) != 6:
        return False
    if [number for number, _ in blocks] != [1, 2, 3, 4, 5, 6]:
        return False
    for _, block in blocks:
        if len(re.findall(r"(?<!\w)([A-E])\)\s*", block)) < 5:
            return False
    return True


def apply_known_question_bank_fixes(question_no: int, raw: str) -> tuple[str, list[str]]:
    notes: list[str] = []
    fixed = raw
    if question_no == 406 and "\nYalnız I\nB)" in fixed:
        fixed = fixed.replace("\nYalnız I\nB)", "\nA) Yalnız I\nB)")
        notes.append("PDF'de A secenek etiketi eksikti; importer A) olarak tamamladi.")
    if question_no == 406 and "Türkiye’nin Üyesi Olduğu Uluslararası" in fixed:
        fixed = re.sub(
            r"\nTürkiye’nin Üyesi Olduğu Uluslararası\nKuruluşlar\s*$",
            "",
            fixed,
        )
        notes.append("Sonraki kategori basligi secenek metninden ayrildi.")
    if question_no == 554 and "\nA) Sabahattin Ali" in fixed:
        fixed = fixed.replace("\nA) Sabahattin Ali", "\nE) Sabahattin Ali")
        notes.append("PDF'de son secenek A) yazilmis; importer E) olarak duzeltti.")
    if question_no == 603 and "\nA) Hırvatistan" in fixed:
        fixed = fixed.replace("\nA) Hırvatistan", "\nE) Hırvatistan")
        notes.append("PDF'de son secenek A) yazilmis; importer E) olarak duzeltti.")
    return fixed, notes


def parse_question_text(raw: str, question_no: int | None = None) -> tuple[str, dict[str, str], list[str]]:
    notes: list[str] = []
    text = clean_pdf_spacing(raw)
    label_matches = list(re.finditer(r"(?<!\w)([A-E])\)\s*", text))

    if len(label_matches) < 5:
        notes.append(f"{len(label_matches)} secenek etiketi bulundu; 5 bekleniyordu.")
    if len(label_matches) > 5:
        label_matches = label_matches[:5]
        notes.append("5'ten fazla secenek etiketi bulundu; ilk 5 secenek kullanildi.")

    prompt = text
    options = {letter: "" for letter in "ABCDE"}
    if label_matches:
        prompt = text[: label_matches[0].start()]
        labels = [match.group(1) for match in label_matches]
        if labels != list("ABCDE")[: len(labels)]:
            notes.append(f"Secenek etiketleri siradisi: {', '.join(labels)}.")
        for idx, match in enumerate(label_matches[:5]):
            end = label_matches[idx + 1].start() if idx + 1 < len(label_matches) else len(text)
            target_letter = "ABCDE"[idx] if labels != list("ABCDE")[: len(labels)] else match.group(1)
            options[target_letter] = clean_pdf_spacing(text[match.end() : end])

    prompt = re.sub(r"^(?:Soru\s*)?\d{1,3}\s*[\.\)]?\s*", "", prompt).strip()
    prompt = clean_pdf_spacing(prompt)
    for letter in "ABCDE":
        options[letter] = clean_pdf_spacing(options[letter])
        if not options[letter]:
            notes.append(f"{letter} secenegi bos gorunuyor.")

    if question_no and not prompt:
        notes.append(f"{question_no} numarali soru metni bos gorunuyor.")

    return prompt, options, notes


def parse_question_bank_answers(pdf) -> dict[int, str]:
    answer_text = "\n".join(
        normalize_text(pdf.pages[index].extract_text(x_tolerance=1, y_tolerance=3))
        for index in range(100, 104)
    )
    return {
        int(number): answer
        for number, answer in re.findall(r"(\d{1,3})\s*-\s*([A-E])", answer_text)
    }


def category_id_for_question(question_no: int, category_map: dict[int, int]) -> int | None:
    return category_map.get(question_no)


def extract_question_bank_questions(
    pdf_path: Path, category_map: dict[int, int]
) -> tuple[list[ParsedQuestion], dict[str, object]]:
    questions: list[ParsedQuestion] = []
    report: dict[str, object] = {}
    with pdfplumber.open(pdf_path) as pdf:
        answers = parse_question_bank_answers(pdf)
        seen_numbers: set[int] = set()
        for page_index in range(0, 100):
            left, right = page_columns(pdf.pages[page_index])
            page_text = "\n".join([left, right])
            for question_no, raw_block in split_question_bank_blocks(page_text):
                fixed_block, fix_notes = apply_known_question_bank_fixes(question_no, raw_block)
                prompt, options, parse_notes = parse_question_text(fixed_block, question_no)
                correct = answers.get(question_no, "")
                notes = fix_notes + parse_notes
                if not correct:
                    notes.append("Cevap anahtarinda karsilik bulunamadi.")
                if question_no in seen_numbers:
                    notes.append("Soru numarasi tekrar ediyor.")
                seen_numbers.add(question_no)
                questions.append(
                    ParsedQuestion(
                        source="question_bank",
                        question_key=f"qb-{question_no}",
                        source_question_no=question_no,
                        category_id=category_id_for_question(question_no, category_map),
                        trial_no=None,
                        trial_question_no=None,
                        page_no=page_index + 1,
                        prompt=prompt,
                        options=options,
                        correct_answer=correct,
                        explanation="",
                        raw_text=raw_block,
                        needs_review=bool(notes),
                        review_notes=notes,
                    )
                )

        postprocess_question_bank_questions(questions)
        missing_questions = [number for number in range(1, 778) if number not in seen_numbers]
        missing_answers = [number for number in range(1, 778) if number not in answers]
        report = {
            "pdf": str(pdf_path),
            "questions_found": len(questions),
            "unique_questions": len(seen_numbers),
            "answers_found": len(answers),
            "missing_questions": missing_questions,
            "missing_answers": missing_answers,
            "needs_review": sum(1 for question in questions if question.needs_review),
        }
    return questions, report


def postprocess_question_bank_questions(questions: list[ParsedQuestion]) -> None:
    by_number = {question.source_question_no: question for question in questions}
    for question in questions:
        for letter in "ABCDE":
            cleaned, changed = strip_category_heading_tail(question.options.get(letter, ""))
            if changed:
                question.options[letter] = cleaned

    q497 = by_number.get(497)
    q498 = by_number.get(498)
    if q497 and q498 and "Timur Devleti" in q497.options.get("E", ""):
        option, paragraph = q497.options["E"].split("\nTimur Devleti", 1)
        paragraph = "Timur Devleti" + paragraph
        q497.options["E"] = option.strip()
        if not q498.prompt.startswith("Timur Devleti"):
            q498.prompt = clean_pdf_spacing(f"{paragraph}\n{q498.prompt}")


def parse_trial_answer_key(pdf) -> dict[tuple[int, int], str]:
    answer_text = "\n".join(
        normalize_text(pdf.pages[index].extract_text(x_tolerance=1, y_tolerance=3))
        for index in range(194, 199)
    )
    entries: dict[tuple[int, int], str] = {}
    starts = list(re.finditer(r"Deneme\s+(\d{1,3})", answer_text, flags=re.I))
    for idx, match in enumerate(starts):
        trial_no = int(match.group(1))
        end = starts[idx + 1].start() if idx + 1 < len(starts) else len(answer_text)
        chunk = answer_text[match.end() : end]
        for question_no, answer in re.findall(r"([1-6])\s*-\s*([A-E])", chunk):
            entries[(trial_no, int(question_no))] = answer
    return entries


def solution_heading_pattern() -> re.Pattern[str]:
    return re.compile(
        r"DENEME\s*(\d{1,3})\s*(?:Ç|Ç|C)\s*(?:Ö|Ö|O)\s*Z\s*(?:Ü|Ü|U)\s*M",
        flags=re.I,
    )


def solution_answer_pattern() -> re.Pattern[str]:
    return re.compile(r"(?:Cevap|Çözüm)\s*:?\s*([A-E])", flags=re.I)


def clean_solution_text(value: str) -> str:
    value = re.sub(r"^\s*[1-6]\s*[\.\)]?\s*", "", value.strip())
    value = re.sub(r"\n{3,}", "\n\n", value)
    return clean_pdf_spacing(value)


def collapse_spaced_pdf_line(line: str) -> str:
    groups = re.split(r" {2,}", line.rstrip())
    collapsed: list[str] = []
    for group in groups:
        tokens = group.split(" ")
        if len(tokens) > 1 and sum(1 for token in tokens if len(token) <= 2) / len(tokens) > 0.65:
            collapsed.append("".join(tokens))
        else:
            collapsed.append(group)
    return " ".join(group for group in collapsed if group)


def clean_pypdf_solution_pages(reader: PdfReader, start: int = 101, end: int = 194) -> str:
    pages: list[str] = []
    for index in range(start, end):
        raw = normalize_text(reader.pages[index].extract_text() or "")
        pages.append("\n".join(collapse_spaced_pdf_line(line) for line in raw.splitlines()))
    return normalize_text("\n".join(pages))


def split_trial_solutions(solution_text: str) -> dict[tuple[int, int], str] | None:
    headings = list(solution_heading_pattern().finditer(solution_text))
    if len(headings) != 100:
        return None

    solutions: dict[tuple[int, int], str] = {}
    for idx, heading in enumerate(headings):
        trial_no = int(heading.group(1))
        start = heading.end()
        end = headings[idx + 1].start() if idx + 1 < len(headings) else len(solution_text)
        chunk = solution_text[start:end].strip()
        answer_matches = list(solution_answer_pattern().finditer(chunk))
        if len(answer_matches) < 6:
            return None
        cursor = 0
        for question_index, answer_match in enumerate(answer_matches[:6], start=1):
            segment = chunk[cursor : answer_match.end()]
            cursor = answer_match.end()
            solutions[(trial_no, question_index)] = clean_solution_text(segment)

    if len(solutions) != 600:
        return None
    return solutions


def parse_trial_solutions(pdf) -> dict[tuple[int, int], str]:
    pdf_path = getattr(getattr(pdf, "stream", None), "name", None)
    if PdfReader and pdf_path:
        try:
            reader = PdfReader(str(pdf_path))
            clean_solution_text_from_pypdf = clean_pypdf_solution_pages(reader)
            pypdf_solutions = split_trial_solutions(clean_solution_text_from_pypdf)
            if pypdf_solutions:
                return pypdf_solutions
        except Exception:
            pass

    solution_text = "\n".join(
        normalize_text(pdf.pages[index].extract_text(x_tolerance=1, y_tolerance=3))
        for index in range(101, 194)
    )
    return split_trial_solutions(solution_text) or {}


def extract_trial_questions(pdf_path: Path) -> tuple[list[ParsedQuestion], dict[str, object]]:
    questions: list[ParsedQuestion] = []
    pypdf_reader = PdfReader(str(pdf_path)) if PdfReader else None
    with pdfplumber.open(pdf_path) as pdf:
        answer_key = parse_trial_answer_key(pdf)
        solutions = parse_trial_solutions(pdf)
        for trial_no in range(1, 101):
            blocks: list[tuple[int, str]] = []
            if pypdf_reader is not None:
                pypdf_text = clean_pypdf_trial_text(pypdf_reader.pages[trial_no].extract_text() or "")
                pypdf_blocks = split_pypdf_trial_blocks(pypdf_text, trial_no)
                if trial_blocks_are_complete(pypdf_blocks):
                    blocks = pypdf_blocks

            if not blocks:
                page = pdf.pages[trial_no]
                left, right = page_columns(page)
                left = clean_trial_noise(left)
                right = clean_trial_noise(right)
                if trial_no == 63:
                    left = re.sub(r"(?m)^\s*11\.", "1.", left, count=1)
                blocks = split_expected_blocks(left, [1, 2, 3]) + split_expected_blocks(right, [4, 5, 6])
            found_numbers = {number for number, _ in blocks}
            for missing in sorted(set(range(1, 7)) - found_numbers):
                raw = ""
                prompt = ""
                options = {letter: "" for letter in "ABCDE"}
                notes = [f"Deneme {trial_no} soru {missing} metni otomatik bolunemedi."]
                correct = answer_key.get((trial_no, missing), "")
                questions.append(
                    ParsedQuestion(
                        source="trial",
                        question_key=f"trial-{trial_no}-{missing}",
                        source_question_no=None,
                        category_id=None,
                        trial_no=trial_no,
                        trial_question_no=missing,
                        page_no=trial_no + 1,
                        prompt=prompt,
                        options=options,
                        correct_answer=correct,
                        explanation=solutions.get((trial_no, missing), ""),
                        raw_text=raw,
                        needs_review=True,
                        review_notes=notes,
                    )
                )
            for question_no, raw_block in blocks:
                prompt, options, parse_notes = parse_question_text(raw_block, question_no)
                correct = answer_key.get((trial_no, question_no), "")
                notes = parse_notes
                if not correct:
                    notes.append("Deneme cevap anahtarinda karsilik bulunamadi.")
                explanation = solutions.get((trial_no, question_no), "")
                if not explanation:
                    notes.append("Deneme cozum metni bulunamadi.")
                questions.append(
                    ParsedQuestion(
                        source="trial",
                        question_key=f"trial-{trial_no}-{question_no}",
                        source_question_no=None,
                        category_id=None,
                        trial_no=trial_no,
                        trial_question_no=question_no,
                        page_no=trial_no + 1,
                        prompt=prompt,
                        options=options,
                        correct_answer=correct,
                        explanation=explanation,
                        raw_text=raw_block,
                        needs_review=bool(notes),
                        review_notes=notes,
                    )
                )

    questions.sort(key=lambda item: (item.trial_no or 0, item.trial_question_no or 0))
    found = {(question.trial_no, question.trial_question_no) for question in questions}
    report = {
        "pdf": str(pdf_path),
        "questions_found": len(questions),
        "answers_found": len(answer_key),
        "expected_questions": 600,
        "missing_questions": [
            [trial_no, question_no]
            for trial_no in range(1, 101)
            for question_no in range(1, 7)
            if (trial_no, question_no) not in found
        ],
        "needs_review": sum(1 for question in questions if question.needs_review),
    }
    return questions, report


def insert_questions(con: sqlite3.Connection, questions: Iterable[ParsedQuestion]) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    for question in questions:
        con.execute(
            """
            INSERT INTO questions (
                question_key, source, source_question_no, category_id, trial_no, trial_question_no,
                page_no, prompt, option_a, option_b, option_c, option_d, option_e,
                correct_answer, explanation, raw_text, needs_review, review_notes, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                question.question_key,
                question.source,
                question.source_question_no,
                question.category_id,
                question.trial_no,
                question.trial_question_no,
                question.page_no,
                question.prompt,
                question.options.get("A", ""),
                question.options.get("B", ""),
                question.options.get("C", ""),
                question.options.get("D", ""),
                question.options.get("E", ""),
                question.correct_answer,
                question.explanation,
                question.raw_text,
                1 if question.needs_review else 0,
                json.dumps(question.review_notes, ensure_ascii=False),
                now,
            ),
        )


def save_report(con: sqlite3.Connection, report: dict[str, object]) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    for key, value in report.items():
        con.execute(
            "INSERT INTO import_report (key, value, updated_at) VALUES (?, ?, ?)",
            (key, json.dumps(value, ensure_ascii=False), now),
        )


def import_all(db_path: Path = DB_PATH) -> dict[str, object]:
    DATA_DIR.mkdir(exist_ok=True)
    question_bank_pdf = find_pdf(QUESTION_BANK_FILENAME, "KPSS_QUESTION_BANK_PDF")
    trials_pdf = find_pdf(TRIALS_FILENAME, "KPSS_TRIALS_PDF")

    con = connect(db_path)
    create_schema(con)
    category_map = seed_categories(con)

    question_bank_questions, question_bank_report = extract_question_bank_questions(
        question_bank_pdf, category_map
    )
    trial_questions, trial_report = extract_trial_questions(trials_pdf)
    insert_questions(con, question_bank_questions)
    insert_questions(con, trial_questions)

    total_questions = len(question_bank_questions) + len(trial_questions)
    all_ids = [row["id"] for row in con.execute("SELECT id FROM questions")]
    random.shuffle(all_ids)
    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "database": str(db_path),
        "question_bank": question_bank_report,
        "trials": trial_report,
        "total_questions": total_questions,
        "total_needs_review": sum(
            1 for row in con.execute("SELECT id FROM questions WHERE needs_review = 1")
        ),
    }
    save_report(con, report)
    con.execute(
        "INSERT INTO study_state (key, value, updated_at) VALUES (?, ?, ?)",
        ("karma_used_ids", "[]", datetime.now().isoformat(timespec="seconds")),
    )
    con.commit()
    con.close()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="KPSS PDF importer")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="SQLite veritabani yolu")
    args = parser.parse_args()
    report = import_all(args.db)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
