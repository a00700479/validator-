import os
import re
from typing import List, Tuple

from domain.entities import ValidationError
from config.columns import COLUMN_NAMES


class FileNameValidator:
    """Проверяет формат имени файла (названиеКомпании_YYYYMMDD.csv)."""
    
    @property
    def name(self) -> str:
        return "FILENAME"
    
    def validate(self, filepath: str) -> List[ValidationError]:
        filename = os.path.basename(filepath)
        errors = []
        
        if not filename.lower().endswith(".csv"):
            errors.append(ValidationError(
                code=self.name,
                message=f"Файл должен иметь расширение .csv: '{filename}'"
            ))
            return errors
        
        pattern = r'^.+_(\d{8})\.csv$'
        match = re.match(pattern, filename, re.IGNORECASE)
        
        if not match:
            errors.append(ValidationError(
                code=self.name,
                message=f"Имя файла должно быть в формате название_YYYYMMDD.csv: '{filename}'"
            ))
            return errors
        
        date_str = match.group(1)
        year = int(date_str[:4])
        month = int(date_str[4:6])
        day = int(date_str[6:8])
        
        if not (2000 <= year <= 2100):
            errors.append(ValidationError(
                code=self.name,
                message=f"Некорректный год в имени файла: {year}"
            ))
        
        if not (1 <= month <= 12):
            errors.append(ValidationError(
                code=self.name,
                message=f"Некорректный месяц в имени файла: {month}"
            ))
        
        if not (1 <= day <= 31):
            errors.append(ValidationError(
                code=self.name,
                message=f"Некорректный день в имени файла: {day}"
            ))
        
        return errors


class HeaderValidator:   
    @property
    def name(self) -> str:
        return "HEADER"
    
    def check_delimiter(self, filepath: str) -> Tuple[bool, str]:
        """
        Check if file uses correct delimiter (|).
        
        Args:
            filepath: Path to CSV file
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                first_line = f.readline().strip()
            
            if not first_line:
                return False, "Файл пуст"
            
            pipe_count = first_line.count('|')
            comma_count = first_line.count(',')
            semicolon_count = first_line.count(';')
            tab_count = first_line.count('\t')
            
            if pipe_count >= 15:
                return True, ""

            if comma_count > pipe_count:
                return False, "файл использует ',' вместо '|' в качестве разделителя"
            elif semicolon_count > pipe_count:
                return False, "файл использует ';' вместо '|' в качестве разделителя"
            elif tab_count > pipe_count:
                return False, "файл использует TAB вместо '|' в качестве разделителя"
            else:
                return False, "неправильный разделитель, ожидается '|' (вертикальная черта)"
        
        except UnicodeDecodeError:
            try:
                with open(filepath, 'r', encoding='cp1251') as f:
                    first_line = f.readline().strip()
                return False, "файл использует кодировку CP1251 вместо UTF-8 (также проверьте разделитель)"
            except:
                return False, "ошибка чтения файла"
        except Exception as e:
            return False, f"Ошибка проверки разделителя: {str(e)}"
    
    def validate(self, headers: List[str]) -> Tuple[bool, List[str]]:
        """
        Validate headers strictly against expected columns.
        
        Returns:
            Tuple of (is_valid, list of mismatch messages)
        """
        mismatches = []
        
        expected = COLUMN_NAMES
        actual = [h.strip() for h in headers]
        
        if len(actual) != len(expected):
            mismatches.append(
                f"Количество колонок: ожидается {len(expected)}, получено {len(actual)}"
            )
        
        min_len = min(len(expected), len(actual))
        for i in range(min_len):
            if actual[i] != expected[i]:
                mismatches.append(
                    f"Колонка {i+1}: ожидается '{expected[i]}', получено '{actual[i]}'"
                )
        
        if len(actual) > len(expected):
            for i in range(len(expected), len(actual)):
                mismatches.append(f"Лишняя колонка {i+1}: '{actual[i]}'")
        
        if len(actual) < len(expected):
            for i in range(len(actual), len(expected)):
                mismatches.append(f"Отсутствует колонка {i+1}: '{expected[i]}'")
        
        return len(mismatches) == 0, mismatches
    
    def get_expected_columns(self) -> List[str]:
        """Return list of expected column names."""
        return COLUMN_NAMES.copy()
