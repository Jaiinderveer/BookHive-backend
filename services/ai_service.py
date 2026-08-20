import json
from google import genai
from google.genai import types
from fastapi import HTTPException
from config import settings
from database.mongodb import DBHelper
from services.tool_executor import execute_tool

SYSTEM_PROMPT = """You are BookHive AI.
You assist librarians in managing the library.

Rules:
- Never answer unrelated questions.
- Never discuss politics.
- Never discuss programming.
- Never discuss general knowledge.
- Only perform library operations.
- Whenever CRUD is requested, ALWAYS use available tools.
- Never invent books.
- Never invent members.
- Never fabricate data.
- Ask for missing information before calling tools.
- ALWAYS ask for explicit confirmation before performing destructive actions like deleting a book or a member.
- Keep responses concise.
- When creating a new book, you MUST collect ALL required fields from the user: title, author, ISBN, category, quantity, publisher, publication_year. NEVER use default values like "Unknown" for author, "General" for category, or any other placeholder values.
- If any required book field is missing, ask the user for it before calling create_book.
- When searching for books by title, use exact case-insensitive matching."""

TOOLS = [
    {
        "name": "create_book",
        "description": "Create a new book in the library.",
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
        "description": "Issue a book to a member.",
        "parameters": {
            "type": "object",
            "properties": {
                "book_title": {"type": "string", "description": "Book title"},
                "member_name": {"type": "string", "description": "Member name"},
                "due_days": {"type": "integer", "description": "Days until due date (default 14)"},
            },
            "required": ["book_title", "member_name"],
        },
    },
    {
        "name": "return_book",
        "description": "Return a book from a member.",
        "parameters": {
            "type": "object",
            "properties": {
                "book_title": {"type": "string", "description": "Book title"},
                "member_name": {"type": "string", "description": "Member name"},
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
        "description": "Adjust the quantity of an existing book by a delta (e.g. add 5 copies).",
        "parameters": {
            "type": "object",
            "properties": {
                "book_title": {"type": "string", "description": "Title of the book to adjust"},
                "quantity_delta": {"type": "integer", "description": "Change in number of copies (positive to add, negative to remove)"},
            },
            "required": ["book_title", "quantity_delta"],
        },
    },
    {
        "name": "extend_due_date",
        "description": "Extend the due date of an issued book for a member by a number of days.",
        "parameters": {
            "type": "object",
            "properties": {
                "book_title": {"type": "string", "description": "Title of the book"},
                "member_name": {"type": "string", "description": "Name of the member"},
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

def _format_result(result):
    if isinstance(result, list):
        return json.dumps(result, default=str, indent=2)
    if isinstance(result, dict):
        return json.dumps(result, default=str, indent=2)
    return str(result)

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
            results.append({"tool": tool_name, "success": False, "error": exc.detail})
            response = {"error": exc.detail}
        except Exception:
            results.append({"tool": tool_name, "success": False, "error": "Tool execution failed"})
            response = {"error": "Tool execution failed"}

        response_parts.append(
            types.Part(
                functionResponse=types.FunctionResponse(name=tool_name, id=call.id, response=response)
            )
        )
    return results, response_parts


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
            if not reply_text:
                reply_text = "I completed the requested operations."
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
            return {"reply": "Operation completed.", "tool_results": all_results}

    reply = "I completed the requested operations. Please verify the results above."
    if text_buffer:
        reply = text_buffer.strip() + "\n\n" + reply
    return {
        "reply": reply,
        "tool_results": all_results,
    }
