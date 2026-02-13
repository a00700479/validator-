#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path
from typing import List


from config.settings import Settings
from services.csv_service import CsvService
from services.blacklist_service import BlacklistService
from services.report_service import ReportService
from services.address_parser import AddressParser
from services.search_service import SearchService, SearchResult
from validators.file_validators import FileNameValidator, HeaderValidator
from pipeline.validation_pipeline import ValidationPipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CSV инструмент для валидации и поиска",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Команды")
    
    validate_parser = subparsers.add_parser(
        "validate",
        help="Валидация CSV файла",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  %(prog)s validate --input data.csv --output result.csv
  %(prog)s validate --input data.csv --output result.csv --blacklist blacklist.json
        """
    )
    
    validate_parser.add_argument(
        "--input", "-i",
        required=True,
        help="Путь к входным CSV файлам (можно указать несколько через запятую)"
    )
    
    validate_parser.add_argument(
        "--output", "-o",
        required=True,
        help="Путь к выходному CSV файлу с результатами"
    )
    
    # Определяем дефолтный путь к blacklist
    default_blacklist = Path(__file__).parent / "config" / "blacklist.json"
    
    validate_parser.add_argument(
        "--blacklist", "-b",
        default=str(default_blacklist) if default_blacklist.exists() else None,
        help=f"Путь к JSON файлу с blacklist подсетей (по умолчанию: {default_blacklist.name})"
    )
    
    validate_parser.add_argument(
        "--skip-whois",
        action="store_true",
        help="Пропустить проверку страны через whois"
    )
    
    validate_parser.add_argument(
        "--skip-filename-check",
        action="store_true",
        help="Пропустить проверку формата имени файла"
    )
    
    validate_parser.add_argument(
        "--max-errors",
        type=int,
        default=50,
        help="Максимальное количество ошибок для вывода (по умолчанию: 50)"
    )
    
    search_parser = subparsers.add_parser(
        "search",
        help="Поиск IP адресов в CSV файлах",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  %(prog)s search --address 192.168.1.1 --files data.csv
  %(prog)s search --address 192.168.1.1,10.0.0.5 --files data1.csv data2.csv
  %(prog)s search --address addresses.txt --files test_data/*.csv
        """
    )
    
    search_parser.add_argument(
        "--address", "-a",
        required=True,
        help="IP адрес, список адресов (через запятую) или путь к файлу с адресами"
    )
    
    search_parser.add_argument(
        "--files", "-f",
        nargs="+",
        required=True,
        help="CSV файлы для поиска (можно указать несколько)"
    )
    
    search_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Подробный вывод (включая все поля найденных строк)"
    )
    
    return parser.parse_args()


def print_header_error(mismatches: list, expected_columns: list) -> None:
    print("\n" + "!" * 70)
    print("!" * 70)
    print("!!")
    print("!!  ❌ КРИТИЧЕСКАЯ ОШИБКА: ЗАГОЛОВКИ ТАБЛИЦЫ НЕ СОВПАДАЮТ!")
    print("!!")
    print("!" * 70)
    print("!" * 70)
    
    print("\n📋 ОЖИДАЕМЫЕ КОЛОНКИ:")
    for i, col in enumerate(expected_columns, 1):
        print(f"   {i:2}. {col}")
    
    print("\n❌ НЕСОВПАДЕНИЯ:")
    for mismatch in mismatches:
        print(f"   • {mismatch}")
    
    print("\n" + "!" * 70)
    print("!!  Исправьте заголовки таблицы и запустите скрипт заново!")
    print("!" * 70 + "\n")


def cmd_validate(args) -> int:
    """Execute validate command."""
    # Parse input files (comma-separated or single)
    input_files = [f.strip() for f in args.input.split(',')]
    
    # Initialize settings
    settings = Settings(
        input_file=input_files[0],  # Keep first file for compatibility
        output_file=args.output,
        blacklist_file=args.blacklist,
        whois_enabled=False, 
    )
    
    # Initialize services
    csv_service = CsvService(settings)
    blacklist_service = BlacklistService()
    report_service = ReportService()
    
    print("\n" + "=" * 60)
    print("  CSV VALIDATOR")
    print("=" * 60)
    
    if args.blacklist:
        print(f"\n📂 Загрузка blacklist: {args.blacklist}")
        blacklist, error = blacklist_service.load_blacklist(args.blacklist)
        if error:
            report_service.print_error(error)
            return 1
        settings.blacklist = blacklist
        total_subnets = sum(len(v) for v in blacklist.values())
        print(f"   Загружено {total_subnets} подсетей из {len(blacklist)} источников")
    
    # === File-level validations ===
    file_errors = []
    
    # Validate filename format for all files
    if not args.skip_filename_check:
        filename_validator = FileNameValidator()
        for input_file in input_files:
            file_errors.extend(filename_validator.validate(input_file))
    
    # === Check delimiter and headers BEFORE reading for all files ===
    header_validator = HeaderValidator()
    for input_file in input_files:
        # Check delimiter
        delimiter_valid, delimiter_error = header_validator.check_delimiter(input_file)
        if not delimiter_valid:
            report_service.print_error(f"{Path(input_file).name}: {delimiter_error}")
            print("\n💡 Подсказка: CSV файл должен использовать '|' (вертикальная черта) в качестве разделителя")
            return 1
        
        # Check headers for each file individually (before source_file is added)
        # We read the first line directly to avoid any DataFrame modifications
        try:
            with open(input_file, 'r', encoding=settings.csv_encoding) as f:
                first_line = f.readline().strip()
                if first_line:
                    headers = [h.strip() for h in first_line.split(settings.csv_delimiter)]
                    headers_valid, mismatches = header_validator.validate(headers)
                    if not headers_valid:
                        print(f"\n📄 Файл: {Path(input_file).name}")
                        print_header_error(mismatches, header_validator.get_expected_columns())
                        return 1
        except Exception as e:
            # If we can't read headers, it will be caught later during full file read
            pass
    
    # === Read CSV files ===
    print(f"\n📂 Чтение файлов: {len(input_files)} файл(ов)")
    df, read_errors = csv_service.read_multiple_csvs(input_files)
    
    # Report read errors
    if read_errors:
        for filepath, error in read_errors.items():
            report_service.print_error(f"{Path(filepath).name}: {error}")
    
    if df.empty:
        report_service.print_error("Все файлы пусты или не содержат данных")
        return 1
    
    # Count unique source files
    source_files_count = df['source_file'].nunique() if 'source_file' in df.columns else 1
    print(f"   Загружено {len(df)} строк из {source_files_count} файл(ов), {len(df.columns)} колонок")
    print("   ✅ Заголовки таблицы корректны")
    
    # Print file errors if any (filename only at this point)
    if file_errors:
        report_service.print_file_errors(file_errors)
    
    # === Initialize pipeline ===
    pipeline = ValidationPipeline(settings)
    
    # Check and print whois warning at startup
    whois_warning = pipeline.get_whois_startup_warning()
    if whois_warning:
        report_service.print_startup_warning(whois_warning)
    
    # === Validate rows with progress ===
    report = pipeline.validate_with_live_progress(df)
    
    # === Print row errors ===
    report_service.print_row_errors(report, max_errors=args.max_errors)
    
    # === Print summary ===
    whois_final_warning = pipeline.get_whois_final_warning()
    report_service.print_summary(report, whois_final_warning)
    
    # === Write output files ===
    print(f"💾 Сохранение результатов...")
    full_error, errors_error = csv_service.write_two_output_files(df, report, args.output)
    
    if full_error or errors_error:
        if full_error:
            report_service.print_error(f"Полный файл: {full_error}")
        if errors_error:
            report_service.print_error(f"Файл с ошибками: {errors_error}")
        return 1
    
    # Show output file names
    output_base = Path(args.output)
    full_output = output_base.parent / f"{output_base.stem}_full{output_base.suffix}"
    errors_output = output_base.parent / f"{output_base.stem}_errors{output_base.suffix}"
    
    print(f"   ✅ Полный результат: {full_output}")
    print(f"   ✅ Только ошибки: {errors_output}")
    print()
    
    # Return non-zero if there were validation errors
    return 0 if report.valid_rows == report.total_rows and not file_errors else 1


def print_search_header():
    """Print search tool header."""
    print("\n" + "=" * 60)
    print("  IP ADDRESS SEARCH")
    print("=" * 60)


def print_search_params(addresses: List[str], files: List[str]):
    """Print search parameters."""
    print(f"\n🔍 Параметры поиска:")
    print(f"   Адресов для поиска: {len(addresses)}")
    for addr in addresses:
        print(f"      • {addr}")
    print(f"   Файлов для проверки: {len(files)}")


def print_search_warnings(result: SearchResult):
    """Print warnings about files."""
    if not result.files_with_warnings:
        return
    
    print(f"\n⚠️  ПРЕДУПРЕЖДЕНИЯ ({len(result.files_with_warnings)}):\n")
    for file_path, warning in result.files_with_warnings:
        print(f"   📄 {file_path}")
        print(f"      {warning}\n")


def print_search_results(result: SearchResult, verbose: bool = False):
    """Print search results."""
    if not result.matches:
        print("\n❌ РЕЗУЛЬТАТЫ:")
        print("   Совпадений не найдено\n")
        return
    
    print(f"\n✅ НАЙДЕНО СОВПАДЕНИЙ: {len(result.matches)}\n")
    
    # Group matches by searched address
    matches_by_addr = {}
    for match in result.matches:
        if match.ip_searched not in matches_by_addr:
            matches_by_addr[match.ip_searched] = []
        matches_by_addr[match.ip_searched].append(match)
    
    # Print matches grouped by address
    for search_addr, matches in matches_by_addr.items():
        print(f"🔎 IP: {search_addr} → найдено в {len(matches)} строках")
        print("   " + "─" * 55)
        
        for idx, match in enumerate(matches, 1):
            match_icon = "🎯" if match.match_type == "exact" else "📡"
            match_label = "точное совпадение" if match.match_type == "exact" else "в подсети"
            
            print(f"\n   {match_icon} Совпадение #{idx} ({match_label})")
            print(f"      Файл:    {match.file_path}")
            print(f"      Строка:  {match.line_number}")
            print(f"      Сеть:    {match.network_found}{match.mask_found}")
            print(f"      Подсеть: {match.subnet}")
            
            if verbose and match.row_data:
                print(f"\n      📋 Данные строки:")
                for key, value in match.row_data.items():
                    # Truncate long values
                    display_value = value if len(value) <= 50 else value[:47] + "..."
                    print(f"         • {key}: {display_value}")
        
        print()


def print_search_summary(result: SearchResult):
    """Print search summary."""
    print("─" * 60)
    print("\n📊 ИТОГИ:")
    print(f"   Проверено файлов:      {result.files_checked}")
    print(f"   Искали адресов:        {len(result.searched_addresses)}")
    print(f"   Найдено совпадений:    {len(result.matches)}")
    
    # Count unique addresses found
    found_addrs = set(m.ip_searched for m in result.matches)
    print(f"   Адресов найдено:       {len(found_addrs)}")
    print(f"   Адресов не найдено:    {len(result.searched_addresses) - len(found_addrs)}")
    
    if result.files_with_warnings:
        print(f"   Файлов с warning:      {len(result.files_with_warnings)}")
    
    print()


def cmd_search(args) -> int:
    """Execute search command."""
    print_search_header()
    
    # Parse input addresses
    print(f"\n📥 Парсинг входных адресов...")
    addresses, error = AddressParser.parse_addresses(args.address)
    
    if error:
        print(f"\n❌ ОШИБКА: {error}\n")
        return 1
    
    print(f"   ✅ Загружено {len(addresses)} адресов")
    
    # Expand file globs if needed
    file_paths = []
    for pattern in args.files:
        path = Path(pattern)
        if '*' in pattern or '?' in pattern:
            # Glob pattern
            parent = path.parent if path.parent.exists() else Path('.')
            files = list(parent.glob(path.name))
            file_paths.extend([str(f) for f in files if f.is_file()])
        else:
            file_paths.append(pattern)
    
    if not file_paths:
        print("\n❌ ОШИБКА: Не найдено ни одного файла для поиска\n")
        return 1
    
    print_search_params(addresses, file_paths)
    
    # Initialize services
    settings = Settings()
    search_service = SearchService(settings)
    
    # Perform search
    print(f"\n🔎 Поиск в файлах...")
    result = search_service.search_addresses_in_files(addresses, file_paths)
    
    # Print warnings
    print_search_warnings(result)
    
    # Print results
    print_search_results(result, verbose=args.verbose)
    
    # Print summary
    print_search_summary(result)
    
    # Return 0 if found matches, 1 if not
    return 0 if result.matches else 1


def main() -> int:
    """Main entry point."""
    args = parse_args()
    
    # Check if command was specified
    if not args.command:
        print("\n❌ ОШИБКА: Не указана команда. Используйте 'validate' или 'search'")
        print("\nПримеры:")
        print("  python main.py validate --input data.csv --output result.csv")
        print("  python main.py search --address 192.168.1.1 --files data.csv")
        print("\nДля справки используйте: python main.py validate --help или python main.py search --help\n")
        return 1
    
    # Route to appropriate command
    if args.command == "validate":
        return cmd_validate(args)
    elif args.command == "search":
        return cmd_search(args)
    else:
        print(f"\n❌ ОШИБКА: Неизвестная команда '{args.command}'\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
