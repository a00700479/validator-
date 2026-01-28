from abc import ABC, abstractmethod
from typing import Optional
import pandas as pd


class DataFrameValidator(ABC):
    """
    Abstract base class for DataFrame validators.
    
    Validators apply vectorized operations to entire DataFrame columns
    and return a Series with error messages (empty string = no error).
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Validator name for error codes."""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description for progress display."""
        pass
    
    @abstractmethod
    def validate(self, df: pd.DataFrame) -> pd.Series:
        """
        Validate DataFrame and return Series with error messages.
        """
        pass
    
    def _make_error(self, message: str, field: Optional[str] = None) -> str:
        """Helper to create formatted error message."""
        if field:
            return f"[{self.name}] {field}: {message}"
        return f"[{self.name}] {message}"
    
    def _empty_errors(self, df: pd.DataFrame) -> pd.Series:
        """Return Series of empty strings (no errors)."""
        return pd.Series("", index=df.index)
