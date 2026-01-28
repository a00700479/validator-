"""CSV file handling service."""
import pandas as pd
from typing import List, Tuple, Optional, Dict
from pathlib import Path

from config.settings import Settings
from domain.entities import ValidationReport


class CsvService:
    """Service for reading and writing CSV files."""
    
    def __init__(self, settings: Settings):
        self._settings = settings
    
    def read_csv(self, filepath: str) -> Tuple[pd.DataFrame, Optional[str]]:
        """
        Read CSV file with specified delimiter.
        
        Args:
            filepath: Path to CSV file
            
        Returns:
            Tuple of (DataFrame, error_message)
        """
        try:
            # Check file exists
            if not Path(filepath).exists():
                return pd.DataFrame(), f"Файл не найден: {filepath}"
            
            # Read with specified encoding and delimiter
            df = pd.read_csv(
                filepath,
                sep=self._settings.csv_delimiter,
                encoding=self._settings.csv_encoding,
                dtype=str,  # Read all as strings
                keep_default_na=False,  # Don't convert empty strings to NaN
                on_bad_lines='warn',  # Warn about malformed lines but don't crash
            )
            
            return df, None
            
        except UnicodeDecodeError:
            return pd.DataFrame(), f"Ошибка кодировки: файл должен быть в {self._settings.csv_encoding}"
        except pd.errors.ParserError as e:
            return pd.DataFrame(), f"Ошибка парсинга CSV: {str(e)}"
        except Exception as e:
            return pd.DataFrame(), f"Ошибка чтения файла: {str(e)}"
    
    def get_headers(self, df: pd.DataFrame) -> List[str]:
        """Get column headers from DataFrame."""
        return list(df.columns)
    
    def read_multiple_csvs(self, filepaths: List[str]) -> Tuple[pd.DataFrame, Dict[str, str]]:
        """
        Read multiple CSV files and merge them with source file column.
        
        Args:
            filepaths: List of paths to CSV files
            
        Returns:
            Tuple of (merged DataFrame, dict of errors by filepath)
        """
        dataframes = []
        errors = {}
        
        for filepath in filepaths:
            df, error = self.read_csv(filepath)
            
            if error:
                errors[filepath] = error
                continue
            
            if df.empty:
                errors[filepath] = "Файл пуст или не содержит данных"
                continue
            
            # Add source file column
            df['source_file'] = Path(filepath).name
            dataframes.append(df)
        
        # If all files failed, return empty DataFrame
        if not dataframes:
            return pd.DataFrame(), errors
        
        # Merge all DataFrames
        merged_df = pd.concat(dataframes, ignore_index=True)
        
        return merged_df, errors
    
    def write_csv_with_results(
        self,
        df: pd.DataFrame,
        report: ValidationReport,
        output_path: str
    ) -> Optional[str]:
        """
        Write CSV with validation results column.
        
        Args:
            df: Original DataFrame
            report: ValidationReport with result_column
            output_path: Path to output file
            
        Returns:
            Error message or None if successful
        """
        try:
            # Add results column to DataFrame
            df_output = df.copy()
            df_output[self._settings.result_column_name] = report.result_column
            
            # Write to file
            df_output.to_csv(
                output_path,
                sep=self._settings.csv_delimiter,
                encoding=self._settings.csv_encoding,
                index=False,
            )
            
            return None
            
        except Exception as e:
            return f"Ошибка записи файла: {str(e)}"
    
    def write_two_output_files(
        self,
        df: pd.DataFrame,
        report: ValidationReport,
        output_path: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Write two output files: full results and errors only.
        
        Args:
            df: Original DataFrame
            report: ValidationReport with result_column
            output_path: Base path for output files
            
        Returns:
            Tuple of (full_file_error, errors_file_error)
        """
        try:
            # Add results column to DataFrame
            df_output = df.copy()
            df_output[self._settings.result_column_name] = report.result_column
            
            # Determine output paths
            output_base = Path(output_path)
            full_output = output_base.parent / f"{output_base.stem}_full{output_base.suffix}"
            errors_output = output_base.parent / f"{output_base.stem}_errors{output_base.suffix}"
            
            # Write full results
            df_output.to_csv(
                full_output,
                sep=self._settings.csv_delimiter,
                encoding=self._settings.csv_encoding,
                index=False,
            )
            
            # Write errors only
            df_errors = df_output[df_output[self._settings.result_column_name] != "ok"]
            df_errors.to_csv(
                errors_output,
                sep=self._settings.csv_delimiter,
                encoding=self._settings.csv_encoding,
                index=False,
            )
            
            return None, None
            
        except Exception as e:
            error_msg = f"Ошибка записи файлов: {str(e)}"
            return error_msg, error_msg
