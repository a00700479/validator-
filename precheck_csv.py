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
import pandas as pd
from openpyxl import load_workbook
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


def normalized_header_for_fixed(
    actual_header: list[str], expected: list[str]
) -> tuple[list[str], list[str]]:
    """
    Возвращает:
      - fixed_header: заголовок ровно как expected (если удалось сопоставить)
      - problems: список проблем (если не удалось)
    """
    # Сначала попробуем "мягкое сопоставление"
    mapping, problems = build_lenient_mapping(actual_header[: len(expected)], expected)
    if problems:
        # Мягко не получилось - вернем строгие несовпадения как проблемы
        mism = compare_headers_strict(actual_header[: len(expected)], expected)
        problems2 = [
            f"Колонка {i}: ожидается '{exp}', получено '{act}'"
            for (i, exp, act) in mism
            if exp != act
        ]
        return expected[:], (problems + problems2)

    # Если mapping есть — значит различия только в регистре/пробелах/BOM
    # FIXED заголовок должен быть строго expected
    return expected[:], []


def build_fixed_csv(
    csv_file: Path,
    text: str,
    delim: str,
    expected_cols: list[str],
    out_dir: Path,
) -> Path:
    """
    Делает временный CSV, который "съест" main.py:
    - заголовок приводим к expected_cols (по позиции)
    - строки обрезаем до 16 или дополняем пустыми до 16
    - лишние колонки от хвостовых ||| игнорируем
    - пишем UTF-8 (без BOM) c тем же разделителем '|'
    """

    out_dir.mkdir(parents=True, exist_ok=True)
    fixed_path = out_dir / f"{csv_file.stem}_FIXED.csv"

    lines = text.splitlines()
    if not lines:
        raise ValueError("Файл пустой")

    reader = csv.reader(lines, delimiter=delim)
    rows = list(reader)
    if not rows:
        raise ValueError("Не удалось прочитать CSV")

    header = rows[0]
    data_rows = rows[1:]

    # нормализуем заголовки и приводим к длине expected
    header = [normalized_header_for_fixed(x) for x in header]
    header16 = (header + [""] * len(expected_cols))[: len(expected_cols)]

    # ВАЖНО: чтобы main.py не падал на заголовках — делаем их ровно ожидаемыми
    header16 = expected_cols[:]  # именно так: фиксируем строго

    fixed_rows = [header16]

    for r in data_rows:
        # обрезаем/дополняем до 16
        r16 = (r + [""] * len(expected_cols))[: len(expected_cols)]
        fixed_rows.append(r16)

    # пишем как UTF-8 без BOM, newline = "" важно для csv в винде
    with open(fixed_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="|", quoting=csv.QUOTE_MINIMAL)
        w.writerows(fixed_rows)

    return fixed_path


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

    if contains_token(method, "telnet") and is_empty(row.get("Проверочный IP+Порт")):
        errors.append(
            f"Строка {rownum}: указан telnet, но Проверочный IP+Порт не указан"
        )

    if contains_token(method, "dig") and is_empty(row.get("DNS Host")):
        errors.append(f"Строка {rownum}: указан dig, но DNS Host не указан")

    if row.get("Protocol") and is_empty(row.get("Port")):
        errors.append(f"Строка {rownum}: указан Protocol, но Port не указан")

    return errors


def cell(row: list[str], idx: int) -> str:
    return (row[idx] if idx < len(row) else "").strip()


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
            if is_empty(check_ipport):
                errs.append("Указан telnet, но ячейка 'Проверочный IP+Порт' пустая")
            # URL не нужен, но не считаем ошибкой, если заполнен

    if "ping" in methods:
        # - ping: нужен IP (берем из Проверочный IP+Порт)
        if is_empty(check_ipport) and is_empty(dns):
            errs.append("Указан ping, но нет ни IP, ни DNS для проверки")

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
        if is_empty(dns):
            errs.append("Указан curl, о не заполнен 'DNS Host'")
    else:
        # для всех остальных методов URL НЕ обязателен
        # но если заполнен - просто проверим, что это похоже на URL
        if not is_empty(url):
            if not (
                url.lower().startswith("http://")
                or url.lower().startswith("https://")
                or "." in url  # разрешаем домены типа v-a.yandex.ru
            ):

                errs.append(f"URL проверки имеет формат: '{url}')")
    return errs


# -------------------------------------------------
# Запуск main.py validate
# -------------------------------------------------


def run_main_validate(
    project_dir: Path,
    fixed_csv: Path,
    out_csv: Path,
    skip_whois: bool = True,
) -> tuple[str, int]:
    """
    Запускает main.py validate и возвращает (stdout + stderr, returncode)
    """
    cmd = [
        sys.executable,
        str(project_dir / "main.py"),
        "validate",
        "--input",
        str(fixed_csv),
        "--output",
        str(out_csv),
    ]
    if skip_whois:
        cmd.append("--skip-whois")

    env = dict(**dict(os.environ))
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    p = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(project_dir),  # важно: main.py любит запуск из своей папки
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
            rs.print_startup_warning(
                f"• ({cnt} шт.) {msg}\n Примеры строк: {ex_str}{tail}"
            )
        else:
            rs.print_startup_warning(f"• ({cnt} шт.) {msg}")


def build_excel_report(
    main_csv: Path,
    excel_path: Path,
    sep: str,
    precheck_txt: Path | None = None,
    main_log_txt: Path | None = None,
) -> None:
    """
    Делает Excel-отчёт:
      - MAIN_RESULT: таблица из main.csv
      - MAIN_LOG: лог main.py (если есть)
      - PRECHECK: precheck-отчёт (если есть)
    """
    excel_path.parent.mkdir(parents=True, exist_ok=True)

    # 1) Таблица main.py -> Excel
    df = pd.read_csv(main_csv, sep=sep, encoding="utf-8")
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="MAIN_RESULT", index=False)

    # 2) Добавляем текстовые листы
    wb = load_workbook(excel_path)

    def add_text_sheet(sheet_name: str, txt_path: Path):
        if not txt_path or not txt_path.exists():
            return
        ws = wb.create_sheet(sheet_name)
        text = txt_path.read_text(encoding="utf-8", errors="replace")
        # пишем построчнов колонку А\
        for i, line in enumerate(text.splitlines(), start=1):
            ws.cell(row=i, column=1, value=line)

    add_text_sheet("MAIN_LOG", main_log_txt)
    add_text_sheet("PRECHECK", precheck_txt)

    # Удобно: закрепим шапку таблицы
    ws0 = wb["MAIN_RESULT"]
    ws0.freeze_panes = "A2"
    ws0.auto_filter.ref = ws0.dimensions

    wb.save(excel_path)


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
    if inp.is_file():
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

        # Группировка всех проблем
        counts = defaultdict(int)  # текст проблемы -> сколько раз
        examples = defaultdict(
            list
        )  # текст проблемы -> список строк-примеров (до лимита)

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

            delim = "|"
            if "|" not in header_line:
                rs.print_error(
                    "Не найден разделитель '|'. Файл должен быть сохранен как CSV с разделителем |"
                )
                continue

            # 3) Парсим CSV
            rows, header = parse_rows(text, delim)

            # Сколько колонок реально в файле
            rs.print_startup_warning(
                f"Колонок в файле: {len(header)} (по Инструкции должно быть {len(COLUMN_NAMES)})"
            )

            extra = len(header) - len(COLUMN_NAMES)
            if extra > 0:
                add_group(counts, examples, f"Файл содержит лишние колонки: +{extra}")
            elif extra < 0:
                add_group(
                    counts,
                    examples,
                    f"Файл содержит меньше колонок: {len(header)} вместо {len(COLUMN_NAMES)}",
                )

            # 4) заголовки (НЕ останавливаемся, просто фиксируем)

            mism = compare_headers_strict(header[: len(COLUMN_NAMES)], COLUMN_NAMES)
            if mism:
                # одну запись "тип проблемы" + детали отдельными пунктами
                add_group(counts, examples, "Несовпадение в написании заголовков")
                for col_no, expected, got in mism:
                    add_group(
                        counts,
                        examples,
                        f"Заголовок: колонка {col_no}: ожидается '{expected}', получено '{got}'",
                    )
            else:
                rs.print_startup_warning("Заголовки: ОК")

            # 5) Проверяем строки и собираем ВСЕ ошибки
            if not rows:
                rs.print_error("В файле нет строк данных (только заголовок)")
                continue

            total = 0
            bad = 0

            extra_cols_noted = False

            for i, row in enumerate(rows, start=2):  # start=2 потому что 1- заголовок
                # пропускаем полностью пустые строки
                if all((c or "").strip() == "" for c in row):
                    continue

                total += 1
                row_has_problem = False

                # 1) Проверка количества колонок
                if len(row) < len(COLUMN_NAMES):
                    row_has_problem = True
                    rs.print_error(
                        f"Строка {i}: количество колонок  = {len(row)}, ожидается {len(COLUMN_NAMES)} "
                        "(не хватает колонок)"
                    )
                    add_group(
                        counts,
                        examples,
                        f"Строки: не хватает колонок (меньше {len(COLUMN_NAMES)})",
                        i,
                    )
                    row16 = row + [""] * (len(COLUMN_NAMES) - len(row))

                elif len(row) > len(COLUMN_NAMES):
                    row_has_problem = True
                    if not extra_cols_noted:
                        rs.print_startup_warning(
                            f"Обнаружены лишние колонки в строках (пример: строка {i}: + {len(row) - len(COLUMN_NAMES)}). "
                            "Лишнее игнорируется"
                        )
                        add_group(
                            counts,
                            examples,
                            f"Строки: лишние колонки (больше {len(COLUMN_NAMES)})",
                            i,
                        )

                    row16 = row[: len(COLUMN_NAMES)]

                else:
                    row16 = row

                # 2) логические правила заполнения
                errs = validate_row_rules(row16)
                if errs:
                    row_has_problem = True
                    for e in errs:
                        add_group(counts, examples, e, i)

                # 3) финально считаем строку "битой"
                if row_has_problem:
                    bad += 1

            rs.print_startup_warning(f"Итого строк данных: {total}")
            rs.print_startup_warning(f"Строк с ошибками: {bad}")

            # 6) Готовим FIXED CSV и запускаем main.py

            fixed_dir = report_dir / "_temp"
            main_out_csv = report_dir / f"{csv_file.stem}_MAIN_result.csv"
            main_log_txt = report_dir / f"{csv_file.stem}_MAIN.txt"

            try:
                fixed_csv = build_fixed_csv(
                    csv_file=csv_file,
                    text=text,
                    delim=delim,  # тот, который мы определили
                    expected_cols=COLUMN_NAMES,  # 16 наших ожидаемых
                    out_dir=fixed_dir,
                )
                rs.print_startup_warning(
                    f"Создан FIXED CSV для main.py:  {fixed_csv.name}"
                )

                main_log, rc = run_main_py_validate(
                    project_dir=Path(__file__).parent,  # папка, где лежит main.py
                    fixed_csv=fixed_csv,
                    out_csv=main_out_csv,
                    skip_whois=True,
                )

                # пишем отдельный лог main.py
                main_log_txt.write_text(main_log, encoding="utf-8")

                if rc == 0:
                    rs.print_startup_warning(f"main.py: OK. Результат: {main_out_csv}")
                    rs.print_startup_warning(f"Лог main.py: {main_log_txt}")
                else:
                    rs.print_error(
                        f"main.py завершился с кодом {rc}. Cм. лог: {main_log_txt.name}"
                    )

            except Exception as e:
                rs.print_error(
                    f"Не удалось подготовить FIXED CSV / запустить main.py: {e}"
                )

            main_excel = report_dir / f"{csv_file.stem}_REPORT.xlsx"

            if main_out_csv.exists():
                try:
                    build_excel_report(
                        main_csv=main_out_csv,
                        excel_path=main_excel,
                        sep="|",  #  у нас разделитель по форме
                        precheck_txt=precheck_report_path,
                        main_log_txt=main_log_txt,
                    )
                    rs.print_row_errors(f"Excel-отчет: {main_excel.name}")
                except Exception as e:
                    rs.print_error(f"Не удалось соборать Excel-отчет: {e}")

            dump_groups(rs, "Сводка проблем (сгруппировано)", counts, examples)

        print("Отчет сохранен:", precheck_report_path)

    print("Предварительная проверка завершена")


if __name__ == "__main__":
    main()
