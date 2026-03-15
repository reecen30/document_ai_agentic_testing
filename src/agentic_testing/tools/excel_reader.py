"""
Excel Reader tools — read from the Evidence Store workbook.
All tools are read-only against the evidence store.
"""
import json
import os
from typing import Any, Dict, List, Optional, Type
import pandas as pd
from crewai.tools import BaseTool
from pydantic import BaseModel, Field


class ReadDocumentDataInput(BaseModel):
    workbook_path: str = Field(..., description="Absolute path to the evidence store workbook")
    sheet_name: str = Field(default="DocumentData")
    transaction_ids: Optional[List[int]] = Field(default=None)
    process_stage_ids: Optional[List[int]] = Field(default=None)
    document_type_names: Optional[List[str]] = Field(default=None)
    date_from: Optional[str] = Field(default=None, description="YYYY-MM-DD")
    date_to: Optional[str] = Field(default=None, description="YYYY-MM-DD")
    max_rows: int = Field(default=5000)


class ReadDocumentDataTool(BaseTool):
    name: str = "read_document_data"
    description: str = (
        "Read rows from the DocumentData sheet of the evidence store workbook. "
        "Filter by transaction_ids, process_stage_ids, document_type_names, or date range. "
        "Returns JSON array of rows."
    )
    args_schema: Type[BaseModel] = ReadDocumentDataInput

    def _run(
        self,
        workbook_path: str,
        sheet_name: str = "DocumentData",
        transaction_ids: Optional[List[int]] = None,
        process_stage_ids: Optional[List[int]] = None,
        document_type_names: Optional[List[str]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        max_rows: int = 5000,
    ) -> str:
        try:
            df = pd.read_excel(workbook_path, sheet_name=sheet_name)
            if transaction_ids:
                df = df[df["TransactionID"].isin(transaction_ids)]
            if process_stage_ids:
                df = df[df["ProcessStageID"].isin(process_stage_ids)]
            if document_type_names:
                df = df[df["DocumentTypeName"].isin(document_type_names)]
            if date_from:
                df = df[pd.to_datetime(df["CreatedDateTime"]) >= pd.to_datetime(date_from)]
            if date_to:
                df = df[pd.to_datetime(df["CreatedDateTime"]) <= pd.to_datetime(date_to)]
            df = df[df.get("Active", pd.Series([True] * len(df))) == 1] if "Active" in df.columns else df
            df = df.head(max_rows)
            return json.dumps(df.fillna("").to_dict(orient="records"))
        except Exception as e:
            return json.dumps({"error": str(e), "tool": "read_document_data"})


class ReadModelDataInput(BaseModel):
    workbook_path: str
    sheet_name: str = Field(default="ai.ModelData")
    transaction_ids: Optional[List[int]] = None
    model_name_ids: Optional[List[int]] = None
    model_stage_ids: Optional[List[int]] = None
    in_argument_fields: Optional[List[str]] = None
    max_rows: int = 5000


class ReadModelDataTool(BaseTool):
    name: str = "read_model_data"
    description: str = (
        "Read rows from the ai.ModelData sheet of the evidence store workbook. "
        "Filter by transaction_ids, model_name_ids, model_stage_ids, or In_Argument_Field values. "
        "Returns JSON array of rows."
    )
    args_schema: Type[BaseModel] = ReadModelDataInput

    def _run(
        self,
        workbook_path: str,
        sheet_name: str = "ai.ModelData",
        transaction_ids: Optional[List[int]] = None,
        model_name_ids: Optional[List[int]] = None,
        model_stage_ids: Optional[List[int]] = None,
        in_argument_fields: Optional[List[str]] = None,
        max_rows: int = 5000,
    ) -> str:
        try:
            df = pd.read_excel(workbook_path, sheet_name=sheet_name)
            if transaction_ids:
                df = df[df["TransactionID"].isin(transaction_ids)]
            if model_name_ids:
                df = df[df["ModelNameID"].isin(model_name_ids)]
            if model_stage_ids:
                df = df[df["ModelStageID"].isin(model_stage_ids)]
            if in_argument_fields:
                df = df[df["In_Argument_Field"].isin(in_argument_fields)]
            if "Active" in df.columns:
                df = df[df["Active"] == 1]
            df = df.head(max_rows)
            return json.dumps(df.fillna("").to_dict(orient="records"))
        except Exception as e:
            return json.dumps({"error": str(e), "tool": "read_model_data"})


class ReadExceptionLogsInput(BaseModel):
    workbook_path: str
    sheet_name: str = Field(default="ExceptionLogs")
    transaction_ids: Optional[List[int]] = None
    max_rows: int = 2000


class ReadExceptionLogsTool(BaseTool):
    name: str = "read_exception_logs"
    description: str = "Read exception log rows from the evidence store workbook. Returns JSON array."
    args_schema: Type[BaseModel] = ReadExceptionLogsInput

    def _run(
        self,
        workbook_path: str,
        sheet_name: str = "ExceptionLogs",
        transaction_ids: Optional[List[int]] = None,
        max_rows: int = 2000,
    ) -> str:
        try:
            df = pd.read_excel(workbook_path, sheet_name=sheet_name)
            if transaction_ids and "TransactionID" in df.columns:
                df = df[df["TransactionID"].isin(transaction_ids)]
            return json.dumps(df.head(max_rows).fillna("").to_dict(orient="records"))
        except Exception as e:
            return json.dumps({"error": str(e), "tool": "read_exception_logs"})


class ReadApiDataInput(BaseModel):
    workbook_path: str
    sheet_name: str = Field(default="api.APIData")
    transaction_ids: Optional[List[int]] = None
    max_rows: int = 2000


class ReadApiDataTool(BaseTool):
    name: str = "read_api_data"
    description: str = "Read API call data from the evidence store workbook. Returns JSON array."
    args_schema: Type[BaseModel] = ReadApiDataInput

    def _run(
        self,
        workbook_path: str,
        sheet_name: str = "api.APIData",
        transaction_ids: Optional[List[int]] = None,
        max_rows: int = 2000,
    ) -> str:
        try:
            df = pd.read_excel(workbook_path, sheet_name=sheet_name)
            if transaction_ids and "TransactionID" in df.columns:
                df = df[df["TransactionID"].isin(transaction_ids)]
            return json.dumps(df.head(max_rows).fillna("").to_dict(orient="records"))
        except Exception as e:
            return json.dumps({"error": str(e), "tool": "read_api_data"})


class ReadLookupSheetInput(BaseModel):
    workbook_path: str
    sheet_name: str = Field(..., description="e.g. DocumentTypes, ProcessStages, ai.ModelNames")


class ReadLookupSheetTool(BaseTool):
    name: str = "read_lookup_sheet"
    description: str = "Read any lookup/reference sheet (DocumentTypes, ProcessStages, ai.ModelNames, etc.) from the evidence store workbook."
    args_schema: Type[BaseModel] = ReadLookupSheetInput

    def _run(self, workbook_path: str, sheet_name: str) -> str:
        try:
            df = pd.read_excel(workbook_path, sheet_name=sheet_name)
            return json.dumps(df.fillna("").to_dict(orient="records"))
        except Exception as e:
            return json.dumps({"error": str(e), "tool": "read_lookup_sheet"})


# Convenience instances
read_document_data = ReadDocumentDataTool()
read_model_data = ReadModelDataTool()
read_exception_logs = ReadExceptionLogsTool()
read_api_data = ReadApiDataTool()
read_lookup_sheet = ReadLookupSheetTool()
