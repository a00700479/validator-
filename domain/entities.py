"""Domain entities for CSV validation."""
from dataclasses import dataclass, field
from typing import Optional, List
import pandas as pd


@dataclass
class ValidationError:
    """Represents a single validation error."""
    
    code: str
    message: str
    field: Optional[str] = None
    
    def __str__(self) -> str:
        if self.field:
            return f"[{self.code}] {self.field}: {self.message}"
        return f"[{self.code}] {self.message}"


@dataclass 
class RowValidationResult:    
    row_index: int
    line_number: int  # line_number = row_index + 2 (header is line 1)
    errors: List[str] = field(default_factory=list)
    
    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0
    
    def to_string(self) -> str:
        if self.is_valid:
            return "ok"
        return "; ".join(self.errors)


@dataclass
class ValidationReport:
    total_rows: int
    valid_rows: int
    error_details: pd.DataFrame
    result_column: pd.Series
    warnings_column: Optional[pd.Series] = None
    
    @property
    def invalid_rows(self) -> int:
        return self.total_rows - self.valid_rows
    
    @property
    def success_rate(self) -> float:
        if self.total_rows == 0:
            return 0.0
        return self.valid_rows / self.total_rows * 100
