"""Report generation service."""
import sys
from typing import List, Optional, TextIO

from domain.entities import ValidationError, ValidationReport


class ReportService:
    """Service for generating validation reports."""
    
    def __init__(self, output: TextIO = sys.stdout):
        self._output = output
    
    def print_startup_warning(self, message: str) -> None:
        """Print warning at script startup."""
        print(f"\n{message}\n", file=self._output)
    
    def print_file_errors(self, errors: List[ValidationError]) -> None:
        """Print file-level validation errors."""
        if not errors:
            return
        
        print("\n" + "=" * 60, file=self._output)
        print("ОШИБКИ ФАЙЛА:", file=self._output)
        print("=" * 60, file=self._output)
        
        for error in errors:
            print(f"  [❌] {error}", file=self._output)
        
        print("", file=self._output)
    
    def print_row_errors(self, report: ValidationReport, max_errors: int = 50) -> None:
        """
        Print row-level validation errors.
        
        Args:
            report: ValidationReport with error details
            max_errors: Maximum number of errors to display
        """
        if report.error_details.empty:
            return
        
        print("\n" + "=" * 60, file=self._output)
        print("ОШИБКИ СТРОК:", file=self._output)
        print("=" * 60, file=self._output)
        
        displayed = 0
        for _, row in report.error_details.iterrows():
            if displayed >= max_errors:
                remaining = len(report.error_details) - max_errors
                print(f"\n  ... и ещё {remaining} строк с ошибками", file=self._output)
                break
            
            # Обрабатываем случай, когда Number пустой или невалидный
            try:
                number_str = f"Number {int(row['number'])}"
            except (ValueError, TypeError):
                number_str = "Number не указан"
            
            print(f"  [❌] {number_str}: {row['errors']}", file=self._output)
            displayed += 1
        
        print("", file=self._output)
    
    def print_summary(
        self,
        report: ValidationReport,
        final_warning: Optional[str] = None
    ) -> None:
        """Print validation summary."""
        print("\n" + "=" * 60, file=self._output)
        print("ИТОГИ ВАЛИДАЦИИ:", file=self._output)
        print("=" * 60, file=self._output)
        
        print(f"  Всего строк:     {report.total_rows}", file=self._output)
        
        # Don't show 100% if there are errors (avoid rounding to 100%)
        rate = report.success_rate
        if report.invalid_rows > 0 and round(rate, 1) >= 100.0:
            rate_str = "99.9"
        else:
            rate_str = f"{rate:.1f}"
        
        print(f"  Успешных:        {report.valid_rows} ({rate_str}%)", file=self._output)
        print(f"  С ошибками:      {report.invalid_rows}", file=self._output)
        
        if final_warning:
            print(f"\n  {final_warning}", file=self._output)
        
        print("=" * 60 + "\n", file=self._output)
    
    def print_success(self, output_file: str) -> None:
        """Print success message."""
        print(f"✅ Результаты сохранены в: {output_file}\n", file=self._output)
    
    def print_error(self, message: str) -> None:
        """Print error message."""
        print(f"❌ ОШИБКА: {message}\n", file=self._output)
