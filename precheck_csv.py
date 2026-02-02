# ===============================
# PRECHECK: предварительная проверка CSV
# ================================
# Назначение:
#   1) Собрать ВСЕ ошибки формата (кодировка, разделитель, заголовки)
#   2) Собрать ошибки заполнения (пустые обязательные поля) и базовую логику методов проверки
#   3) Если возможно БЕЗ двусмысленности — запустить основной валидатор (main.py validate) на временной копии
#
# Важно:
#   - Исходный CSV НЕ изменяется
#   - Отчёты сохраняются в папку reports рядом с входными файлами (или в указанную --reports-dir)
#   - main.py запускать вручную больше не нужно — этот скрипт сам вызовет его "под капотом"
# ==============================

import argparse
import csv
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from collections import defaultdict

from services.report_service import ReportService
from config.columns import (
    COLUMN_NAMES,
    REQUIRED_COLUMNS,
    VALID_PROTOCOLS,
    VALID_CHECK_METHODS,
)

# Какие разделители пытаемся распознать
DELIMS = ["|", ";", ",", "\t"]


# ----------------------------
# Чтение файла с возможно разными кодировками (вдруг не utf-8)
# --------------------------


def detect_encoding_and_text(path: Path) -> tuple[str, str]:
    """
    Пытаемся прочитать файл в разных кодировках.
    Возвращаем (кодировка, текст).
    """
    raw = path.read_bytes()

    # Сначала пробуем норму по ТЗ: UTF-8
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return enc, raw.decode(enc)
        except UnicodeDecodeError:
            pass
    # Фолбэки (в реальности часто встречаются)
    for enc in ("cp1251", "cp866", "latin-1"):
        try:
            return enc, raw.decode(enc, errors="replace")
        except Exception:
            continue
    # Последний шанс - не упасть вообще
    return "unknown", raw.decode("utf-8", errors="replace")


# -------------------------------------------------
# Работа с разделителем и заголовками
# -------------------------------------------------
def detect_delimiter(header_line: str) -> tuple[str | None, dict]:
    """
    Определяем разделитель по строке заголовков.
    Всегда возвращаем (delim, counts).
    Если разделитель не найден - delim = None
    """
    counts = {d: header_line.count(d) for d in DELIMS}
    best = max(counts, key=counts.get)
    if counts[best] == 0:
        return None, counts
    return best, counts


def split_header(header_line: str, delim: str) -> list[str]:
    """
    Разбиваем строку заголовков на колонки.
    """
    return [h.strip().replace("\ufeff", "") for h in header_line.rstrip().split(delim)]


def parse_rows(text: str, delim: str) -> tuple[list[list[str]], list[str]]:
    """
    Разбираем CSV в строки.
    """
    lines = text.splitlines()
    if not lines:
        return [], []

    header = split_header(lines[0], delim)
    reader = csv.reader(lines, delimiter=delim)
    rows = list(reader)
    return rows[1:], header


# -------------------------------------------------
# Сравнение и нормализация заголовков
# -------------------------------------------------


def norm(s: str) -> str:
    """
    Нормализация строки для мягкого сравнения:
    без BOM, без лишних пробелов, без учёта регистра.
    """
    s = s.replace("\ufeff", "").strip()
    s = re.sub(r"\s+", " ", s)
    return s.casefold()


def compare_headers_strict(actual: list[str], expected: list[str]):
    """
    Строгое сравнение заголовков по позициям.
    """
    mismatches = []
    for i in range(max(len(actual), len(expected))):
        exp = expected[i] if i < len(expected) else None
        act = actual[i] if i < len(actual) else None
        if exp != act:
            mismatches.append((i + 1, exp, act))
    return mismatches


def build_lenient_mapping(actual: list[str], expected: list[str]):
    """
    Пытаемся безопасно сопоставить заголовки,
    если отличаются только регистр / пробелы.
    """
    if len(actual) != len(expected):
        return None, ["Количество колонок не совпадает"]

    mapping = {}
    used = set()
    problems = []

    exp_map = {norm(e): e for e in expected}

    for a in actual:
        key = norm(a)
        if key not in exp_map:
            problems.append(f"Неизвестная колонка: '{a}'")
            continue
        e = exp_map[key]
        if e in used:
            problems.append(f"Дублирующая колонка: '{a}' -> '{e}'")
            continue
        mapping[a] = e
        used.add(e)

    if problems or len(used) != len(expected):
        return None, problems

    return mapping, []


# -------------------------------------------------
# Проверка заполнения и логики
# -------------------------------------------------


def is_empty(v) -> bool:
    return v is None or str(v).strip() == ""


def contains_token(method: str, token: str) -> bool:
    parts = re.split(r"[,\s;]+", (method or "").lower())
    return token.lower() in parts


def precheck_filling_and_logic(row: dict, rownum: int) -> list[str]:
    """
    Проверка пустых полей и логических зависимостей.
    """
    errors = []

    # Обязательные поля
    required = [
        "Number",
        "Название сервиса",
        "юр_лицо",
        "ОГРН",
        "IPv4/IPv6",
        "Сеть в формате network ID",
        "MASK",
        "CDN Yes/No",
        "Protocol",
        "Способ проверки",
    ]

    for field in required:
        if is_empty(row.get(field)):
            errors.append(f"Строка {rownum}: обязательное поле пустое:{field}")
    method = row.get("Способ проверки", "")

    if contains_token(method, "curl") and is_empty(row.get("URL проверки")):
        errors.append(f"Строка {rownum}: указан curl, но URL проверки не указан")

    if contains_token(method, "telnet") and is_empty(row.get("Проверочный IP+порт")):
        errors.append(
            f"Строка {rownum}: указан telnet, но Проверочный IP+порт не указан"
        )

    if contains_token(method, "dig") and is_empty(row.get("DNS Host")):
        errors.append(f"Строка {rownum}: указан dig, но DNS Host не указан")

    if row.get("Protocol") and is_empty(row.get("Port")):
        errors.append(f"Строка {rownum}: указан Protocol, но Port не указан")

    return errors


def cell(row: list[str], idx: int) -> str:
    return (row[idx] if idx < len(row) else "").strip()


def is_empty(s: str) -> bool:
    return s.strip() == ""


def split_csv_list(value: str) -> list[str]:
    """
    Разбивает список значений в одной ячейке.
    Поддерживаем: "a,b", "a; b", "a b" (на всякий случай).
    """
    v = (value or "").strip().lower()
    if not v:
        return []
    v = v.replace(";", ",")
    parts = [p.strip() for p in v.split(",") if p.strip()]
    return parts


def normalize_protocols(value: str) -> set[str]:
    """
    Protocol может быть: tcp, udp, оба, tcp,udp, udp,tcp, tcp/udp.
    Возвращаем множество {'tcp','udp'} и т.п.
    """

    # гарантируем, что v всегда определена
    v = (value or "").strip().lower()
    if not v:
        return set()

    v = v.replace("/", ",").replace(";", ",")
    v = re.sub(r"\s+", "", v)

    if v in {"оба", "both"}:
        return {"tcp", "udp"}

    parts = [p for p in v.split(",") if p]
    out: set[str] = set()

    for p in parts:
        if p in {"оба", "both"}:
            out.update({"tcp", "udp"})
        else:
            out.add(p)

    return out


_ipv4_re = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
_bracket_ipv6_port_re = re.compile(r"^\[.+\]:(\d{1,5})$")
_ipv4_port_re = re.compile(r"^(\d{1,3}(\.\d{1,3}){3}):(\d{1,5})$")


def looks_like_ip_port(value: str) -> bool:
    v = (value or "").strip()
    if not v:
        return False

    m = _ipv4_port_re.match(v)
    if m:
        port = int(m.group(3))
        return 1 <= port <= 65535

    m2 = _bracket_ipv6_port_re.match(v)
    if m2:
        port = int(m2.group(1))
        return 1 <= port <= 65535

    # для ping допускаем просто IPv4 (без порта)
    if _ipv4_re.match(v):
        return True

    return False


def validate_row_rules(row: list[str]) -> list[str]:
    """
    Возвращает список ошибок по строке.
    Проверки основаны на ТЗ:
    - пустые обязательные поля
    - Protocol ↔ Port
    - Способ проверки ↔ URL ↔ Проверочный IP+Порт
    """
    errs: list[str] = []

    # Индексы по ожидаемым колонкам (фиксированные позиции)
    IDX_PORT = 7
    IDX_PROTOCOL = 9
    IDX_DNS = 10
    IDX_SNI = 11
    IDX_CHECK_IPPORT = 12
    IDX_URL = 13
    IDX_METHOD = 14

    port = cell(row, IDX_PORT)
    protocol_raw = cell(row, IDX_PROTOCOL)
    dns = cell(row, IDX_DNS)
    sni = cell(row, IDX_SNI)
    check_ipport = cell(row, IDX_CHECK_IPPORT)
    url = cell(row, IDX_URL)
    method_raw = cell(row, IDX_METHOD)

    # 1) Пустые обязательные ячейки (по REQUIRED_COLUMNS из config.colomns)
    for col in REQUIRED_COLUMNS:
        v = cell(row, col.index)
        if is_empty(v):
            errs.append(f"Пустое обязательное поле: '{col.name}'")

    # 2) Protocol: tcp/udp/оба
    protocols = normalize_protocols(protocol_raw)
    if protocols:
        bad = [p for p in protocols if p not in VALID_PROTOCOLS]
        if bad:
            errs.append(
                f"Недопустимое значение Protocol: {bad} (ожидается tcp/udp или оба)"
            )
    # если указан Protocol, но ячейка Port пустая - то это ошибка (собираем противоречие)
    if (not is_empty(protocol_raw)) and is_empty(port):
        errs.append("Указан Protocol, но ячейка Port пустая")
    if (not is_empty(port)) and is_empty(protocol_raw):
        errs.append("Указан Port, но ячейка Protocol пустая")

    # 3) Способ проверки: может быть список
    methods = [m.strip().lower() for m in split_csv_list(method_raw)]

    # (если поле пустое — оно уже попадёт как "пустое обязательное", если в REQUIRED_COLUMNS)
    for m in methods:
        if m not in VALID_CHECK_METHODS:
            errs.append(f"Недопустимый способ проверки: '{m}'")

    # 4) Правила по методам из таблицы Word

    if "telnet" in methods:
        # - telnet: обязателен Проверочный IP+Порт; URL обычно пуст
        if is_empty(check_ipport):
            # строгий режим: порт в IP+Port должен совпадать с колонкой Port
            if not is_empty(port) and not is_empty(check_ipport):
                try:
                    port_int = int(port)
                except ValueError:
                    errs.append("Port должен быть числом, получено: '{port}'")
                    port_int = None

                ip2, p2 = _parse_ip_port(check_ipport)
                if port_int is not None and p2 is not None and port_int != p2:
                    errs.append(
                        f"telnet: Port={port_int}, но в Проверочный IP+Порт указан порт {p2} (должны совпадать)"
                    )

    if "ping" in methods:
        # - ping: нужен IP (берем из Проверочный IP+Порт)
        if is_empty(check_ipport):
            errs.append(
                "Указан ping, но ячейка 'Проверочный IP+Порт' пустая (нужен IP для проверки)"
            )

    if "dig" in methods:
        # - dig: нужен DNS Host (или SNI/HTTP HOST), URL не нужен
        if is_empty(dns) and is_empty(sni):
            errs.append(
                "Указан dig, но ячейки 'DNS Host' и 'SNI/HTTP HOST' пустые (нужно имя для проверки)"
            )

    # 5) HTTPS + TCP => SNI/HTTP HOST обязателен
    if url.lower().startswith("https://") and ("tcp" in protocols):
        if is_empty(sni):
            errs.append("Для https (tcp) обязательно поле 'SNI/HTTP HOST'")

    # 6) Формат Проверочного IP+Порт (строго)
    parsed_ip, parsed_port = (
        _parse_ip_port(check_ipport) if not is_empty(check_ipport) else (None, None)
    )
    if not is_empty(check_ipport) and parsed_ip is None:
        errs.append(
            "Проверочный IP+Порт должен быть в формате IPv4:Port, например 1.2.3.4: 443"
        )

    # 7) URL проверки: строго по форме

    if "curl" in methods:
        # для curl URL обязателен и должен быть http(s)
        if is_empty(url):
            errs.append("Указан curl, но ячейка 'URL проверки' пустая")
        elif not _is_http_url(url):
            errs.append(
                f"URL проверки при curl должен начинаться с http:// или https:// (получено: '{url}')"
            )
    else:
        # для всех остальных методов URL должен быть пустым
        if not is_empty(url):
            errs.append(
                f"URL проверки должно быть пустым для метода(ов) {methods} (получено: '{url}')"
            )
    return errs


# -------------------------------------------------
# Запуск main.py validate
# -------------------------------------------------


def run_main_validator(temp_csv: Path, output_csv: Path):
    cmd = [
        sys.executable,
        "main.py",
        "validate",
        "--input",
        str(temp_csv),
        "--output",
        str(output_csv),
        "--skip-whois",
    ]

    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    p = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    return (p.stdout or "") + (p.stderr or ""), p.returncode


def write_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8-sig")


def format_header_mismatches(mism) -> str:
    lines = []
    for item in mism:
        try:
            col_no, expected, got = item
            lines.append(f"Колонка {col_no}: ожидается *{expected}*, получено *{got}*")
        except Exception:
            lines.append(str(item))
    return "\n".join(lines)


IPV4_RE = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")
IPPORT_RE = re.compile(r"^(.+):(\d{1,5})$")


def _is_valid_ipv4(ip: str) -> bool:
    ip = (ip or "").strip()
    if not IPV4_RE.match(ip):
        return False
    parts = ip.split(".")
    return all(0 <= int(p) <= 255 for p in parts)


def _parse_ip_port(value: str):
    """Возвращает (ip, port_int) или (None,  None) если формат неверный"""
    s = (value or "").strip()
    m = IPPORT_RE.match(s)
    if not m:
        return None, None

    ip = m.group(1).strip()
    port_str = m.group(2).strip()

    try:
        port = int(port_str)
    except ValueError:
        return None, None

    if port < 1 or port > 65535:
        return None, None

    if not _is_valid_ipv4(ip):
        return None, None

    return ip, port


def _is_http_url(url: str) -> bool:
    s = (url or "").strip().lower()
    return s.startswith("http://") or s.startswith("https://")


@dataclass
class FileOutcome:
    file: Path
    ran_validator: bool

MAX_EXAMPLES_PER_TYPE = 15

def add_group(counts: dict, examples: dict, key: str, line_no: int | None = None):
    """Увеличивает счетчик ошибок и сохраняет номера строк-примеров"""
    counts[key] += 1
    if line_no is not None and len(examples[key]) < MAX_EXAMPLES_PER_TYPE:
        examples[key].append(line_no)

def dump_groups(rs, title: str, counts: dict, examples: dict):
    """Печатает сгруппированные ошибки по убыванию частоты"""
    if not counts:
        rs.print_startup_warning(f"{title}: нет")
        return
    
    rs.print_startup_warning(title + ":")

    # сортируем по количеству (самые частые сверху)
    for msg, cnt in sorted(counts.items(), key=lambda kv: kv[1], reverse=True):
            ex = examples.get(msg, [])
            ex_str = ", ".join(str(x) for x in ex)
            tail = " ..." if cnt > len(ex) else ""
            if ex_str:
                rs.print_startup_warning(f"• ({cnt} шт.) {msg}\n Примеры строк: {ex_str}{tail}")
            else:
                rs.print_startup_warning(f"• ({cnt} шт.) {msg})    


# -------------------------------------------------
# ЕДИНАЯ ТОЧКА ВХОДА
# -------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Precheck CSV + сбор всех ошибок в отчет"
    )
    parser.add_argument("--input", "-i", required=True, help="CSV файл или папка с CSV")
    args = parser.parse_args()

    inp = Path(args.input)

    # Защита: проверяем, что это CSV или папка с CSV
    if inp.is_file:
        if inp.suffix.lower() != ".csv":
            print("ОШИБКА: Входной файл не является CSV:", inp.name)
            print("Пожалуйста, перетащите файл с расширением .csv")
            return
    else:
        csv_file = list(inp.glob("*.csv"))
        if not csv_file:
            print("ОШИБКА: в папке нет ни одного CSV файла:", inp)
            return

    files = [inp] if inp.is_file() else csv_file

    report_dir = Path(r"C:\Users\user\Documents\White list\reports")
    report_dir.mkdir(parents=True, exist_ok=True)

    for csv_file in files:
        precheck_report_path = report_dir / f"{csv_file.stem}_PRECHECK.txt"

        # 1) читаем файл как текст
        enc, text = detect_encoding_and_text(csv_file)

        # 2) открываем отчет и записываем грамотно
        with open(precheck_report_path, "w", encoding="utf-8-sig") as f:
            rs = ReportService(output=f)
            rs.print_startup_warning(f"Проверка файла: {csv_file.name}")
            if enc.lower().startswith("utf-8"):
                rs.print_startup_warning("Кодировка: UTF-8")
            else:
                rs.print_startup_warning(f"Кодировка: {enc}")

            lines = text.splitlines()
            if not lines:
                rs.print_error("Файл пустой")
                continue

            header_line = lines[0] if lines else ""

            # по ТЗ разделитель строго |
            if "|" not in header_line:
                rs.print_error(
                    'Ошибка формата: не обнаружен обязательный разделитель "|".'
                    "Файл должен быть сохранен как CSV с разделителем |"
                )
                continue

            # detect_delimiter может вернуть None или (delim, counts) — обрабатываем оба случая
            det = detect_delimiter(header_line)
            if det is None:
                rs.print_error("Не удалось определить разделитель")
                continue

            delim = "|"

            # 3) Парсим CSV
            rows, header = parse_rows(text, delim)

            # Сколько колонок реально в файле
            rs.print_startup_warning(
                f"Колонок в файле: {len(header)} (по Инструкции должно быть {len(COLUMN_NAMES)})"
            )

            extra = len(header) - len(COLUMN_NAMES)
            if extra > 0:
                add_group(
                    counts, examples,
                    f"Файл содержит лишние колонки: +{extra}"
                )
            elif extra < 0:
                add_group(
                    counts, examples,
                    f"Файл содержит меньше колонок: {len(header)} вместо {len(COLUMN_NAMES)}"
                )
                
             
            # 4) заголовки (НЕ останавливаемся, просто фиксируем)
            header_for_compare = header[: len(COLUMN_NAMES)]
            mism = compare_headers_strict(header[:len(COLUMN_NAMES)], COLUMN_NAMES)
            if mism:
                # одну запись "тип проблемы" + детали отдельными пунктами
                add_group(counts, examples, "Несовпадение в написании заголовков")
                for col_no, expected, got in mism:
                    add_group(
                        counts, examples,
                        f"Заголовок: колонка {col_no}: ожидается '{expected}', получено '{got}'"
                    )
            else:
                # можно не добавлять в группировку, чтобы не шуметь 
                pass        
                
            else:
                rs.print_startup_warning("Заголовки: ОК")

            # 5) Проверяем строки и собираем ВСЕ ошибки
            if not rows:
                rs.print_error("В файле нет строк данных (только заголовок)")
                continue

            total = 0
            bad = 0

            # Группировка всех проблем
            counts = defaultdict(int)    # текст проблемы -> сколько раз
            examples = defaultdict(list) # текст проблемы -> список строк-примеров (до лимита)

            for i, row in enumerate(rows, start=2):  # start=2 потому что 1- заголовок
                # пропускаем полностью пустые строки
                if all((c or "").strip() == "" for c in row):
                    continue

                total += 1

                # Приводим к 16 колонкам, но фиксируем проблему 
                if len(row) < len(COLUMN_NAMES):
                    add_group(
                        counts, examples,
                        f"Строка имеет меньше колонок: {len(row)} вместо {len(COLUMN_NAMES)} (строку нельзя корректно проверить)",
                        line_no=i
                    )
                    # дополним пустыми, чтобы validate_row_rules нашел пустые обязательные поля
                    row16 = row + [""] * (len(COLUMN_NAMES) - len(row))

                elif len(row) > len(COLUMN_NAMES):
                    add_group(
                        counts, examples,
                        f"Строка имеет лишние колонки: +{len(row) - len(COLUMN_NAMES)}",
                        line_no=i
                    )
                    row16 = row[:len(COLUMN_NAMES)]

                else:
                    row16 = row

                errs = validate_row_rules(row16)
                
                if errs:
                    bad += 1
                    for e in errs:
                    add_group(counts, examples, e, line_no=i)

                    # но все равно поробуем проверим то, что невозможно: дополним пустыми до 16
                    # row16 = row + [""] * (len(COLUMN_NAMES) - len(row))

            rs.print_startup_warning(f"Итого строк данных: {total}")
            rs.print_startup_warning(f"Строк с ошибками: {bad}")

            dump_groups(rs. "Сводка проблем (сгруппировано)", counts, examples)

        print("Отчет сохранен:", precheck_report_path)

    print("Предварительная проверка завершена")


if __name__ == "__main__":
    main()
