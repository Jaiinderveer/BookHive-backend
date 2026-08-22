import json
import logging
from google import genai
from google.genai import types
from fastapi import HTTPException
from config import settings
from database.mongodb import DBHelper
from services.tool_executor import execute_tool

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are BookHive AI, a librarian assistant for the BookHive library management system.

STRICT RULES:
- Only perform or discuss BookHive library operations.
- Never invent books, members, transactions, or any database data.
- Never fabricate missing values.
- Never expose MongoDB ObjectIds, Book IDs, Member IDs, Transaction IDs, or other internal database identifiers in your user-facing response.
- Use tools whenever the user requests a library operation or asks for live library data.

BOOK LOOKUP:
- Book title matching is case-insensitive. Treat capitalization differences as the same title.
- For example, "Jaiinderveer- the legend" and "jaiinderveer- the legend" refer to the same book.
- Do not claim a book is missing merely because capitalization differs.
- When a book title is supplied for an operation, use the appropriate book-search/quantity tool before deciding that it does not exist.

MEMBER LOOKUP:
- Member name matching is case-insensitive. Treat capitalization differences as the same member.
- Membership IDs are exact. Pass one whenever the librarian has given it.

AMBIGUOUS MATCHES:
- A tool may report that a title or a name matched several records. That operation did NOT happen and nothing was changed.
- Never guess which record was meant and never retry with the same ambiguous value.
- Show the librarian the candidates the tool listed and ask which one they mean.
- Once they answer, retry the same tool with the exact isbn or membership_id.

BOOK CREATION:
- NEVER create a book merely because the user confirmed they want to create it.
- Before calling create_book, collect ALL required fields from the user: title, author, ISBN, category, and quantity.
- Publisher and publication year should also be collected when required by the normal BookHive form/schema, but do not invent them.
- NEVER use placeholders such as "Unknown", "General", "N/A", "None", or made-up values.
- If any required field is missing, STOP and ask the user for the missing fields instead of calling create_book.
- If the user only asked to add copies to an existing book, use adjust_book_quantity; do not create a new book.

CONFIRMATIONS:
- Ask for explicit confirmation before destructive actions such as deleting a book or member.

EMPTY RESULTS:
- An empty tool result is a valid result, not an error.
- If there are no overdue books, say exactly that there are currently no overdue books.
- Do not say "No records found" as a generic response.

TOOL FAILURES:
- A tool response containing an "error" field means that operation FAILED and nothing was changed.
- Never say or imply that an operation succeeded when its tool response contained an error.
- State plainly which operation failed and give the reason from the error.
- An empty list or an empty result is NOT a failure. Only an "error" field means failure.
- When several operations were requested and only some failed, say clearly which ones succeeded and which ones failed.
- Never invent or guess the outcome of a failed operation.

RESPONSE STYLE:
- Keep responses concise and natural.
- When structured tool results are shown by the UI, do not repeat the entire result list in text.
- Do not mention internal tool names or implementation details."""

TOOLS = [
    {
        "name": "create_book",
        "description": "Create a new book ONLY after the user has explicitly supplied every required field: title, author, ISBN, category, and quantity. NEVER invent or default missing fields. NEVER use placeholders such as Unknown or General.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Book title"},
                "author": {"type": "string", "description": "Book author"},
                "isbn": {"type": "string", "description": "ISBN number"},
                "category": {"type": "string", "description": "Book category"},
                "publisher": {"type": "string", "description": "Publisher name"},
                "publication_year": {"type": "integer", "description": "Publication year"},
                "quantity": {"type": "integer", "description": "Number of copies"},
            },
            "required": ["title", "author", "isbn", "category", "quantity"],
        },
    },
    {
        "name": "update_book",
        "description": "Update an existing book's details.",
        "parameters": {
            "type": "object",
            "properties": {
                "book_id": {"type": "string", "description": "Book ID"},
                "title": {"type": "string", "description": "Book title"},
                "author": {"type": "string", "description": "Book author"},
                "isbn": {"type": "string", "description": "ISBN number"},
                "category": {"type": "string", "description": "Book category"},
                "publisher": {"type": "string", "description": "Publisher name"},
                "publication_year": {"type": "integer", "description": "Publication year"},
                "quantity": {"type": "integer", "description": "Number of copies"},
                "available_quantity": {"type": "integer", "description": "Available copies"},
            },
            "required": ["book_id"],
        },
    },
    {
        "name": "delete_book",
        "description": "Delete a book from the library.",
        "parameters": {
            "type": "object",
            "properties": {
                "book_id": {"type": "string", "description": "Book ID"},
            },
            "required": ["book_id"],
        },
    },
    {
        "name": "search_book",
        "description": "Search for books by title, author, ISBN, or category.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Book title"},
                "author": {"type": "string", "description": "Book author"},
                "isbn": {"type": "string", "description": "ISBN number"},
                "category": {"type": "string", "description": "Book category"},
            },
        },
    },
    {
        "name": "list_books",
        "description": "List all books in the library.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "create_member",
        "description": "Register a new library member.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Member full name"},
                "email": {"type": "string", "description": "Member email"},
                "phone": {"type": "string", "description": "Member phone"},
                "address": {"type": "string", "description": "Member address"},
                "username": {"type": "string", "description": "Login username"},
                "password": {"type": "string", "description": "Temporary login password"},
            },
            "required": ["name", "email", "phone", "username", "password"],
        },
    },
    {
        "name": "update_member",
        "description": "Update an existing member's details.",
        "parameters": {
            "type": "object",
            "properties": {
                "member_id": {"type": "string", "description": "Member ID"},
                "name": {"type": "string", "description": "Member full name"},
                "email": {"type": "string", "description": "Member email"},
                "phone": {"type": "string", "description": "Member phone"},
                "address": {"type": "string", "description": "Member address"},
            },
            "required": ["member_id"],
        },
    },
    {
        "name": "delete_member",
        "description": "Delete a member from the library.",
        "parameters": {
            "type": "object",
            "properties": {
                "member_id": {"type": "string", "description": "Member ID"},
            },
            "required": ["member_id"],
        },
    },
    {
        "name": "search_member",
        "description": "Search for members by name.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Member name"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "issue_book",
        "description": "Issue a book to a member. Supply isbn and/or membership_id when a title or name matched more than one record.",
        "parameters": {
            "type": "object",
            "properties": {
                "book_title": {"type": "string", "description": "Book title"},
                "member_name": {"type": "string", "description": "Member name"},
                "isbn": {"type": "string", "description": "Exact ISBN, to pick between books sharing a title"},
                "membership_id": {"type": "string", "description": "Exact membership ID, to pick between members sharing a name"},
                "due_days": {"type": "integer", "description": "Days until due date (default 14)"},
            },
            "required": ["book_title", "member_name"],
        },
    },
    {
        "name": "return_book",
        "description": "Return a book from a member. Supply isbn and/or membership_id when a title or name matched more than one record.",
        "parameters": {
            "type": "object",
            "properties": {
                "book_title": {"type": "string", "description": "Book title"},
                "member_name": {"type": "string", "description": "Member name"},
                "isbn": {"type": "string", "description": "Exact ISBN, to pick between books sharing a title"},
                "membership_id": {"type": "string", "description": "Exact membership ID, to pick between members sharing a name"},
            },
            "required": ["book_title", "member_name"],
        },
    },
    {
        "name": "dashboard_summary",
        "description": "Get library dashboard summary metrics.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
     {
        "name": "list_transactions",
        "description": "List all transactions, optionally filtered by status.",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter by status: issued or returned"},
            },
        },
    },
    {
        "name": "adjust_book_quantity",
        "description": "Adjust the quantity of an existing book by a delta (e.g. add 5 copies). Supply isbn when a title matched more than one book.",
        "parameters": {
            "type": "object",
            "properties": {
                "book_title": {"type": "string", "description": "Title of the book to adjust"},
                "isbn": {"type": "string", "description": "Exact ISBN, to pick between books sharing a title"},
                "quantity_delta": {"type": "integer", "description": "Change in number of copies (positive to add, negative to remove)"},
            },
            "required": ["book_title", "quantity_delta"],
        },
    },
    {
        "name": "extend_due_date",
        "description": "Extend the due date of an issued book for a member by a number of days. Supply isbn and/or membership_id when a title or name matched more than one record.",
        "parameters": {
            "type": "object",
            "properties": {
                "book_title": {"type": "string", "description": "Title of the book"},
                "member_name": {"type": "string", "description": "Name of the member"},
                "isbn": {"type": "string", "description": "Exact ISBN, to pick between books sharing a title"},
                "membership_id": {"type": "string", "description": "Exact membership ID, to pick between members sharing a name"},
                "days": {"type": "integer", "description": "Number of days to extend the due date"},
            },
            "required": ["book_title", "member_name", "days"],
        },
    },
]

def _build_client():
    if not settings.GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="Gemini API key is not configured")
    return genai.Client(api_key=settings.GEMINI_API_KEY)


def _generation_config():
    declarations = [
        types.FunctionDeclaration(
            name=tool["name"],
            description=tool["description"],
            parametersJsonSchema=tool["parameters"],
        )
        for tool in TOOLS
    ]
    return types.GenerateContentConfig(
        systemInstruction=SYSTEM_PROMPT,
        tools=[types.Tool(functionDeclarations=declarations)],
        temperature=0.2,
    )

_INTERNAL_KEYS = {
    "id", "_id", "book_id", "member_id", "transaction_id", "user_id", "created_at"
}

def _sanitize_for_display(value):
    """Remove internal database identifiers from frontend-facing tool results."""
    if isinstance(value, list):
        return [_sanitize_for_display(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _sanitize_for_display(val)
            for key, val in value.items()
            if key not in _INTERNAL_KEYS
        }
    return value

def _format_result(result):
    # Keep an empty list as valid JSON. The frontend uses [] to render the
    # appropriate contextual empty state instead of showing a fake error.
    return json.dumps(_sanitize_for_display(result), default=str, indent=2) if isinstance(result, (list, dict)) else str(result)

def _execute_calls(function_calls, db: DBHelper):
    results = []
    response_parts = []
    for call in function_calls:
        tool_name = call.name
        arguments = dict(call.args or {})
        try:
            result = execute_tool(tool_name, arguments, db)
            safe_result = json.loads(json.dumps(result, default=str))
            results.append({"tool": tool_name, "success": True, "result": _format_result(result)})
            response = {"result": safe_result}
        except HTTPException as exc:
            # Expected, already user-safe failure (validation, "not found", ...).
            # Logged for operators; the detail is safe to pass on unchanged.
            logger.warning("AI tool %s failed: %s", tool_name, exc.detail)
            results.append({"tool": tool_name, "success": False, "error": exc.detail})
            response = {"status": "failed", "tool": tool_name, "error": exc.detail}
        except Exception:
            # Unexpected failure. The traceback goes to the server log only; the
            # model and the frontend get a safe message that still identifies
            # which operation failed.
            logger.exception("AI tool %s raised an unexpected error", tool_name)
            detail = f"The {tool_name.replace('_', ' ')} operation failed unexpectedly."
            results.append({"tool": tool_name, "success": False, "error": detail})
            response = {"status": "failed", "tool": tool_name, "error": detail}

        response_parts.append(
            types.Part(
                functionResponse=types.FunctionResponse(name=tool_name, id=call.id, response=response)
            )
        )
    return results, response_parts


def _failure_summary(tool_results):
    """Factual account of failed tool calls. Never invents an outcome.

    Used only when the model produced no post-tool answer of its own, so the
    reply can never imply success for an operation that failed.
    """
    failures = [r for r in tool_results if not r.get("success")]
    if not failures:
        return ""

    lines = []
    for result in failures:
        # Operation names are shown as plain words, never internal identifiers.
        operation = str(result.get("tool") or "operation").replace("_", " ")
        reason = result.get("error") or "the operation could not be completed"
        lines.append(f"- {operation}: {reason}")

    summary = "Some operations did not complete:\n" + "\n".join(lines)

    succeeded = sorted({
        str(r.get("tool")).replace("_", " ")
        for r in tool_results
        if r.get("success") and r.get("tool")
    })
    if succeeded:
        summary += "\n\nCompleted successfully: " + ", ".join(succeeded) + "."

    return summary


def _fallback_reply(text_buffer, tool_results):
    """Reply to use when the model never produced a post-tool answer."""
    failure_summary = _failure_summary(tool_results)
    if not failure_summary:
        return (text_buffer or "").strip()

    # Text emitted alongside the tool calls is usually an optimistic "I'll do
    # that now", so it must never stand in as the final answer for an operation
    # that failed.
    return failure_summary


def process_chat(message: str, db: DBHelper, history=None):
    if history is None:
        history = []

    try:
        client = _build_client()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to initialize Gemini client")

    config = _generation_config()

    contents = []
    for turn in history:
        if not turn or not turn.get("content"):
            continue
        role = "user" if turn.get("role") == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part(text=turn["content"])]))

    contents.append(types.Content(role="user", parts=[types.Part(text=message)]))

    all_results = []
    try:
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=contents,
            config=config,
        )
    except Exception:
        raise HTTPException(status_code=500, detail="Gemini request failed. Please try again.")

    # Preserve the exact model content (including thought signatures) and give the
    # model up to three tool rounds for dependent CRUD requests.
    text_buffer = ""
    for _ in range(3):
        function_calls = response.function_calls or []

        if not function_calls:
            reply_text = response.text or ""
            if text_buffer:
                reply_text = (text_buffer + "\n\n" + reply_text).strip()
            if not reply_text.strip():
                # The model returned nothing usable. Report what the tools
                # actually did instead of an empty reply.
                reply_text = _fallback_reply(text_buffer, all_results)
            return {"reply": reply_text, "tool_results": all_results}

        if not response.candidates or not response.candidates[0].content:
            raise HTTPException(status_code=500, detail="No usable response from Gemini")

        # Capture any text the model emitted alongside the function calls.
        candidate_content = response.candidates[0].content
        parts = getattr(candidate_content, "parts", None)
        if parts:
            for part in parts:
                part_text = getattr(part, "text", None)
                if part_text:
                    text_buffer += part_text + "\n"

        results, response_parts = _execute_calls(function_calls, db)
        all_results.extend(results)
        contents.extend(
            [
                response.candidates[0].content,
                types.Content(role="user", parts=response_parts),
            ]
        )
        try:
            response = client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=contents,
                config=config,
            )
        except Exception:
            # The tools already ran. Report what actually happened rather than
            # the text the model emitted before it knew the outcome.
            logger.exception("Gemini follow-up request failed after tool execution")
            return {"reply": _fallback_reply(text_buffer, all_results), "tool_results": all_results}

    # Tool-round budget exhausted. The last response may still carry the model's
    # own answer, so use it instead of discarding it — but only when the model
    # has stopped requesting tools, since pending calls were never executed.
    trailing_text = ""
    try:
        if not (response.function_calls or []):
            trailing_text = response.text or ""
    except Exception:
        logger.warning("Could not read trailing text from the final Gemini response", exc_info=True)

    if trailing_text.strip():
        reply = trailing_text.strip()
        if text_buffer:
            reply = (text_buffer + "\n\n" + reply).strip()
        return {"reply": reply, "tool_results": all_results}

    return {
        "reply": _fallback_reply(text_buffer, all_results),
        "tool_results": all_results,
    }