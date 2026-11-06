"""One error shape for the whole API: `{"error": {"code": <English>, "message": <Hebrew>}}`.

`code` is stable and is what the client branches on. `message` is shown to the user as is.
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

MESSAGES: dict[str, str] = {
    "unauthorized": "צריך להתחבר מחדש",
    "invalid_credentials": "האימייל או הסיסמה לא נכונים",
    "dev_login_disabled": "הכניסה הזו לא זמינה בסביבה הזו",
    "forbidden": "אין לך הרשאה לפעולה הזו",
    "tenant_suspended": "החשבון של המפעל מושהה. פנו אלינו כדי לחדש אותו",
    "not_found": "לא מצאנו את מה שחיפשת",
    "method_not_allowed": "הפעולה הזו לא נתמכת",
    "validation_error": "חלק מהפרטים לא תקינים",
    "quota_reached": "הגעתם למכסת ההצעות של החודש",
    "upload_rejected": "חלק מהקבצים לא תקינים, ולכן ההעלאה לא בוצעה. הפרטים ליד כל קובץ",
    "drawing_finished": "הפענוח כבר הסתיים",
    "drawing_busy": "הפענוח עדיין רץ. אפשר לשנות סוג עמוד כשהוא מסתיים",
    "not_awaiting_confirmation": "העמודים כבר אושרו",
    "bom_mapping_incomplete": "בכתב הכמויות חסרה עמודת פריט או עמודת כמות. בחרו אותן ואז אשרו",
    "audit_not_ready": "הבדיקה עוד לא הסתיימה. אפשר ליצור הצעה מתוקנת כשהיא מוכנה",
    "sku_exists": 'כבר יש במחירון מוצר עם מק"ט היצרן הזה',
    "supplier_exists": "כבר יש ספק בשם הזה",
    "default_rule_required": "צריך להשאיר חוק רווח כללי אחד, כדי שלכל שורה עם עלות יהיה מחיר",
    "quote_sent": "ההצעה כבר נשלחה ולא משתנה. כדי לשנות מחיר צרו גרסה חדשה",
    "quote_draft": "הגרסה הזו עוד לא נשלחה, אז אפשר לערוך אותה ישירות",
    "line_priced": "לשורה כבר יש מחיר. אפשר לשנות אותו בפרטי השורה",
    "not_undoable": "את הפעולה הזו כבר אי אפשר לבטל",
    # the chat (08 §11)
    "proposal_expired": "ההצעה עודכנה מאז. ליצור את השינוי מחדש?",
    "proposal_not_pending": "ההצעה הזו כבר טופלה",
    "invalid_message": "ההודעה ריקה או ארוכה מדי",
    "remember_not_offered": "אי אפשר לזכור את השינוי הזה כך. אפשר להחיל אותו רק בהצעה הזו",
    "already_undone": "הפעולה כבר בוטלה",
    "no_drawing": "להצעה הזו אין שרטוט לחשב ממנו מחדש",
    "data_terms_required": "לפני השרטוט הראשון צריך לענות על שתי שאלות ולאשר את תנאי השימוש בנתונים",
    "already_decided": "כבר החלטתם על הפריט הזה",
    "global_conflict": "בשכבה המשותפת כבר יש ערך אחר לפריט הזה. הוא נשאר בתור",
    "logo_type": "הלוגו צריך להיות תמונת PNG או JPEG",
    "logo_too_large": "הלוגו גדול מדי. אפשר עד 1MB ועד 4000 פיקסלים לכל צד",
    # the chat builder (13 §4.2, S27)
    "model_unavailable": "לא הצלחנו לקרוא את ההודעה כרגע. נסו לשלוח אותה שוב בעוד רגע",
    "not_pending": "ההקלטה הזו כבר טופלה",
    "nothing_to_undo": "אין מה לבטל",
    "recording_invalid": "ההקלטה ריקה, ארוכה מדי או בפורמט שלא נתמך",
    "internal_error": "משהו השתבש אצלנו. נסו שוב בעוד רגע",
}

STATUS_CODES: dict[int, str] = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed"}


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[dict[str, Any]] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class ApiError(Exception):
    def __init__(self, status: int, code: str, details: list[dict[str, Any]] | None = None) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.details = details


def error_response(status: int, code: str, details: list[dict[str, Any]] | None = None) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(code=code, message=MESSAGES.get(code, MESSAGES["internal_error"]), details=details)
    )
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return JSONResponse(body.model_dump(exclude_none=True), status_code=status, headers=headers)


# Documented on every route, so the generated client knows the error shape.
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    "4XX": {"model": ErrorResponse, "description": "Error"},
}


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status, exc.code, exc.details)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return error_response(exc.status_code, STATUS_CODES.get(exc.status_code, "internal_error"))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Field locations and types only: never echo the submitted values (they may be a password).
        details = [{"loc": list(e.get("loc", ())), "type": e.get("type", "")} for e in exc.errors()]
        return error_response(422, "validation_error", details)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        return error_response(500, "internal_error")
